# filename: services/booking_service.py
# This is assumed to be the original content or a previously known state.
# Significant refactoring would be needed to align it with current CrawlerService.
# Consider deprecating this file if its functionality is covered by CrawlerService.

from appium import webdriver
from appium.options.android import UiAutomator2Options
from config import APPIUM_SERVER_URL, GENERAL_CAPABILITIES, DB_PATH
from db.connection import init_db, close_db
from pages.list_page import ListPage
from pages.secondary_page import SecondaryPage
from pages.detail_page import DetailPage
from parsers.mja_parser import parse_mja
from parsers.secondary_parser import parse_secondary_page_data
from parsers.detail_parser import extract_raw_details_from_xml_text, parse_detail_data, check_if_multiday_from_xml
from db.repository import insert_booking_base, update_booking_secondary_ids, save_booking_details
from logger import get_logger
import time

logger = get_logger(__name__)

class BookingService:
    def __init__(self, test_mode=False):
        self.conn = init_db(DB_PATH, test_mode=test_mode)
        self.driver = None
        self.list_page = None
        self.secondary_page = None
        self.detail_page = None
        self.processed_mjr_ids_this_run = set() # Track MJR IDs processed in this run

    def start_driver(self):
        logger.info("Starting Appium driver...")
        try:
            capabilities_options = UiAutomator2Options().load_capabilities(GENERAL_CAPABILITIES)
            self.driver = webdriver.Remote(command_executor=APPIUM_SERVER_URL, options=capabilities_options)
            self.driver.implicitly_wait = 5 # Adjust as needed
            self.list_page = ListPage(self.driver)
            self.secondary_page = SecondaryPage(self.driver)
            self.detail_page = DetailPage(self.driver)
            logger.info("Appium driver started and page objects initialized.")
            return True
        except Exception as e:
            logger.exception(f"Failed to start Appium driver: {e}")
            return False

    def stop_driver(self):
        if self.driver:
            logger.info("Stopping Appium driver...")
            self.driver.quit()
            self.driver = None
            logger.info("Appium driver stopped.")

    def navigate_to_bookings_list(self):
        # This method would contain logic to ensure the app is on the main bookings list.
        # For now, we assume it starts there or can navigate there easily.
        # Example: Check for a known element on the list page.
        if self.list_page and self.list_page.is_displayed():
            logger.info("Already on bookings list page or navigated successfully.")
            return True
        else:
            logger.warning("Could not confirm navigation to bookings list page.")
            # Add more specific navigation logic if needed (e.g., clicking tabs)
            return False # Or attempt navigation

    def process_all_bookings(self, max_bookings_to_process=None):
        if not self.driver:
            logger.error("Driver not started. Cannot process bookings.")
            return

        if not self.navigate_to_bookings_list():
            logger.error("Failed to navigate to booking list. Aborting.")
            return

        processed_count = 0
        scroll_attempts_without_new = 0
        max_scrolls_no_new = 3 # Stop scrolling if no new bookings are found after this many scrolls

        while True:
            if max_bookings_to_process is not None and processed_count >= max_bookings_to_process:
                logger.info(f"Reached processing limit of {max_bookings_to_process} bookings.")
                break

            logger.info("Fetching cards from list page...")
            current_cards_data = self.list_page.get_cards()

            if not current_cards_data and scroll_attempts_without_new == 0: # No cards on first load
                logger.warning("No booking cards found on the list page initially.")
                break
            if not current_cards_data: # No cards after a scroll
                 logger.info("No more cards found on this scroll iteration.")
                 scroll_attempts_without_new += 1
                 if scroll_attempts_without_new >= max_scrolls_no_new:
                      logger.info("Reached max scroll attempts without finding new cards. Ending list processing.")
                      break
                 # Scroll and continue
                 logger.info("Attempting to scroll down for more bookings...")
                 self.list_page.scroll() # Use the last known element ID if available
                 time.sleep(2) # Wait for new cards to load
                 continue


            new_card_found_this_iteration = False
            last_processed_mja_for_scroll = None

            for card_data in current_cards_data:
                mja_id = card_data.get('booking_id')
                if not mja_id:
                    logger.warning(f"Skipping card with no booking_id: {card_data}")
                    continue
                
                last_processed_mja_for_scroll = mja_id # Keep track for scrolling

                # Check if this MJA's MJR has already been fully processed in this run
                # This requires linking MJA to MJR earlier or checking status
                # For now, let's assume we process each MJA path once through secondary
                # This is a simplified check; more robust logic needed if resuming.
                # We will rely on the database to know if already scraped.

                insert_booking_base(self.conn, card_data) # Insert or ignore base data

                # Check DB if this MJA is already fully scraped
                # This is a simplified check, a proper status check would be better
                # cursor = self.conn.cursor()
                # cursor.execute("SELECT status FROM bookings WHERE booking_id = ?", (mja_id,))
                # row = cursor.fetchone()
                # if row and row[0] == 'scraped':
                #     logger.debug(f"Booking MJA {mja_id} already marked as scraped. Skipping detailed processing.")
                #     continue


                logger.info(f"Processing MJA card: {mja_id}")
                new_card_found_this_iteration = True
                scroll_attempts_without_new = 0 # Reset on finding a processable card

                # Click on the MJA card
                if self.list_page.click_element(AppiumBy.XPATH, f'//android.view.ViewGroup[starts-with(@content-desc, "{mja_id}")]'):
                    time.sleep(1.5) # Wait for secondary page to load

                    # --- Secondary Page Processing ---
                    if self.secondary_page.is_displayed():
                        sec_page_info = self.secondary_page.get_info()
                        if sec_page_info and sec_page_info.get('mjr_id_raw'):
                            mjr_id = sec_page_info['mjr_id_raw']
                            mjb_id = sec_page_info.get('mjb_id_raw')
                            appt_count = sec_page_info.get('appointment_count_hint')
                            type_h = sec_page_info.get('type_hint_raw')

                            logger.info(f"Secondary page: MJB={mjb_id}, MJR={mjr_id}, ApptCount={appt_count}, Type={type_h}")
                            update_booking_secondary_ids(self.conn, mja_id, mjb_id, mjr_id, appt_count, type_h)

                            if mjr_id in self.processed_mjr_ids_this_run:
                                logger.info(f"MJR {mjr_id} (from MJA {mja_id}) already processed in this run. Navigating back.")
                                self.driver.back() # Back to list
                                time.sleep(1)
                                continue # Next MJA card

                            if self.secondary_page.click_mjr_link(mjr_id):
                                time.sleep(2) # Wait for detail page to load

                                # --- Detail Page Processing ---
                                if self.detail_page.is_displayed():
                                    detail_page_source = self.driver.page_source # Get initial source
                                    is_multiday = check_if_multiday_from_xml(detail_page_source)
                                    logger.info(f"Detail page for MJR {mjr_id} is_multiday: {is_multiday}")

                                    final_xml_to_parse = detail_page_source
                                    if is_multiday:
                                        logger.info("Multiday booking detected, attempting to scroll to disclaimer...")
                                        # Scroll logic for multiday (simplified here)
                                        for _scroll_attempt in range(3): # Max 3 scrolls
                                            if self.detail_page.is_element_displayed(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("By accepting this assignment")', timeout=1):
                                                logger.info("Disclaimer found on multiday page.")
                                                final_xml_to_parse = self.driver.page_source # Get source after scroll
                                                break
                                            logger.debug("Scrolling multiday detail page...")
                                            # Simplified scroll, use a more robust one if needed
                                            self.driver.swipe(500, 1500, 500, 500, 800)
                                            time.sleep(1)
                                        else:
                                            logger.warning("Disclaimer not found after scrolls on multiday page. Using current source.")
                                            final_xml_to_parse = self.driver.page_source


                                    raw_details = extract_raw_details_from_xml_text(final_xml_to_parse) # Old parser
                                    if raw_details:
                                        parsed_details = parse_detail_data(raw_details) # Old parser
                                        parsed_details['mjr_id'] = mjr_id # Ensure MJR ID is linked
                                        parsed_details['mja_id'] = mja_id # Link the original MJA
                                        
                                        # For multiday, save_booking_details needs to handle list of payments
                                        # This simplified version assumes parse_detail_data handles multiday structure
                                        # and save_booking_details can take it.
                                        # The new processor model is better for this.
                                        if parsed_details.get('is_multiday'):
                                            logger.info(f"Saving MULTIDAY booking details for MJR {mjr_id}")
                                            # This part needs significant change to align with new multiday save logic
                                            # where individual MJA blocks are saved.
                                            # For now, this will likely fail for multiday or save incompletely.
                                            # This old service does not have the logic to iterate MJA blocks from detail page.
                                            # It would typically only save against the current MJA_ID.
                                            logger.warning("Old BookingService: Multiday saving is simplified and may not be complete.")
                                            save_booking_details(self.conn, parsed_details)
                                        else:
                                            logger.info(f"Saving SINGLE DAY booking details for MJA {mja_id} (MJR {mjr_id})")
                                            save_booking_details(self.conn, parsed_details)
                                        
                                        self.processed_mjr_ids_this_run.add(mjr_id) # Mark MJR as processed for this run
                                        processed_count += 1
                                    else:
                                        logger.error(f"Failed to extract raw details for MJR {mjr_id}.")
                                        update_booking_status(self.conn, mja_id, "error_detail_extract")

                                else: # Not on detail page
                                    logger.error(f"Failed to reach detail page for MJR {mjr_id}.")
                                    update_booking_status(self.conn, mja_id, "error_nav_detail")
                                # Navigate back from Detail page
                                logger.debug("Navigating back from Detail to Secondary...")
                                self.driver.back(); time.sleep(1)
                            else: # Failed to click MJR link
                                logger.error(f"Failed to click MJR link for MJA {mja_id}.")
                                update_booking_status(self.conn, mja_id, "error_click_mjr")
                        else: # Failed to get secondary page info
                            logger.error(f"Failed to get info from secondary page for MJA {mja_id}.")
                            update_booking_status(self.conn, mja_id, "error_secondary_info")
                        # Navigate back from Secondary page
                        logger.debug("Navigating back from Secondary to List...")
                        self.driver.back(); time.sleep(1)
                    else: # Not on secondary page
                        logger.error(f"Not on secondary page after clicking MJA {mja_id}.")
                        update_booking_status(self.conn, mja_id, "error_nav_secondary")
                        # May need more robust back navigation here
                else: # Failed to click MJA card
                    logger.error(f"Failed to click MJA card {mja_id}.")
                    update_booking_status(self.conn, mja_id, "error_click_mja")
                
                if max_bookings_to_process is not None and processed_count >= max_bookings_to_process:
                    break # Exit inner loop if limit reached

            if not new_card_found_this_iteration and current_cards_data: # Scrolled but no new cards to process
                scroll_attempts_without_new += 1
                logger.info(f"No new cards found in this view. Scroll attempts without new: {scroll_attempts_without_new}")

            if scroll_attempts_without_new >= max_scrolls_no_new:
                logger.info(f"Reached max scroll attempts ({max_scrolls_no_new}) without new cards. Ending list processing.")
                break # Exit outer while loop

            if current_cards_data: # Only scroll if there were cards to scroll past
                logger.info("Scrolling list page for more bookings...")
                # Use the booking_id of the last card seen on this iteration as a potential scroll anchor
                # This part of list_page.scroll might need refinement.
                self.list_page.scroll(last_element_booking_id=last_processed_mja_for_scroll)
                time.sleep(3) # Wait for scroll and new items to load
            else: # No cards at all, implies end or an error.
                logger.info("No cards found, breaking list processing loop.")
                break

        logger.info(f"Finished processing bookings. Total processed in this run: {processed_count}")


    def cleanup(self):
        if self.conn:
            close_db(self.conn)
        self.stop_driver()