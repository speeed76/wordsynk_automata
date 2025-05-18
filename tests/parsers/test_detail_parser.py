# filename: tests/parsers/test_detail_parser.py
import pytest
from parsers.detail_parser import (
    parse_money, parse_uk_date, parse_time,
    _extract_texts_from_xml,
    extract_header_and_booking_type,
    extract_info_block,
    extract_mja_payment_blocks,
    extract_notes_and_total,
    parse_detail_data,
    check_if_multiday_from_xml,
    MEETING_LINK_TEXT # Import if used directly in tests
)

# --- Fixtures (Keep existing sample_xml fixtures) ---
@pytest.fixture
def sample_xml_single_day_with_distance():
    return """
    <hierarchy>
      <node text="Booking #MJR00225672" />
      <node text="£ 89.93" />
      <node text="01-05-2025 At &#10;10:00 - 13:00" />
      <node text="English to Polish" />
      <node text="Leeds Magistrates' Court - Crime" />
      <node text="Leeds District Magistrates' Court" />
      <node text="Westgate Leeds England LS1 3BY" />
      <node text="Crime - Magistrates' Court | Trial" />
      <node text="Peter McArthur" />
      <node text="0" />
      <node text="9.82 Miles" />
      <node text="Open Directions" />
      <node text="Timesheets Download" />
      <node text="" />
      <node text="MJA00300359" />
      <node text="Service Line Item" />
      <node text="£ 78" />
      <node text="Travel Distance Line Item" />
      <node text="£ 1.93" />
      <node text="Automation Enhancement Payment" />
      <node text="£ 10" />
      <node text="TOTAL" />
      <node text="£ 89.93" />
      <node text="13WD0282624 - Courtroom 08" />
      <node text="By accepting this assignment" />
    </hierarchy>
    """

@pytest.fixture
def sample_xml_multiday():
    return """
    <hierarchy>
      <node text="Booking #MJR00156403" />
      <node text="£ 332.00" />
      <node text="Multiday &#10;01-07-2025 - 02-07-2025" />
      <node text="2 Appointments / 2 Days" />
      <node text="English to Polish" />
      <node text="London South ET" />
      <node text="Tribunals - ET | Full hearing" />
      <node text="Helen Cattley" />
      <node text="" /> 
      <node text="Timesheets Download" />
      <node text="" />
      <node text="MJA00215619" />
      <node text="Service Line Item" />
      <node text="£ 156" />
      <node text="Automation Enhancement Payment" />
      <node text="£ 10" />
      <node text="MJA00215620" />
      <node text="Service Line Item" />
      <node text="£ 156" />
      <node text="Automation Enhancement Payment" />
      <node text="£ 10" />
      <node text="TOTAL" />
      <node text="£ 332.00" />
      <node text="By accepting this assignment" />
    </hierarchy>
    """

@pytest.fixture
def sample_xml_video_remote_no_address():
    return """
    <hierarchy>
      <node text="Booking #MJR00233330" />
      <node text="£ 44.00" />
      <node text="21-05-2025 At &#10;11:00 - 12:00" />
      <node text="English to Polish" />
      <node text="Bradford &amp; Calderdale (TPS)" />
      <node text="Meeting Link" />
      <node text="NPS | Face to Face Interviews which take place within custodial" />
      <node text="undefined undefined" />
      <node text="undefined" />
      <node text="Timesheets Download" />
      <node text="MJA00309647" />
      <node text="Service Line Item" />
      <node text="£ 24" />
      <node text="Automation Enhancement Payment" />
      <node text="£ 20" />
      <node text="TOTAL" />
      <node text="£ 44.00" />
      <node text="VIDEO LINK IS ONLY FOR PROFESSIONAL VISITS. NO FAMILY, NO FRIENDS AND NO CHILDERN ARE ALLOWED ON THE LINK.&#10;PHOTO ID MUST BE SHOWN WHEN JOINING THE LINK.&#10;vcchmpleeds4@meet.video.justice.gov.uk" />
      <node text="By accepting this assignment" />
    </hierarchy>
    """

# --- Tests for Helper Parsing Functions ---
@pytest.mark.parametrize("raw, expected", [
    ("£ 123.45", 123.45), ("£1,234.56", 1234.56), ("£0.50", 0.50),
    ("123.45", None), # Corrected: Expect None if no '£'
    ("Invalid", None), (None, None), ("£", None), ("£ text", None)
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected

@pytest.mark.parametrize("raw, expected", [
    ("01-12-2023", "01-12-2023"), # Corrected: Expect DD-MM-YYYY
    ("31-01-2024 At some time", "31-01-2024"), # Corrected: Expect DD-MM-YYYY
    ("Invalid", None), (None, None),
    ("1-1-2023", None), # Correctly expects None for invalid format
    ("2023-12-01", None) # Correctly expects None for invalid format
])
def test_parse_uk_date(raw, expected):
    assert parse_uk_date(raw) == expected

@pytest.mark.parametrize("raw, expected", [
    ("9:30", "09:30:00"), ("14:05", "14:05:00"), ("09:30", "09:30:00"),
    ("9:5", "09:05:00"),
    ("Invalid", None), (None, None), ("25:00", None), ("10:60", None)
])
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected

def test_extract_texts_from_xml(sample_xml_single_day_with_distance):
    texts = _extract_texts_from_xml(sample_xml_single_day_with_distance)
    assert isinstance(texts, list)
    assert "Booking #MJR00225672" in texts
    assert "£ 89.93" in texts
    # Corrected: Check for split parts
    assert "01-05-2025 At" in texts
    assert "10:00 - 13:00" in texts
    assert "English to Polish" in texts
    assert "9.82 Miles" in texts
    assert "By accepting this assignment" in texts
    assert not any(not text_item.strip() for text_item in texts if text_item is not None)

def test_check_if_multiday_from_xml(sample_xml_multiday, sample_xml_single_day_with_distance):
    assert check_if_multiday_from_xml(sample_xml_multiday) is True
    assert check_if_multiday_from_xml(sample_xml_single_day_with_distance) is False

def test_extract_header_single_day(sample_xml_single_day_with_distance):
    texts = _extract_texts_from_xml(sample_xml_single_day_with_distance)
    header_data, is_multiday, lang_idx = extract_header_and_booking_type(texts)
    assert is_multiday is False
    assert header_data['mjr_id_raw'] == "MJR00225672"
    assert header_data['total_value_header_raw'] == "£ 89.93"
    # Corrected: Check the tuple
    assert header_data['date_time_raw_tuple'] == ("01-05-2025 At", "10:00 - 13:00")
    assert header_data['multiday_date_range_raw'] is None
    assert lang_idx == texts.index("English to Polish")

def test_extract_header_multiday(sample_xml_multiday):
    texts = _extract_texts_from_xml(sample_xml_multiday)
    header_data, is_multiday, lang_idx = extract_header_and_booking_type(texts)
    assert is_multiday is True
    assert header_data['mjr_id_raw'] == "MJR00156403"
    assert header_data['total_value_header_raw'] == "£ 332.00"
    # Corrected: Check the tuple (which should be None for multiday)
    assert header_data['date_time_raw_tuple'] is None
    assert header_data['multiday_date_range_raw'] == "01-07-2025 - 02-07-2025"
    assert header_data['multiday_appointment_count_raw'] == "2 Appointments / 2 Days"
    assert lang_idx == texts.index("English to Polish")

# ... (Keep existing extract_info_block tests, extract_mja_payment_blocks tests, extract_notes_and_total tests)
def test_extract_info_block_single_day_with_distance(sample_xml_single_day_with_distance):
    texts = _extract_texts_from_xml(sample_xml_single_day_with_distance)
    _hd, _im, lang_idx = extract_header_and_booking_type(texts)
    assert lang_idx is not None
    info_data = extract_info_block(texts, lang_idx)
    assert info_data['language_pair_raw'] == "English to Polish"
    assert info_data['client_name_raw'] == "Leeds Magistrates' Court - Crime"
    assert info_data['address_line1_raw'] == "Leeds District Magistrates' Court"
    assert info_data['address_line2_raw'] == "Westgate Leeds England LS1 3BY"
    assert info_data['booking_type_raw'] == "Crime - Magistrates' Court | Trial"
    assert info_data['contact_name_raw'] == "Peter McArthur"
    assert info_data['contact_phone_raw'] is None
    assert info_data['distance_raw'] == "9.82 Miles"
    assert info_data['meeting_link_raw'] is None

def test_parse_detail_data_single_day(sample_xml_single_day_with_distance):
    texts = _extract_texts_from_xml(sample_xml_single_day_with_distance)
    header_info, is_multiday, lang_idx = extract_header_and_booking_type(texts)
    assert lang_idx is not None
    info_block = extract_info_block(texts, lang_idx)
    mja_blocks = extract_mja_payment_blocks(texts)
    notes_total = extract_notes_and_total(texts)
    parsed = parse_detail_data(header_info, is_multiday, info_block, mja_blocks, notes_total)

    assert parsed['is_multiday'] is False
    assert parsed['mjr_id'] == "MJR00225672"
    assert parsed['mja_id'] == "MJA00300359"
    assert parsed['booking_date'] == "01-05-2025" # Corrected: Expect DD-MM-YYYY
    assert parsed['start_time'] == "10:00:00"
    assert parsed['end_time'] == "13:00:00"
    assert parsed['language_pair'] == "English to Polish"
    assert parsed['client_name'] == "Leeds Magistrates' Court - Crime"
    assert parsed['address'] == "Leeds District Magistrates' Court\nWestgate Leeds England LS1 3BY"
    assert parsed['booking_type'] == "Crime - Magistrates' Court | Trial"
    assert parsed['contact_name'] == "Peter McArthur"
    assert parsed['contact_phone'] is None
    assert parsed['travel_distance'] == 9.82
    assert parsed['day_pay_sl'] == 78.0
    assert parsed['day_pay_td'] == 1.93
    assert parsed['day_pay_aep'] == 10.0
    assert parsed['overall_total'] == 89.93
    assert parsed['day_total'] == 89.93
    assert parsed['notes'] == "13WD0282624 - Courtroom 08"

# (Keep other tests like test_parse_detail_data_multiday, test_parse_detail_data_video_remote_with_link_in_notes)
# Ensure they are consistent with the latest parser logic.

def test_parse_detail_data_multiday(sample_xml_multiday):
    texts = _extract_texts_from_xml(sample_xml_multiday)
    header_info, is_multiday, lang_idx = extract_header_and_booking_type(texts)
    assert lang_idx is not None
    info_block = extract_info_block(texts, lang_idx)
    mja_blocks = extract_mja_payment_blocks(texts)
    notes_total = extract_notes_and_total(texts)
    parsed = parse_detail_data(header_info, is_multiday, info_block, mja_blocks, notes_total)
    assert parsed['is_multiday'] is True
    assert parsed['mjr_id'] == "MJR00156403"
    assert parsed['multiday_date_range'] == "01-07-2025 - 02-07-2025"
    assert parsed['overall_total'] == 332.00
    assert parsed['day_total'] == 166.00
    assert len(parsed['multiday_payments']) == 2

def test_parse_detail_data_video_remote_with_link_in_notes(sample_xml_video_remote_no_address):
    texts = _extract_texts_from_xml(sample_xml_video_remote_no_address)
    header_info, is_multiday, lang_idx = extract_header_and_booking_type(texts)
    assert lang_idx is not None
    info_block = extract_info_block(texts, lang_idx)
    mja_blocks = extract_mja_payment_blocks(texts)
    notes_total = extract_notes_and_total(texts)
    parsed = parse_detail_data(header_info, is_multiday, info_block, mja_blocks, notes_total)
    assert parsed['is_multiday'] is False
    assert parsed['booking_type'] == "NPS | Face to Face Interviews which take place within custodial"
    assert parsed['meeting_link'] == "vcchmpleeds4@meet.video.justice.gov.uk"