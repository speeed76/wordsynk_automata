# filename: processors/list_processor.py
import os
from logger import get_logger
from db.repository import (
    insert_booking_base, 
    get_processed_booking_ids, # This gets MJA IDs already in DB
    update_booking_status,
    get_mjr_id_for_mja, # To get MJR ID for a given MJA
    get_all_mja_ids_for_mjr, # To get all MJAs for a given MJR
    check_if_all_mjas_for_mjr_scraped # To check if an MJR is fully done
)
from pages.list_page import ListPage
from state.models import ScrapeState, BookingCardStatus, BookingProcessingStatus
from state.manager import StateManager
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import TimeoutException, StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple, Set

from config import DUMP_XML_MODE
from utils.xml_dumper import save_xml_dump


if TYPE_CHECKING:
    from services.crawler_service import CrawlerService

logger = get_logger(__name__)

class ListProcessor:
    def __init__(self, driver, conn, list_page: ListPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: Optional['CrawlerService'] = None):
        self.driver = driver
        self.conn = conn
        self.list_page = list_page
        self.state_manager = state_manager
        self.target_display_id_str = target_display_id
        self.crawler_service = crawler_service
        
        self.processed_ids_this_cycle: Set[str] = set() # MJA IDs processed (clicked or skipped) in the current view/scroll cycle
        self.session_clicked_mja_ids: Set[str] = set() # MJA IDs clicked throughout this entire scrape session (mainly for DUMP_XML_MODE)
        self.session_fully_processed_mjr_ids: Set[str] = set() # MJR IDs that have been fully scraped in this session

        self.scroll_attempts = 0
        self.max_scroll_attempts = 3 
        self.last_good_scroll_anchor_id: Optional[str] = None
        self.screenshot_dir = "screenshots"
        if not os.path.exists(self.screenshot_dir):
             try: os.makedirs(self.screenshot_dir)
             except OSError as e: logger.error(f"Could not create screenshot dir '{self.screenshot_dir}': {e}")

    def _ensure_on_list_page(self, initial_check=False) -> bool:
        # ... (Same as previous version) ...
        if not initial_check: return self.list_page.is_displayed(timeout=1)
        retries = 3
        while retries > 0:
            if self.list_page.is_displayed(timeout=1): return True
            logger.warning("Not on list page. Attempting back.")
            try: self.driver.back(); time.sleep(1.5)
            except Exception as e: logger.error(f"Error navigating back: {e}")
            retries -= 1
        logger.error("Failed to ensure list page."); return False

    def _apply_display_setting(self):
        # ... (Same as previous version) ...
        if self.target_display_id_str == "0" or not self.target_display_id_str: return
        try: self.driver.update_settings({"displayId": int(self.target_display_id_str)})
        except ValueError: logger.warning(f"Target display ID '{self.target_display_id_str}' not an int.")
        except Exception as e: logger.error(f"Failed to apply displayId setting: {e}")

    def _is_element_fully_visible(self, element: WebElement, window_height: int) -> bool:
        # ... (Same as previous version) ...
        try:
            loc = element.location; sz = element.size; top_m = 0.15; bot_m = 0.85 # Margins
            top_b = window_height * top_m; bot_b = window_height * bot_m
            el_top = loc['y']; el_bot = el_top + sz['height']
            is_vis = el_top >= top_b and el_bot <= bot_b and element.is_displayed()
            logger.debug(f"Visibility check for element at y={el_top}, h={sz['height']}: FullyVis={is_vis} (Bounds:{top_b:.0f}-{bot_b:.0f})")
            return is_vis
        except: return False


    def _select_card_to_click(
        self, unprocessed_cards_data: List[Dict[str, Any]], window_height: int
    ) -> Optional[Tuple[Dict[str, Any], WebElement]]:
        if not unprocessed_cards_data: return None
        
        candidates = []
        screen_center_y = window_height / 2

        for card_data in unprocessed_cards_data:
            booking_id = card_data.get('booking_id')
            if not booking_id: continue

            # Element must be clickable and fully visible to be a candidate
            try:
                # Construct selector carefully based on how content-desc is formed by mja_parser
                # The mja_parser now puts the status into 'card_status' field.
                # The raw content-desc might or might not have the status prefix.
                # We need to find the element based on its MJA ID primarily.
                click_selector = f'//android.view.ViewGroup[@content-desc and contains(@content-desc, "{booking_id}")]'
                
                # Stricter: find based on exact start if no prefix, or with prefix
                # card_status_val = card_data.get('card_status').value if card_data.get('card_status') else BookingCardStatus.NORMAL.value
                # desc_prefix_for_find = f"{card_status_val}, " if card_status_val not in [BookingCardStatus.NORMAL.value, BookingCardStatus.UNKNOWN.value] else ""
                # click_selector = f'//android.view.ViewGroup[starts-with(@content-desc, "{desc_prefix_for_find}{booking_id}")]'

                element = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((AppiumBy.XPATH, click_selector))
                )
                if self._is_element_fully_visible(element, window_height):
                    loc = element.location
                    sz = element.size
                    el_center_y = loc['y'] + (sz['height'] / 2)
                    candidates.append({'data': card_data, 'element': element, 'distance': abs(el_center_y - screen_center_y)})
                else:
                    logger.debug(f"Card {booking_id} (Status: {card_data.get('card_status', {}).get('value', 'N/A')}) found but not fully visible for click.")
            except (TimeoutException, NoSuchElementException):
                logger.warning(f"Could not locate clickable element for {booking_id} with selector: {click_selector}")
            except Exception as e_loc:
                logger.error(f"Error locating element for {booking_id}: {e_loc}")
        
        if not candidates:
            logger.info("No suitable (fully visible, clickable) 'Normal' unprocessed cards found.")
            return None
        
        candidates.sort(key=lambda x: x['distance']) # Closest to center
        selected = candidates[0]
        logger.info(f"Selected card {selected['data']['booking_id']} (Status: {selected['data'].get('card_status').value}) to click.")
        return selected['data'], selected['element']

    def process(self, is_initial_entry=True) -> ScrapeState:
        logger.info(f"Processing State: LIST (Display {self.target_display_id_str}, Initial Entry: {is_initial_entry})")
        session_id_str = f"session_{self.state_manager.session_id if self.state_manager else 'unknown'}"

        if is_initial_entry:
            self.processed_ids_this_cycle.clear()
            self.scroll_attempts = 0 # Reset scroll attempts on a truly fresh list view (e.g., after detail page)
            if DUMP_XML_MODE and self.driver:
                 try: save_xml_dump(self.driver.page_source, "MJA_list", session_id_str, sequence_or_stage="initial_view_00")
                 except Exception as e: logger.error(f"Could not dump initial list XML: {e}")
        
        if not self._ensure_on_list_page(initial_check=is_initial_entry): # Only do thorough check on initial entry
            self.state_manager.update_state(ScrapeState.ERROR, error_message="Failed to ensure on list page"); return ScrapeState.ERROR
        
        try:
            self._apply_display_setting()
            cards_on_screen_data = self.list_page.get_cards() # Gets parsed data from XML
            logger.info(f"Found data for {len(cards_on_screen_data)} cards on screen via XML.")

            if not cards_on_screen_data:
                 if self.scroll_attempts == 0 and is_initial_entry: 
                     self.state_manager.update_state(ScrapeState.ERROR, error_message="No cards on list page initially"); return ScrapeState.ERROR
                 else: 
                     logger.warning("ListPage.get_cards returned no card data. Will proceed to scroll/finish logic.")
            
            unprocessed_for_click_candidates_data: List[Dict[str, Any]] = []
            window_height = self.driver.get_window_size()['height']
            current_view_last_good_anchor_id: Optional[str] = None
            any_new_unprocessed_card_found_on_screen = False

            if cards_on_screen_data:
                for card_data in cards_on_screen_data:
                    booking_id = card_data.get('booking_id')
                    card_status_enum = card_data.get('card_status', BookingCardStatus.NORMAL)
                    if not booking_id: continue 

                    logger.debug(f"Evaluating Card MJA: {booking_id}, Parsed List Status: {card_status_enum.value if card_status_enum else 'N/A'}")

                    skip_this_card_for_processing = False
                    
                    # Check if MJA was clicked in this session (for XML dump mode primarily, or if we want to avoid re-clicking within a session)
                    if booking_id in self.session_clicked_mja_ids:
                        logger.debug(f"Card {booking_id} already in session_clicked_mja_ids. Skipping for click.")
                        skip_this_card_for_processing = True
                    
                    # Check if this MJA's parent MJR has been fully processed this session (efficiency)
                    if not skip_this_card_for_processing:
                        mjr_id_for_card = get_mjr_id_for_mja(self.conn, booking_id) # Assumes MJA base data is in DB
                        if mjr_id_for_card and mjr_id_for_card in self.session_fully_processed_mjr_ids:
                            logger.info(f"Card {booking_id} (MJR: {mjr_id_for_card}) belongs to an MJR already fully processed this session. Skipping detailed scrape.")
                            update_booking_status(self.conn, booking_id, BookingProcessingStatus.SCRAPED.value, "Skipped, MJR processed this session")
                            skip_this_card_for_processing = True
                        elif mjr_id_for_card and check_if_all_mjas_for_mjr_scraped(self.conn, mjr_id_for_card) : # Check DB for full MJR completion
                             logger.info(f"Card {booking_id} (MJR: {mjr_id_for_card}) belongs to an MJR already fully scraped in DB. Adding to session processed MJRs and skipping.")
                             self.session_fully_processed_mjr_ids.add(mjr_id_for_card)
                             skip_this_card_for_processing = True


                    # If already processed in current view cycle (e.g. seen, determined skippable, now re-evaluating view after no click)
                    if booking_id in self.processed_ids_this_cycle and not skip_this_card_for_processing:
                        logger.debug(f"Card {booking_id} already in processed_ids_this_cycle. Not re-adding to click candidates unless forced.")
                        # This state means we saw it, decided not to click or couldn't, and are now re-evaluating the screen.
                        # It should not be re-added to click candidates unless it's the only option left after a scroll.
                        # For now, if it's in this_cycle, it means it was handled or deemed unclickable.

                    if skip_this_card_for_processing:
                        if booking_id not in self.processed_ids_this_cycle: self.processed_ids_this_cycle.add(booking_id)
                        # Try to update scroll anchor even for skipped cards if they are visible
                        try:
                            temp_el = self.driver.find_element(AppiumBy.XPATH, f'//android.view.ViewGroup[@content-desc and contains(@content-desc, "{booking_id}")]')
                            if self._is_element_fully_visible(temp_el, window_height): current_view_last_good_anchor_id = booking_id
                        except: pass
                        continue

                    # If not skipped by any of the above, it's a new, unprocessed card for this view cycle
                    any_new_unprocessed_card_found_on_screen = True
                    self.processed_ids_this_cycle.add(booking_id) # Mark as seen in this cycle

                    # Handle based on card status parsed from list
                    if card_status_enum == BookingCardStatus.CANCELLED:
                        logger.info(f"Booking {booking_id} is CANCELLED on list. Saving base info, status, and skipping detail scrape.")
                        insert_booking_base(self.conn, card_data) # Will set status to 'cancelled_on_list'
                        self.session_clicked_mja_ids.add(booking_id) # Consider it "handled" for the session
                        current_view_last_good_anchor_id = booking_id
                        continue
                    
                    if card_status_enum in [BookingCardStatus.NEW_OFFER, BookingCardStatus.VIEWED]:
                        logger.info(f"Booking {booking_id} is '{card_status_enum.value}' on list. Saving base info, status, and skipping detail scrape.")
                        insert_booking_base(self.conn, card_data) # Save its presence and status from list
                        update_booking_status(self.conn, booking_id, BookingProcessingStatus.SKIPPED_OFFER_VIEWED.value, f"Card status: {card_status_enum.value}")
                        self.session_clicked_mja_ids.add(booking_id)
                        current_view_last_good_anchor_id = booking_id
                        continue
                    
                    if card_status_enum == BookingCardStatus.NORMAL: # Or any other status that requires full processing
                        logger.debug(f"Card {booking_id} is Normal/Processable. Adding to click candidates.")
                        unprocessed_for_click_candidates_data.append(card_data)
                    else: # Unknown status, treat as seen but not for click
                        logger.warning(f"Card {booking_id} has unhandled status '{card_status_enum.value}'. Marking as processed for this cycle.")
                        current_view_last_good_anchor_id = booking_id
                
                if current_view_last_good_anchor_id: self.last_good_scroll_anchor_id = current_view_last_good_anchor_id
                elif cards_on_screen_data : self.last_good_scroll_anchor_id = cards_on_screen_data[-1].get('booking_id') # Fallback

            if any_new_unprocessed_card_found_on_screen:
                logger.debug("New unprocessed cards (not skipped by session logic) were found on this screen view. Resetting scroll_attempts.")
                self.scroll_attempts = 0 
            
            logger.info(f"Found {len(unprocessed_for_click_candidates_data)} 'Normal' (or processable) cards for potential click.")
            selected_card_tuple = None
            if unprocessed_for_click_candidates_data:
                selected_card_tuple = self._select_card_to_click(unprocessed_for_click_candidates_data, window_height)

            if selected_card_tuple:
                selected_card_data, clickable_element = selected_card_tuple
                booking_id_to_click = selected_card_data['booking_id']
                
                insert_booking_base(self.conn, selected_card_data) # Ensure base record exists or is updated
                self.session_clicked_mja_ids.add(booking_id_to_click) # Mark as clicked for this session
                self.last_good_scroll_anchor_id = booking_id_to_click # Update scroll anchor
                
                self.state_manager.update_state(ScrapeState.SECONDARY, current_booking_id=booking_id_to_click, last_processed_booking_id=booking_id_to_click)
                try:
                    logger.info(f"Attempting click on selected card {booking_id_to_click}")
                    clickable_element.click()
                    logger.info(f"Clicked card {booking_id_to_click}")
                    time.sleep(1.5) # Wait for navigation
                    return ScrapeState.SECONDARY
                except StaleElementReferenceException:
                    logger.warning(f"Element for {booking_id_to_click} became stale before click. Retrying LIST.")
                    self.processed_ids_this_cycle.remove(booking_id_to_click) # Allow re-evaluation
                    self.session_clicked_mja_ids.discard(booking_id_to_click)
                    self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None) # Stay on list, force re-process
                    return ScrapeState.LIST
                except Exception as click_e:
                    logger.exception(f"Click error for {booking_id_to_click}: {click_e}")
                    update_booking_status(self.conn, booking_id_to_click, BookingProcessingStatus.ERROR_LIST.value, f"Click error: {click_e}")
                    self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Click error on {booking_id_to_click}")
                    return ScrapeState.ERROR
            else: # No card was selected for click (none suitable, or all skippable and no new ones)
                logger.info("No suitable card was selected to click on this screen view.")
                # If we didn't click, and we know there were no *new* processable items, it's an unproductive view.
                if not any_new_unprocessed_card_found_on_screen and cards_on_screen_data: # Screen had cards, but all were "old"
                    self.scroll_attempts += 1
                    logger.debug(f"Incremented scroll_attempts to {self.scroll_attempts} as no new processable cards were found.")
                # If cards_on_screen_data was empty, scroll_attempts might also increment below if not at max.

            # Scroll Action: If no card was clicked
            if self.scroll_attempts >= self.max_scroll_attempts:
                logger.info(f"Max scroll attempts ({self.max_scroll_attempts}) reached without finding new items to click or process. Finishing.")
                self.state_manager.finish_session(status='completed_max_scrolls')
                return ScrapeState.FINISHED
            else:
                # Increment scroll_attempts if we are scrolling because no click happened AND we haven't already incremented it
                # due to 'any_new_unprocessed_card_found_on_screen' being false.
                # This condition is tricky; the main idea is: if a scroll is about to happen, it counts as an attempt.
                # The reset of scroll_attempts now happens if any_new_unprocessed_card_found_on_screen is true.
                # If it's false, we are in a scroll-due-to-no-new-items scenario.
                if not selected_card_tuple and not any_new_unprocessed_card_found_on_screen and cards_on_screen_data:
                    # This case is already handled by incrementing above.
                    pass
                elif not selected_card_tuple: # If no click happened for other reasons (e.g. visibility) or empty screen.
                    self.scroll_attempts += 1 

                logger.info(f"Attempting scroll (current attempt: {self.scroll_attempts}/{self.max_scroll_attempts})")
                try:
                    logger.debug(f"Using anchor '{self.last_good_scroll_anchor_id}' for scroll.")
                    self.list_page.scroll(self.last_good_scroll_anchor_id) # list_page.scroll handles its own timing
                    if DUMP_XML_MODE and self.driver: save_xml_dump(self.driver.page_source, "MJA_list", session_id_str, sequence_or_stage=f"scroll_{self.scroll_attempts:02d}")
                    if self.crawler_service: self.crawler_service.take_screenshot_on_display(str(self.target_display_id_str), os.path.join(self.screenshot_dir, f"after_scroll_{self.scroll_attempts}.png"))
                    logger.debug("Waiting after scroll..."); time.sleep(2.0) # Wait for UI to settle after scroll
                    self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None) # Stay on LIST, but not initial entry
                    return ScrapeState.LIST
                except Exception as scroll_e:
                    logger.exception(f"Scroll error: {scroll_e}")
                    self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Scroll error: {scroll_e}")
                    return ScrapeState.ERROR
        except Exception as e:
            logger.exception(f"ListProcessor error: {e}")
            self.state_manager.update_state(ScrapeState.ERROR, error_message=f"ListProcessor unhandled error: {e}")
            return ScrapeState.ERROR