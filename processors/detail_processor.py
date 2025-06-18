# filename: processors/detail_processor.py
import sqlite3
import time
from logger import get_logger
from pages.detail_page import DetailPage
from state.models import ScrapeState, BookingProcessingStatus # Added BookingProcessingStatus
from state.manager import StateManager
from parsers.detail_parser import (
    parse_detail_data, _extract_texts_from_xml,
    extract_header_and_booking_type, extract_info_block,
    extract_mja_payment_blocks, extract_notes_and_total
)
from db.repository import (
    save_booking_details, update_booking_status,
    get_secondary_hints_for_mjr, update_hints_for_mjr, # Ensure this is used correctly
    get_mjr_id_for_mja, # New import for efficiency
    update_all_mja_statuses_for_mjr # New import for efficiency
)
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.webdriver.common.appiumby import AppiumBy
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING

from config import DUMP_XML_MODE
from utils.xml_dumper import save_xml_dump

if TYPE_CHECKING:
    from services.crawler_service import CrawlerService
    from processors.list_processor import ListProcessor # For type hinting list_processor

logger = get_logger(__name__)

class DetailProcessor:
    def __init__(self, driver, conn, det_page: DetailPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: Optional['CrawlerService'] = None):
        self.driver = driver
        self.conn = conn
        self.det_page = det_page
        self.state_manager = state_manager
        self.target_display_id_str = target_display_id
        self.crawler_service = crawler_service
        # self.current_scrape_attempt = 1 # Managed by state_manager now
        self.disclaimer_selector = 'new UiSelector().textStartsWith("By accepting this assignment")'
        self.max_scrolls = 7 
        self.list_page_container_selector = '//androidx.recyclerview.widget.RecyclerView'

    def _navigate_back_to_list(self) -> ScrapeState:
        # ... (Same as previous version, seems okay) ...
        try:
            logger.info("Navigating back to list page (Detail -> Secondary -> List)...")
            logger.debug("Executing first back() command."); self.driver.back(); time.sleep(0.8) 
            logger.debug("Executing second back() command."); self.driver.back(); time.sleep(1.2)
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector)))
                logger.info("Navigation successful: Confirmed back on list page.")
            except TimeoutException:
                logger.warning("Did not confirm list page after two back(). Trying one more.")
                try: self.driver.back(); time.sleep(1.5); WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector))); logger.info("Confirmed back on list page after third back().")
                except: logger.error("Still not on list page after third back().")
            self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None, current_mjr_id=None)
            return ScrapeState.LIST
        except Exception as nav_e: 
            logger.exception(f"Failed during back navigation: {nav_e}")
            self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Back navigation failed: {nav_e}")
            return ScrapeState.ERROR


    def _is_disclaimer_visible(self) -> bool:
        # ... (Same as previous version) ...
        try: WebDriverWait(self.driver, 0.2).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, self.disclaimer_selector))); return True
        except: return False

    def _apply_display_setting(self):
        # ... (Same as previous version) ...
        if self.target_display_id_str == "0" or not self.target_display_id_str: return
        try: self.driver.update_settings({"displayId": int(self.target_display_id_str)})
        except ValueError: logger.warning(f"Target display ID '{self.target_display_id_str}' not an int.")
        except Exception as e: logger.error(f"Failed to apply displayId setting: {e}")

    def _get_current_texts_and_source(self) -> Tuple[List[str], str]:
        # ... (Same as previous version) ...
        page_source = ""; texts = []
        try:
            self._apply_display_setting()
            page_source = self.driver.page_source
            if not page_source: logger.error("Failed to get page source for detail page."); return [], ""
            texts = _extract_texts_from_xml(page_source)
        except Exception as e: logger.exception(f"Unexpected error getting page source/texts: {e}")
        return texts, page_source

    def process(self) -> ScrapeState:
        current_mja_in_state = self.state_manager.current_booking_id # MJA that led us here
        current_mjr_from_state = self.state_manager.current_mjr_id
        logger.info(f"Processing State: DETAIL (Display {self.target_display_id_str}, MJA_trigger: {current_mja_in_state}, MJR: {current_mjr_from_state})")
        
        try:
            self.det_page.wait_until_displayed(timeout=10)
            logger.info(f"Successfully confirmed on Detail Page for MJR {current_mjr_from_state}")
        except TimeoutException:
            logger.error(f"Failed to confirm Detail Page for MJR {current_mjr_from_state}. Resetting.")
            self.state_manager.update_state(ScrapeState.NAVIGATING_TO_LIST, current_booking_id=None, current_mjr_id=None, error_message="Detail page not found after nav")
            return ScrapeState.NAVIGATING_TO_LIST
        except Exception as page_load_e:
            logger.exception(f"Unexpected error confirming detail page: {page_load_e}")
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja_in_state, current_mjr_id=current_mjr_from_state, error_message=f"Detail page load error: {page_load_e}")
            return ScrapeState.ERROR

        header_info: Dict[str, Any] = {}
        info_block: Dict[str, Any] = {}
        all_mja_blocks_raw: List[Dict[str, Any]] = [] # Raw blocks from parser
        notes_total_info: Dict[str, Any] = {}
        is_multiday = False
        lang_idx: Optional[int] = None
        mjr_id_final = current_mjr_from_state 

        try:
            initial_texts, initial_page_source = self._get_current_texts_and_source()
            if not initial_page_source:
                raise ValueError("Failed to get initial page source from detail page after confirmation.")
            
            header_info, is_multiday, lang_idx = extract_header_and_booking_type(initial_texts)
            parsed_mjr_from_header = header_info.get('mjr_id_raw')

            if parsed_mjr_from_header:
                if mjr_id_final and mjr_id_final != parsed_mjr_from_header:
                    logger.warning(f"State MJR ({mjr_id_final}) != Parsed MJR from header ({parsed_mjr_from_header}). Using state MJR.")
                elif not mjr_id_final: 
                    mjr_id_final = parsed_mjr_from_header
            
            if not mjr_id_final: 
                 # If still no mjr_id_final, try to get it from the DB using current_mja_in_state
                if current_mja_in_state:
                    mjr_id_final = get_mjr_id_for_mja(self.conn, current_mja_in_state)
                    if mjr_id_final:
                        logger.info(f"Retrieved MJR ID {mjr_id_final} from DB for MJA {current_mja_in_state}")
                    else: # Fallback if MJA not in DB or has no MJR yet
                        mjr_id_final = current_mja_in_state # Less ideal, but an identifier
                        logger.warning(f"Could not determine MJR ID from state or header, using MJA {current_mja_in_state} as fallback ID.")
                else: # No MJA trigger, no header MJR - this is problematic
                    mjr_id_final = "UNKNOWN_MJR_DETAIL"
                    logger.error("MJR ID could not be determined for Detail Page processing.")


            logger.info(f"Processing Detail for MJR: '{mjr_id_final}', IsMultiday={is_multiday}")

            if DUMP_XML_MODE:
                save_xml_dump(initial_page_source, "Detail_MJR", mjr_id_final, sequence_or_stage="initial_view_00")

            if lang_idx is None: 
                raise ValueError(f"Critical language anchor text not found for MJR {mjr_id_final}.")
            
            info_block = extract_info_block(initial_texts, lang_idx)

            # --- Scroll loop to gather all payment blocks ---
            scroll_count = 0
            last_page_source_for_comparison = initial_page_source
            # No need for processed_mja_ids_in_this_detail_view, extract_mja_payment_blocks will return all it finds
            
            # Initial extraction before any scrolling
            all_mja_blocks_raw = extract_mja_payment_blocks(initial_texts)

            if not self._is_disclaimer_visible() and not (is_multiday and len(all_mja_blocks_raw) >= header_info.get('appointment_count_hint', 1)): # Only scroll if needed
                logger.info("Starting scroll loop for more payments or disclaimer...")
                while scroll_count < self.max_scrolls:
                    current_texts_loop, current_page_source_loop = self._get_current_texts_and_source()
                    if not current_page_source_loop: logger.warning("Empty page source in scroll loop."); break
                    
                    if DUMP_XML_MODE and scroll_count >= 0: # Dump first scroll attempt too
                        save_xml_dump(current_page_source_loop, "Detail_MJR", mjr_id_final, sequence_or_stage=f"scroll_{scroll_count+1:02d}")

                    # Re-extract MJA blocks from the new view and merge/replace if more complete
                    # For simplicity, let's assume extract_mja_payment_blocks gets everything visible.
                    # A more robust approach would merge based on MJA IDs if blocks get split by scrolling.
                    # Current extract_mja_payment_blocks re-parses the whole visible text.
                    all_mja_blocks_raw = extract_mja_payment_blocks(current_texts_loop) 
                                        
                    if self._is_disclaimer_visible():
                        logger.info(f"Disclaimer found after {scroll_count + 1} scrolls.")
                        break
                    
                    if current_page_source_loop == last_page_source_for_comparison and scroll_count > 0:
                        logger.warning("Page source unchanged after scroll. Breaking scroll.")
                        break
                    last_page_source_for_comparison = current_page_source_loop
                    
                    logger.debug(f"Scrolling detail page (attempt {scroll_count + 1})...");
                    size = self.driver.get_window_size(); start_x=size['width']//2
                    start_y=int(size['height']*0.7); end_y=int(size['height']*0.3)
                    try: self.driver.swipe(start_x, start_y, start_x, end_y, 800); time.sleep(1.5)
                    except Exception as e_swipe: logger.error(f"Swipe error: {e_swipe}."); break
                    scroll_count += 1
                else:
                    if not self._is_disclaimer_visible():
                        logger.warning(f"Max scrolls ({self.max_scrolls}) reached, disclaimer not visible.")
            else:
                 logger.info("Skipping scroll loop: Disclaimer visible initially or all expected MJA blocks for multiday found.")


            final_texts_for_notes, final_page_source_for_dump = self._get_current_texts_and_source() # Get final state for notes
            if DUMP_XML_MODE and final_page_source_for_dump and final_page_source_for_dump != last_page_source_for_comparison and scroll_count > 0 :
                 save_xml_dump(final_page_source_for_dump, "Detail_MJR", mjr_id_final, sequence_or_stage=f"final_view_{scroll_count:02d}")
            
            if final_texts_for_notes:
                notes_total_info = extract_notes_and_total(final_texts_for_notes)
            else:
                logger.error("Failed to get final texts for notes/total extraction. Using initial texts as fallback.")
                notes_total_info = extract_notes_and_total(initial_texts)

            logger.info("Consolidating all extracted data...")
            # Pass all_mja_blocks_raw which contains all MJA payment dicts found on the page
            parsed_mjr_data = parse_detail_data(header_info, is_multiday, info_block, all_mja_blocks_raw, notes_total_info)
            
            # Ensure mjr_id_final is the one from the parsed data if available, otherwise stick to earlier determination
            mjr_id_final = parsed_mjr_data.get('mjr_id', mjr_id_final)
            if not mjr_id_final or mjr_id_final == "UNKNOWN_MJR_DETAIL":
                 raise ValueError(f"MJR ID is still unknown after full parsing for MJA trigger {current_mja_in_state}.")

            logger.debug(f"Final Parsed MJR Data for {mjr_id_final} (is_multiday: {is_multiday}): {str(parsed_mjr_data)[:1000]}...")

            if is_multiday:
                logger.info(f"Processing MULTIDAY save for MJR ID: {mjr_id_final}")
                multiday_payment_entries = parsed_mjr_data.get('multiday_payments', []) # This list now contains dicts with full data for each MJA day
                
                if not multiday_payment_entries:
                    logger.warning(f"Multiday booking MJR {mjr_id_final}, but no MJA payment entries derived by parser.")
                    # This might be an error if appointment_count_hint > 0
                    if current_mja_in_state:
                        update_booking_status(self.conn, current_mja_in_state, BookingProcessingStatus.ERROR_DETAIL_EXTRACT.value, f"Multiday MJR {mjr_id_final} no MJA payment entries")
                else:
                    logger.info(f"Saving {len(multiday_payment_entries)} MJA entries for MJR {mjr_id_final}.")
                    all_mjas_for_this_mjr_saved = True
                    for mja_day_data in multiday_payment_entries:
                        mja_id_for_this_day = mja_day_data.get('mja')
                        if not mja_id_for_this_day:
                            logger.error(f"Multiday entry for MJR {mjr_id_final} is missing MJA identifier. Data: {mja_day_data}")
                            all_mjas_for_this_mjr_saved = False
                            continue

                        # Merge common MJR data with specific MJA day data
                        db_record = {
                            **{k: v for k, v in parsed_mjr_data.items() if k not in ['multiday_payments', 'day_pay_sl', 'day_pay_td', 'day_pay_tt', 'day_pay_aep', 'day_pay_ooh', 'day_pay_urg', 'day_total', 'mja_id']}, # common MJR fields
                            **mja_day_data, # Per-MJA fields (mja, booking_date, day_pay_*, day_total for this MJA)
                            'mjr_id': mjr_id_final, # Ensure mjr_id is set
                            'processing_id': mjr_id_final,
                            'is_multiday': 1,
                            # appointment_sequence should be derived by ListProcessor based on card order or by db query
                            'status': BookingProcessingStatus.SCRAPED.value,
                            'scrape_attempt': self.state_manager.current_scrape_attempt
                        }
                        # appointment_sequence might need to be set based on index in loop if not in mja_day_data
                        if 'appointment_sequence' not in db_record or db_record['appointment_sequence'] is None:
                             db_record['appointment_sequence'] = multiday_payment_entries.index(mja_day_data) + 1


                        try:
                            save_booking_details(self.conn, db_record, attempt_count=self.state_manager.current_scrape_attempt)
                        except Exception as save_exc:
                            all_mjas_for_this_mjr_saved = False
                            logger.error(f"Failed to save MJA day {mja_id_for_this_day} for MJR {mjr_id_final}: {save_exc}")
                            update_booking_status(self.conn, mja_id_for_this_day, BookingProcessingStatus.ERROR_SAVE.value, str(save_exc)[:200])
                    
                    if all_mjas_for_this_mjr_saved:
                        logger.info(f"All MJA days for MJR {mjr_id_final} processed.")
                        # Mark this MJR as fully processed for this session to improve efficiency
                        if self.crawler_service:
                            list_processor: Optional['ListProcessor'] = self.crawler_service.processors.get(ScrapeState.LIST) #type: ignore
                            if list_processor and hasattr(list_processor, 'session_fully_processed_mjr_ids'):
                                list_processor.session_fully_processed_mjr_ids.add(mjr_id_final)
                                logger.info(f"Marked MJR {mjr_id_final} as fully processed for this session (efficiency).")
                        # Update status for all MJAs of this MJR if they were pending
                        update_all_mja_statuses_for_mjr(self.conn, mjr_id_final, BookingProcessingStatus.SCRAPED.value)

            else: # Single Day
                 mja_id_to_save = parsed_mjr_data.get('mja_id') or current_mja_in_state # MJA ID for the single day booking
                 if not mja_id_to_save:
                     raise ValueError(f"Cannot save single day for MJR {mjr_id_final} - MJA ID is missing from parsed data and state.")
                 
                 logger.info(f"Processing SINGLE DAY save for MJA: {mja_id_to_save} (MJR: {mjr_id_final})")
                 single_day_db_record = {
                     **parsed_mjr_data, # Contains all necessary fields including day_pay_* and day_total
                     'mja_id': mja_id_to_save, # Ensure it's the correct MJA ID
                     'mjr_id': mjr_id_final,
                     'processing_id': mjr_id_final,
                     'is_multiday': 0,
                     'appointment_sequence': 1,
                     'status': BookingProcessingStatus.SCRAPED.value,
                     'scrape_attempt': self.state_manager.current_scrape_attempt
                 }
                 del single_day_db_record['multiday_payments'] # Not applicable for single day
                 save_booking_details(self.conn, single_day_db_record, attempt_count=self.state_manager.current_scrape_attempt)
            
            self.state_manager.record_booking_scraped() 
            return self._navigate_back_to_list()

        except Exception as e:
            logger.exception(f"Error during detail page content processing (MJR: {mjr_id_final or 'Unknown'} / MJA_trigger: {current_mja_in_state or 'Unknown'}): {e}")
            error_message = f"Detail content processing error: {str(e)[:200]}"
            # Update status of the MJA that led to this detail page, if known
            if current_mja_in_state:
                update_booking_status(self.conn, current_mja_in_state, BookingProcessingStatus.ERROR_DETAIL_EXTRACT.value, error_message)
            
            self._navigate_back_to_list() 
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja_in_state, current_mjr_id=current_mjr_from_state, error_message=error_message)
            return ScrapeState.ERROR