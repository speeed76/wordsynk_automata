# filename: state/manager.py
import sqlite3
import time
from typing import Optional, Dict, Any
from logger import get_logger
from .models import ScrapeState # Relative import

logger = get_logger(__name__)

class StateManager:
    """Manages the state of the scrape session persisted in the database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.session_id: Optional[int] = None
        self.start_time: Optional[str] = None
        self.current_state: ScrapeState = ScrapeState.INITIALIZING
        self.previous_state: Optional[ScrapeState] = None
        self.current_booking_id: Optional[str] = None # Current MJA ID
        self.current_mjr_id: Optional[str] = None    # Current MJR ID
        self.last_processed_booking_id: Optional[str] = None # Last MJA processed on LIST page for scroll anchor
        self.total_bookings_scraped_session: int = 0
        self.total_errors_session: int = 0
        self.current_scrape_attempt: int = 0 # Current attempt for a specific booking detail

    def _execute_query(self, query: str, params: tuple = ()) -> Optional[sqlite3.Cursor]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Database error during query: {query} | PARAMS: {params} | ERROR: {e}")
            self.conn.rollback()
            return None

    def load_or_create_session(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT session_id, start_time, last_state, current_booking_id, current_mjr_id,
                   last_processed_booking_id, total_bookings_scraped, total_errors
            FROM bookings_scrape
            WHERE status = 'running' OR status = 'error'
            ORDER BY CASE status WHEN 'running' THEN 1 WHEN 'error' THEN 2 ELSE 3 END, start_time DESC
            LIMIT 1
        """)
        row = cursor.fetchone()

        if row:
            self.session_id, self.start_time, last_state_str, self.current_booking_id, \
            self.current_mjr_id, self.last_processed_booking_id, \
            self.total_bookings_scraped_session, self.total_errors_session = row
            try:
                self.current_state = ScrapeState[last_state_str] if last_state_str else ScrapeState.NAVIGATING_TO_LIST
            except KeyError:
                logger.warning(f"Invalid last_state '{last_state_str}' from DB. Defaulting to NAVIGATING_TO_LIST.")
                self.current_state = ScrapeState.NAVIGATING_TO_LIST
            
            if self.current_state not in [ScrapeState.SECONDARY, ScrapeState.DETAIL, ScrapeState.LIST]: # Resume list if not mid-booking
                 self.current_state = ScrapeState.NAVIGATING_TO_LIST
            logger.info(f"Resuming session {self.session_id} from state {self.current_state.name}. Last MJA: {self.last_processed_booking_id}, Current MJA: {self.current_booking_id}, MJR: {self.current_mjr_id}")
            self._execute_query("UPDATE bookings_scrape SET status = 'running', start_time = ? WHERE session_id = ?", (time.strftime("%Y-%m-%d %H:%M:%S"), self.session_id))
        else:
            self.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.current_state = ScrapeState.NAVIGATING_TO_LIST
            self.total_bookings_scraped_session = 0; self.total_errors_session = 0
            insert_cursor = self._execute_query(
                "INSERT INTO bookings_scrape (start_time, status, last_state) VALUES (?, 'running', ?)",
                (self.start_time, self.current_state.name)
            )
            if insert_cursor: self.session_id = insert_cursor.lastrowid; logger.info(f"Created new scrape session {self.session_id}")
            else: raise Exception("Failed to initialize scrape session in database.")
        
        if self.current_booking_id and self.current_state in [ScrapeState.DETAIL, ScrapeState.SECONDARY]:
            cursor.execute("SELECT scrape_attempt FROM bookings WHERE booking_id = ?", (self.current_booking_id,))
            attempt_row = cursor.fetchone()
            self.current_scrape_attempt = attempt_row[0] if attempt_row and attempt_row[0] is not None else 0
        else: self.current_scrape_attempt = 0

    def update_state(self, new_state: ScrapeState,
                     current_booking_id: Optional[str] = ..., # Use Ellipsis for "no change"
                     current_mjr_id: Optional[str] = ...,
                     last_processed_booking_id: Optional[str] = ...,
                     error_message: Optional[str] = None):
        self.previous_state = self.current_state
        self.current_state = new_state

        if current_booking_id is not ...: self.current_booking_id = current_booking_id
        if current_mjr_id is not ...: self.current_mjr_id = current_mjr_id
        if last_processed_booking_id is not ...: self.last_processed_booking_id = last_processed_booking_id
        
        if new_state == ScrapeState.ERROR: # Increment error count if we are setting error state
            if error_message: logger.error(f"Error state triggered: {error_message}")
            else: logger.error("Error state triggered with no specific message.")
            self.total_errors_session +=1
        elif new_state == ScrapeState.DETAIL and self.previous_state == ScrapeState.SECONDARY:
            self.current_scrape_attempt = 0 # Reset for new detail page

        if self.session_id is not None:
            current_status = 'error' if new_state == ScrapeState.ERROR else 'running'
            current_error_msg_for_db = error_message if new_state == ScrapeState.ERROR else self.get_current_error_message() # Keep last error if just updating state
            
            self._execute_query(
                """UPDATE bookings_scrape SET last_state = ?, current_booking_id = ?, current_mjr_id = ?,
                   last_processed_booking_id = ?, error_message = ?, total_errors = ?, status = ?
                   WHERE session_id = ?""",
                (self.current_state.name, self.current_booking_id, self.current_mjr_id,
                 self.last_processed_booking_id, current_error_msg_for_db, self.total_errors_session,
                 current_status, self.session_id)
            )
        logger.debug(f"State updated to {self.current_state.name} for session {self.session_id} (MJA: {self.current_booking_id}, MJR: {self.current_mjr_id}, LastProcMJA: {self.last_processed_booking_id})")

    def increment_scrape_attempt(self):
        self.current_scrape_attempt += 1

    def record_booking_scraped(self):
        self.total_bookings_scraped_session += 1
        if self.session_id is not None:
             self._execute_query("UPDATE bookings_scrape SET total_bookings_scraped = ? WHERE session_id = ?",
                                (self.total_bookings_scraped_session, self.session_id))

    def finish_session(self, status: str = 'completed', final_error_message: Optional[str] = None):
        self.current_state = ScrapeState.FINISHED if status == 'completed' else ScrapeState.ERROR
        end_time = time.strftime("%Y-%m-%d %H:%M:%S")
        if self.session_id is not None:
            final_status = 'error' if self.current_state == ScrapeState.ERROR else status
            error_msg_to_save = final_error_message if final_error_message else self.get_current_error_message()
            
            self._execute_query(
                "UPDATE bookings_scrape SET end_time = ?, status = ?, last_state = ?, error_message = ? WHERE session_id = ?",
                (end_time, final_status, self.current_state.name, error_msg_to_save, self.session_id)
            )
        logger.info(f"Scrape session {self.session_id} finished with status: {final_status}. Total scraped: {self.total_bookings_scraped_session}, Total errors: {self.total_errors_session}.")

    def get_current_error_message(self) -> Optional[str]:
        if not self.session_id: return None
        cursor = self.conn.cursor()
        cursor.execute("SELECT error_message FROM bookings_scrape WHERE session_id = ?", (self.session_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None