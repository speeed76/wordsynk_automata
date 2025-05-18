# filename: pages/list_page.py
import time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException
)
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from lxml import etree
from parsers.mja_parser import parse_mja # This will now handle status prefixes
from logger import get_logger
from typing import List, Dict, Any, Optional

logger = get_logger(__name__)

class ListPage:
    """
    Page Object for the main booking list screen.
    Uses efficient XML parsing of page_source for data extraction.
    Handles scrolling of the list.
    """
    CARD_CONTAINER_SELECTOR = 'androidx.recyclerview.widget.RecyclerView'
    # XPath to find ViewGroup elements that are likely booking cards based on having a content-desc
    # We will rely on parse_mja to validate if it's a true booking card
    BOOKING_CARD_XPATH = '//android.view.ViewGroup[@content-desc]'


    def __init__(self, driver):
        self.driver = driver

    def is_displayed(self, timeout=5) -> bool:
        """Checks if the main list container is visible."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((AppiumBy.CLASS_NAME, self.CARD_CONTAINER_SELECTOR))
            )
            logger.debug("List page container is displayed.")
            return True
        except TimeoutException:
            logger.debug("List page container not displayed within timeout.")
            return False
        except Exception as e:
            logger.error(f"Error checking if list page is displayed: {e}")
            return False

    def get_cards(self) -> List[Dict[str, Any]]:
        """
        Finds all potential booking cards by parsing the page source XML
        and passes their content-desc to the mja_parser.
        The mja_parser will determine if it's a valid card and extract data including status.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, where each dictionary
                                  contains the parsed data for a booking card.
        """
        cards_data = []
        logger.info("Getting list page cards using XML parsing...")
        try:
            if not self.is_displayed(timeout=3):
                logger.error("List page container not found before getting page source for cards.")
                return cards_data

            page_source = self.driver.page_source
            if not page_source:
                logger.error("Failed to get page source for list page.")
                return cards_data

            xml_root = etree.fromstring(page_source.encode('utf-8'))
            card_nodes = xml_root.xpath(self.BOOKING_CARD_XPATH)
            logger.debug(f"Found {len(card_nodes)} potential card nodes via XPath on XML source (ViewGroup with content-desc).")

            for node in card_nodes:
                content_desc = node.get('content-desc', '')
                if content_desc: # Process any non-empty content-desc
                    logger.debug(f"Processing content-desc: '{content_desc}'")
                    try:
                        # parse_mja will handle status prefixes and MJA ID extraction
                        parsed_info = parse_mja(content_desc)
                        if parsed_info and parsed_info.get('booking_id'):
                            cards_data.append(parsed_info)
                            logger.debug(f"Successfully parsed card: {parsed_info.get('booking_id')}, Status: {parsed_info.get('card_status').value}")
                        elif parsed_info and parsed_info.get('card_status') == BookingCardStatus.CANCELLED and parsed_info.get('booking_id') is None:
                            # Handle case where parser identified 'Cancelled' but no MJA ID
                            logger.warning(f"Found a 'Cancelled' card with no MJA ID in content-desc: '{content_desc}'. Storing minimal info.")
                            cards_data.append(parsed_info) # Store to record cancellation
                        # else: # parse_mja returning None means it wasn't a valid MJA card entry
                            # logger.debug(f"Content-desc '{content_desc}' did not parse to a valid MJA card.")

                    except Exception as parse_e:
                        logger.error(f"Error parsing content-desc '{content_desc}': {parse_e}")
        except etree.XMLSyntaxError as xml_e:
            logger.error(f"Failed to parse page source XML: {xml_e}")
        except TimeoutException:
            logger.warning("List page container not found for get_cards.")
        except Exception as e:
            logger.exception(f"An unexpected error occurred in get_cards: {e}")

        logger.info(f"Successfully extracted data for {len(cards_data)} cards from list page XML source.")
        return cards_data

    def scroll(self, last_element_booking_id: Optional[str] = None, direction: str = 'down'):
        """
        Performs a scroll gesture, prioritizing anchoring to the last known element
        or the scroll container, with refined coordinates and percentage.
        """
        try:
            logger.debug(f"Scrolling {direction}...")
            scroll_anchor_element = None
            element_to_scroll_id = None

            if last_element_booking_id:
                 try:
                      # This selector needs to find the element regardless of prefix, using contains MJA ID
                      last_elem_selector = f'//android.view.ViewGroup[@content-desc and contains(@content-desc, "{last_element_booking_id}")]'
                      scroll_anchor_element = WebDriverWait(self.driver, 2).until(
                          EC.presence_of_element_located((AppiumBy.XPATH, last_elem_selector))
                      )
                      element_to_scroll_id = scroll_anchor_element.id
                      logger.debug(f"Found element containing {last_element_booking_id} to use as scroll anchor.")
                 except (NoSuchElementException, TimeoutException):
                      logger.warning(f"Could not re-find element containing {last_element_booking_id} for scroll. Attempting container scroll.")
                      element_to_scroll_id = None

            if not element_to_scroll_id: # Fallback to container
                try:
                    container_element = WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((AppiumBy.CLASS_NAME, self.CARD_CONTAINER_SELECTOR))
                    )
                    element_to_scroll_id = container_element.id
                    logger.debug(f"Using {self.CARD_CONTAINER_SELECTOR} container as scroll anchor.")
                except (NoSuchElementException, TimeoutException):
                    logger.warning(f"Could not find {self.CARD_CONTAINER_SELECTOR} container. Falling back to coordinate-based scroll.")
                    element_to_scroll_id = None

            scroll_percent = 0.6

            if element_to_scroll_id:
                try:
                    self.driver.execute_script('mobile: scrollGesture', {
                        'elementId': element_to_scroll_id,
                        'direction': direction,
                        'percent': scroll_percent
                    })
                    logger.debug(f"Scrolled using elementId: {element_to_scroll_id} with percent: {scroll_percent}")
                    time.sleep(1); return
                except Exception as el_scroll_e:
                    logger.warning(f"Could not scroll using elementId ('{el_scroll_e}'). Falling back to coordinate-based scroll.")

            logger.debug("Performing coordinate-based screen scroll with refined bounds.")
            size = self.driver.get_window_size()
            start_x = size['width'] // 2
            start_y = int(size['height'] * 0.7); end_y = int(size['height'] * 0.3)
            scroll_gesture_height = start_y - end_y

            if scroll_gesture_height <= 0:
                 logger.error(f"Calculated scroll gesture height ({scroll_gesture_height}) is not positive. Cannot scroll by coordinates.")
                 return

            self.driver.execute_script('mobile: scrollGesture', {
                'left': start_x, 'top': start_y, 'width': 1,
                'height': scroll_gesture_height,
                'direction': direction,
                'percent': 1.0
            })
            logger.debug(f"Scrolled using coordinates from y={start_y} to y={end_y} (gesture height: {scroll_gesture_height}).")
            time.sleep(1)

        except Exception as e:
            logger.exception(f"An error occurred during the scroll operation: {e}")