# filename: config.py
import os
from appium.options.common import AppiumOptions
from typing import Optional # Added this import

# --- Appium Server Configuration ---
APPIUM_SERVER_URL = "http://localhost:4723"

# --- General Appium Capabilities ---
GENERAL_CAPABILITIES = AppiumOptions()
GENERAL_CAPABILITIES.platform_name = "Android"
GENERAL_CAPABILITIES.automation_name = "UiAutomator2"
GENERAL_CAPABILITIES.device_name = "emulator-5554" # Example: 'emulator-5554' or real device ID
GENERAL_CAPABILITIES.app_package = "com.wordsynknetwork.moj"
GENERAL_CAPABILITIES.app_activity = ".MainActivity" # Common main activity
GENERAL_CAPABILITIES.no_reset = True
GENERAL_CAPABILITIES.full_reset = False
GENERAL_CAPABILITIES.new_command_timeout = 300 # seconds
# GENERAL_CAPABILITIES.udid = "YOUR_DEVICE_UDID" # For real devices
# GENERAL_CAPABILITIES.app = "/path/to/your/app.apk" # If installing app

# --- Database Configuration ---
DB_NAME = "bookings.db"
# Get the absolute path to the directory where this config file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, DB_NAME)


# --- XML Dumping Configuration ---
# Set to True to enable XML dumping mode, False for normal operation
DUMP_XML_MODE = True # Set to True to enable XML dumping for testing/debugging
# Root directory where all XML dumps for different sessions/bookings will be stored
XML_DUMP_ROOT_DIR = "xml_capture_base"


# --- Logging Configuration ---
LOG_LEVEL = "DEBUG"  # e.g., DEBUG, INFO, WARNING, ERROR
LOG_FILE = "booking_scraper.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s (%(filename)s:%(lineno)d)"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- Target Display Configuration for Multi-Display Emulators ---
# Name of the display to target if multiple displays are detected (e.g., "internal", "virtual_display_2")
# Set to None to automatically try to use the display with the focused app, or "internal" as default.
TARGET_DISPLAY_NAME: Optional[str] = None # "internal" or "virtual_display_X" or None