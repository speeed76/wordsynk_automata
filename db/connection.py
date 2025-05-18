# filename: db/connection.py
import sqlite3
import os
from logger import get_logger
from config import DB_PATH # Use DB_PATH from config
from .models import ( # Use relative import for models within the same package
    BOOKINGS_TABLE_SCHEMA,
    MULTIDAY_HEADERS_TABLE_SCHEMA,
    BOOKINGS_SCRAPE_TABLE_SCHEMA,
    # Add other schemas if they exist in models.py
    # BOOKING_STATUS_TABLE_SCHEMA,
    # BOOKING_HISTORY_TABLE_SCHEMA
)
from typing import Optional # Added this import

logger = get_logger(__name__)

def _execute_schema(cursor: sqlite3.Cursor, schema: str, table_name: str):
    """Helper function to execute a schema if the table doesn't exist."""
    try:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        if not cursor.fetchone():
            logger.debug(f"Table '{table_name}' not found, creating now...")
            cursor.executescript(schema) # Use executescript for multi-statement schemas if needed
            logger.info(f"Table '{table_name}' created successfully.")
        else:
            logger.debug(f"Table '{table_name}' already exists.")
    except sqlite3.Error as e:
        logger.error(f"Error handling table '{table_name}': {e}")
        raise # Re-raise the exception to be handled by the caller


def init_db(db_path: str = DB_PATH, test_mode: bool = False) -> sqlite3.Connection:
    """
    Initializes the SQLite database. Creates tables if they don't exist.
    If test_mode is True, it will delete the existing DB file to start fresh.

    Args:
        db_path (str): The path to the SQLite database file.
        test_mode (bool): If True, resets the database by deleting the file.

    Returns:
        sqlite3.Connection: The database connection object.
    """
    if test_mode and os.path.exists(db_path):
        try:
            logger.warning(f"TEST_MODE: Deleting existing database at {db_path}")
            os.remove(db_path)
        except OSError as e:
            logger.error(f"Error deleting database file in test_mode: {e}")
            # Decide if this is critical or if we can proceed
            # For now, let's proceed and sqlite3.connect will create a new one if deletion failed

    conn = None
    try:
        # The connect function will create the DB file if it doesn't exist.
        conn = sqlite3.connect(db_path, check_same_thread=False) # check_same_thread=False if used across threads
        logger.info(f"Database connection established to: {db_path}")

        # Enable Write-Ahead Logging (WAL) for better concurrency and performance
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            logger.debug("Enabled WAL journal mode.")
        except sqlite3.Error as e:
            logger.warning(f"Could not enable WAL journal mode: {e}")


        cursor = conn.cursor()
        # Create tables using schemas from models.py
        _execute_schema(cursor, BOOKINGS_TABLE_SCHEMA, "bookings")
        _execute_schema(cursor, MULTIDAY_HEADERS_TABLE_SCHEMA, "multiday_headers")
        _execute_schema(cursor, BOOKINGS_SCRAPE_TABLE_SCHEMA, "bookings_scrape")
        # Add other table creations here if needed
        # _execute_schema(cursor, BOOKING_STATUS_TABLE_SCHEMA, "booking_status")
        # _execute_schema(cursor, BOOKING_HISTORY_TABLE_SCHEMA, "booking_history")

        conn.commit() # Commit schema changes
        logger.debug("Table creation/check complete.")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        if conn:
            conn.rollback() # Rollback any partial changes
            conn.close()
        raise # Re-raise the exception
    except Exception as e: # Catch other potential errors like permissions
        logger.error(f"An unexpected error occurred during database initialization: {e}")
        if conn:
            conn.close()
        raise


def close_db(conn: Optional[sqlite3.Connection]): # Optional was used here
    """Closes the database connection if it's open."""
    if conn:
        try:
            conn.close()
            logger.info("Database connection closed.")
        except sqlite3.Error as e:
            logger.error(f"Error closing database connection: {e}")

if __name__ == '__main__':
    # Example of initializing the database (creates it if not exists)
    # Set test_mode=True to reset it for testing
    logger.info("Initializing database directly from connection.py (for testing/setup)...")
    connection = init_db(test_mode=False) # Set to True to reset DB on run
    if connection:
        logger.info("Database initialized successfully.")
        close_db(connection)
    else:
        logger.error("Database initialization failed.")