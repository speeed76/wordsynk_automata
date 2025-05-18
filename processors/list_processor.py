# filename: processors/list_processor.py
import os
from logger import get_logger
from db.repository import insert_booking_base, get_processed_booking_ids, update_booking_status
from pages.list_page import ListPage
from state.models import ScrapeState, BookingCardStatus, BookingProcessingStatus
from state.manager import StateManager
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import TimeoutException, StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple

from config import DUMP_XML_MODE
from utils.xml_dumper import save_xml_dump


if TYPE_CHECKING:
    from services.crawler_service import CrawlerService

logger = get_logger(__name__)

class ListProcessor:
    def __init__(self, driver, conn, list_page: ListPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: 'CrawlerService' = None):
        self.driver = driver
        self.conn = conn
        self.list_page = list_page
        self.state_manager = state_manager
        self.target_display_id_str = target_display_id
        self.crawler_service = crawler_service
        self.processed_ids_this_cycle = set()
        self.session_clicked_mja_ids = set()
        self.scroll_attempts = 0
        self.max_scroll_attempts = 3 # Default, can be configured
        self.last_good_scroll_anchor_id: Optional[str] = None
        self.screenshot_dir = "screenshots"
        if not os.path.exists(self.screenshot_dir):
             try: os.makedirs(self.screenshot_dir)
             except OSError as e: logger.error(f"Could not create screenshot dir '{self.screenshot_dir}': {e}")

    def _ensure_on_list_page(self, initial_check=False) -> bool:
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
        if self.target_display_id_str == "0" or not self.target_display_id_str: return
        try: self.driver.update_settings({"displayId": int(self.target_display_id_str)})
        except ValueError: logger.warning(f"Target display ID '{self.target_display_id_str}' not an int.")
        except Exception as e: logger.error(f"Failed to apply displayId setting: {e}")

    def _is_element_fully_visible(self, element: WebElement, window_height: int) -> bool:
        try:
            loc = element.location; sz = element.size; top_m = 0.15; bot_m = 0.85
            top_b = window_height * top_m; bot_b = window_height * bot_m
            el_top = loc['y']; el_bot = el_top + sz['height']
            is_vis = el_top >= top_b and el_bot <= bot_b and element.is_displayed()
            logger.debug(f"Visibility check for element at y={el_top}, h={sz['height']}: FullyVis={is_vis} (Bounds:{top_b:.0f}-{bot_b:.0f})")
            return is_vis
        except: return False

    def _select_card_to_click(
        self, unprocessed_cards: List[Dict[str, Any]], window_height: int
    ) -> Optional[Tuple[Dict[str, Any], WebElement]]:
        if not unprocessed_cards: return None
        candidates = []
        screen_center_y = window_height / 2
        for card_data in unprocessed_cards:
            booking_id = card_data.get('booking_id')
            if not booking_id: continue
            try:
                click_selector = f'//android.view.ViewGroup[@content-desc and contains(@content-desc, "{booking_id}")]'
                element = WebDriverWait(self.driver, 2).until(EC.element_to_be_clickable((AppiumBy.XPATH, click_selector)))
                if self._is_element_fully_visible(element, window_height):
                    loc = element.location; sz = element.size; el_center_y = loc['y'] + (sz['height'] / 2)
                    candidates.append({'data': card_data, 'element': element, 'distance': abs(el_center_y - screen_center_y)})
                else: logger.debug(f"Card {booking_id} (Normal) found but not fully visible for click.")
            except: pass
        if not candidates: logger.info("No suitable (fully visible, clickable) 'Normal' unprocessed cards found."); return None
        candidates.sort(key=lambda x: x['distance']); selected = candidates[0]
        logger.info(f"Selected card {selected['data']['booking_id']} (Status: Normal) to click.")
        return selected['data'], selected['element']

    def process(self, is_initial_entry=True) -> ScrapeState:
        logger.info(f"Processing State: LIST (Display {self.target_display_id_str}, Initial Entry: {is_initial_entry})")
        session_id_str = f"session_{self.state_manager.session_id if self.state_manager else 'unknown'}"

        if is_initial_entry:
            self.processed_ids_this_cycle.clear()
            # self.scroll_attempts = 0 # Reset scroll attempts on truly fresh list view
            # session_clicked_mja_ids is for the entire session in dump mode, not reset here
            if DUMP_XML_MODE and self.driver:
                 try: save_xml_dump(self.driver.page_source, "MJA_list", session_id_str, sequence_or_stage="initial_view_00")
                 except Exception as e: logger.error(f"Could not dump initial list XML: {e}")
        
        # If it's not an initial entry, it implies a scroll just happened or returning from error.
        # The scroll_attempts should have been managed by the previous call.
        # If it's the very first time (is_initial_entry=True), reset scroll_attempts.
        if is_initial_entry:
            self.scroll_attempts = 0


        if is_initial_entry and not self._ensure_on_list_page(initial_check=True):
            self.state_manager.update_state(ScrapeState.ERROR, error_message="Failed to ensure on list page"); return ScrapeState.ERROR
        
        all_processed_ids_db = get_processed_booking_ids(self.conn) if not DUMP_XML_MODE else set()

        try:
            self._apply_display_setting()
            cards_on_screen = self.list_page.get_cards()
            logger.info(f"Found data for {len(cards_on_screen)} cards on screen via XML.")

            if not cards_on_screen:
                 if self.scroll_attempts == 0 and is_initial_entry: # First ever view, no cards
                     self.state_manager.update_state(ScrapeState.ERROR, error_message="No cards on list page"); return ScrapeState.ERROR
                 else: # No cards after a scroll, or not initial entry (e.g. list was empty after processing all)
                     logger.warning("ListPage.get_cards returned no card data. Proceeding to scroll/finish logic.")
                     # Fall through to scroll/finish logic
            
            unprocessed_for_click_candidates = []
            window_height = self.driver.get_window_size()['height']
            temp_last_good_anchor = None
            any_new_unprocessed_card_found_on_screen = False # New flag

            if cards_on_screen: # Only process if cards were actually found
                for card_data in cards_on_screen:
                    booking_id = card_data.get('booking_id')
                    card_status_enum = card_data.get('card_status', BookingCardStatus.NORMAL)
                    if not booking_id: continue
                    logger.debug(f"Card {booking_id}: Parsed card_status_enum: {card_status_enum.value if card_status_enum else 'N/A'}")

                    skip_this_card = False
                    is_in_cycle = booking_id in self.processed_ids_this_cycle
                    
                    if DUMP_XML_MODE:
                        if booking_id in self.session_clicked_mja_ids: skip_this_card = True; logger.debug(f"Card {booking_id} already in DUMP_XML_MODE session_clicked_mja_ids. Skipping.")
                    else:
                        db_status_val = None; is_in_db_final = False
                        cursor = self.conn.cursor(); cursor.execute("SELECT status FROM bookings WHERE booking_id = ?", (booking_id,)); db_row = cursor.fetchone()
                        db_status_val = db_row[0] if db_row else None
                        is_in_db_final = db_status_val in [BookingProcessingStatus.SCRAPED.value, BookingProcessingStatus.CANCELLED_ON_LIST.value, BookingProcessingStatus.SKIPPED_OFFER_VIEWED.value]
                        if is_in_db_final: skip_this_card = True; logger.debug(f"Card {booking_id} already in final DB state ('{db_status_val}'). Skipping.")
                    
                    if is_in_cycle:
                        if not skip_this_card: logger.debug(f"Card {booking_id} already in processed_ids_this_cycle. Skipping.")
                        skip_this_card = True 

                    if skip_this_card:
                        if not is_in_cycle: self.processed_ids_this_cycle.add(booking_id)
                        try:
                             desc_prefix = f"{card_status_enum.value}, " if card_status_enum not in [BookingCardStatus.NORMAL, BookingCardStatus.UNKNOWN] else ""
                             element = self.driver.find_element(AppiumBy.XPATH, f'//android.view.ViewGroup[@content-desc and starts-with(@content-desc, "{desc_prefix}{booking_id}")]')
                             if self._is_element_fully_visible(element, window_height): temp_last_good_anchor = booking_id
                        except: pass
                        continue

                    any_new_unprocessed_card_found_on_screen = True # Found a card not skipped for being processed

                    if card_status_enum == BookingCardStatus.CANCELLED:
                        logger.info(f"Booking {booking_id} is CANCELLED. Saving base info only.")
                        insert_booking_base(self.conn, card_data)
                        self.processed_ids_this_cycle.add(booking_id); temp_last_good_anchor = booking_id
                        if DUMP_XML_MODE: self.session_clicked_mja_ids.add(booking_id)
                        continue 
                    if card_status_enum in [BookingCardStatus.NEW_OFFER, BookingCardStatus.VIEWED]:
                        logger.info(f"Booking {booking_id} is '{card_status_enum.value}'. Skipping full scrape.")
                        update_booking_status(self.conn, booking_id, BookingProcessingStatus.SKIPPED_OFFER_VIEWED.value, f"Card status: {card_status_enum.value}")
                        self.processed_ids_this_cycle.add(booking_id); temp_last_good_anchor = booking_id
                        if DUMP_XML_MODE: self.session_clicked_mja_ids.add(booking_id)
                        continue 
                    if card_status_enum == BookingCardStatus.NORMAL:
                        logger.debug(f"Card {booking_id} is Normal and unprocessed. Adding to click candidates.")
                        unprocessed_for_click_candidates.append(card_data)
                    else:
                        logger.warning(f"Card {booking_id} has unhandled status '{card_status_enum.value}'. Marking for this cycle.")
                        self.processed_ids_this_cycle.add(booking_id)

                if temp_last_good_anchor: self.last_good_scroll_anchor_id = temp_last_good_anchor
                elif cards_on_screen: self.last_good_scroll_anchor_id = cards_on_screen[-1].get('booking_id')
            
            # If we found any new, unprocessed card on screen (regardless of type or clickability for now)
            # it means the previous scroll (if any) was productive in bringing new items.
            if any_new_unprocessed_card_found_on_screen:
                logger.debug("New unprocessed cards were visible on this screen view. Resetting scroll_attempts.")
                self.scroll_attempts = 0 
            
            logger.info(f"Found {len(unprocessed_for_click_candidates)} 'Normal' unprocessed cards for potential click.")
            selection = None
            if unprocessed_for_click_candidates:
                selection = self._select_card_to_click(unprocessed_for_click_candidates, window_height)

            if selection:
                selected_card_data, clickable_element = selection
                # self.scroll_attempts = 0 # Already reset if any_new_unprocessed_card_found_on_screen
                booking_id_to_click = selected_card_data['booking_id']
                insert_booking_base(self.conn, selected_card_data)
                self.processed_ids_this_cycle.add(booking_id_to_click)
                if DUMP_XML_MODE: self.session_clicked_mja_ids.add(booking_id_to_click)
                self.last_good_scroll_anchor_id = booking_id_to_click
                self.state_manager.update_state(ScrapeState.SECONDARY, current_booking_id=booking_id_to_click, last_processed_booking_id=booking_id_to_click)
                try:
                    logger.info(f"Attempting click on selected card {booking_id_to_click}"); clickable_element.click(); logger.info(f"Clicked card {booking_id_to_click}"); time.sleep(1.5)
                    return ScrapeState.SECONDARY
                except StaleElementReferenceException: logger.warning(f"Element for {booking_id_to_click} stale."); self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None); return ScrapeState.LIST
                except Exception as click_e: logger.exception(f"Click error: {click_e}"); self.state_manager.update_state(ScrapeState.ERROR); return ScrapeState.ERROR
            else: # No 'Normal' card was selected for click (either none found, or none visible enough)
                logger.info("No suitable 'Normal' unprocessed card was selected to click on this screen.")
                # If no card was clicked, but new unprocessed items *were* seen, we already reset scroll_attempts.
                # If no card was clicked AND no new unprocessed items were seen at all (any_new_unprocessed_card_found_on_screen is False),
                # then we proceed to increment scroll_attempts if we scroll.

            # Scroll Action: Only if no card was selected for clicking
            if self.scroll_attempts >= self.max_scroll_attempts:
                logger.info(f"Max scroll attempts ({self.max_scroll_attempts}) reached without successful click. Finishing.")
                self.state_manager.finish_session(status='completed_max_scrolls'); return ScrapeState.FINISHED
            else:
                # Increment scroll_attempts ONLY if the screen had no new processable items *at all*
                # OR if it had new items, but none were clickable and we are forced to scroll.
                # The reset of scroll_attempts now happens if *any* new unprocessed card is found.
                # So, we should increment here if we are about to scroll because no click happened.
                if not selection: # If we didn't click anything
                    self.scroll_attempts += 1 
                
                logger.info(f"Attempting scroll (current attempt: {self.scroll_attempts}/{self.max_scroll_attempts})")
                try:
                    logger.debug(f"Using anchor '{self.last_good_scroll_anchor_id}' for scroll.")
                    self.list_page.scroll(self.last_good_scroll_anchor_id)
                    if DUMP_XML_MODE and self.driver: save_xml_dump(self.driver.page_source, "MJA_list", session_id_str, sequence_or_stage=f"scroll_{self.scroll_attempts:02d}")
                    if self.crawler_service: self.crawler_service.take_screenshot_on_display(str(self.target_display_id_str), os.path.join(self.screenshot_dir, f"after_scroll_{self.scroll_attempts}.png"))
                    logger.debug("Waiting after scroll..."); time.sleep(2.0)
                    self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None)
                    return ScrapeState.LIST
                except Exception as scroll_e: logger.exception(f"Scroll error: {scroll_e}"); self.state_manager.update_state(ScrapeState.ERROR); return ScrapeState.ERROR
        except Exception as e: logger.exception(f"ListProcessor error: {e}"); self.state_manager.update_state(ScrapeState.ERROR); return ScrapeState.ERROR