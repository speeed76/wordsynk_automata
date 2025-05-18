# filename: tests/parsers/test_mja_parser.py
import pytest
from parsers.mja_parser import parse_mja
from state.models import BookingCardStatus # Import the new Enum
from typing import Dict, Optional, Any

@pytest.mark.parametrize("desc, expected_output", [
    (
        "MJA00000001, AB1 2CD, 09:00 to 10:00, English to Polish",
        {
            "booking_id": "MJA00000001", "card_status": BookingCardStatus.NORMAL,
            "postcode": "AB1 2CD", "start_time_raw": "09:00", "end_time_raw": "10:00",
            "calculated_duration_str": "01:00", "language_pair": "English to Polish",
            "isRemote": 0, "original_duration_str": "09:00 to 10:00"
        }
    ),
    ( # With status prefix
        "Viewed, MJA00000002, M11AA, 14:30 - 15:30, English to French",
        {
            "booking_id": "MJA00000002", "card_status": BookingCardStatus.VIEWED,
            "postcode": "M1 1AA", "start_time_raw": "14:30", "end_time_raw": "15:30",
            "calculated_duration_str": "01:00", "language_pair": "English to French",
            "isRemote": 0, "original_duration_str": "14:30 to 15:30"
        }
    ),
    (
        "Cancelled, MJA00000003, Remote, 10:00 to 11:00, English to Spanish",
        {
            "booking_id": "MJA00000003", "card_status": BookingCardStatus.CANCELLED,
            "postcode": None, "start_time_raw": "10:00", "end_time_raw": "11:00",
            "calculated_duration_str": "01:00", "language_pair": "English to Spanish",
            "isRemote": 1, "original_duration_str": "10:00 to 11:00"
        }
    ),
    (
        "New Offer, MJA00000004, English to German", # No postcode, no duration
        {
            "booking_id": "MJA00000004", "card_status": BookingCardStatus.NEW_OFFER,
            "postcode": None, "start_time_raw": None, "end_time_raw": None,
            "calculated_duration_str": None, "language_pair": "English to German",
            "isRemote": 1, "original_duration_str": None
        }
    ),
    (
        "MJA00000005", # Only MJA ID, normal status
        {
            "booking_id": "MJA00000005", "card_status": BookingCardStatus.NORMAL,
            "postcode": None, "start_time_raw": None, "end_time_raw": None,
            "calculated_duration_str": None, "language_pair": None,
            "isRemote": 1, "original_duration_str": None
        }
    ),
    ( # Status prefix with only MJA ID
        "Viewed, MJA00000006",
        {
            "booking_id": "MJA00000006", "card_status": BookingCardStatus.VIEWED,
            "postcode": None, "start_time_raw": None, "end_time_raw": None,
            "calculated_duration_str": None, "language_pair": None,
            "isRemote": 1, "original_duration_str": None
        }
    ),
    ( # Unknown prefix
        "UnknownStatus, MJA00000007, AB1 2CD, 09:00 to 10:00, English to Polish",
        {
            "booking_id": "MJA00000007", "card_status": BookingCardStatus.NORMAL, # Defaults to NORMAL if prefix not in KNOWN_STATUS_PREFIXES
            "postcode": "AB1 2CD", "start_time_raw": "09:00", "end_time_raw": "10:00",
            "calculated_duration_str": "01:00", "language_pair": "English to Polish", # Language pair parsing needs to be robust
            "isRemote": 0, "original_duration_str": "09:00 to 10:00"
        }
    ),
    ("InvalidDescription", None),
    ("", None)
])
def test_parse_mja_various_inputs(desc, expected_output):
    result = parse_mja(desc)
    assert result == expected_output

def test_parse_mja_no_mja_id_after_status():
    desc = "Cancelled, NoMJAIDHere, AB1 2CD, 09:00 to 10:00, English to Polish"
    assert parse_mja(desc) is None