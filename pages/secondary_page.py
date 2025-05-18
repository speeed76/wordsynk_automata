# filename: pages/secondary_page.py
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from parsers.secondary_parser import parse_secondary_page_data # Import the parser
from logger import get_logger
from typing import Optional, Dict, Any
import time

logger = get_logger(__name__)

class SecondaryPage:
    """
    Page Object for the secondary booking screen (MJB page).
    This page typically shows an MJB ID and a link to an MJR ID.
    """

    # --- Locators ---
    # Assuming a title or unique element that identifies this page.
    # This might be the MJB ID itself or a static title.
    # Using a generic approach for now; needs to be adapted to the actual app.
    # Example: A TextView containing "Booking #MJB"
    PAGE_TITLE_SELECTOR_TEXT_STARTS_WITH = "Booking #MJB" # Partial text for the title
    # Example: XPath for the clickable element leading to the MJR page
    # This is highly dependent on the app's structure.
    # It might be the element whose content-desc starts with "MJR"
    MJR_LINK_XPATH_TEMPLATE = '//android.view.ViewGroup[@content-desc and starts-with(@content-desc, "{mjr_id}")]'


    def __init__(self, driver):
        self.driver = driver

    def is_displayed(self, timeout=5) -> bool:
        """Checks if the secondary page title is visible."""
        try:
            # Check for an element that uniquely identifies the secondary page
            # Using text based locator as an example
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textStartsWith("{self.PAGE_TITLE_SELECTOR_TEXT_STARTS_WITH}")'))
            )
            logger.debug("Secondary page title is displayed.")
            return True
        except TimeoutException:
            logger.debug("Secondary page title not displayed within timeout.")
            return False
        except Exception as e:
            logger.error(f"Error checking if secondary page is displayed: {e}")
            return False

    def get_info(self, page_source: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Extracts MJB ID, MJR ID, appointment count hint, and type hint from the page source.
        Uses the secondary_parser.

        Args:
            page_source (Optional[str]): The XML page source. If None, it will be fetched.

        Returns:
            Optional[Dict[str, Any]]: Parsed data or None if parsing fails.
        """
        logger.info("Getting secondary page info using targeted XML parsing...")
        try:
            if not self.is_displayed(timeout=3):
                logger.error("Cannot get secondary page info: page not displayed correctly.")
                return None

            current_page_source = page_source if page_source else self.driver.page_source
            if not current_page_source:
                logger.error("Failed to get page source for secondary page.")
                return None

            parsed_data = parse_secondary_page_data(current_page_source)
            if parsed_data and parsed_data.get('mjr_id_raw'): # MJR ID is crucial
                return parsed_data
            else:
                logger.error(f"Failed to parse necessary IDs from secondary page. Parsed: {parsed_data}")
                return None
        except Exception as e:
            logger.exception(f"An error occurred in get_info for secondary page: {e}")
            return None

    def click_mjr_link(self, mjr_id: str, timeout=7) -> bool:
        """
        Attempts to find and click the link/element corresponding to the given MJR ID.

        Args:
            mjr_id (str): The MJR ID to find and click.
            timeout (int): Time to wait for the element to be clickable.

        Returns:
            bool: True if click was successful, False otherwise.
        """
        if not mjr_id:
            logger.error("Cannot click MJR link: No MJR ID provided.")
            return False

        mjr_link_selector = self.MJR_LINK_XPATH_TEMPLATE.format(mjr_id=mjr_id)
        logger.debug(f"Attempting to click MJR link element using XPath: {mjr_link_selector}")
        try:
            mjr_element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, mjr_link_selector))
            )
            mjr_element.click()
            logger.debug(f"Clicked MJR link element for {mjr_id}.")
            # Add a short pause for page transition to begin
            time.sleep(1.5)
            return True
        except TimeoutException:
            logger.error(f"Timeout: MJR link element for {mjr_id} not found or not clickable within {timeout}s.")
            return False
        except NoSuchElementException: # Should be caught by WebDriverWait, but good for clarity
            logger.error(f"NoSuchElement: MJR link element for {mjr_id} not found.")
            return False
        except Exception as e:
            logger.exception(f"An unexpected error occurred while clicking MJR link for {mjr_id}: {e}")
            return False
