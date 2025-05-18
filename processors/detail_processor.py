# filename: processors/detail_processor.py
import sqlite3
import time
from logger import get_logger
from pages.detail_page import DetailPage
from state.models import ScrapeState
from state.manager import StateManager
from parsers.detail_parser import (
    parse_detail_data, check_if_multiday_from_xml, _extract_texts_from_xml,
    extract_header_and_booking_type, extract_info_block,
    extract_mja_payment_blocks, extract_notes_and_total
)
from db.repository import (
    save_booking_details, update_booking_status,
    get_secondary_hints_for_mjr, update_hints_for_mjr
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

logger = get_logger(__name__)

class DetailProcessor:
    def __init__(self, driver, conn, det_page: DetailPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: 'CrawlerService' = None):
        self.driver = driver; self.conn = conn; self.det_page = det_page; self.state_manager = state_manager
        self.target_display_id_str = target_display_id; self.crawler_service = crawler_service
        self.current_scrape_attempt = 1
        self.disclaimer_selector = 'new UiSelector().textStartsWith("By accepting this assignment")'
        self.max_scrolls = 7
        self.list_page_container_selector = '//androidx.recyclerview.widget.RecyclerView'

    def _navigate_back_to_list(self) -> ScrapeState:
        # ... (Same as previous full version)
        try:
            logger.info("Navigating back to list page (Detail -> Secondary -> List)...")
            logger.debug("Executing first back() command."); self.driver.back(); time.sleep(0.8)
            logger.debug("Executing second back() command."); self.driver.back(); time.sleep(1.2)
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector)))
                logger.info("Navigation successful: Confirmed back on list page.")
            except TimeoutException:
                logger.warning("Did not confirm list page. Trying one more back().")
                try: self.driver.back(); time.sleep(1.5); WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector))); logger.info("Confirmed back on list page after third back().")
                except: logger.error("Still not on list page after third back().")
            self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None, current_mjr_id=None)
            return ScrapeState.LIST
        except Exception as nav_e: logger.exception(f"Failed during back navigation: {nav_e}"); self.state_manager.update_state(ScrapeState.ERROR); return ScrapeState.ERROR


    def _is_disclaimer_visible(self) -> bool:
        # ... (Same as previous full version)
        try: WebDriverWait(self.driver, 0.2).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, self.disclaimer_selector))); return True
        except: return False


    def _apply_display_setting(self):
        # ... (Same as previous full version)
        if self.target_display_id_str == "0" or not self.target_display_id_str: return
        try: self.driver.update_settings({"displayId": int(self.target_display_id_str)})
        except ValueError: logger.warning(f"Target display ID '{self.target_display_id_str}' not an int.")
        except Exception as e: logger.error(f"Failed to apply displayId setting: {e}")

    def _get_current_texts_and_source(self) -> Tuple[List[str], str]:
        # ... (Same as previous full version)
        page_source = ""; texts = []
        try:
            self._apply_display_setting()
            page_source = self.driver.page_source
            if not page_source: logger.error("Failed to get page source for detail page."); return [], ""
            texts = _extract_texts_from_xml(page_source)
        except Exception as e: logger.exception(f"Unexpected error getting page source/texts: {e}")
        return texts, page_source


    def process(self) -> ScrapeState:
        current_mja_in_state = self.state_manager.current_booking_id
        current_mjr_from_state = self.state_manager.current_mjr_id
        logger.info(f"Processing State: DETAIL (Display {self.target_display_id_str}, MJA: {current_mja_in_state}, MJR: {current_mjr_from_state})")
        
        if not self.det_page.is_displayed(timeout=2):
            logger.warning(f"Resumed/Entered DETAIL state for MJR {current_mjr_from_state} but not on detail page. Resetting to NAVIGATING_TO_LIST.")
            self.state_manager.update_state(ScrapeState.NAVIGATING_TO_LIST, current_booking_id=None, current_mjr_id=None)
            return ScrapeState.NAVIGATING_TO_LIST

        header_info, info_block, all_mja_blocks, notes_total_info = {}, {}, [], {}
        is_multiday = False; lang_idx = None; mjr_id_final = current_mjr_from_state
        try:
            logger.info("Waiting for detail page elements to be fully ready..."); self.det_page.wait_until_displayed(timeout=10)
            initial_texts, initial_page_source = self._get_current_texts_and_source()
            if not initial_page_source: raise ValueError("Failed to get initial page source from detail page.")
            
            header_info, is_multiday, lang_idx = extract_header_and_booking_type(initial_texts)
            parsed_mjr_from_header = header_info.get('mjr_id_raw')
            if parsed_mjr_from_header:
                if mjr_id_final and mjr_id_final != parsed_mjr_from_header: logger.warning(f"State MJR ({mjr_id_final}) != Parsed MJR ({parsed_mjr_from_header}). Using state.")
                elif not mjr_id_final: mjr_id_final = parsed_mjr_from_header
            if not mjr_id_final: mjr_id_final = current_mja_in_state if current_mja_in_state else "UNKNOWN_DETAIL_ID"
            logger.info(f"Initial Check: IsMultiday={is_multiday}, MJR ID='{mjr_id_final}'")
            if DUMP_XML_MODE: save_xml_dump(initial_page_source, "Detail_MJR", mjr_id_final, sequence_or_stage="initial_view_00")
            if lang_idx is None: raise ValueError(f"Critical anchor '{LANGUAGE_TEXT}' not found.")
            info_block = extract_info_block(initial_texts, lang_idx)

            logger.info("Starting scroll loop for payments..."); scroll_count = 0
            last_page_source_for_comparison = initial_page_source
            processed_mja_ids_session = set()
            while scroll_count < self.max_scrolls:
                current_texts, current_page_source = self._get_current_texts_and_source()
                if not current_page_source: logger.warning("Empty page source in scroll loop."); break
                if DUMP_XML_MODE and scroll_count > 0: save_xml_dump(current_page_source, "Detail_MJR", mjr_id_final, sequence_or_stage=f"scroll_{scroll_count:02d}")
                current_mja_blocks = extract_mja_payment_blocks(current_texts)
                for block in current_mja_blocks:
                    mja_id = block.get('mja'); is_s_frag = (mja_id is None and 'pay_sl' in block)
                    if mja_id and mja_id not in processed_mja_ids_session: all_mja_blocks.append(block); processed_mja_ids_session.add(mja_id); logger.info(f"  Added new MJA block: {mja_id}")
                    elif is_s_frag and not any(b.get('mja') is None for b in all_mja_blocks): all_mja_blocks.append(block); logger.info("  Added single day payment fragment.")
                if self._is_disclaimer_visible(): logger.info(f"Disclaimer found after {scroll_count} scrolls."); break
                if current_page_source == last_page_source_for_comparison and scroll_count > 0: logger.warning("Page source unchanged after scroll."); break
                last_page_source_for_comparison = current_page_source
                logger.debug("Scrolling detail page..."); size=self.driver.get_window_size(); start_x=size['width']//2
                start_y=int(size['height']*0.7); end_y=int(size['height']*0.3)
                try: self.driver.swipe(start_x, start_y, start_x, end_y, 800); time.sleep(1.5)
                except Exception as e_swipe: logger.error(f"Swipe error: {e_swipe}."); break
                scroll_count += 1
            else: logger.warning(f"Max scrolls ({self.max_scrolls}) reached.")

            final_texts, final_page_source_for_dump = self._get_current_texts_and_source()
            if DUMP_XML_MODE and final_page_source_for_dump and final_page_source_for_dump != last_page_source_for_comparison and scroll_count > 0 :
                 save_xml_dump(final_page_source_for_dump, "Detail_MJR", mjr_id_final, sequence_or_stage=f"final_view_{scroll_count:02d}")
            if final_texts: notes_total_info = extract_notes_and_total(final_texts)
            else: logger.error("Failed to get final texts for notes/total.")

            logger.info("Consolidating all extracted data...");
            parsed_data = parse_detail_data(header_info, is_multiday, info_block, all_mja_blocks, notes_total_info)
            logger.debug(f"Final Parsed Data (day_total: {parsed_data.get('day_total')}): {str(parsed_data)[:1000]}...")

            if not mjr_id_final or mjr_id_final == "UNKNOWN_DETAIL_ID":
                 mjr_id_final = parsed_data.get('mjr_id');
                 if not mjr_id_final: raise ValueError("MJR ID is still unknown after full parsing.")

            if is_multiday:
                logger.info(f"Processing MULTIDAY save for MJR ID: {mjr_id_final}")
                multiday_payments_parsed = parsed_data.get('multiday_payments', [])
                if not multiday_payments_parsed:
                    logger.warning(f"Multiday booking MJR {mjr_id_final}, but no payment details found.")
                    if current_mja_in_state: update_booking_status(self.conn, current_mja_in_state, 'error', f"Multiday {mjr_id_final} no MJA blocks parsed")
                else:
                    logger.info(f"Saving {len(multiday_payments_parsed)} MJA payment blocks for MJR {mjr_id_final}.")
                    for i, day_specific_data in enumerate(multiday_payments_parsed):
                        mja_id_from_day = day_specific_data.get('mja')
                        if not mja_id_from_day: continue
                        
                        # Construct booking_data for each MJA
                        booking_data = {
                            'mja_id': mja_id_from_day, 'mjr_id': mjr_id_final,
                            'processing_id': mjr_id_final, 'is_multiday': 1,
                            'appointment_sequence': i + 1,
                            # Common MJR-level info
                            'language_pair': parsed_data.get('language_pair'),
                            'client_name': parsed_data.get('client_name'),
                            'address': parsed_data.get('address'),
                            'booking_type': parsed_data.get('booking_type'),
                            'contact_name': parsed_data.get('contact_name'),
                            'contact_phone': parsed_data.get('contact_phone'),
                            'travel_distance': parsed_data.get('travel_distance'),
                            'meeting_link': parsed_data.get('meeting_link'),
                            'notes': parsed_data.get('notes'),
                            'overall_total': parsed_data.get('overall_total'),
                            # Day-specific fields from 'day_specific_data' (which is an item from 'multiday_payments')
                            'booking_date': day_specific_data.get('booking_date'), # Crucial fix
                            'start_time': day_specific_data.get('start_time'),     # Crucial fix
                            'end_time': day_specific_data.get('end_time'),         # Crucial fix
                            'duration': day_specific_data.get('duration'),       # Crucial fix
                            # Payment items for the day
                            **{f'day_{k}': v for k, v in day_specific_data.items() if k not in ['mja', 'booking_date', 'start_time', 'end_time', 'duration']},
                            'day_total': parsed_data.get('day_total'), # Average day total for the MJR
                            'status': 'scraped', 'scrape_attempt': self.current_scrape_attempt
                        }
                        save_booking_details(self.conn, booking_data, attempt_count=self.current_scrape_attempt)
                    
                    first_mja_id_in_sequence = multiday_payments_parsed[0].get('mja') if multiday_payments_parsed else None
                    if first_mja_id_in_sequence: # This implies processing_id was set on the first MJA of sequence
                        hints = get_secondary_hints_for_mjr(self.conn, mjr_id_final)
                        if hints: update_hints_for_mjr(self.conn, mjr_id_final, hints[0], hints[1])
                        else: logger.warning(f"Could not retrieve hints for MJR {mjr_id_final} to apply.")
            else: # Single Day
                 mja_id_to_save = parsed_data.get('mja_id') or current_mja_in_state # Use parsed MJA_ID first
                 if not mja_id_to_save : raise ValueError(f"Cannot save single day for MJR {mjr_id_final} - MJA ID missing.")
                 logger.info(f"Processing SINGLE DAY save for MJA: {mja_id_to_save} (MJR: {mjr_id_final})")
                 booking_data = parsed_data.copy() # parsed_data already has all necessary fields for single day
                 booking_data['mja_id'] = mja_id_to_save # Ensure this key is correct for save_booking_details
                 booking_data['is_multiday'] = 0
                 booking_data['appointment_sequence'] = 1
                 booking_data['processing_id'] = mjr_id_final # Link to MJR
                 booking_data['status'] = 'scraped'
                 booking_data['scrape_attempt'] = self.current_scrape_attempt
                 save_booking_details(self.conn, booking_data, attempt_count=self.current_scrape_attempt)
            return self._navigate_back_to_list()
        except Exception as e:
            logger.exception(f"Error processing detail page (MJR: {mjr_id_final or 'Unknown'} / MJA: {current_mja_in_state or 'Unknown'}): {e}")
            if current_mja_in_state: update_booking_status(self.conn, current_mja_in_state, 'error', f"Detail processing error: {str(e)[:200]}")
            self._navigate_back_to_list(); self.state_manager.update_state(ScrapeState.ERROR); return ScrapeState.ERROR