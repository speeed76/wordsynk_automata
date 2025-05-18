# filename: services/crawler_service.py
import os
import time
import base64
import subprocess
from appium import webdriver
from appium.options.common import AppiumOptions # Ensure AppiumOptions is imported
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from typing import Optional, Dict, List, Any

from config import APPIUM_SERVER_URL, GENERAL_CAPABILITIES, DB_PATH, DUMP_XML_MODE, XML_DUMP_ROOT_DIR
from db.connection import init_db, close_db
from pages.list_page import ListPage
from pages.secondary_page import SecondaryPage
from pages.detail_page import DetailPage
from processors.list_processor import ListProcessor
from processors.secondary_processor import SecondaryProcessor
from processors.detail_processor import DetailProcessor
from state.manager import StateManager
from state.models import ScrapeState
from utils.display_manager import DisplayManager
from utils.xml_dumper import initialize_dumper
from logger import get_logger

logger = get_logger(__name__)

class CrawlerService:
    """
    Main service to orchestrate the booking scraping process.
    Manages Appium driver, database connection, page objects, processors, and state.
    """
    def __init__(self, db_path: str = DB_PATH, test_mode: bool = False, target_display_name: Optional[str] = None):
        logger.info("Initializing Crawler Service...")
        self.conn = init_db(db_path, test_mode=test_mode)
        logger.info(f"Database initialized{' in test mode (reset)' if test_mode else ''}.")

        self.driver: Optional[webdriver.Remote] = None
        try:
            logger.info("Attempting to start Appium session with pre-configured AppiumOptions...")
            self.driver = webdriver.Remote(
                command_executor=APPIUM_SERVER_URL,
                options=GENERAL_CAPABILITIES # Pass the AppiumOptions object directly
            )
            self.driver.implicitly_wait = 1 # Small implicit wait
            logger.info("Appium session started.")
        except WebDriverException as e:
            logger.exception(f"Failed to start Appium session: {e}")
            self.cleanup(); raise

        self.display_manager = DisplayManager(self.driver)
        self.target_display_id_str: str = self.display_manager.get_target_display_id(target_display_name)

        if self.target_display_id_str and self.target_display_id_str != "0":
            logger.info(f"Updating Appium settings to target display ID: {self.target_display_id_str}")
            try:
                self.driver.update_settings({"displayId": int(self.target_display_id_str)})
            except ValueError:
                logger.warning(f"Target display ID '{self.target_display_id_str}' is not an integer. Using Appium default or previously set.")
            except Exception as e:
                 logger.error(f"Error setting displayId via Appium settings: {e}")
        else:
            logger.info("Using Appium default display (no specific displayId setting applied or target is '0').")
            if not self.target_display_id_str: # If it was None from get_target_display_id
                 self.target_display_id_str = "0"

        if DUMP_XML_MODE:
            initialize_dumper(XML_DUMP_ROOT_DIR)
            logger.info(f"XML DUMP MODE IS ENABLED. XML files will be saved to '{XML_DUMP_ROOT_DIR}'")

        self.list_page = ListPage(self.driver)
        self.secondary_page = SecondaryPage(self.driver)
        self.detail_page = DetailPage(self.driver)
        logger.info("Page objects initialized.")

        self.state_manager = StateManager(self.conn)
        self.state_manager.load_or_create_session()
        logger.info(f"State manager initialized. Session: {self.state_manager.session_id}, Current state: {self.state_manager.current_state.name}")

        self.processors = {
            ScrapeState.LIST: ListProcessor(self.driver, self.conn, self.list_page, self.state_manager, self.target_display_id_str, self),
            ScrapeState.SECONDARY: SecondaryProcessor(self.driver, self.conn, self.secondary_page, self.state_manager, self.target_display_id_str, self),
            ScrapeState.DETAIL: DetailProcessor(self.driver, self.conn, self.detail_page, self.state_manager, self.target_display_id_str, self)
        }
        logger.info("Processors initialized.")
        logger.info("Crawler Service initialized successfully.")

    def take_screenshot_on_display(self, display_id_to_capture_str: str, filepath: str) -> bool:
        if not self.driver: logger.error("Driver not available for screenshot."); return False
        if not self.display_manager: logger.error("DisplayManager not available for screenshot."); return False
        
        if not display_id_to_capture_str:
            display_id_to_capture_str = self.target_display_id_str if self.target_display_id_str else "0"
        
        temp_device_path = f"/sdcard/appium_temp_screenshot_{display_id_to_capture_str}.png"
        logger.debug(f"Attempting screenshot for display {display_id_to_capture_str} to {filepath} (via {temp_device_path})")

        try:
            if not hasattr(self, 'display_manager') or self.display_manager is None:
                 logger.error("DisplayManager not available for taking screenshot."); return False

            capture_command_parts = ["shell", "screencap", "-d", display_id_to_capture_str, "-p", temp_device_path]
            success_capture, out_err_capture = self.display_manager.execute_adb_command_raw(capture_command_parts)
            if not success_capture:
                logger.error(f"ADB screencap command failed for display {display_id_to_capture_str}. Output/Error: {out_err_capture}")
                # Do not return False immediately if adb is known to be unstable for this, allow pull attempt
                # return False
            logger.debug(f"Executed: adb {' '.join(capture_command_parts)}")

            # Proceed to pull even if capture command result was uncertain due to "Killed" messages.
            # The file might still exist.
            try:
                b64_data = self.driver.pull_file(temp_device_path)
                logger.debug(f"Pulling file from device: {temp_device_path}")

                screenshot_bytes = base64.b64decode(b64_data)
                with open(filepath, "wb") as f: f.write(screenshot_bytes)
                logger.debug(f"Decoding and saving screenshot to: {filepath}")

                cleanup_command_parts = ["shell", "rm", temp_device_path]
                success_rm, out_err_rm = self.display_manager.execute_adb_command_raw(cleanup_command_parts)
                if success_rm: logger.debug(f"Removing temporary file from device: {temp_device_path}")
                else: logger.warning(f"Failed to remove temporary screenshot from device: {temp_device_path}. Output/Error: {out_err_rm}")
                
                logger.info(f"Successfully saved screenshot for display {display_id_to_capture_str} to {filepath}")
                return True
            except Exception as pull_e: # Catch errors during pull_file or decode
                logger.error(f"Error during screenshot pull/decode for display {display_id_to_capture_str}: {pull_e}")
                if not success_capture: # If capture also failed, it's a definite fail
                    logger.error("Screenshot capture and pull both failed.")
                    return False
                # If capture might have succeeded but pull failed, it's tricky. For now, report as fail.
                return False
                
        except Exception as e:
            logger.exception(f"Failed to take screenshot for display {display_id_to_capture_str}: {e}")
            return False

    def run(self):
        logger.info(f"Starting crawler run loop (targeting display: {self.target_display_id_str})...")
        max_consecutive_errors = 3
        consecutive_error_count = 0
        is_processing_fresh_list_view = True # Initialize to True

        try:
            while self.state_manager.current_state not in [ScrapeState.FINISHED, ScrapeState.ERROR]:
                current_state_enum = self.state_manager.current_state
                
                logger.info(f"--- Executing State: {current_state_enum.name} (Fresh List View Flag for LIST state: {is_processing_fresh_list_view if current_state_enum == ScrapeState.LIST else 'N/A'}) ---")

                if current_state_enum == ScrapeState.NAVIGATING_TO_LIST:
                    is_processing_fresh_list_view = True # Always a fresh view when navigating
                    try:
                        if self.list_page.is_displayed(timeout=10):
                            self.state_manager.update_state(ScrapeState.LIST)
                            logger.info("Successfully navigated to list page.")
                            consecutive_error_count = 0
                            # is_processing_fresh_list_view remains True for this first entry
                            continue
                        else:
                            logger.warning("Not on list page initially, trying one back navigation.")
                            self.driver.back(); time.sleep(2) # Allow time for navigation
                            if self.list_page.is_displayed(timeout=5):
                                self.state_manager.update_state(ScrapeState.LIST)
                                logger.info("Successfully navigated to list page after one back().")
                                consecutive_error_count = 0
                                # is_processing_fresh_list_view remains True
                                continue
                            else:
                                logger.error("Failed to navigate to list page initially.")
                                self.state_manager.update_state(ScrapeState.ERROR, error_message="Initial navigation to list page failed")
                    except Exception as nav_e:
                        logger.exception(f"Error during initial navigation: {nav_e}")
                        self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Initial navigation error: {nav_e}")
                
                processor = self.processors.get(current_state_enum)
                if processor:
                    try:
                        previous_state_before_process_call = self.state_manager.current_state # Capture state before processor might change it
                        
                        if current_state_enum == ScrapeState.LIST:
                            processor.process(is_initial_entry=is_processing_fresh_list_view)
                            # After ListProcessor runs, if it scrolled and stayed in LIST, 
                            # the next LIST iteration for that view isn't "fresh".
                            # If it moved to SECONDARY, then the next LIST entry (after DETAIL) will be fresh.
                            if self.state_manager.current_state == ScrapeState.LIST and previous_state_before_process_call == ScrapeState.LIST:
                                is_processing_fresh_list_view = False 
                            else: # Transitioned away from LIST, or came from another state to LIST
                                is_processing_fresh_list_view = True
                        else:
                            processor.process()
                            # If any other processor results in transitioning back to LIST
                            if self.state_manager.current_state == ScrapeState.LIST and previous_state_before_process_call != ScrapeState.LIST :
                                is_processing_fresh_list_view = True
                        
                        logger.debug(f"Processor for {current_state_enum.name} finished. State Manager Current State: {self.state_manager.current_state.name}")
                        
                        if self.state_manager.current_state == ScrapeState.ERROR:
                            logger.error(f"Processor for {current_state_enum.name} set ERROR state. Current booking: {self.state_manager.current_booking_id}")
                            consecutive_error_count +=1
                        else:
                            consecutive_error_count = 0
                    except Exception as proc_e:
                        logger.exception(f"Error during {current_state_enum.name} processing: {proc_e}")
                        self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Processor {current_state_enum.name} error: {proc_e}")
                        consecutive_error_count +=1
                else:
                    logger.error(f"No processor for state: {current_state_enum.name}. Stopping.")
                    self.state_manager.update_state(ScrapeState.ERROR, error_message=f"No processor for state {current_state_enum.name}")
                    consecutive_error_count +=1

                if consecutive_error_count >= max_consecutive_errors:
                     logger.error(f"Reached maximum consecutive errors ({max_consecutive_errors}). Stopping crawler.")
                     self.state_manager.update_state(ScrapeState.ERROR, error_message="Max consecutive errors reached"); break
                if self.state_manager.current_state != ScrapeState.ERROR: time.sleep(0.5)
        except Exception as e:
            logger.exception(f"Unexpected error during run loop: {e}")
            self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Unhandled crawler error: {e}")
        finally:
            logger.info(f"Crawler run loop finished. Final state: {self.state_manager.current_state.name}")
            self.cleanup()

    def cleanup(self):
        logger.info("Cleaning up crawler resources...")
        if self.driver:
            try: self.driver.quit(); logger.info("Appium session closed.")
            except Exception as e: logger.error(f"Error closing Appium session: {e}")
            self.driver = None
        if self.conn:
            close_db(self.conn)
        logger.info("Crawler cleanup finished.")