# filename: utils/display_manager.py
import subprocess
import re
from logger import get_logger
from typing import Dict, Optional, List, Tuple

logger = get_logger(__name__)

class DisplayManager:
    def __init__(self, driver, default_target_display_id: Optional[str] = "0"):
        self.driver = driver
        # default_target_display_id is used if no specific target can be found
        self.default_target_display_id = default_target_display_id if default_target_display_id else "0"


    def execute_adb_command_raw(self, command_parts: List[str]) -> Tuple[bool, str]:
        """Executes an ADB command and returns success status and output/error."""
        try:
            # Ensure adb is in PATH or provide full path
            process = subprocess.run(['adb'] + command_parts, capture_output=True, text=True, check=False, timeout=10)
            if process.returncode == 0:
                return True, process.stdout.strip()
            else:
                # Log stderr if error, otherwise stdout
                error_output = process.stderr.strip() if process.stderr.strip() else process.stdout.strip()
                logger.error(f"ADB command failed: {' '.join(command_parts)}. Return code: {process.returncode}. Output: {error_output}")
                # Specific check for "Killed"
                if "killed" in error_output.lower():
                     logger.error("ADB command was killed, possibly due to system/emulator issues.")
                return False, error_output
        except subprocess.TimeoutExpired:
            logger.error(f"ADB command timed out: {' '.join(command_parts)}")
            return False, "Timeout"
        except FileNotFoundError:
            logger.error("ADB command not found. Ensure ADB is in your system PATH.")
            return False, "ADB not found"
        except Exception as e:
            logger.exception(f"Exception executing ADB command {' '.join(command_parts)}: {e}")
            return False, str(e)

    def _get_display_ids(self) -> Dict[str, str]:
        """
        Retrieves available display IDs and their types (e.g., internal, virtual) using ADB.
        Example output format: {'internal': '0', 'virtual_display_1': '4619827259835644672'}
        """
        displays = {}
        success, output = self.execute_adb_command_raw(["shell", "dumpsys", "SurfaceFlinger", "--display-id"])
        if success and output:
            # Example output line: "Display 4619827259835644672 (virtual_display_1):"
            # Or for internal: "Display 0 (Internal Display):"
            display_pattern = re.compile(r"Display\s+(\d+)\s+\(([^)]+)\):")
            for line in output.splitlines():
                match = display_pattern.search(line)
                if match:
                    display_id = match.group(1)
                    display_name_raw = match.group(2).lower()
                    if "internal" in display_name_raw:
                        displays['internal'] = display_id
                    else: # For virtual displays, try to use a unique name
                        displays[display_name_raw.replace(" ", "_")] = display_id
        else:
            logger.warning(f"Could not get display IDs from SurfaceFlinger. Output: {output}")
        logger.info(f"Detected displays: {displays}")
        return displays

    def _get_focused_window_display_id(self) -> Optional[str]:
        """
        Attempts to find the display ID of the currently focused application window.
        Returns the display ID as a string, or None if not found or error.
        """
        # Get focused app and window
        success, output = self.execute_adb_command_raw(
            ["shell", "dumpsys", "window", "windows"]
        )
        focused_app_package = None
        if success and output:
            # Look for mCurrentFocus or mFocusedApp for the package name
            # Example: mCurrentFocus=Window{... com.wordsynknetwork.moj/com.wordsynknetwork.moj.MainActivity}
            # Example: mFocusedApp=ActivityRecord{... com.wordsynknetwork.moj/.MainActivity ...}
            focus_match = re.search(r"mCurrentFocus=Window{[^ ]+ ([^/]+)/[^ }]+}|mFocusedApp=ActivityRecord{[^ ]+ ([^/]+)/[^ ]+ .*?}", output)
            if focus_match:
                focused_app_package = focus_match.group(1) or focus_match.group(2) # Take first non-None group
                logger.debug(f"Detected focused app package: {focused_app_package}")

        if not focused_app_package or focused_app_package != GENERAL_CAPABILITIES.get('appPackage'):
            logger.warning(f"Target app {GENERAL_CAPABILITIES.get('appPackage')} not focused. Current focus: {focused_app_package}")
            return None # Target app not focused

        # If target app is focused, get its display ID
        success_disp, output_disp = self.execute_adb_command_raw(
             ["shell", "dumpsys", "SurfaceFlinger", "--display-id"] # Check all displays
        )
        if success_disp and output_disp:
            # This is complex because SurfaceFlinger lists all displays, not just focused one.
            # A more reliable method would be to parse 'dumpsys activity a . | grep "* TaskRecord"'
            # which sometimes includes displayId for the top task.
            # For now, if the app is focused, we assume it's on one of the known displays.
            # The logic in get_target_display_id will try to use "internal" or a specific named one.
            # This function is more about confirming which display ID an app *IS* on if multiple are active.
            # Let's assume for now if app is focused, it's on the primary/internal or the one set in Appium.
            # A more robust implementation would parse `dumpsys activity activities` to find the displayId of the focused task.
            logger.debug("Cannot reliably determine focused window's display ID from SurfaceFlinger alone without more parsing. Returning None to let other logic decide.")
            return None # Let get_target_display_id handle selection
        return None


    def get_target_display_id(self, target_display_name: Optional[str] = None) -> str:
        """
        Determines the target display ID.
        If target_display_name is provided (e.g., "internal", "virtual_display_1"), uses that.
        Otherwise, attempts to find the display with the focused target app.
        Defaults to internal display or "0".
        """
        available_displays = self._get_display_ids()
        if not available_displays:
            logger.warning("No displays detected via ADB. Defaulting to display ID '0'.")
            return "0"

        if target_display_name and target_display_name in available_displays:
            logger.info(f"Using specified target display: {target_display_name} (ID: {available_displays[target_display_name]})")
            return available_displays[target_display_name]
        
        # If no specific name, or name not found, try to use internal or default.
        if 'internal' in available_displays:
            logger.info(f"Defaulting to internal display (ID: {available_displays['internal']})")
            return available_displays['internal']
        
        # If only one display listed, use that one
        if len(available_displays) == 1:
            single_display_id = list(available_displays.values())[0]
            logger.info(f"Only one display detected (ID: {single_display_id}). Using that.")
            return single_display_id

        logger.warning(f"Target display '{target_display_name}' not found or not specified, and no clear default. Defaulting to display ID '0'. Available: {available_displays}")
        return "0" # Fallback

    def get_current_app_focus_info(self) -> Optional[Dict[str, str]]:
        """
        Gets the package name and display ID of the currently focused application window.
        Returns a dict {'package': name, 'display_id': id} or None.
        """
        # This method is complex due to parsing `dumpsys window windows`.
        # The "ADB command failed: Killed" suggests this is where issues can occur if the app is unstable.
        # For simplification, if this is problematic, one might have to rely on Appium's active element
        # or assume the target display set initially is still correct, unless an error forces re-check.
        logger.info("Checking current app focus and display ID...")
        success, output = self.execute_adb_command_raw(["shell", "dumpsys", "window", "displays"]) # Get display info
        if not success:
            logger.error("Failed to get display configuration from ADB.")
            return None
        
        # Parse display IDs and their properties, particularly looking for the one matching our target.
        # This is a simplified representation. `dumpsys window displays` gives more info.
        # We primarily rely on setting displayId via Appium and assume it works.
        # This function would be more about *verifying* after the fact.
        
        # Try to get focused app
        success_focus, output_focus = self.execute_adb_command_raw(
            ["shell", "dumpsys", "window", "windows"] # Check all windows
        )
        if success_focus and output_focus:
            # Look for mCurrentFocus or mFocusedApp
            # Example: mCurrentFocus=Window{u0 com.wordsynknetwork.moj/com.wordsynknetwork.moj.MainActivity}
            # Example: mFocusedApp=ActivityRecord{... token=android.os.BinderProxy@xxx {com.wordsynknetwork.moj/com.wordsynknetwork.moj.MainActivity}}
            focus_match = re.search(r"mCurrentFocus=Window{[^ ]+ ([^/]+)/[^ }]+}|mFocusedApp=ActivityRecord{[^ ]+ ([^/]+)/[^ ]+ .*?}", output_focus)
            if focus_match:
                package_name = focus_match.group(1) or focus_match.group(2)
                if package_name:
                    # Assuming the focused app is on the self.target_display_id if set.
                    # This is a simplification; properly linking focused app to its actual display_id from dumpsys is more involved.
                    logger.debug(f"Focused app seems to be {package_name}. Assuming it's on target display {self.target_display_id_str}")
                    return {'package': package_name, 'display_id': self.target_display_id_str}
        
        logger.warning("Could not determine focused app or its display ID reliably via ADB dumpsys window.")
        return None