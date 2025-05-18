# filename: db/models.py
from enum import Enum # Already in state/models.py, but good for clarity if this file were standalone

# Schema for the main bookings table
BOOKINGS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,      -- MJA ID (Unique for each booking day/part)
    mjr_id TEXT,                      -- MJR ID (Links parts of a multiday booking)
    creation_id TEXT,                 -- MJB ID (From secondary page)
    processing_id TEXT,               -- Corresponds to MJR ID (From secondary page)
    
    card_status TEXT,                 -- New field: Status from list card (e.g., Cancelled, New Offer, Viewed, Normal)
    
    is_multiday INTEGER DEFAULT 0,    -- Boolean (0 or 1)
    appointment_sequence INTEGER,     -- For multiday, e.g., 1, 2, 3... (1 for single day)
    appointment_count_hint INTEGER,   -- Total appointments for the MJR (from secondary page)
    type_hint TEXT,                   -- "Face To Face" or "Video Remote Interpreting" (from secondary page)

    language_pair TEXT,
    client_name TEXT,
    address TEXT,                     -- Full address, potentially multi-line
    booking_type TEXT,                -- e.g., "Tribunals - ET | Full hearing"
    contact_name TEXT,
    contact_phone TEXT,
    travel_distance REAL,             -- Parsed numeric distance (e.g., 9.82)
    meeting_link TEXT,                -- URL or email for remote meetings

    booking_date TEXT,                -- DD-MM-YYYY (For single day, or start date of multi-day if applicable)
    start_time TEXT,                  -- HH:MM:SS (Parsed from list or detail)
    end_time TEXT,                    -- HH:MM:SS (Parsed from list or detail)
    duration TEXT,                    -- Calculated duration as HH:MM string (from mja_parser or detail)

    -- Payment details for the specific MJA day
    day_pay_sl REAL,                  -- Service Line Item
    day_pay_ooh REAL,                 -- Out of Hours Uplift
    day_pay_urg REAL,                 -- Urgency Uplift
    day_pay_td REAL,                  -- Travel Distance Line Item
    day_pay_tt REAL,                  -- Travel Time Line Item
    day_pay_aep REAL,                 -- Automation Enhancement Payment
    day_total REAL,                   -- Calculated total for this day (overall_total for single, avg for multi)

    notes TEXT,
    
    -- Fields from list page (content-desc) that might not be on detail page
    postcode TEXT,                    -- Sanitized postcode from list view
    isRemote INTEGER DEFAULT 0,       -- Boolean (0 or 1) based on list view postcode/remote text

    -- Meta fields
    last_updated TEXT,
    scrape_attempt INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'     -- e.g., pending, scraped, error, cancelled_on_list, skipped_offer_viewed
);
"""

# Schema for multiday booking headers (MJR specific overall info)
MULTIDAY_HEADERS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS multiday_headers (
    mjr_id TEXT PRIMARY KEY,
    date_range TEXT,
    appointment_info TEXT,
    overall_total REAL,
    header_total REAL,
    last_updated TEXT
);
"""

# Schema for tracking scrape sessions and progress
BOOKINGS_SCRAPE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings_scrape (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL,
    last_state TEXT,
    current_booking_id TEXT,
    current_mjr_id TEXT,
    last_processed_booking_id TEXT,
    total_bookings_scraped INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    error_message TEXT
);
"""