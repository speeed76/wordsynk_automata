# filename: parsers/secondary_parser.py
import re
from typing import Optional, Dict, Any
import html
from logger import get_logger

logger = get_logger(__name__)

# --- Constants ---
FACE_TO_FACE_TEXT = "Face To Face"
VIDEO_REMOTE_TEXT = "Video Remote Interpreting"
REMOTE_TEXT = "Remote" # Fallback if specific remote type not found

# --- Regex Patterns ---
MJB_ID_PATTERN = re.compile(r"Booking\s+#(MJB\d{8})")
MJR_DESC_PATTERN = re.compile(r"(MJR\d{8})[,\s]*(.*?)[,\s]*(?:Appointments\s*:\s*(\d+)|$)")
APPOINTMENT_DESC_PATTERN = re.compile(r"Appointments\s*:\s*(\d+)")


def parse_secondary_page_data(xml_content: str) -> Dict[str, Any]:
    """
    Parses the Secondary (MJB) page XML source to extract MJB ID,
    associated MJR ID, appointment count hint, and type hint.
    Uses targeted regex on text and content-desc attributes.
    Regex for attributes made more lenient for test robustness.
    """
    results = {
        'mjb_id_raw': None,
        'mjr_id_raw': None,
        'appointment_count_hint': 1, # Default to 1
        'type_hint_raw': None
    }
    logger.debug("--- Parsing Secondary Page XML Targeting Specific Attributes ---")

    # Use simpler regex to find attributes, removing \b
    text_attribute_regex = re.compile(r'text="([^"]*)"')
    desc_attribute_regex = re.compile(r'content-desc="([^"]*)"')

    mjr_desc_found = False

    try:
        matches = desc_attribute_regex.finditer(xml_content)
        for match in matches:
            desc = html.unescape(match.group(1)).strip()
            mjr_match = MJR_DESC_PATTERN.search(desc)
            if mjr_match:
                results['mjr_id_raw'] = mjr_match.group(1).strip()
                logger.debug(f"  Found MJR content-desc: \"{desc}\"")
                logger.debug(f"    Extracted MJR ID: {results['mjr_id_raw']}")

                type_hint_candidate = mjr_match.group(2).strip(" ,") if mjr_match.group(2) else None
                if type_hint_candidate:
                    if FACE_TO_FACE_TEXT.lower() in type_hint_candidate.lower():
                        results['type_hint_raw'] = FACE_TO_FACE_TEXT
                    elif VIDEO_REMOTE_TEXT.lower() in type_hint_candidate.lower():
                         results['type_hint_raw'] = VIDEO_REMOTE_TEXT
                    elif REMOTE_TEXT.lower() in type_hint_candidate.lower():
                         results['type_hint_raw'] = REMOTE_TEXT
                    else:
                         results['type_hint_raw'] = type_hint_candidate
                    logger.debug(f"    Extracted Type Hint: {results['type_hint_raw']}")
                else:
                     logger.debug("    No Type Hint text found between MJR ID and Appointments.")

                appt_count_str = mjr_match.group(3)
                if appt_count_str:
                    try:
                        results['appointment_count_hint'] = int(appt_count_str.strip())
                        logger.debug(f"    Extracted Appt Count: {results['appointment_count_hint']}")
                    except ValueError:
                        logger.warning(f"Could not parse appointment count '{appt_count_str}' from MJR desc. Defaulting to 1.")
                        results['appointment_count_hint'] = 1
                else:
                    logger.debug("    Appointment count not found in MJR desc. Defaulting to 1.")
                mjr_desc_found = True
                break
    except Exception as e:
        logger.error(f"Error processing content-desc attributes: {e}")

    if not mjr_desc_found:
         logger.warning("Could not find any content-desc attribute containing an MJR ID.")

    try:
        matches = text_attribute_regex.finditer(xml_content)
        for match in matches:
            text = html.unescape(match.group(1)).strip()
            mjb_match = MJB_ID_PATTERN.search(text)
            if mjb_match:
                results['mjb_id_raw'] = mjb_match.group(1)
                logger.debug(f"  Found MJB ID in text: {results['mjb_id_raw']}")
                break
    except Exception as e:
        logger.error(f"Error processing text attributes: {e}")

    if not results['mjb_id_raw']:
         logger.warning("Could not find MJB ID in any text attribute.")

    logger.debug(f"--- Secondary Page Targeted Extraction Finished: {results} ---")
    return results