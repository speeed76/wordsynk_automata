# filename: tests/parsers/test_secondary_parser.py
import pytest
from parsers.secondary_parser import parse_secondary_page_data, MJR_DESC_PATTERN, APPOINTMENT_DESC_PATTERN, FACE_TO_FACE_TEXT, VIDEO_REMOTE_TEXT, REMOTE_TEXT

# Sample XML snippets (more realistic structure)
XML_SAMPLE_1 = """
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout">
    <node index="1" class="android.widget.LinearLayout">
        <node index="0" class="android.widget.TextView" text="Booking #MJB00247605" />
        <node index="1" class="android.view.ViewGroup">
            <node index="0" class="android.view.ViewGroup" content-desc="MJR00236264, Face To Face, Appointments : 1"/>
        </node>
    </node>
  </node>
</hierarchy>
"""

XML_SAMPLE_2_VIDEO_REMOTE = """
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout">
     <node index="1" class="android.widget.TextView" text="Some Title"/>
     <node index="2" class="android.view.ViewGroup">
        <node index="0" class="android.widget.TextView" text="Booking #MJB12345678" />
        <node index="1" class="android.view.ViewGroup" content-desc="MJR87654321, Video Remote Interpreting, Appointments : 3"/>
     </node>
  </node>
</hierarchy>
"""

XML_SAMPLE_3_REMOTE_FALLBACK = """
<hierarchy>
  <node text="Booking #MJB00000001" />
  <node content-desc="MJR00000002, Remote, Appointments : 1" />
</hierarchy>
"""

XML_SAMPLE_NO_APPOINTMENTS = """
<hierarchy>
  <node text="Booking #MJB99998888" />
  <node content-desc="MJR11122333, Face To Face" />
</hierarchy>
"""

XML_SAMPLE_NO_MJR_IN_DESC = """
<hierarchy>
  <node text="Booking #MJB77776666" />
  <node content-desc="Some other description without MJR ID" />
</hierarchy>
"""

XML_SAMPLE_NO_MJB_ID = """
<hierarchy>
  <node text="Some other title" />
  <node content-desc="MJR55554444, Face To Face, Appointments : 1" />
</hierarchy>
"""

XML_SAMPLE_EMPTY = "<hierarchy />"

XML_SAMPLE_HTML_ENTITIES = """
<hierarchy>
  <node text="Booking #MJBENTITY" />
  <node content-desc="MJRENTITY01, Face &amp; To &lt; Face, Appointments : 1" />
</hierarchy>
"""

XML_SAMPLE_APPT_FALLBACK = """
<hierarchy>
  <node text="Booking #MJBFALLBACK" />
  <node content-desc="MJRFALLBACK1, Face To Face" />
  <node text="Appointments : 2" /> </hierarchy>
"""


@pytest.mark.parametrize("xml_content, expected_output", [
    (XML_SAMPLE_1, {
        'mjb_id_raw': 'MJB00247605', 'mjr_id_raw': 'MJR00236264',
        'appointment_count_hint': 1, 'type_hint_raw': FACE_TO_FACE_TEXT
    }),
    (XML_SAMPLE_2_VIDEO_REMOTE, {
        'mjb_id_raw': 'MJB12345678', 'mjr_id_raw': 'MJR87654321',
        'appointment_count_hint': 3, 'type_hint_raw': VIDEO_REMOTE_TEXT
    }),
    (XML_SAMPLE_3_REMOTE_FALLBACK, {
        'mjb_id_raw': 'MJB00000001', 'mjr_id_raw': 'MJR00000002',
        'appointment_count_hint': 1, 'type_hint_raw': REMOTE_TEXT
    }),
    (XML_SAMPLE_NO_APPOINTMENTS, {
        'mjb_id_raw': 'MJB99998888', 'mjr_id_raw': 'MJR11122333',
        'appointment_count_hint': 1, 'type_hint_raw': FACE_TO_FACE_TEXT
    }),
    (XML_SAMPLE_NO_MJR_IN_DESC, {
        'mjb_id_raw': 'MJB77776666', 'mjr_id_raw': None,
        'appointment_count_hint': 1, 'type_hint_raw': None
    }),
    (XML_SAMPLE_NO_MJB_ID, {
        'mjb_id_raw': None, 'mjr_id_raw': 'MJR55554444',
        'appointment_count_hint': 1, 'type_hint_raw': FACE_TO_FACE_TEXT
    }),
    (XML_SAMPLE_EMPTY, {
        'mjb_id_raw': None, 'mjr_id_raw': None,
        'appointment_count_hint': 1, 'type_hint_raw': None
    }),
    (XML_SAMPLE_HTML_ENTITIES, {
        'mjb_id_raw': 'MJBENTITY', 'mjr_id_raw': 'MJRENTITY01',
        'appointment_count_hint': 1, 'type_hint_raw': "Face & To < Face"
    }),
    (XML_SAMPLE_APPT_FALLBACK, {
        'mjb_id_raw': 'MJBFALLBACK', 'mjr_id_raw': 'MJRFALLBACK1',
        'appointment_count_hint': 1, # The count in separate text node is not parsed by current logic
        'type_hint_raw': FACE_TO_FACE_TEXT
    }),
])
def test_parse_secondary_page_data(xml_content, expected_output):
    result = parse_secondary_page_data(xml_content)
    assert result == expected_output

def test_parse_secondary_page_data_bad_appt_count():
    xml_content_bad_appt = """
    <hierarchy>
      <node text="Booking #MJBADAPPT" />
      <node content-desc="MJRBAPPT01, Face To Face, Appointments : XYZ" />
    </hierarchy>
    """
    expected = {
        'mjb_id_raw': 'MJBADAPPT', 'mjr_id_raw': 'MJRBAPPT01',
        'appointment_count_hint': 1,
        'type_hint_raw': FACE_TO_FACE_TEXT
    }
    result = parse_secondary_page_data(xml_content_bad_appt)
    assert result == expected

def test_secondary_regex_patterns():
    match = MJR_DESC_PATTERN.search("MJR12345678, Face To Face, Appointments : 3")
    assert match is not None; assert match.group(1) == "MJR12345678"; assert match.group(2) == "Face To Face"; assert match.group(3) == "3"
    match = MJR_DESC_PATTERN.search("MJR98765432, Video Remote Interpreting")
    assert match is not None; assert match.group(1) == "MJR98765432"; assert match.group(2) == "Video Remote Interpreting"; assert match.group(3) is None
    assert APPOINTMENT_DESC_PATTERN.search("Appointments : 5").group(1) == "5"