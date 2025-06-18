# filename: db/repository.py
import sqlite3
from logger import get_logger
from typing import Dict, Any, List, Tuple, Optional, Set
import time
# MODIFIED: Using time_utils for parsing, assuming it has a function to get time objects
# If direct HH:MM:SS string is needed for DB, ensure formatting is handled.
# from utils.time_utils import parse_datetime_from_time_string
from parsers.detail_parser import parse_time as format_time_for_db # Keep if this specific format is needed for list page items
from state.models import BookingCardStatus, BookingProcessingStatus # Added BookingProcessingStatus

logger = get_logger(__name__)

def insert_booking_base(conn: sqlite3.Connection, card_data: Dict[str, Any]):
    # ... (implementation as provided previously, seems mostly okay for base insertion logic) ...
    card_status_enum = card_data.get('card_status', BookingCardStatus.NORMAL)
    db_status = BookingProcessingStatus.PENDING.value # Default status for normal bookings
    if card_status_enum == BookingCardStatus.CANCELLED:
        db_status = BookingProcessingStatus.CANCELLED_ON_LIST.value
    elif card_status_enum in [BookingCardStatus.NEW_OFFER, BookingCardStatus.VIEWED]:
        db_status = BookingProcessingStatus.SKIPPED_OFFER_VIEWED.value


    columns = [
        'booking_id', 'postcode',
        'start_time', 'end_time', 'duration', # These are from list card (mja_parser)
        'language_pair', 'isRemote', 'status', 'card_status', 'mjr_id' # Added mjr_id placeholder if available early
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
        db_status, 
        card_status_enum.value if card_status_enum else BookingCardStatus.UNKNOWN.value,
        card_data.get('mjr_id') # If mja_parser could ever get this (unlikely)
    )

    if not values_tuple[0]:
        logger.error(f"Attempted to insert booking without booking_id. Data: {card_data}")
        return

    sql = f'''
        INSERT INTO bookings ({', '.join(columns)}, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(booking_id) DO UPDATE SET
            postcode = excluded.postcode,
            start_time = excluded.start_time,
            end_time = excluded.end_time,
            duration = excluded.duration,
            language_pair = excluded.language_pair,
            isRemote = excluded.isRemote,
            status = CASE
                         WHEN bookings.status = '{BookingProcessingStatus.SCRAPED.value}' AND excluded.status = '{BookingProcessingStatus.CANCELLED_ON_LIST.value}' THEN excluded.status
                         WHEN bookings.status = '{BookingProcessingStatus.SCRAPED.value}' THEN bookings.status 
                         ELSE excluded.status
                     END,
            card_status = excluded.card_status,
            mjr_id = COALESCE(excluded.mjr_id, bookings.mjr_id), -- Update mjr_id if new one provided
            last_updated = CURRENT_TIMESTAMP
        WHERE bookings.booking_id = excluded.booking_id; 
    '''
    try:
        cursor = conn.cursor()
        cursor.execute(sql, values_tuple)
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Inserted/Updated base booking record for {values_tuple[0]} with card_status: {card_status_enum.value if card_status_enum else None}, db_status: {db_status}")
        else:
            logger.debug(f"Base booking {values_tuple[0]} not inserted/updated by upsert (e.g., status was '{BookingProcessingStatus.SCRAPED.value}' and no change needed).")
    except sqlite3.Error as e:
        logger.error(f"Failed to insert/update base booking {values_tuple[0]}: {e}"); conn.rollback()


def update_booking_secondary_ids(conn: sqlite3.Connection,
                                 booking_id: str, creation_id: Optional[str], processing_id: Optional[str], # processing_id is mjr_id
                                 appointment_count: Optional[int], type_hint: Optional[str]):
    if not booking_id:
        logger.warning("Attempted to update secondary IDs without booking_id (MJA ID).")
        return
    
    cursor = conn.cursor()
    cursor.execute("SELECT mjr_id FROM bookings WHERE booking_id = ?", (booking_id,))
    row = cursor.fetchone()
    if not row:
        logger.warning(f"Booking (MJA) {booking_id} not found in DB. Cannot update secondary IDs/hints.")
        return

    # If processing_id (MJR ID from secondary page) is different from existing mjr_id in DB, log warning or handle.
    # For now, we assume processing_id is the authoritative MJR ID.
    
    sql = '''
        UPDATE bookings 
        SET 
            creation_id = ?, 
            processing_id = ?, 
            mjr_id = ?,  -- This is the key update for linking MJA to MJR
            appointment_count_hint = ?, 
            type_hint = ?, 
            last_updated = CURRENT_TIMESTAMP
        WHERE booking_id = ? 
        AND (
            ifnull(creation_id, '') <> ifnull(?, '') OR 
            ifnull(processing_id, '') <> ifnull(?, '') OR
            ifnull(mjr_id, '') <> ifnull(?, '') OR 
            ifnull(appointment_count_hint, -1) <> ifnull(?, -1) OR
            ifnull(type_hint, '') <> ifnull(?, '')
        )
    '''
    # processing_id from secondary page is the MJR ID
    values = (creation_id, processing_id, processing_id, appointment_count, type_hint, booking_id,
              creation_id, processing_id, processing_id, appointment_count, type_hint)
    try:
        cursor.execute(sql, values)
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Updated secondary IDs & hints for MJA {booking_id} (MJR set to {processing_id})")
        else:
            logger.debug(f"No change in secondary IDs/hints for MJA {booking_id} or already up-to-date.")
    except sqlite3.Error as e:
        logger.error(f"Failed to update secondary IDs/hints for MJA {booking_id}: {e}")
        conn.rollback()

def save_booking_details(conn: sqlite3.Connection, parsed_data: Dict[str, Any], attempt_count: int = 1):
    # This function now receives a fully formed dictionary for a single MJA day
    # (either a single-day booking or one day of a multi-day booking)
    mja_id = parsed_data.get('mja_id') # This should be the specific MJA for the day
    if not mja_id:
        logger.error(f"Cannot save details: 'mja_id' is missing from parsed_data. Data: {parsed_data}")
        return

    # Ensure all expected columns in 'bookings' table are covered by keys in parsed_data or defaults
    column_map = {
        'booking_id': 'mja_id', 'mjr_id': 'mjr_id', 'creation_id': 'creation_id', 'processing_id': 'processing_id',
        'card_status': 'card_status', 'is_multiday': 'is_multiday', 
        'appointment_sequence': 'appointment_sequence', 'appointment_count_hint': 'appointment_count_hint',
        'type_hint': 'type_hint', 'language_pair': 'language_pair', 'client_name': 'client_name', 
        'address': 'address', 'booking_type': 'booking_type', 'contact_name': 'contact_name', 
        'contact_phone': 'contact_phone', 'travel_distance': 'travel_distance', 'meeting_link': 'meeting_link',
        'booking_date': 'booking_date', 'start_time': 'start_time', 'end_time': 'end_time', 
        'duration': 'duration', # Duration from detail parse, might differ from list
        'day_pay_sl': 'day_pay_sl', 'day_pay_ooh': 'day_pay_ooh', 'day_pay_urg': 'day_pay_urg',
        'day_pay_td': 'day_pay_td', 'day_pay_tt': 'day_pay_tt', 'day_pay_aep': 'day_pay_aep',
        'day_total': 'day_total', # This is now the sum for the specific MJA day
        'notes': 'notes', 'postcode': 'postcode', 'isRemote': 'isRemote',
        'scrape_attempt': 'scrape_attempt', 'status': 'status'
    }

    db_columns = []
    value_placeholders = []
    values_list = []
    set_clauses = []

    for db_col, data_key in column_map.items():
        db_columns.append(db_col)
        value_placeholders.append('?')
        if data_key == 'scrape_attempt':
            values_list.append(attempt_count)
        elif data_key == 'status':
            values_list.append(parsed_data.get(data_key, BookingProcessingStatus.SCRAPED.value)) # Default to scraped if status not in parsed_data
        else:
            values_list.append(parsed_data.get(data_key)) # Will be None if key missing
        
        if db_col != 'booking_id': # booking_id is MJA ID here, used for conflict target
            set_clauses.append(f"{db_col} = excluded.{db_col}")
            
    # Ensure last_updated is always set on update
    set_clauses.append("last_updated = CURRENT_TIMESTAMP")
    # Do not revert status from error states by a simple re-scrape unless explicitly intended.
    # The status field in parsed_data (defaulting to SCRAPED) will drive the update.

    sql = f"""
        INSERT INTO bookings ({', '.join(db_columns)}, last_updated)
        VALUES ({', '.join(['?'] * len(db_columns))}, CURRENT_TIMESTAMP)
        ON CONFLICT(booking_id) DO UPDATE SET
            {', '.join(set_clauses)}
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(values_list))
        conn.commit()
        logger.info(f"Saved/Updated details for booking MJA {mja_id} (MJR: {parsed_data.get('mjr_id')})")
    except sqlite3.Error as e:
        logger.error(f"Failed to save/update details for MJA {mja_id}: {e}\nSQL: {sql}\nValues: {tuple(values_list)}")
        conn.rollback()
        # raise # Optionally re-raise

# --- New and Modified Helper Functions for MJR processing ---

def get_mjr_id_for_mja(conn: sqlite3.Connection, mja_id: str) -> Optional[str]:
    """Retrieves the MJR ID for a given MJA ID from the database."""
    if not mja_id: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT mjr_id FROM bookings WHERE booking_id = ?", (mja_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve mjr_id for MJA {mja_id}: {e}")
        return None

def get_all_mja_ids_for_mjr(conn: sqlite3.Connection, mjr_id: str) -> Set[str]:
    """Retrieves all MJA IDs associated with a given MJR ID."""
    if not mjr_id: return set()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT booking_id FROM bookings WHERE mjr_id = ?", (mjr_id,))
        return {row[0] for row in cursor.fetchall() if row[0]}
    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve MJA IDs for MJR {mjr_id}: {e}")
        return set()

def check_if_all_mjas_for_mjr_scraped(conn: sqlite3.Connection, mjr_id: str) -> bool:
    """
    Checks if all expected MJA bookings for a given MJR ID are marked as 'scraped'.
    Relies on 'appointment_count_hint' from one of the MJA records.
    """
    if not mjr_id: return False
    try:
        cursor = conn.cursor()
        # Get appointment_count_hint (expected number of MJAs)
        cursor.execute("SELECT appointment_count_hint FROM bookings WHERE mjr_id = ? AND appointment_count_hint IS NOT NULL LIMIT 1", (mjr_id,))
        row = cursor.fetchone()
        if not row or row[0] is None:
            logger.debug(f"No appointment_count_hint found for MJR {mjr_id} to check for full scrape. Assuming not fully scraped.")
            return False 
        expected_mja_count = row[0]
        if expected_mja_count <= 0 : # Invalid count hint
             logger.debug(f"Invalid appointment_count_hint ({expected_mja_count}) for MJR {mjr_id}. Cannot confirm full scrape.")
             return False


        # Get count of actually scraped MJAs for this MJR
        cursor.execute("SELECT COUNT(booking_id) FROM bookings WHERE mjr_id = ? AND status = ?", (mjr_id, BookingProcessingStatus.SCRAPED.value))
        scraped_mja_count = cursor.fetchone()[0]
        
        is_fully_scraped = scraped_mja_count >= expected_mja_count
        if is_fully_scraped:
            logger.debug(f"MJR {mjr_id} confirmed as fully scraped in DB (expected {expected_mja_count}, found {scraped_mja_count}).")
        else:
            logger.debug(f"MJR {mjr_id} not yet fully scraped in DB (expected {expected_mja_count}, found {scraped_mja_count}).")
        return is_fully_scraped
    except sqlite3.Error as e:
        logger.error(f"Error checking if MJR {mjr_id} is fully scraped: {e}")
        return False # Assume not fully scraped on error

def update_all_mja_statuses_for_mjr(conn: sqlite3.Connection, mjr_id: str, new_status: str, reason: Optional[str] = None):
    """Updates the status of all MJA records associated with a given MJR ID."""
    if not mjr_id:
        logger.warning("Attempted to update all MJA statuses without an MJR ID.")
        return
    sql = """
        UPDATE bookings 
        SET status = ?, last_updated = CURRENT_TIMESTAMP 
        WHERE mjr_id = ? AND status <> ? 
    """ # Only update if status is different, to avoid unnecessary writes
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (new_status, mjr_id, new_status))
        conn.commit()
        if cursor.rowcount > 0:
            log_msg = f"Updated status to '{new_status}' for {cursor.rowcount} MJA records of MJR {mjr_id}" + (f" (Reason: {reason})" if reason else "")
            logger.info(log_msg)
        else:
            logger.debug(f"No MJA records needed status update to '{new_status}' for MJR {mjr_id}.")
    except sqlite3.Error as e:
        logger.error(f"Failed to update statuses for MJAs of MJR {mjr_id}: {e}")
        conn.rollback()


# --- Functions from previous version assumed to be okay or not directly related to this issue ---
def get_processed_booking_ids(conn: sqlite3.Connection) -> Set[str]:
    # ... (same as before) ...
    try:
        cursor = conn.cursor(); cursor.execute("SELECT booking_id FROM bookings")
        return {row[0] for row in cursor.fetchall() if row[0]}
    except sqlite3.Error as e: logger.error(f"Failed to retrieve processed booking IDs: {e}"); return set()

def get_booking_by_processing_id(conn: sqlite3.Connection, processing_id: str) -> Optional[Tuple]:
    # ... (same as before) ...
    if not processing_id: return None
    try: cursor = conn.cursor(); cursor.execute("SELECT * FROM bookings WHERE processing_id = ?", (processing_id,)); return cursor.fetchone()
    except sqlite3.Error as e: logger.error(f"Failed to retrieve booking by processing_id {processing_id}: {e}"); return None

def get_booking_refs(conn: sqlite3.Connection, booking_id: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    # ... (same as before) ...
    try:
        cursor = conn.cursor(); cursor.execute("SELECT creation_id, processing_id FROM bookings WHERE booking_id = ?", (booking_id,))
        row = cursor.fetchone(); return row if row else (None, None)
    except sqlite3.Error as e: logger.error(f"Failed to retrieve booking refs for {booking_id}: {e}"); return (None, None)

def update_booking_status(conn: sqlite3.Connection, booking_id: str, status: str, reason: Optional[str] = None):
    # ... (same as before) ...
     if not booking_id: logger.warning("Attempted to update status with no booking_id."); return
     sql = "UPDATE bookings SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE booking_id = ? AND status <> ?"
     try:
         cursor = conn.cursor(); cursor.execute(sql, (status, booking_id, status)); conn.commit()
         log_msg = f"Updated status to '{status}' for booking {booking_id}" + (f" (Reason: {reason})" if reason else "")
         if cursor.rowcount > 0: logger.info(log_msg)
         else: logger.debug(f"Booking {booking_id} status already '{status}' or not found.")
     except sqlite3.Error as e: logger.error(f"Failed to update status for booking {booking_id}: {e}"); conn.rollback()


def get_secondary_hints_for_mjr(conn: sqlite3.Connection, mjr_id: str) -> Optional[Tuple[Optional[int], Optional[str]]]:
    # ... (same as before, but ensure it's robust if some MJAs don't have hints) ...
    if not mjr_id: return None
    try:
        cursor = conn.cursor()
        # Get hints from any MJA associated with this MJR, prefer lower sequence or booking_id
        cursor.execute("""
            SELECT appointment_count_hint, type_hint 
            FROM bookings 
            WHERE mjr_id = ? 
              AND appointment_count_hint IS NOT NULL 
              AND type_hint IS NOT NULL 
            ORDER BY ifnull(appointment_sequence, 999999) ASC, booking_id ASC 
            LIMIT 1
        """, (mjr_id,))
        row = cursor.fetchone()
        if row: 
            logger.debug(f"Found hints for MJR {mjr_id}: Count={row[0]}, Type='{row[1]}'")
            return row[0], row[1] # Return as tuple
        else: 
            logger.warning(f"Could not find any record with secondary hints for MJR {mjr_id}.")
            return None, None # Return tuple of Nones
    except sqlite3.Error as e: 
        logger.error(f"Failed to retrieve secondary hints for MJR {mjr_id}: {e}")
        return None, None


def update_hints_for_mjr(conn: sqlite3.Connection, mjr_id: str, appointment_count_hint: Optional[int], type_hint: Optional[str]):
    # This function applies the *same* hint to all MJAs of an MJR.
    if not mjr_id: logger.warning("Attempted to update hints without MJR ID."); return
    if appointment_count_hint is None and type_hint is None: 
        logger.debug(f"No valid hints to update for MJR {mjr_id}.")
        return
    
    set_clauses = []
    values = []
    if appointment_count_hint is not None:
        set_clauses.append("appointment_count_hint = ?")
        values.append(appointment_count_hint)
    if type_hint is not None:
        set_clauses.append("type_hint = ?")
        values.append(type_hint)
    
    if not set_clauses: return # Should not happen if previous check passes

    values.append(mjr_id) # For the WHERE clause

    sql = f"""
        UPDATE bookings 
        SET {', '.join(set_clauses)}, last_updated = CURRENT_TIMESTAMP 
        WHERE mjr_id = ? 
    """
    # To avoid updating if values are already the same (optional, but reduces writes)
    # Can add conditions to WHERE like: AND (ifnull(appointment_count_hint, -1) <> ifnull(?, -1) OR ...)
    # For simplicity, this updates all matching MJR records if hints are provided.

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(values))
        conn.commit()
        if cursor.rowcount > 0: 
            logger.info(f"Updated hints ({cursor.rowcount} MJA records) for MJR {mjr_id} with Count={appointment_count_hint}, Type='{type_hint}'.")
        else: 
            logger.debug(f"No hint updates performed for MJR {mjr_id} (possibly already up-to-date or no records found).")
    except sqlite3.Error as e: 
        logger.error(f"Failed to update hints for MJR {mjr_id}: {e}")
        conn.rollback()