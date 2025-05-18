# filename: pages/base_page.py
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from logger import get_logger
import time

logger = get_logger(__name__)

class BasePage:
    """Base class for all Page Objects"""

    def __init__(self, driver):
        self.driver = driver

    def find_element(self, by, value, timeout=10):
        """Finds a single element with explicit wait."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            logger.warning(f"Element not found: (By: {by}, Value: {value}) within {timeout}s")
            return None
        except Exception as e:
            logger.error(f"Error finding element (By: {by}, Value: {value}): {e}")
            return None


    def find_elements(self, by, value, timeout=10):
        """Finds multiple elements with explicit wait."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_all_elements_located((by, value))
            )
        except TimeoutException:
            logger.warning(f"Elements not found: (By: {by}, Value: {value}) within {timeout}s")
            return []
        except Exception as e:
            logger.error(f"Error finding elements (By: {by}, Value: {value}): {e}")
            return []

    def click_element(self, by, value, timeout=10):
        """Finds and clicks an element."""
        element = self.find_element(by, value, timeout)
        if element:
            try:
                element.click()
                logger.debug(f"Clicked element: (By: {by}, Value: {value})")
                return True
            except Exception as e:
                logger.error(f"Error clicking element (By: {by}, Value: {value}): {e}")
        return False

    def send_keys_to_element(self, by, value, text, timeout=10):
        """Finds an element and sends keys to it."""
        element = self.find_element(by, value, timeout)
        if element:
            try:
                element.send_keys(text)
                logger.debug(f"Sent keys '{text}' to element: (By: {by}, Value: {value})")
                return True
            except Exception as e:
                logger.error(f"Error sending keys to element (By: {by}, Value: {value}): {e}")
        return False

    def get_element_text(self, by, value, timeout=10):
        """Gets the text of an element."""
        element = self.find_element(by, value, timeout)
        if element:
            try:
                return element.text
            except Exception as e:
                logger.error(f"Error getting text from element (By: {by}, Value: {value}): {e}")
        return None

    def is_element_displayed(self, by, value, timeout=1):
        """Checks if an element is displayed."""
        # Use a short timeout for a quick check
        element = self.find_element(by, value, timeout=timeout)
        if element:
            try:
                return element.is_displayed()
            except NoSuchElementException: # Should be caught by find_element, but as a safeguard
                return False
            except Exception as e:
                logger.error(f"Error checking display status for element (By: {by}, Value: {value}): {e}")
                return False
        return False

    def wait_until_displayed(self, by, value, timeout=10, poll_frequency=0.5):
        """
        Waits until an element is present and displayed.
        This is a custom polling loop as is_displayed might not work with EC.visibility_of_element_located directly.
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.is_element_displayed(by, value, timeout=1): # Quick check within loop
                return True
            time.sleep(poll_frequency)
        logger.warning(f"Element (By: {by}, Value: {value}) did not become displayed within {timeout}s.")
        raise TimeoutException(f"Element (By: {by}, Value: {value}) not displayed after {timeout}s")