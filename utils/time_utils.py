# filename: utils/time_utils.py
import datetime
from typing import Optional
from logger import get_logger

logger = get_logger(__name__)

def parse_datetime_from_time_string(time_str: Optional[str]) -> Optional[datetime.time]:
    """
    Parses a time string (e.g., "HH:MM") into a datetime.time object.
    Returns None if parsing fails or input is invalid.
    """
    if not time_str:
        return None
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour < 24 and 0 <= minute < 60:
                return datetime.datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
            else:
                logger.warning(f"Time values out of range: hour={hour}, minute={minute} from '{time_str}'")
                return None
        else:
            logger.warning(f"Time string '{time_str}' not in HH:MM format.")
            return None
    except ValueError:
        logger.warning(f"Could not parse time string '{time_str}' to time object due to ValueError.")
        return None

def calculate_duration_string(start_time_obj: Optional[datetime.time], end_time_obj: Optional[datetime.time]) -> Optional[str]:
    """
    Calculates the duration between two datetime.time objects and returns it as "HH:MM".
    Handles overnight durations. Returns "00:00" if times are identical.
    Returns None if either input is None or if start_time is after end_time in a non-overnight context.
    """
    if not start_time_obj or not end_time_obj:
        return None

    # Use a dummy date to combine with time objects for timedelta calculation
    dummy_date = datetime.date(2000, 1, 1)
    start_dt = datetime.datetime.combine(dummy_date, start_time_obj)
    end_dt = datetime.datetime.combine(dummy_date, end_time_obj)

    if end_dt == start_dt:
        return "00:00"

    # Handle overnight case: if end_time is earlier than start_time, assume it's on the next day
    if end_dt < start_dt:
        end_dt += datetime.timedelta(days=1)

    duration_delta = end_dt - start_dt
    total_seconds = duration_delta.total_seconds()

    # Should not happen if overnight logic is correct, but as a safeguard
    if total_seconds < 0:
        logger.warning(f"Calculated negative duration for start {start_time_obj} and end {end_time_obj}.")
        return None

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    return f"{hours:02d}:{minutes:02d}"