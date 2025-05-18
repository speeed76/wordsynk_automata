# filename: pages/detail_page.py
from typing import Dict, Optional, Any
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from logger import get_logger

logger = get_logger(__name__)

class DetailPage:
    """
    Page Object for the final booking detail (MJR) screen.
    Provides methods to identify the page and wait for it to load.
    Data extraction logic is handled by the DetailProcessor and Parsers.
    """
    TITLE_SELECTOR_TEXT_STARTS_WITH = "Booking #MJR" # Partial text for the title

    def __init__(self, driver):
        """Initializes the DetailPage."""
        self.driver = driver

    def wait_until_displayed(self, timeout=10):
        """
        Waits for the detail page title element to be present.
        """
        try:
            logger.debug(f"Waiting up to {timeout}s for detail page title: '{self.TITLE_SELECTOR_TEXT_STARTS_WITH}'")
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textStartsWith("{self.TITLE_SELECTOR_TEXT_STARTS_WITH}")'))
            )
            logger.debug("Detail page title is displayed.")
        except TimeoutException:
            logger.warning("Detail page did not load within timeout (title not found).")
            raise
        except Exception as e:
             logger.error(f"Error waiting for detail page: {e}")
             raise

    def is_displayed(self, timeout=1) -> bool:
        """
        Quickly checks if the detail page title element is currently present.
        """
        initial_wait_time = self.driver.timeouts.implicit_wait # Store and set to 0 for quick check
        try:
            self.driver.implicitly_wait = timeout # Brief wait for find
            self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textStartsWith("{self.TITLE_SELECTOR_TEXT_STARTS_WITH}")')
            logger.debug("is_displayed check: Detail page title found.")
            return True
        except NoSuchElementException:
            logger.debug("is_displayed check: Detail page title not found.")
            return False
        except Exception as e:
            logger.error(f"Error checking if detail page is displayed: {e}")
            return False
        finally:
            self.driver.implicitly_wait = initial_wait_time # Restore