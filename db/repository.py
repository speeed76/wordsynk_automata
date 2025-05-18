# filename: db/repository.py
import sqlite3
from logger import get_logger
from typing import Dict, Any, List, Tuple, Optional, Set
import time
from parsers.detail_parser import parse_time as format_time_for_db
from state.models import BookingCardStatus # Import for type hinting if needed

logger = get_logger(__name__)

def insert_booking_base(conn: sqlite3.Connection, card_data: Dict[str, Any]):
    """
    Inserts the initial minimal booking record from list page card data.
    Includes parsed start_time, end_time, calculated_duration_str, and card_status.
    The 'status' column in the DB will be set based on 'card_status'.
    """
    card_status_enum = card_data.get('card_status', BookingCardStatus.NORMAL)
    db_status = 'pending' # Default status for normal bookings
    if card_status_enum == BookingCardStatus.CANCELLED:
        db_status = 'cancelled_on_list'
    # For New Offer / Viewed, they will be skipped by ListProcessor, but if we were to save them:
    # elif card_status_enum in [BookingCardStatus.NEW_OFFER, BookingCardStatus.VIEWED]:
    # db_status = 'skipped_offer_viewed' # Or some other informational status

    columns = [
        'booking_id', 'postcode',
        'start_time', 'end_time', 'duration',
        'language_pair', 'isRemote', 'status', 'card_status' # Added card_status
    ]

    db_start_time = format_time_for_db(card_data.get('start_time_raw'))
    db_end_time = format_time_for_db(card_data.get('end_time_raw'))

    values_tuple = (
        card_data.get('booking_id'),
        card_data.get('postcode'),
        db_start_time,
        db_end_time,
        card_data.get('calculated_duration_str'),
        card_data.get('language_pair'),
        1 if card_data.get('isRemote') == 1 else 0,
        db_status, # Use the determined db_status
        card_status_enum.value if card_status_enum else BookingCardStatus.UNKNOWN.value # Store enum's value
    )

    if not values_tuple[0]:
        logger.error("Attempted to insert booking without booking_id. Data: %s", card_data)
        return

    # INSERT OR IGNORE will not update if already exists.
    # If a booking was 'NORMAL' and later becomes 'CANCELLED', we need an UPDATE.
    # For simplicity, let's use INSERT OR REPLACE for base data, or handle update logic specifically.
    # Given that this function might be called again if a card is re-evaluated,
    # an upsert that updates status is better.
    
    # Simpler: INSERT OR IGNORE, then separate UPDATE for status if needed
    # Or, more complex upsert:
    sql = f'''
        INSERT INTO bookings ({', '.join(columns)}, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(booking_id) DO UPDATE SET
            postcode = excluded.postcode,
            start_time = excluded.start_time,
            end_time = excluded.end_time,
            duration = excluded.duration,
            language_pair = excluded.language_pair,
            isRemote = excluded.isRemote,
            status = excluded.status,              -- Allow status to be updated
            card_status = excluded.card_status,    -- Allow card_status to be updated
            last_updated = CURRENT_TIMESTAMP
        WHERE bookings.status <> 'scraped'; -- Avoid overwriting fully scraped data with just list data
                                           -- or allow updates only if new status is more final (e.g. cancelled)
    '''
    # Refined condition for update: only update if current status is not final (e.g. scraped)
    # or if the new status is a "final" list status like 'cancelled_on_list'.
    # This upsert logic can get complex. For now, a simple upsert that updates these fields
    # if the card is seen again might be acceptable.

    try:
        cursor = conn.cursor()
        cursor.execute(sql, values_tuple)
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Inserted/Updated base booking record for {values_tuple[0]} with card_status: {card_status_enum.value if card_status_enum else None}, db_status: {db_status}")
        else:
            logger.debug(f"Base booking record for {values_tuple[0]} already exists and no changes made by upsert (e.g., status was 'scraped').")
    except sqlite3.Error as e:
        logger.error(f"Failed to insert/update base booking {values_tuple[0]}: {e}")
        conn.rollback()

# ... (rest of repository.py remains the same as the last full version provided) ...

# [FULL REPRINT OF db/repository.py WITH ALL CORRECTIONS SO FAR]
# filename: db/repository.py
import sqlite3
from logger import get_logger
from typing import Dict, Any, List, Tuple, Optional, Set
import time
from parsers.detail_parser import parse_time as format_time_for_db # For list page time parsing
from state.models import BookingCardStatus # Import for type hinting if needed

logger = get_logger(__name__)

def insert_booking_base(conn: sqlite3.Connection, card_data: Dict[str, Any]):
    card_status_enum = card_data.get('card_status', BookingCardStatus.NORMAL)
    db_status = 'pending'
    if card_status_enum == BookingCardStatus.CANCELLED:
        db_status = 'cancelled_on_list'
    # For NEW_OFFER or VIEWED, ListProcessor will skip them, so they won't reach here for insertion
    # unless the logic changes. If they were to be inserted, db_status could be 'skipped_offer_viewed'.

    columns = [
        'booking_id', 'postcode',
        'start_time', 'end_time', 'duration',
        'language_pair', 'isRemote', 'status', 'card_status'
    ]
    db_start_time = format_time_for_db(card_data.get('start_time_raw'))
    db_end_time = format_time_for_db(card_data.get('end_time_raw'))
    values_tuple = (
        card_data.get('booking_id'), card_data.get('postcode'),
        db_start_time, db_end_time, card_data.get('calculated_duration_str'),
        card_data.get('language_pair'), 1 if card_data.get('isRemote') == 1 else 0,
        db_status, card_status_enum.value if card_status_enum else BookingCardStatus.UNKNOWN.value
    )

    if not values_tuple[0]: logger.error(f"Attempted to insert booking without booking_id. Data: {card_data}"); return

    # Upsert: Insert if new, or update specific fields if MJA ID exists and status is not 'scraped'
    # This prevents overwriting a fully scraped record with just list data, but allows updating status.
    sql = f'''
        INSERT INTO bookings ({', '.join(columns)}, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(booking_id) DO UPDATE SET
            postcode = excluded.postcode,
            start_time = excluded.start_time,
            end_time = excluded.end_time,
            duration = excluded.duration,
            language_pair = excluded.language_pair,
            isRemote = excluded.isRemote,
            status = CASE
                         WHEN bookings.status = 'scraped' AND excluded.status = 'cancelled_on_list' THEN excluded.status -- Allow update to cancelled
                         WHEN bookings.status = 'scraped' THEN bookings.status -- Keep scraped if new is not more definitive
                         ELSE excluded.status
                     END,
            card_status = excluded.card_status,
            last_updated = CURRENT_TIMESTAMP
        WHERE bookings.booking_id = excluded.booking_id; 
    '''
    # The WHERE clause on DO UPDATE is tricky. Simpler might be to update only if not scraped,
    # or always update these base fields and let detail scrape fill more.
    # For now, the CASE statement tries to handle status updates intelligently.

    try:
        cursor = conn.cursor()
        cursor.execute(sql, values_tuple)
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Inserted/Updated base booking record for {values_tuple[0]} with card_status: {card_status_enum.value if card_status_enum else None}, db_status: {db_status}")
        else:
            logger.debug(f"Base booking {values_tuple[0]} not inserted/updated (e.g. already scraped and not cancelled).")
    except sqlite3.Error as e:
        logger.error(f"Failed to insert/update base booking {values_tuple[0]}: {e}"); conn.rollback()


def update_booking_secondary_ids(conn: sqlite3.Connection,
                                 booking_id: str, creation_id: Optional[str], processing_id: Optional[str],
                                 appointment_count: Optional[int], type_hint: Optional[str]):
    if not booking_id: logger.warning("Attempted to update secondary IDs without booking_id."); return
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM bookings WHERE booking_id = ?", (booking_id,))
    if not cursor.fetchone(): logger.warning(f"Booking {booking_id} not found. Cannot update secondary IDs/hints."); return
    sql = '''
        UPDATE bookings SET creation_id = ?, processing_id = ?, mjr_id = ?,
            appointment_count_hint = ?, type_hint = ?, last_updated = CURRENT_TIMESTAMP
        WHERE booking_id = ? AND (
            ifnull(creation_id, '') <> ifnull(?, '') OR ifnull(processing_id, '') <> ifnull(?, '') OR
            ifnull(mjr_id, '') <> ifnull(?, '') OR ifnull(appointment_count_hint, -1) <> ifnull(?, -1) OR
            ifnull(type_hint, '') <> ifnull(?, '')
        )'''
    values = (creation_id, processing_id, processing_id, appointment_count, type_hint, booking_id,
              creation_id, processing_id, processing_id, appointment_count, type_hint)
    try:
        cursor.execute(sql, values)
        conn.commit()
        if cursor.rowcount > 0: logger.info(f"Updated secondary IDs & hints for booking {booking_id}")
    except sqlite3.Error as e: logger.error(f"Failed to update secondary IDs/hints for {booking_id}: {e}"); conn.rollback()

def save_multiday_header(conn: sqlite3.Connection, header_data: Dict[str, Any]):
    mjr_id = header_data.get('mjr_id')
    if not mjr_id: logger.error(f"Cannot save multiday header without mjr_id. Data: {header_data}"); return
    required_keys = ['mjr_id', 'date_range', 'appointment_info', 'overall_total', 'header_total']
    values_tuple = tuple(header_data.get(key) for key in required_keys)
    sql = f'''
        INSERT INTO multiday_headers (mjr_id, date_range, appointment_info, overall_total, header_total, last_updated)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(mjr_id) DO UPDATE SET
            date_range=excluded.date_range, appointment_info=excluded.appointment_info,
            overall_total=excluded.overall_total, header_total=excluded.header_total, last_updated=CURRENT_TIMESTAMP;'''
    try:
        cursor = conn.cursor(); cursor.execute(sql, values_tuple); conn.commit()
        logger.info(f"Saved/Replaced multiday header for MJR ID: {mjr_id}")
    except sqlite3.Error as e: logger.error(f"Failed to save multiday header for MJR ID {mjr_id}: {e}"); conn.rollback()

def save_booking_details(conn: sqlite3.Connection, parsed_data: Dict[str, Any], attempt_count: int = 1):
    booking_id = parsed_data.get('mja_id')
    if not booking_id: logger.error(f"Cannot save details without mja_id. Data: {parsed_data}"); return
    column_map = {
        'booking_id': 'mja_id', 'mjr_id': 'mjr_id', 'processing_id': 'processing_id',
        'is_multiday': 'is_multiday', 'appointment_sequence': 'appointment_sequence',
        'language_pair': 'language_pair', 'client_name': 'client_name', 'address': 'address',
        'booking_type': 'booking_type', 'contact_name': 'contact_name', 'contact_phone': 'contact_phone',
        'travel_distance': 'travel_distance', 'meeting_link': 'meeting_link',
        'booking_date': 'booking_date', 'start_time': 'start_time', 'end_time': 'end_time',
        'day_pay_sl': 'day_pay_sl', 'day_pay_ooh': 'day_pay_ooh', 'day_pay_urg': 'day_pay_urg',
        'day_pay_td': 'day_pay_td', 'day_pay_tt': 'day_pay_tt', 'day_pay_aep': 'day_pay_aep',
        'day_total': 'day_total', 'notes': 'notes',
        'scrape_attempt': 'scrape_attempt', 'status': 'status'
    }
    db_columns, value_placeholders, values_list, set_clauses = [], [], [], []
    for db_col, data_key in column_map.items():
        value = attempt_count if data_key == 'scrape_attempt' else 'scraped' if data_key == 'status' else parsed_data.get(data_key)
        db_columns.append(db_col); value_placeholders.append('?'); values_list.append(value)
        if db_col != 'booking_id': set_clauses.append(f"{db_col} = excluded.{db_col}")
    set_clauses.extend(["last_updated = CURRENT_TIMESTAMP", "status = excluded.status", "scrape_attempt = excluded.scrape_attempt"])
    sql = f"INSERT INTO bookings ({', '.join(db_columns)}) VALUES ({', '.join(value_placeholders)}) ON CONFLICT(booking_id) DO UPDATE SET {', '.join(set_clauses)};"
    try:
        cursor = conn.cursor(); cursor.execute(sql, tuple(values_list)); conn.commit()
        logger.info(f"Saved/Updated details for booking {booking_id}")
    except sqlite3.Error as e: logger.error(f"Failed to save/update details for {booking_id}: {e}\nSQL: {sql}\nValues: {tuple(values_list)}"); conn.rollback(); raise

def get_processed_booking_ids(conn: sqlite3.Connection) -> Set[str]:
    try:
        cursor = conn.cursor(); cursor.execute("SELECT booking_id FROM bookings")
        return {row[0] for row in cursor.fetchall() if row[0]}
    except sqlite3.Error as e: logger.error(f"Failed to retrieve processed booking IDs: {e}"); return set()

def get_booking_by_processing_id(conn: sqlite3.Connection, processing_id: str) -> Optional[Tuple]:
    if not processing_id: return None
    try: cursor = conn.cursor(); cursor.execute("SELECT * FROM bookings WHERE processing_id = ?", (processing_id,)); return cursor.fetchone()
    except sqlite3.Error as e: logger.error(f"Failed to retrieve booking by processing_id {processing_id}: {e}"); return None

def get_booking_refs(conn: sqlite3.Connection, booking_id: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    try:
        cursor = conn.cursor(); cursor.execute("SELECT creation_id, processing_id FROM bookings WHERE booking_id = ?", (booking_id,))
        row = cursor.fetchone(); return row if row else (None, None)
    except sqlite3.Error as e: logger.error(f"Failed to retrieve booking refs for {booking_id}: {e}"); return (None, None)

def update_booking_status(conn: sqlite3.Connection, booking_id: str, status: str, reason: Optional[str] = None):
     if not booking_id: logger.warning("Attempted to update status with no booking_id."); return
     sql = "UPDATE bookings SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE booking_id = ?"
     try:
         cursor = conn.cursor(); cursor.execute(sql, (status, booking_id)); conn.commit()
         log_msg = f"Updated status to '{status}' for booking {booking_id}" + (f" (Reason: {reason})" if reason else "")
         if cursor.rowcount > 0: logger.info(log_msg)
         else: logger.warning(f"Booking {booking_id} not found to update status to '{status}'.")
     except sqlite3.Error as e: logger.error(f"Failed to update status for booking {booking_id}: {e}"); conn.rollback()

def get_secondary_hints_for_mjr(conn: sqlite3.Connection, mjr_id: str) -> Optional[Tuple[Optional[int], Optional[str]]]:
    if not mjr_id: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT appointment_count_hint, type_hint FROM bookings WHERE mjr_id = ? AND is_multiday = 1 AND appointment_count_hint IS NOT NULL AND type_hint IS NOT NULL ORDER BY appointment_sequence ASC, booking_id ASC LIMIT 1", (mjr_id,))
        row = cursor.fetchone()
        if row: logger.debug(f"Found hints for MJR {mjr_id}: Count={row[0]}, Type='{row[1]}'"); return row
        else: logger.warning(f"Could not find record with secondary hints for MJR {mjr_id}."); return None
    except sqlite3.Error as e: logger.error(f"Failed to retrieve secondary hints for MJR {mjr_id}: {e}"); return None

def update_hints_for_mjr(conn: sqlite3.Connection, mjr_id: str, appointment_count_hint: Optional[int], type_hint: Optional[str]):
    if not mjr_id: logger.warning("Attempted to update hints without MJR ID."); return
    if appointment_count_hint is None and type_hint is None: logger.debug(f"No hints to update for MJR {mjr_id}."); return
    sql = "UPDATE bookings SET appointment_count_hint = ?, type_hint = ?, last_updated = CURRENT_TIMESTAMP WHERE mjr_id = ? AND (ifnull(appointment_count_hint, -1) <> ifnull(?, -1) OR ifnull(type_hint, '') <> ifnull(?, ''))"
    values = (appointment_count_hint, type_hint, mjr_id, appointment_count_hint, type_hint)
    try:
        cursor = conn.cursor(); cursor.execute(sql, values); conn.commit()
        if cursor.rowcount > 0: logger.info(f"Updated hints ({cursor.rowcount} records) for MJR {mjr_id}.")
        else: logger.debug(f"No hint updates needed for MJR {mjr_id}.")
    except sqlite3.Error as e: logger.error(f"Failed to update hints for MJR {mjr_id}: {e}"); conn.rollback()