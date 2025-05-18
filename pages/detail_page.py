# filename: pages/detail_page.py
from typing import Dict, Optional, Any # Kept for consistency
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import (
    NoSuchElementException, # Not strictly needed if WebDriverWait is always used for checks
    TimeoutException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from logger import get_logger
# import time # Not used by the reverted methods

logger = get_logger(__name__)

class DetailPage:
    """
    Page Object for the final booking detail (MJR) screen.
    Provides methods to identify the page and wait for it to load.
    Data extraction logic is handled by the DetailProcessor and Parsers.
    """
    # Using a UIAutomator selector for the title as it's generally reliable
    TITLE_SELECTOR_TEXT_STARTS_WITH = "Booking #MJR"

    def __init__(self, driver):
        """Initializes the DetailPage."""
        self.driver = driver

    def _find_element_for_check(self, by, value, timeout=1):
        """
        Internal helper to find an element with a short timeout, used by is_displayed.
        Returns the element or None.
        """
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            logger.debug(f"Element not found by _find_element_for_check: (By: {by}, Value: {value}) within {timeout}s")
            return None
        except Exception as e: # Catch other potential exceptions during find
            logger.error(f"Error in _find_element_for_check (By: {by}, Value: {value}): {e}")
            return None

    def wait_until_displayed(self, timeout=10):
        """
        Waits for the detail page title element to be present and implicitly visible.
        Raises TimeoutException if not found within the timeout.
        """
        try:
            logger.debug(f"Waiting up to {timeout}s for detail page title: '{self.TITLE_SELECTOR_TEXT_STARTS_WITH}'")
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textStartsWith("{self.TITLE_SELECTOR_TEXT_STARTS_WITH}")'))
            )
            logger.debug("Detail page title is displayed.")
        except TimeoutException:
            logger.warning(f"Detail page did not load within timeout (title '{self.TITLE_SELECTOR_TEXT_STARTS_WITH}' not found).")
            raise # Re-raise to be handled by the processor
        except Exception as e:
             logger.error(f"Error waiting for detail page: {e}")
             raise # Re-raise

    def is_displayed(self, timeout=2) -> bool:
        """
        Quickly checks if the detail page title element is currently present.
        Uses a short explicit wait via a helper method.
        """
        logger.debug(f"Checking if detail page is displayed (title: '{self.TITLE_SELECTOR_TEXT_STARTS_WITH}', timeout: {timeout}s)")
        element = self._find_element_for_check(
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().textStartsWith("{self.TITLE_SELECTOR_TEXT_STARTS_WITH}")',
            timeout=timeout
        )
        if element is not None:
            # For Appium, presence via WebDriverWait usually implies it's interactable enough.
            logger.debug("is_displayed check: Detail page title found.")
            return True
        else:
            logger.debug("is_displayed check: Detail page title not found.")
            return False