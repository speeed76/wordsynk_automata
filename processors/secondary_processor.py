# filename: processors/secondary_processor.py
import sqlite3
import time
from logger import get_logger
from pages.secondary_page import SecondaryPage
from state.models import ScrapeState
from state.manager import StateManager
from parsers.secondary_parser import parse_secondary_page_data
from db.repository import update_booking_secondary_ids, update_booking_status
from selenium.common.exceptions import TimeoutException
from typing import TYPE_CHECKING, Optional, Dict, Any # Ensure Any is imported

from config import DUMP_XML_MODE
from utils.xml_dumper import save_xml_dump

if TYPE_CHECKING:
    from services.crawler_service import CrawlerService # For type hinting
    from utils.display_manager import DisplayManager # For type hinting

logger = get_logger(__name__)

class SecondaryProcessor:
    """Handles processing of the intermediate MJB page."""
    
    def __init__(self, driver, conn, sec_page: SecondaryPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: Optional['CrawlerService'] = None): # Made crawler_service optional
        self.driver = driver
        self.conn = conn
        self.sec_page = sec_page
        self.state_manager = state_manager
        self.target_display_id_str = target_display_id # Store as string from crawler
        self.crawler_service = crawler_service # Store crawler_service instance
        # Get display_manager from crawler_service if available
        self.display_manager: Optional['DisplayManager'] = getattr(self.crawler_service, 'display_manager', None)


    def _check_active_app_and_display(self) -> bool:
        """
        Checks if the target app has focus on the correct display.
        Uses DisplayManager.
        """
        if not self.display_manager:
            logger.warning("DisplayManager not available in SecondaryProcessor. Skipping display/app check.")
            # If display manager is critical, this might be an error or require a different handling.
            # For now, assume it's okay to proceed if display manager isn't set up (e.g. in certain test contexts)
            return True 
        try:
            app_info = self.display_manager.get_current_app_focus_info()
            if app_info:
                logger.debug(f"Active window: {app_info['package']}, Display: {app_info['display_id']}")
                
                # Use driver.caps instead of driver.desired_capabilities
                target_package = self.driver.caps.get('appPackage') 
                
                if app_info['package'] == target_package and \
                   str(app_info['display_id']) == str(self.target_display_id_str):
                    logger.debug("Target app has focus on the correct display.")
                    return True
                elif app_info['package'] != target_package:
                    logger.error(f"Active window '{app_info['package']}' does not match target app '{target_package}'.")
                    return False
                else: # Target display ID mismatch
                    logger.error(f"App focused on display {app_info['display_id']} but target is {self.target_display_id_str}.")
                    return False
            else:
                # This is where "No active window found for com.wordsynknetwork.moj" is logged
                # Use driver.caps here as well for consistency if needed
                target_package_for_log = self.driver.caps.get('appPackage', 'UNKNOWN_TARGET_PACKAGE')
                logger.error(f"No active window found for {target_package_for_log}")
                return False
        except AttributeError as ae: # Catch specific attribute error if caps isn't there for some reason
            logger.exception(f"AttributeError in _check_active_app_and_display (likely driver.caps): {ae}")
            return False
        except Exception as e:
            logger.exception(f"Exception in _check_active_app_and_display: {e}")
            return False


    def _ensure_on_secondary_page(self) -> bool:
        """Verifies that the driver is on the secondary page."""
        if not self.sec_page.is_displayed(timeout=3): # Check for page title/elements
            logger.warning("Secondary page elements (title) not immediately visible.")
            # Attempt a more robust check for app focus and display
            if not self._check_active_app_and_display(): # This now uses driver.caps
                logger.error("Secondary page check failed: App not focused or on wrong display.")
                return False
            # If app focus is okay, maybe elements just need more time
            if not self.sec_page.is_displayed(timeout=5): # Try again with longer timeout
                 logger.error("Secondary page elements still not visible after extended check.")
                 return False
        logger.info("Confirmed on Secondary Page.")
        return True

    def process(self) -> ScrapeState:
        current_mja = self.state_manager.current_booking_id
        logger.info(f"Processing State: SECONDARY (Display {self.target_display_id_str}, MJA: {current_mja})")

        if not self._ensure_on_secondary_page():
            logger.error(f"Failed to ensure on secondary page for MJA {current_mja}.")
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja, error_message="Failed to ensure on secondary page (processor)")
            return ScrapeState.ERROR

        secondary_page_source = None
        page_info = None

        try:
            if self.driver:
                secondary_page_source = self.driver.page_source
                if not secondary_page_source:
                    logger.error(f"Failed to get page source for secondary page MJA {current_mja}.")
                    self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja, error_message="Empty page source on secondary page")
                    return ScrapeState.ERROR
                
                page_info = parse_secondary_page_data(secondary_page_source)

                if DUMP_XML_MODE:
                    mjb_identifier = page_info.get('mjb_id_raw') if page_info else None
                    primary_folder_id = current_mja if current_mja else "UNKNOWN_MJA_SEC"
                    stage_name = mjb_identifier if mjb_identifier else "UNKNOWN_MJB"
                    save_xml_dump(secondary_page_source, "Secondary", primary_folder_id, sequence_or_stage=stage_name)

            if not page_info or not page_info.get('mjr_id_raw'):
                logger.error(f"Failed to extract MJR ID from secondary page for MJA {current_mja}. Info: {page_info}")
                self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja, error_message="MJR ID missing from secondary page")
                return ScrapeState.ERROR

            mjb_id = page_info.get('mjb_id_raw')
            mjr_id = page_info.get('mjr_id_raw')
            appt_count_hint = page_info.get('appointment_count_hint')
            type_hint = page_info.get('type_hint_raw')
            logger.info(f"Extracted from Secondary XML -> MJB: {mjb_id}, MJR: {mjr_id}, Appt Count: {appt_count_hint}, Type Hint: {type_hint}")

            # Database update always occurs if not in exclusive dump mode (already handled by removing conditional)
            if current_mja:
                update_booking_secondary_ids(self.conn, current_mja, mjb_id, mjr_id, appt_count_hint, type_hint)
            else:
                logger.warning("No current_mja_in_state to update secondary IDs, this might happen if resuming directly to secondary.")

            if self.sec_page.click_mjr_link(mjr_id):
                self.state_manager.update_state(ScrapeState.DETAIL, current_booking_id=current_mja, current_mjr_id=mjr_id)
                return ScrapeState.DETAIL
            else:
                logger.error(f"Failed to click MJR link ({mjr_id}) on secondary page for MJA {current_mja}.")
                self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja, error_message="Failed to click MJR link")
                return ScrapeState.ERROR

        except Exception as e:
            logger.exception(f"Error processing secondary page for MJA {current_mja}: {e}")
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja, error_message=f"Secondary processor error: {str(e)[:200]}") # Truncate long error messages
            return ScrapeState.ERROR