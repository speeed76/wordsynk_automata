# filename: parsers/mja_parser.py
import re
from typing import Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from utils.sanitize import sanitize_postcode
from logger import get_logger
from state.models import BookingCardStatus # Import the Enum

logger = get_logger(__name__)

MJA_ID_REGEX = re.compile(r"(MJA\d{8})") # Regex to find MJA ID
DURATION_REGEX = re.compile(r"(\d{1,2}:\d{2})\s*(?:to|-)\s*(\d{1,2}:\d{2})")

KNOWN_STATUS_PREFIXES = {
    "Cancelled,": BookingCardStatus.CANCELLED,
    "New Offer,": BookingCardStatus.NEW_OFFER,
    "Viewed,": BookingCardStatus.VIEWED,
    # Add other exact prefixes if they exist, including the trailing comma if always present
}

def _parse_time_str_to_datetime(time_str: str) -> Optional[datetime.time]:
    if not time_str: return None
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
             hour = int(parts[0]); minute = int(parts[1])
             if 0 <= hour < 24 and 0 <= minute < 60:
                  return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
    except ValueError: logger.warning(f"Could not parse time string '{time_str}' to time object.")
    return None

def _calculate_duration_str(start_time_obj: Optional[datetime.time], end_time_obj: Optional[datetime.time]) -> Optional[str]:
    if not start_time_obj or not end_time_obj: return None
    dummy_date = datetime(2000, 1, 1)
    start_dt = datetime.combine(dummy_date, start_time_obj)
    end_dt = datetime.combine(dummy_date, end_time_obj)
    if end_dt < start_dt: end_dt += timedelta(days=1)
    elif end_dt == start_dt: return "00:00"
    duration_delta = end_dt - start_dt
    total_seconds = duration_delta.total_seconds()
    if total_seconds < 0: return None
    hours = int(total_seconds // 3600); minutes = int((total_seconds % 3600) // 60)
    return f"{hours:02d}:{minutes:02d}"

def parse_mja(desc_str: str) -> Optional[Dict[str, Any]]:
    if not desc_str:
        logger.debug("MJA Parse: Received empty description string.")
        return None

    original_desc_for_log = desc_str
    logger.debug(f"MJA Parse: Starting parsing for desc_str: '{original_desc_for_log}'")

    card_status = BookingCardStatus.NORMAL
    # Use a temporary variable for stripping prefixes, so original_desc_for_log remains unchanged for logging
    desc_to_process = desc_str 

    for prefix_key, status_enum in KNOWN_STATUS_PREFIXES.items():
        if desc_to_process.startswith(prefix_key):
            card_status = status_enum
            # Strip the prefix and any immediately following space or comma + space
            desc_to_process = desc_to_process[len(prefix_key):].lstrip(" ,") 
            logger.info(f"MJA Parse: Found card status '{status_enum.value}' (Prefix: '{prefix_key}'). Remaining desc for MJA ID: '{desc_to_process}'")
            break # A card should only have one such status prefix
    
    # Now, search for MJA ID in the (potentially modified) desc_to_process
    mja_match = MJA_ID_REGEX.search(desc_to_process)
    if not mja_match:
        logger.warning(f"MJA Parse: No MJA ID found in segment: '{desc_to_process}' (Original full desc: '{original_desc_for_log}')")
        # If a known status was identified but no MJA, decide how to handle.
        # For 'Cancelled', you might want to record it even without MJA if that's possible.
        # For now, if MJA is critical, we return None.
        return None

    booking_id = mja_match.group(1)
    logger.debug(f"MJA Parse ({booking_id}): Extracted MJA ID. Original full desc: '{original_desc_for_log}'")

    # The remaining parts for postcode, duration, language are *after* the MJA ID
    idx_after_mja_id = mja_match.end()
    remaining_after_mja = desc_to_process[idx_after_mja_id:].lstrip(", ")
    
    parts = [p.strip() for p in remaining_after_mja.split(',') if p.strip()]
    logger.debug(f"MJA Parse ({booking_id}): Parts after MJA ID: {parts}")


    postcode_raw = None; start_time_raw = None; end_time_raw = None
    language_pair = None; calculated_duration_str = None; is_remote = 0
    original_duration_str = None
    processed_indices = set() # To track which parts of `parts` list are consumed

    # 1. Identify Duration from `parts`
    for i, part in enumerate(parts):
        duration_match = DURATION_REGEX.search(part)
        if duration_match:
            start_time_raw = duration_match.group(1); end_time_raw = duration_match.group(2)
            start_obj = _parse_time_str_to_datetime(start_time_raw); end_obj = _parse_time_str_to_datetime(end_time_raw)
            calculated_duration_str = _calculate_duration_str(start_obj, end_obj)
            original_duration_str = f"{start_time_raw} to {end_time_raw}" # Store a consistent format
            processed_indices.add(i); logger.debug(f"MJA Parse ({booking_id}): Found Duration in part '{part}'")
            break
            
    # 2. Identify Postcode or "Remote" from `parts`
    # Iterate through parts not yet processed
    for i, part in enumerate(parts):
        if i in processed_indices: continue
        if part.lower() == "remote":
            is_remote = 1; postcode_raw = None; processed_indices.add(i)
            logger.debug(f"MJA Parse ({booking_id}): Found 'Remote' keyword.")
            break 
        if postcode_raw is None: # Only search for postcode if not yet found AND not remote
            potential_postcode = sanitize_postcode(part)
            if potential_postcode:
                postcode_raw = potential_postcode; is_remote = 0; processed_indices.add(i)
                logger.debug(f"MJA Parse ({booking_id}): Found Postcode in part '{part}' -> {postcode_raw}")
                break
                
    if postcode_raw is None and not is_remote: # If no postcode and not explicitly remote
        is_remote = 1; logger.debug(f"MJA Parse ({booking_id}): No postcode found, inferred isRemote=1.")

    # 3. Assign Language Pair (last remaining unprocessed part)
    remaining_parts_for_lang = [parts[i] for i in range(len(parts)) if i not in processed_indices]
    if remaining_parts_for_lang:
        language_pair = remaining_parts_for_lang[-1]
        logger.debug(f"MJA Parse ({booking_id}): Assigned Language Pair: '{language_pair}' from remaining: {remaining_parts_for_lang}")
        if len(remaining_parts_for_lang) > 1:
             logger.warning(f"MJA Parse ({booking_id}): Multiple unassigned parts left: {remaining_parts_for_lang[:-1]}. Using last for lang.")
    else: logger.debug(f"MJA Parse ({booking_id}): No remaining parts for language pair.")

    parsed_result = {
        "booking_id": booking_id, "card_status": card_status, "postcode": postcode_raw,
        "start_time_raw": start_time_raw, "end_time_raw": end_time_raw,
        "calculated_duration_str": calculated_duration_str, "language_pair": language_pair,
        "isRemote": is_remote, "original_duration_str": original_duration_str
    }
    logger.info(f"MJA Parse ({booking_id}): Final parsed data: {parsed_result}")
    return parsed_result