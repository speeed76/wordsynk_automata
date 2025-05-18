# filename: parsers/detail_parser.py
import re
import sys
from typing import Optional, List, Dict, Any, Tuple
import html
from datetime import datetime, timedelta
from logger import get_logger

logger = get_logger(__name__)

# --- Patterns and Constants ---
MJR_ID_PATTERN = re.compile(r"Booking\s+#(MJR\d{8})")
MJA_REF_PATTERN = re.compile(r"MJA\d{8}")
DISTANCE_PATTERN = re.compile(r"([\d\.]+)\s+Miles")
PHONE_PATTERN = re.compile(r"^(\+?44\s?\d{2,4}\s?\d{2,4}\s?\d{2,4}|\+?44\s?\d{3,5}\s?\d{3,5}|0\d{4}\s?\d{6}|0\d{3,5}\s?\d{3,5}\s?\d{0,3})$")
BOOKING_TYPE_SEPARATOR = "|"
APPOINTMENT_COUNT_PATTERN = re.compile(r"(\d+)\s+Appointments\s*/\s*(\d+)\s+Days")
DATE_PART_REGEX = re.compile(r"^(\d{2}-\d{2}-\d{4})\s+At$")
TIME_PART_REGEX = re.compile(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$")
POSTCODE_IN_ADDRESS_REGEX = re.compile(r'\b([A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2})\b', re.IGNORECASE)
MEETING_LINK_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b|\bhttps?://\S+')
MULTIDAY_TEXT = "Multiday"; LANGUAGE_TEXT = "English to Polish"; MEETING_LINK_TEXT = "Meeting Link"
SL_TEXT = "Service Line Item"; TD_TEXT = "Travel Distance Line Item"; TT_TEXT = "Travel Time Line Item"
AEP_TEXT = "Automation Enhancement Payment"; TOTAL_TEXT = "TOTAL"; URGENCY_TEXT = "Urgency"
UPLIFT_TEXT = "Uplift"; DISCLAIMER_START_TEXT = "By accepting this assignment"
INFO_BLOCK_TERMINATORS = ["Timesheets Download", "", SL_TEXT, "Open Directions"]
PAYMENT_LABELS_MAP = {
    "service line item": "pay_sl", "travel distance line item": "pay_td",
    "travel time line item": "pay_tt", "automation enhancement payment": "pay_aep",
}
OOH_SUBSTRING = "uplift"; URGENCY_SUBSTRING = "urgency"

def parse_money(raw_value: Optional[str]) -> Optional[float]:
    if raw_value is None or '£' not in raw_value:
        if raw_value is not None: logger.debug(f"Value '{raw_value}' not parsed as money: '£' missing.")
        return None
    cleaned = re.sub(r"[£,]", "", raw_value).strip()
    try: return float(cleaned)
    except (ValueError, TypeError): logger.warning(f"Could not parse money value (after '£' check): '{raw_value}'"); return None

def parse_uk_date(raw_date_str: Optional[str]) -> Optional[str]:
    if raw_date_str is None: return None
    date_part = raw_date_str.strip().split(' ')[0]
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", date_part):
        logger.warning(f"Date string '{date_part}' is not in DD-MM-YYYY format."); return None
    try: datetime.strptime(date_part, "%d-%m-%Y"); return date_part
    except ValueError: logger.warning(f"Date string '{date_part}' is not a valid date."); return None

def parse_time(raw_time: Optional[str]) -> Optional[str]:
    if raw_time is None: return None
    parts = raw_time.strip().split(':')
    if len(parts) == 2:
        hour_str, minute_str = parts[0].strip(), parts[1].strip()
        if hour_str.isdigit() and minute_str.isdigit():
            hour, minute = int(hour_str), int(minute_str)
            if 0 <= hour < 24 and 0 <= minute < 60: return f"{hour:02d}:{minute:02d}:00"
    logger.warning(f"Could not parse time value: '{raw_time}'"); return None

def _extract_texts_from_xml(xml_content: str) -> List[str]:
    texts: List[str] = []
    text_attribute_regex = re.compile(r'text="([^"]*)"')
    try:
        matches = text_attribute_regex.finditer(xml_content)
        for match in matches:
            value = match.group(1)
            cleaned_text_with_internal_newlines = html.unescape(value).replace("&#10;", "\n")
            lines = cleaned_text_with_internal_newlines.split('\n')
            for line in lines:
                stripped_line = line.strip()
                if stripped_line: texts.append(stripped_line)
    except Exception as e: logger.error(f"Could not regex-process XML: {e}")
    return texts

def extract_header_and_booking_type(texts: List[str]) -> Tuple[Dict[str, Any], bool, Optional[int]]:
    header_data = {'mjr_id_raw': None, 'total_value_header_raw': None, 'date_time_raw_tuple': None, 'multiday_date_range_raw': None, 'multiday_appointment_count_raw': None}
    is_multiday = False; lang_idx = -1
    mjr_id_idx = next((i for i, t in enumerate(texts) if t.startswith("Booking #MJR")), -1)
    multiday_idx = next((i for i, t in enumerate(texts) if t == MULTIDAY_TEXT), -1)
    lang_idx = next((i for i, t in enumerate(texts) if t == LANGUAGE_TEXT), -1)
    if mjr_id_idx != -1:
        mjr_match = MJR_ID_PATTERN.search(texts[mjr_id_idx])
        header_data['mjr_id_raw'] = mjr_match.group(1) if mjr_match else texts[mjr_id_idx]
    header_data['total_value_header_raw'] = next((t for i, t in enumerate(texts) if t.startswith('£') and (lang_idx == -1 or i < lang_idx)), None)
    is_multiday = (multiday_idx != -1)
    if is_multiday:
        if multiday_idx + 2 < len(texts) and (lang_idx == -1 or multiday_idx < lang_idx):
            header_data['multiday_date_range_raw'] = texts[multiday_idx + 1]
            header_data['multiday_appointment_count_raw'] = texts[multiday_idx + 2]
    else:
        date_part_str = None; time_part_str = None
        for i, current_line_text in enumerate(texts):
            if DATE_PART_REGEX.match(current_line_text):
                if i + 1 < len(texts) and TIME_PART_REGEX.match(texts[i+1]):
                    date_part_str = current_line_text; time_part_str = texts[i+1]; break
        if date_part_str and time_part_str: header_data['date_time_raw_tuple'] = (date_part_str, time_part_str)
        else: logger.debug("Could not find single day Date/Time string structured as two lines.")
    logger.debug(f"Header Results: MJR='{header_data['mjr_id_raw']}', Total='{header_data['total_value_header_raw']}', MultiDay={is_multiday}, LangIdx={lang_idx}, DateTimeTuple='{header_data['date_time_raw_tuple']}'")
    return header_data, is_multiday, lang_idx if lang_idx != -1 else None

def extract_info_block(texts: List[str], lang_idx: int) -> Dict[str, Any]:
    info_data = { k: None for k in ['language_pair_raw', 'client_name_raw', 'address_line1_raw', 'address_line2_raw', 'booking_type_raw', 'contact_name_raw', 'contact_phone_raw', 'distance_raw', 'meeting_link_raw']}
    if lang_idx == -1 or lang_idx >= len(texts) : logger.error(f"Invalid Language index ({lang_idx})"); return info_data
    info_data['language_pair_raw'] = texts[lang_idx]
    start_processing_idx = lang_idx + 1
    payment_start_idx = len(texts) 
    for i, t in enumerate(texts[start_processing_idx:], start=start_processing_idx):
        if MJA_REF_PATTERN.match(t) or t in INFO_BLOCK_TERMINATORS: payment_start_idx = i; break
    potential_info_texts = texts[start_processing_idx:payment_start_idx]
    logger.debug(f"Info block scan range: {start_processing_idx} to {payment_start_idx}. Processing {len(potential_info_texts)} items: {potential_info_texts}")
    ptr = 0 
    if ptr < len(potential_info_texts):
        candidate = potential_info_texts[ptr]
        if candidate != MEETING_LINK_TEXT and not DISTANCE_PATTERN.search(candidate) and '|' not in candidate:
            info_data['client_name_raw'] = candidate; ptr += 1; logger.debug(f"  Client Name: '{info_data['client_name_raw']}'")
    if ptr < len(potential_info_texts) and potential_info_texts[ptr] == MEETING_LINK_TEXT:
        logger.debug(f"  Found '{MEETING_LINK_TEXT}'."); ptr += 1
        if ptr < len(potential_info_texts) and MEETING_LINK_PATTERN.search(potential_info_texts[ptr]):
            info_data['meeting_link_raw'] = potential_info_texts[ptr]; ptr += 1; logger.debug(f"  Meeting Link URL: '{info_data['meeting_link_raw']}'")
        else: logger.debug(f"  No valid URL after Meeting Link label. Next: {potential_info_texts[ptr] if ptr < len(potential_info_texts) else 'None'}")
    addr1_candidate = potential_info_texts[ptr] if ptr < len(potential_info_texts) else None
    addr2_candidate = potential_info_texts[ptr+1] if ptr + 1 < len(potential_info_texts) else None
    address_lines_found = 0
    if addr1_candidate and addr2_candidate and (POSTCODE_IN_ADDRESS_REGEX.search(addr2_candidate) or (any(word in addr1_candidate.lower() for word in ["street", "road", "court", "house", "centre", "lane", "building", "floor"]) and '|' not in addr1_candidate and not DISTANCE_PATTERN.search(addr1_candidate) and not PHONE_PATTERN.match(addr1_candidate) and addr1_candidate != MEETING_LINK_TEXT)):
        info_data['address_line1_raw'] = potential_info_texts[ptr]; ptr +=1
        info_data['address_line2_raw'] = potential_info_texts[ptr]; ptr +=1
        address_lines_found = 2; logger.debug(f"  Address L1: '{addr1_candidate}', L2: '{addr2_candidate}'")
    elif addr1_candidate and not info_data.get('address_line1_raw') and (POSTCODE_IN_ADDRESS_REGEX.search(addr1_candidate) or (any(word in addr1_candidate.lower() for word in ["street", "road", "court", "house", "centre", "lane", "building", "floor"]) and '|' not in addr1_candidate and not DISTANCE_PATTERN.search(addr1_candidate) and not PHONE_PATTERN.match(addr1_candidate) and addr1_candidate != MEETING_LINK_TEXT)):
        info_data['address_line1_raw'] = potential_info_texts[ptr]; ptr +=1
        address_lines_found = 1; logger.debug(f"  Address L1 (single): '{addr1_candidate}'")
    if ptr < len(potential_info_texts) and not info_data.get('booking_type_raw'):
        candidate = potential_info_texts[ptr]
        if ('|' in candidate) or (address_lines_found == 0 and not info_data.get('meeting_link_raw') and not PHONE_PATTERN.match(candidate) and not DISTANCE_PATTERN.search(candidate)):
            info_data['booking_type_raw'] = candidate; ptr += 1; logger.debug(f"  Booking Type: '{info_data['booking_type_raw']}'")
    if ptr < len(potential_info_texts) and not info_data.get('contact_name_raw'):
        candidate = potential_info_texts[ptr]
        if not PHONE_PATTERN.match(candidate) and not DISTANCE_PATTERN.search(candidate) and '|' not in candidate:
             info_data['contact_name_raw'] = candidate; ptr += 1; logger.debug(f"  Contact Name: '{info_data['contact_name_raw']}'")
    if ptr < len(potential_info_texts) and not info_data.get('contact_phone_raw'):
        candidate = potential_info_texts[ptr]
        if not DISTANCE_PATTERN.search(candidate): info_data['contact_phone_raw'] = candidate; ptr += 1; logger.debug(f"  Contact Phone: '{info_data['contact_phone_raw']}'")
    if ptr < len(potential_info_texts) and not info_data.get('distance_raw') and DISTANCE_PATTERN.search(potential_info_texts[ptr]):
        info_data['distance_raw'] = potential_info_texts[ptr]; ptr += 1; logger.debug(f"  Distance: '{info_data['distance_raw']}'")
    if ptr < len(potential_info_texts): logger.warning(f"  Unassigned info texts: {potential_info_texts[ptr:]}")
    for key in ['contact_name_raw', 'contact_phone_raw']:
        value = info_data.get(key)
        if value is not None and isinstance(value, str) and ( "undefined" in value.lower() or value.strip() == '0' or value.strip().lower() == 'null'):
            info_data[key] = None; logger.debug(f"Sanitized '{key}' from '{value}' to None.")
    logger.debug(f"Finished parsing info block: {info_data}"); return info_data

def extract_mja_payment_blocks(texts: List[str]) -> List[Dict[str, Any]]:
    mja_payment_blocks = []
    mja_indices = [i for i, t in enumerate(texts) if MJA_REF_PATTERN.match(t)]
    if not mja_indices:
        sl_idx = next((i for i,t in enumerate(texts) if t == SL_TEXT), -1)
        if sl_idx != -1:
             single_day_payments = {'mja': None}; current_idx = sl_idx
             total_idx = next((i for i,t in enumerate(texts[current_idx:], start=current_idx) if t == TOTAL_TEXT), len(texts))
             if current_idx + 1 < total_idx:
                  idx = current_idx + 1 # Start checking pairs after SL text
                  while idx < total_idx:
                      if idx + 1 < total_idx :
                          label_text=texts[idx]; value_text=texts[idx+1]; label_lower=label_text.lower()
                          if value_text.startswith('£'):
                              pay_key=PAYMENT_LABELS_MAP.get(label_lower)
                              if pay_key: single_day_payments[pay_key]=value_text
                              elif URGENCY_SUBSTRING in label_lower: single_day_payments['pay_urg']=value_text
                              elif OOH_SUBSTRING in label_lower and 'pay_ooh' not in single_day_payments: single_day_payments['pay_ooh']=value_text
                          idx += 2
                      else: idx +=1 
             if len(single_day_payments) > 1 : mja_payment_blocks.append(single_day_payments)
        return mja_payment_blocks
    for i, start_idx in enumerate(mja_indices):
        if start_idx >= len(texts): continue
        mja_ref = texts[start_idx]; payment_details = {'mja': mja_ref}
        end_idx = mja_indices[i+1] if i + 1 < len(mja_indices) else len(texts)
        total_idx_after_mja = next((idx for idx, t in enumerate(texts[start_idx+1:], start=start_idx+1) if t == TOTAL_TEXT), -1)
        if total_idx_after_mja != -1: end_idx = min(end_idx, total_idx_after_mja)
        idx = start_idx + 1
        while idx < end_idx:
            if idx + 1 < end_idx:
                label_text=texts[idx]; value_text=texts[idx+1]; label_lower=label_text.lower()
                if value_text.startswith('£'):
                    pay_key=PAYMENT_LABELS_MAP.get(label_lower)
                    if pay_key: payment_details[pay_key]=value_text
                    elif URGENCY_SUBSTRING in label_lower: payment_details['pay_urg']=value_text
                    elif OOH_SUBSTRING in label_lower and 'pay_ooh' not in payment_details: payment_details['pay_ooh']=value_text
                idx += 2
            else: idx += 1
        if len(payment_details) > 1: mja_payment_blocks.append(payment_details)
    logger.debug(f"Extracted {len(mja_payment_blocks)} MJA payment blocks.")
    return mja_payment_blocks

def extract_notes_and_total(texts: List[str]) -> Dict[str, Any]:
    notes_total_data = {'notes_raw': None, 'pay_total_raw': None}
    disclaimer_idx = next((i for i, t in enumerate(texts) if t.startswith(DISCLAIMER_START_TEXT)), len(texts))
    total_label_idx = next((i for i, t in enumerate(texts) if t == TOTAL_TEXT), -1)
    if total_label_idx != -1:
        notes_start_idx = total_label_idx + 1
        if total_label_idx + 1 < len(texts) and texts[total_label_idx + 1].startswith('£'):
            notes_total_data['pay_total_raw'] = texts[total_label_idx + 1]; notes_start_idx = total_label_idx + 2
        if notes_start_idx < disclaimer_idx:
            notes_texts_filtered = [t for t in texts[notes_start_idx:disclaimer_idx] if t not in INFO_BLOCK_TERMINATORS and not MJA_REF_PATTERN.match(t)]
            notes_total_data['notes_raw'] = "\n".join(notes_texts_filtered).strip() if notes_texts_filtered else None
    return notes_total_data

def parse_detail_data(
    header_info: Dict[str, Any], is_multiday: bool, info_block: Dict[str, Any],
    payment_blocks: List[Dict[str, Any]], notes_total_info: Dict[str, Any]
    ) -> Dict[str, Optional[Any]]:
    parsed: Dict[str, Any] = {}
    logger.debug("--- Consolidating and Parsing Detail Data ---")
    parsed['is_multiday'] = 1 if is_multiday else 0
    parsed['mjr_id'] = header_info.get('mjr_id_raw')
    parsed['header_total'] = parse_money(header_info.get('total_value_header_raw'))
    parsed['booking_date'], parsed['start_time'], parsed['end_time'], parsed['duration'] = None, None, None, None

    if is_multiday:
        parsed['multiday_date_range'] = header_info.get('multiday_date_range_raw')
        parsed['multiday_appointment_info'] = header_info.get('multiday_appointment_count_raw')
    else:
        parsed['multiday_date_range'], parsed['multiday_appointment_info'] = None, None
        date_time_tuple = header_info.get('date_time_raw_tuple')
        if date_time_tuple and isinstance(date_time_tuple, tuple) and len(date_time_tuple) == 2:
            date_part_str, time_part_str = date_time_tuple
            date_match = DATE_PART_REGEX.match(date_part_str)
            if date_match: parsed['booking_date'] = parse_uk_date(date_match.group(1))
            time_match = TIME_PART_REGEX.match(time_part_str)
            if time_match:
                parsed['start_time'] = parse_time(time_match.group(1))
                parsed['end_time'] = parse_time(time_match.group(2))
                st_obj = _parse_time_str_to_datetime(time_match.group(1))
                et_obj = _parse_time_str_to_datetime(time_match.group(2))
                parsed['duration'] = _calculate_duration_str(st_obj, et_obj)
        else: logger.warning(f"Could not parse date/time for single day from header: {date_time_tuple}")

    for key, raw_key in {'language_pair': 'language_pair_raw', 'client_name': 'client_name_raw', 'booking_type': 'booking_type_raw', 'contact_name': 'contact_name_raw', 'contact_phone': 'contact_phone_raw', 'meeting_link': 'meeting_link_raw'}.items():
        parsed[key] = info_block.get(raw_key)
    addr1 = info_block.get('address_line1_raw'); addr2 = info_block.get('address_line2_raw')
    parsed['address'] = "\n".join(filter(None, [addr1, addr2])).strip() if (addr1 or addr2) else None
    dist_raw = info_block.get('distance_raw')
    parsed['travel_distance'] = None # Initialize
    if dist_raw:
        dist_match = DISTANCE_PATTERN.search(dist_raw)
        if dist_match:
            try: # Corrected Syntax for try-except block
                parsed['travel_distance'] = float(dist_match.group(1))
            except (ValueError, TypeError):
                logger.warning(f"Could not parse distance value: {dist_raw}")
    
    parsed['overall_total'] = parse_money(notes_total_info.get('pay_total_raw'))
    parsed['multiday_payments'] = []
    calculated_day_total: Optional[float] = None

    if is_multiday:
        parsed['mja_id'] = None
        start_date_obj: Optional[datetime.date] = None
        if parsed.get('multiday_date_range_raw'):
            try:
                start_date_str_from_range = parsed['multiday_date_range_raw'].split(' - ')[0]
                temp_date_uk = parse_uk_date(start_date_str_from_range)
                if temp_date_uk: start_date_obj = datetime.strptime(temp_date_uk, "%d-%m-%Y").date()
            except Exception as e: logger.error(f"Could not parse start date from range '{parsed.get('multiday_date_range_raw')}': {e}")
        for i, day_payment_raw in enumerate(payment_blocks):
            if not isinstance(day_payment_raw, dict): continue
            parsed_day: Dict[str, Any] = {'mja': day_payment_raw.get('mja')}
            day_booking_date: Optional[str] = None
            if start_date_obj:
                try: day_booking_date = (start_date_obj + timedelta(days=i)).strftime("%d-%m-%Y")
                except Exception as e_calc: logger.error(f"Error calculating date for MJA seq {i+1}: {e_calc}")
            parsed_day['booking_date'] = day_booking_date
            parsed_day['start_time'] = None; parsed_day['end_time'] = None; parsed_day['duration'] = None
            for key_suffix in ['sl', 'td', 'tt', 'aep', 'ooh', 'urg']:
                parsed_day[f'pay_{key_suffix}'] = parse_money(day_payment_raw.get(f'pay_{key_suffix}'))
            parsed['multiday_payments'].append(parsed_day)
        num_days = 0
        if parsed['multiday_appointment_info']:
             match = APPOINTMENT_COUNT_PATTERN.search(parsed['multiday_appointment_info'])
             if match:
                  try: num_days_str = match.group(2) or match.group(1); num_days = int(num_days_str) if num_days_str else 0
                  except: num_days = 0
        if num_days == 0 and parsed['multiday_payments']: num_days = len(parsed['multiday_payments'])
        if num_days > 0 and parsed['overall_total'] is not None:
             try: calculated_day_total = round(parsed['overall_total'] / num_days, 2)
             except ZeroDivisionError: calculated_day_total = None
        else: calculated_day_total = None
        for key_suffix in ['sl', 'td', 'tt', 'aep', 'ooh', 'urg']: parsed[f'day_pay_{key_suffix}'] = None
        parsed['day_total'] = calculated_day_total
    else: # Single Day
        single_day_payment_data = payment_blocks[0] if payment_blocks and isinstance(payment_blocks[0], dict) else {}
        parsed['mja_id'] = single_day_payment_data.get('mja')
        parsed['multiday_payments'] = None 
        for key_suffix in ['sl', 'td', 'tt', 'aep', 'ooh', 'urg']:
             parsed[f"day_pay_{key_suffix}"] = parse_money(single_day_payment_data.get(f"pay_{key_suffix}"))
        parsed['day_total'] = parsed['overall_total']
        # booking_date, start_time, end_time, duration are already set from header for single day

    parsed['notes'] = notes_total_info.get('notes_raw')
    if (not parsed['meeting_link'] or parsed['meeting_link'] == MEETING_LINK_TEXT) and parsed['notes']:
         link_match = MEETING_LINK_PATTERN.search(parsed['notes'])
         if link_match: parsed['meeting_link'] = link_match.group(0); logger.info(f"Extracted meeting link from notes: {parsed['meeting_link']}")
    if parsed['meeting_link'] == MEETING_LINK_TEXT: parsed['meeting_link'] = None
    logger.debug(f"Final Parsed Data Keys: {list(parsed.keys())}")
    return parsed

def check_if_multiday_from_xml(xml_content: str) -> bool:
    text_attribute_regex = re.compile(r'\btext="([^"]*)"')
    try:
        for match in text_attribute_regex.finditer(xml_content):
            if MULTIDAY_TEXT in html.unescape(match.group(1)): return True
    except Exception as e: logger.error(f"Error in quick multiday check: {e}")
    return False