# filename: processors/detail_processor.py
import sqlite3
import time
from logger import get_logger
from pages.detail_page import DetailPage
from state.models import ScrapeState
from state.manager import StateManager
from parsers.detail_parser import (
    parse_detail_data, _extract_texts_from_xml, # Removed check_if_multiday_from_xml as it's not used here directly
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
    def __init__(self, driver, conn, det_page: DetailPage, state_manager: StateManager, target_display_id: str = "0", crawler_service: Optional['CrawlerService'] = None):
        self.driver = driver
        self.conn = conn
        self.det_page = det_page
        self.state_manager = state_manager
        self.target_display_id_str = target_display_id
        self.crawler_service = crawler_service
        self.current_scrape_attempt = 1 # Default, should be updated from state_manager if resuming
        self.disclaimer_selector = 'new UiSelector().textStartsWith("By accepting this assignment")'
        self.max_scrolls = 7 # Max scrolls to find disclaimer or end of content
        self.list_page_container_selector = '//androidx.recyclerview.widget.RecyclerView' # Used for back navigation check

    def _navigate_back_to_list(self) -> ScrapeState:
        try:
            logger.info("Navigating back to list page (Detail -> Secondary -> List)...")
            # First back: Detail to Secondary
            logger.debug("Executing first back() command.")
            self.driver.back()
            time.sleep(0.8) # Allow time for transition

            # Second back: Secondary to List
            logger.debug("Executing second back() command.")
            self.driver.back()
            time.sleep(1.2) # Allow time for transition

            # Confirm back on list page
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector))
                )
                logger.info("Navigation successful: Confirmed back on list page.")
            except TimeoutException:
                logger.warning("Did not confirm list page after two back() commands. Trying one more.")
                try:
                    self.driver.back()
                    time.sleep(1.5)
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((AppiumBy.XPATH, self.list_page_container_selector))
                    )
                    logger.info("Confirmed back on list page after third back().")
                except Exception as final_nav_e:
                    logger.error(f"Still not on list page after third back(). Error: {final_nav_e}")
                    # Even if not confirmed, proceed to update state to LIST and let ListProcessor re-evaluate
            
            self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None, current_mjr_id=None)
            return ScrapeState.LIST

        except Exception as nav_e:
            logger.exception(f"Failed during back navigation: {nav_e}")
            # Update state to error, but also attempt to set it to LIST to try recovery from there
            self.state_manager.update_state(ScrapeState.ERROR, error_message=f"Back navigation failed: {nav_e}")
            # self.state_manager.update_state(ScrapeState.LIST, current_booking_id=None, current_mjr_id=None) # Or attempt LIST
            return ScrapeState.ERROR


    def _is_disclaimer_visible(self) -> bool:
        try:
            WebDriverWait(self.driver, 0.2).until( # Very short timeout for a quick check
                EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, self.disclaimer_selector))
            )
            return True
        except TimeoutException:
            return False
        except Exception: # Catch any other error during check
            return False

    def _apply_display_setting(self):
        if self.target_display_id_str == "0" or not self.target_display_id_str:
            return
        try:
            self.driver.update_settings({"displayId": int(self.target_display_id_str)})
        except ValueError:
            logger.warning(f"Target display ID '{self.target_display_id_str}' not an int.")
        except Exception as e:
            logger.error(f"Failed to apply displayId setting: {e}")

    def _get_current_texts_and_source(self) -> Tuple[List[str], str]:
        page_source = ""
        texts: List[str] = []
        try:
            self._apply_display_setting() # Ensure correct display is targeted
            page_source = self.driver.page_source
            if not page_source:
                logger.error("Failed to get page source for detail page.")
                return [], ""
            texts = _extract_texts_from_xml(page_source)
        except Exception as e:
            logger.exception(f"Unexpected error getting page source/texts: {e}")
        return texts, page_source

    def process(self) -> ScrapeState:
        current_mja_in_state = self.state_manager.current_booking_id
        current_mjr_from_state = self.state_manager.current_mjr_id
        logger.info(f"Processing State: DETAIL (Display {self.target_display_id_str}, MJA: {current_mja_in_state}, MJR: {current_mjr_from_state})")
        
        # MODIFIED: Use wait_until_displayed for a more robust check immediately
        try:
            self.det_page.wait_until_displayed(timeout=10) # Increased timeout for initial page confirmation
            logger.info(f"Successfully confirmed on Detail Page for MJR {current_mjr_from_state}")
        except TimeoutException:
            logger.error(f"Failed to confirm Detail Page for MJR {current_mjr_from_state} even after 10s. Resetting to NAVIGATING_TO_LIST.")
            self.state_manager.update_state(ScrapeState.NAVIGATING_TO_LIST, current_booking_id=None, current_mjr_id=None, error_message="Detail page not found")
            return ScrapeState.NAVIGATING_TO_LIST # Or ScrapeState.ERROR directly if NAVIGATING_TO_LIST is problematic
        except Exception as page_load_e:
            logger.exception(f"Unexpected error confirming detail page: {page_load_e}")
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja_in_state, current_mjr_id=current_mjr_from_state, error_message=f"Detail page load error: {page_load_e}")
            return ScrapeState.ERROR


        header_info: Dict[str, Any] = {}
        info_block: Dict[str, Any] = {}
        all_mja_blocks: List[Dict[str, Any]] = []
        notes_total_info: Dict[str, Any] = {}
        is_multiday = False
        lang_idx: Optional[int] = None
        mjr_id_final = current_mjr_from_state # Initialize with state

        try:
            # Page is now confirmed, proceed with extraction
            initial_texts, initial_page_source = self._get_current_texts_and_source()
            if not initial_page_source:
                raise ValueError("Failed to get initial page source from detail page after confirmation.")
            
            header_info, is_multiday, lang_idx = extract_header_and_booking_type(initial_texts)
            parsed_mjr_from_header = header_info.get('mjr_id_raw')

            if parsed_mjr_from_header:
                if mjr_id_final and mjr_id_final != parsed_mjr_from_header:
                    logger.warning(f"State MJR ({mjr_id_final}) != Parsed MJR from header ({parsed_mjr_from_header}). Using state MJR.")
                elif not mjr_id_final: # If state didn't have MJR, use the one from header
                    mjr_id_final = parsed_mjr_from_header
            
            if not mjr_id_final: # Fallback if still no MJR ID
                mjr_id_final = current_mja_in_state if current_mja_in_state else "UNKNOWN_DETAIL_ID"
            
            logger.info(f"Initial Check: IsMultiday={is_multiday}, MJR ID='{mjr_id_final}'")

            if DUMP_XML_MODE:
                save_xml_dump(initial_page_source, "Detail_MJR", mjr_id_final, sequence_or_stage="initial_view_00")

            if lang_idx is None: # Language text is a critical anchor for info_block
                raise ValueError(f"Critical language anchor text not found in initial texts for MJR {mjr_id_final}.")
            
            info_block = extract_info_block(initial_texts, lang_idx)

            logger.info("Starting scroll loop for payments...")
            scroll_count = 0
            last_page_source_for_comparison = initial_page_source
            processed_mja_ids_in_this_detail_view = set() # Track MJAs seen in this specific detail page view

            # Scroll loop to gather all payment blocks
            while scroll_count < self.max_scrolls:
                current_texts_loop, current_page_source_loop = self._get_current_texts_and_source()
                if not current_page_source_loop:
                    logger.warning("Empty page source in scroll loop. Breaking scroll.")
                    break
                
                if DUMP_XML_MODE and scroll_count > 0: # Dump subsequent scrolls
                    save_xml_dump(current_page_source_loop, "Detail_MJR", mjr_id_final, sequence_or_stage=f"scroll_{scroll_count:02d}")

                current_mja_blocks_from_loop = extract_mja_payment_blocks(current_texts_loop)
                new_blocks_found_this_scroll = False
                for block in current_mja_blocks_from_loop:
                    mja_id_from_block = block.get('mja')
                    # For multiday, add if MJA ID is new. For single day (mja_id_from_block is None), add if no block is already present.
                    if mja_id_from_block and mja_id_from_block not in processed_mja_ids_in_this_detail_view:
                        all_mja_blocks.append(block)
                        processed_mja_ids_in_this_detail_view.add(mja_id_from_block)
                        new_blocks_found_this_scroll = True
                        logger.info(f"  Added new MJA block: {mja_id_from_block}")
                    elif not mja_id_from_block and not any(b.get('mja') is None for b in all_mja_blocks): # Single day payment fragment
                        all_mja_blocks.append(block)
                        new_blocks_found_this_scroll = True
                        logger.info("  Added single day payment fragment block.")
                
                if self._is_disclaimer_visible():
                    logger.info(f"Disclaimer found after {scroll_count} scrolls.")
                    break
                
                # Check if page source has changed to prevent infinite loops on static pages
                if current_page_source_loop == last_page_source_for_comparison and scroll_count > 0 and not new_blocks_found_this_scroll:
                    logger.warning("Page source unchanged after scroll and no new MJA blocks found. Breaking scroll.")
                    break
                last_page_source_for_comparison = current_page_source_loop
                
                logger.debug("Scrolling detail page...")
                size = self.driver.get_window_size()
                start_x = size['width'] // 2
                start_y = int(size['height'] * 0.7)
                end_y = int(size['height'] * 0.3)
                try:
                    self.driver.swipe(start_x, start_y, start_x, end_y, 800)
                    time.sleep(1.5) # Wait for content to load after swipe
                except Exception as e_swipe:
                    logger.error(f"Swipe error: {e_swipe}. Breaking scroll.")
                    break
                scroll_count += 1
            else: # Loop finished due to max_scrolls
                if not self._is_disclaimer_visible():
                    logger.warning(f"Max scrolls ({self.max_scrolls}) reached, disclaimer still not visible.")

            # Get final texts for notes and total after all scrolling
            final_texts, final_page_source_for_dump = self._get_current_texts_and_source()
            if DUMP_XML_MODE and final_page_source_for_dump and final_page_source_for_dump != last_page_source_for_comparison and scroll_count > 0:
                 save_xml_dump(final_page_source_for_dump, "Detail_MJR", mjr_id_final, sequence_or_stage=f"final_view_{scroll_count:02d}")
            
            if final_texts:
                notes_total_info = extract_notes_and_total(final_texts)
            else:
                logger.error("Failed to get final texts for notes/total extraction.")
                # Fallback: try to extract from last known good texts if final_texts failed
                if last_page_source_for_comparison == initial_page_source:
                    notes_total_info = extract_notes_and_total(initial_texts)
                else: # If scrolled, this is harder to recover, but try with last scrolled texts
                    temp_texts_for_notes, _ = self._get_current_texts_and_source() # Re-fetch in case it works now
                    notes_total_info = extract_notes_and_total(temp_texts_for_notes if temp_texts_for_notes else initial_texts)


            logger.info("Consolidating all extracted data...")
            parsed_data = parse_detail_data(header_info, is_multiday, info_block, all_mja_blocks, notes_total_info)
            logger.debug(f"Final Parsed Data (day_total: {parsed_data.get('day_total')}): {str(parsed_data)[:1000]}...")

            if not mjr_id_final or mjr_id_final == "UNKNOWN_DETAIL_ID": # Re-check mjr_id after full parsing
                 mjr_id_final = parsed_data.get('mjr_id')
                 if not mjr_id_final:
                     raise ValueError(f"MJR ID is still unknown after full parsing for MJA {current_mja_in_state}.")

            if is_multiday:
                logger.info(f"Processing MULTIDAY save for MJR ID: {mjr_id_final}")
                multiday_payments_parsed = parsed_data.get('multiday_payments', [])
                if not multiday_payments_parsed:
                    logger.warning(f"Multiday booking MJR {mjr_id_final}, but no MJA payment blocks parsed/found.")
                    if current_mja_in_state: # Update status of the MJA that led here
                        update_booking_status(self.conn, current_mja_in_state, 'error_detail_extract', f"Multiday MJR {mjr_id_final} no MJA payment blocks parsed")
                else:
                    logger.info(f"Saving {len(multiday_payments_parsed)} MJA payment blocks for MJR {mjr_id_final}.")
                    for i, day_specific_data in enumerate(multiday_payments_parsed):
                        mja_id_from_day_block = day_specific_data.get('mja')
                        if not mja_id_from_day_block:
                            logger.warning(f"Skipping a day payment block for MJR {mjr_id_final} due to missing MJA ID in block {i+1}.")
                            continue
                        
                        booking_data_for_day = {
                            'mja_id': mja_id_from_day_block, 'mjr_id': mjr_id_final,
                            'processing_id': mjr_id_final, 'is_multiday': 1,
                            'appointment_sequence': i + 1,
                            'language_pair': parsed_data.get('language_pair'),
                            'client_name': parsed_data.get('client_name'),
                            'address': parsed_data.get('address'),
                            'booking_type': parsed_data.get('booking_type'),
                            'contact_name': parsed_data.get('contact_name'),
                            'contact_phone': parsed_data.get('contact_phone'),
                            'travel_distance': parsed_data.get('travel_distance'), # MJR-level travel
                            'meeting_link': parsed_data.get('meeting_link'),
                            'notes': parsed_data.get('notes'), # MJR-level notes
                            'overall_total': parsed_data.get('overall_total'), # MJR-level total
                            'booking_date': day_specific_data.get('booking_date'),
                            'start_time': day_specific_data.get('start_time'), # Per-day if available
                            'end_time': day_specific_data.get('end_time'),     # Per-day if available
                            'duration': day_specific_data.get('duration'),   # Per-day if available
                            **{f'day_pay_{k}': v for k, v in day_specific_data.items() if k.startswith('pay_')}, # All day_pay_ items
                            'day_total': parsed_data.get('day_total'), # Average day total for the MJR
                            'status': 'scraped', 'scrape_attempt': self.state_manager.current_scrape_attempt
                        }
                        save_booking_details(self.conn, booking_data_for_day, attempt_count=self.state_manager.current_scrape_attempt)
                    
                    # Update hints for all MJA_IDs part of this MJR
                    hints = get_secondary_hints_for_mjr(self.conn, mjr_id_final) # Get hints from one of the MJAs (ideally the first)
                    if hints:
                        update_hints_for_mjr(self.conn, mjr_id_final, hints[0], hints[1])
                    else:
                        logger.warning(f"Could not retrieve hints for MJR {mjr_id_final} to apply to all its MJA parts.")
            else: # Single Day
                 mja_id_to_save = parsed_data.get('mja_id') or current_mja_in_state
                 if not mja_id_to_save:
                     raise ValueError(f"Cannot save single day for MJR {mjr_id_final} - MJA ID is missing.")
                 
                 logger.info(f"Processing SINGLE DAY save for MJA: {mja_id_to_save} (MJR: {mjr_id_final})")
                 single_day_booking_data = parsed_data.copy()
                 single_day_booking_data['mja_id'] = mja_id_to_save
                 single_day_booking_data['is_multiday'] = 0
                 single_day_booking_data['appointment_sequence'] = 1
                 single_day_booking_data['processing_id'] = mjr_id_final
                 single_day_booking_data['status'] = 'scraped'
                 single_day_booking_data['scrape_attempt'] = self.state_manager.current_scrape_attempt
                 save_booking_details(self.conn, single_day_booking_data, attempt_count=self.state_manager.current_scrape_attempt)
            
            self.state_manager.record_booking_scraped() # Increment session scrape count
            return self._navigate_back_to_list()

        except Exception as e:
            logger.exception(f"Error processing detail page (MJR: {mjr_id_final or 'Unknown'} / MJA: {current_mja_in_state or 'Unknown'}): {e}")
            error_message = f"Detail processing error: {str(e)[:200]}"
            if current_mja_in_state:
                update_booking_status(self.conn, current_mja_in_state, 'error_detail_extract', error_message)
            
            # Attempt to navigate back regardless of error during processing, then set error state
            self._navigate_back_to_list() 
            self.state_manager.update_state(ScrapeState.ERROR, current_booking_id=current_mja_in_state, current_mjr_id=current_mjr_from_state, error_message=error_message)
            return ScrapeState.ERROR