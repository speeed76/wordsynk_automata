# filename: utils/xml_dumper.py
import os
import datetime
from logger import get_logger
from typing import Optional

logger = get_logger(__name__)

# This will be set by CrawlerService from config.py
XML_DUMP_ROOT_DIR_CONFIG = "xml_dump_default" # Default fallback

def _ensure_dir_exists(dir_path: str):
    """Ensures a directory exists, creating it if necessary."""
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path, exist_ok=True)
            logger.debug(f"Created directory: {dir_path}")
        except OSError as e:
            logger.error(f"Could not create directory '{dir_path}': {e}")
            # Decide if to raise error or just log
            raise # Or return False

def initialize_dumper(root_dump_dir: str):
    """Initializes the dumper by setting the root directory and creating it."""
    global XML_DUMP_ROOT_DIR_CONFIG
    XML_DUMP_ROOT_DIR_CONFIG = root_dump_dir
    try:
        _ensure_dir_exists(XML_DUMP_ROOT_DIR_CONFIG)
        logger.info(f"XML Dumper initialized. Dumps will be saved in: {XML_DUMP_ROOT_DIR_CONFIG}")
    except Exception as e:
        logger.error(f"Failed to initialize XML dumper base directory: {e}")


def save_xml_dump(
    page_source: str,
    page_type_prefix: str, # e.g., "List", "Secondary", "Detail"
    primary_id: str,       # e.g., SessionID for list, MJB for secondary, MJR for detail
    sequence_or_stage: str # e.g., "initial", "scroll_01", or just a simple sequence number
):
    """
    Saves the XML page source to a structured directory.
    Filename: [page_type_prefix]_[primary_id]_[sequence_or_stage]_[timestamp].xml
    Structure: XML_DUMP_ROOT_DIR / [primary_id_folder] / [page_type_prefix_folder] / filename.xml
    """
    if not page_source:
        logger.warning(f"Attempted to save empty page source for {page_type_prefix}_{primary_id}_{sequence_or_stage}")
        return False

    try:
        # Create a folder for the primary_id (e.g., MJR0012345 or session_1)
        primary_id_folder_path = os.path.join(XML_DUMP_ROOT_DIR_CONFIG, primary_id)
        _ensure_dir_exists(primary_id_folder_path)

        # Create a subfolder for the page type (e.g., List, Secondary, Detail)
        page_type_folder_path = os.path.join(primary_id_folder_path, page_type_prefix)
        _ensure_dir_exists(page_type_folder_path)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        # Keep primary_id in filename for flatter structure within type folder
        filename = f"{page_type_prefix}_{primary_id}_{sequence_or_stage}_{timestamp}.xml"
        filepath = os.path.join(page_type_folder_path, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(page_source)
        logger.info(f"Saved XML dump: {filepath}")
        return True
    except Exception as e:
        logger.exception(f"Failed to save XML dump for {page_type_prefix}_{primary_id}_{sequence_or_stage}: {e}")
        return False