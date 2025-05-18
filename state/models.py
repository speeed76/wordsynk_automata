# filename: state/models.py
from enum import Enum

class ScrapeState(Enum):
    """Defines the possible states of the booking scraper."""
    INITIALIZING = 1
    NAVIGATING_TO_LIST = 2
    LIST = 3
    SECONDARY = 4
    DETAIL = 5
    ERROR = 6
    FINISHED = 7
    IDLE = 8

class BookingProcessingStatus(Enum):
    """Defines the processing status of individual bookings in the database."""
    PENDING = "pending"
    SECONDARY_PROCESSED = "secondary_processed"
    SCRAPED = "scraped"
    CANCELLED_ON_LIST = "cancelled_on_list" # New status for cancelled items
    ERROR_LIST = "error_list"
    ERROR_SECONDARY_NAV = "error_nav_secondary"
    ERROR_SECONDARY_INFO = "error_secondary_info"
    ERROR_SECONDARY_CLICK_MJR = "error_click_mjr"
    ERROR_DETAIL_NAV = "error_nav_detail"
    ERROR_DETAIL_EXTRACT = "error_detail_extract"
    ERROR_SAVE = "error_save"
    ERROR_UNKNOWN = "error_unknown"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_MANUAL = "skipped_manual"
    SKIPPED_OFFER_VIEWED = "skipped_offer_viewed" # For New Offer / Viewed

class BookingCardStatus(Enum):
    """Status of a booking as observed directly on the list page card."""
    NORMAL = "Normal" # Default if no prefix
    CANCELLED = "Cancelled"
    NEW_OFFER = "New Offer"
    VIEWED = "Viewed"
    UNKNOWN = "Unknown" # If a prefix is there but not recognized

# User-proposed enum for richer context to parsers (not fully integrated yet)
class BookingDetailContext(Enum):
    """
    Provides more granular context about the booking type being processed,
    which can inform the DetailParser. This state would ideally be determined
    from list/secondary page info and passed to the DetailProcessor.
    """
    # Face-to-Face Single Day
    F2F_SINGLE_NO_TRAVEL = "Face to Face - Single Day - No travel"
    F2F_SINGLE_TRAVEL_DISTANCE_ONLY = "Face to Face - Single Day - Travel distance pay only"
    F2F_SINGLE_FULL_TRAVEL = "Face to Face - Single Day - Travel time and distance pay"

    # Face-to-Face Multi Day
    F2F_MULTI_NO_TRAVEL = "Face to Face - Multi Day - No travel"
    F2F_MULTI_TRAVEL_DISTANCE_ONLY = "Face to Face - Multi Day - Travel distance pay only"
    F2F_MULTI_FULL_TRAVEL = "Face to Face - Multi Day - Travel time and distance pay"

    # Remote Single Day
    REMOTE_SINGLE_NO_LINK_INFO = "Remote - Single Day - No meeting link found in info block"
    REMOTE_SINGLE_WITH_LINK_INFO = "Remote - Single Day - Meeting link found in info block"

    # Remote Multi Day
    REMOTE_MULTI_NO_LINK_INFO = "Remote - Multi Day - No meeting link found in info block"
    REMOTE_MULTI_WITH_LINK_INFO = "Remote - Multi Day - Meeting link found in info block"
    
    CLIENT_ADMIN_NONE = "Client Admin - No details provided"
    CLIENT_ADMIN_NAME_ONLY = "Client Admin - Name only"
    CLIENT_ADMIN_PHONE_ONLY = "Client Admin - Phone number only"
    CLIENT_ADMIN_NAME_AND_PHONE = "Client Admin - Name and phone number"
    
    UNKNOWN_DETAIL_STRUCTURE = "Unknown Detail Structure"