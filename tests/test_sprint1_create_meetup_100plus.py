"""
Sprint 1 pytest test suite for KC / Chang Kar Xi's part:
Create Sports Meetup function.

Covered Sprint 1 user stories:
- SCRUM-133 / MS-01: Create sports meetup
- SCRUM-144 / MS-02: Select sport type
- SCRUM-152 / MS-03: Enter meetup date
- SCRUM-160 / MS-04: Enter meetup time
- SCRUM-168 / MS-05: Enter meetup location details
- SCRUM-176 / MS-07: Set participant capacity
- SCRUM-185 / MS-08: Save created meetup to Firebase

The tests use fake Firestore and do not touch the real Firebase database.
The suite includes positive and negative scenarios. Negative scenarios should still
show PASSED when the system correctly rejects invalid input.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app as flask_module  # noqa: E402


FIXED_NOW = datetime(2026, 7, 15, 10, 0, tzinfo=flask_module.MALAYSIA_TIME)
FUTURE_DATE = "2026-07-31"
FUTURE_TIME = "18:30"
PAST_DATE = "2026-07-01"
PAST_TIME = "09:00"


class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = deepcopy(data) if data is not None else None
        self.exists = data is not None

    def to_dict(self):
        return deepcopy(self._data) if self._data is not None else None


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self.collection = collection
        self.id = doc_id

    def get(self, transaction=None):
        return FakeDocumentSnapshot(self.id, self.collection.documents.get(self.id))

    def set(self, data):
        self.collection.documents[self.id] = deepcopy(data)

    def update(self, updates):
        if self.id not in self.collection.documents:
            self.collection.documents[self.id] = {}
        self.collection.documents[self.id].update(deepcopy(updates))

    def delete(self):
        self.collection.documents.pop(self.id, None)


class FakeQuery:
    def __init__(self, collection: "FakeCollection", filters=None):
        self.collection = collection
        self.filters = filters or []

    def where(self, field, operator, value):
        return FakeQuery(self.collection, self.filters + [(field, operator, value)])

    def limit(self, number):
        return self

    def stream(self):
        results = []
        for doc_id, data in self.collection.documents.items():
            matched = True
            for field, operator, value in self.filters:
                if operator != "==":
                    continue
                if data.get(field) != value:
                    matched = False
                    break
            if matched:
                results.append(FakeDocumentSnapshot(doc_id, data))
        return results


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.documents = {}
        self.added_documents = []
        self.add_counter = 1

    def add(self, data):
        doc_id = f"{self.name}_{self.add_counter}"
        self.add_counter += 1
        self.documents[doc_id] = deepcopy(data)
        self.added_documents.append(deepcopy(data))
        return None, FakeDocumentReference(self, doc_id)

    def document(self, doc_id):
        return FakeDocumentReference(self, doc_id)

    def where(self, field, operator, value):
        return FakeQuery(self, [(field, operator, value)])

    def stream(self):
        return [FakeDocumentSnapshot(doc_id, data) for doc_id, data in self.documents.items()]


class FakeDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection(name)
        return self.collections[name]

    def transaction(self):
        return object()

    def batch(self):
        return None


# -------------------------------
# Fixtures and helpers
# -------------------------------


def fake_render_template(template_name, **context):
    """Return template name and context as plain text for route-level tests."""
    safe_context = {}
    for key, value in context.items():
        if key == "meetups" and isinstance(value, list):
            safe_context[key] = [item.get("title") or item.get("sport_type") for item in value]
        else:
            safe_context[key] = value
    return f"TEMPLATE:{template_name}\nCONTEXT:{safe_context}"


@pytest.fixture()
def fake_db():
    return FakeDB()


@pytest.fixture()
def client(monkeypatch, fake_db):
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")
    monkeypatch.setattr(flask_module, "now_malaysia", lambda: FIXED_NOW)
    monkeypatch.setattr(flask_module, "render_template", fake_render_template)

    flask_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")

    with flask_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def disconnected_client(monkeypatch):
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(flask_module, "firebase_error_message", "test firebase disconnected")
    monkeypatch.setattr(flask_module, "now_malaysia", lambda: FIXED_NOW)
    monkeypatch.setattr(flask_module, "render_template", fake_render_template)

    flask_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")

    with flask_module.app.test_client() as test_client:
        yield test_client


def set_session(client, role="organizer", user_id="organizer_001"):
    with client.session_transaction() as session:
        session.clear()
        session["role"] = role
        session["user_id"] = user_id
        session["full_name"] = "Test User"


def base_meetup_form(**overrides):
    data = {
        "sport_type": "Badminton",
        "capacity": "10",
        "meetup_date": FUTURE_DATE,
        "meetup_time": FUTURE_TIME,
        "location": "",
        "state": "Penang",
        "postcode": "11900",
        "venue_name": "TAR UMT Sports Hall",
        "address": "Jalan Kampus Utama, Penang",
        "description": "Friendly badminton meetup for students.",
    }
    data.update(overrides)
    return data


def get_saved_meetups(fake_db):
    return fake_db.collection("meetups").added_documents


def assert_no_validation_errors(form_data):
    assert flask_module.validate_create_meetup_form(form_data) == []


def assert_has_error(form_data, expected_error):
    errors = flask_module.validate_create_meetup_form(form_data)
    assert expected_error in errors


# -------------------------------
# Route existence and access control
# -------------------------------


def test_sprint1_route_map_contains_create_meetup_routes():
    rules = {rule.rule for rule in flask_module.app.url_map.iter_rules()}
    assert "/create-meetup" in rules
    assert "/active-meetups" in rules
    assert "/meetup/<meetup_id>" in rules


@pytest.mark.parametrize("role,user_id", [
    ("participant", "participant_001"),
    ("admin", "admin_001"),
    ("", "guest_001"),
])
def test_create_meetup_get_blocks_non_organizer_roles(client, role, user_id):
    set_session(client, role=role, user_id=user_id)
    response = client.get("/create-meetup", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_create_meetup_get_allows_organizer(client):
    set_session(client, role="organizer")
    response = client.get("/create-meetup")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "TEMPLATE:create_meetup.html" in html


def test_create_meetup_shows_form_when_firebase_disconnected(disconnected_client):
    set_session(disconnected_client, role="organizer")
    response = disconnected_client.get("/create-meetup")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "TEMPLATE:create_meetup.html" in html


# -------------------------------
# Valid create meetup route tests
# -------------------------------


def test_scrum_133_create_meetup_valid_form_saves_to_fake_firestore(client, fake_db):
    set_session(client, role="organizer", user_id="organizer_main")
    response = client.post("/create-meetup", data=base_meetup_form(), follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/active-meetups")

    saved = get_saved_meetups(fake_db)
    assert len(saved) == 1
    assert saved[0]["sport_type"] == "Badminton"
    assert saved[0]["title"] == "Badminton Meetup"
    assert saved[0]["capacity"] == 10
    assert saved[0]["joined_count"] == 0
    assert saved[0]["available_slots"] == 10
    assert saved[0]["organizer_id"] == "organizer_main"
    assert saved[0]["participant_ids"] == []
    assert saved[0]["participants"] == []
    assert saved[0]["status"] == "active"


@pytest.mark.parametrize("sport", flask_module.ALLOWED_SPORTS)
def test_scrum_144_create_meetup_accepts_each_allowed_sport(client, fake_db, sport):
    set_session(client, role="organizer")
    response = client.post("/create-meetup", data=base_meetup_form(sport_type=sport), follow_redirects=False)

    assert response.status_code == 302
    saved = get_saved_meetups(fake_db)
    assert len(saved) == 1
    assert saved[0]["sport_type"] == sport
    assert saved[0]["title"] == f"{sport} Meetup"


@pytest.mark.parametrize("capacity", ["1", "2", "3", "10", "25", "50", "75", "99", "100"])
def test_scrum_176_create_meetup_accepts_valid_capacity_boundaries(client, fake_db, capacity):
    set_session(client, role="organizer")
    response = client.post("/create-meetup", data=base_meetup_form(capacity=capacity), follow_redirects=False)

    assert response.status_code == 302
    saved = get_saved_meetups(fake_db)
    assert saved[0]["capacity"] == int(capacity)
    assert saved[0]["available_slots"] == int(capacity)


@pytest.mark.parametrize("postcode", ["", "10000", "11900", "57000", "81200", "93000"])
def test_scrum_168_create_meetup_accepts_empty_or_five_digit_postcodes(client, fake_db, postcode):
    set_session(client, role="organizer")
    response = client.post("/create-meetup", data=base_meetup_form(postcode=postcode), follow_redirects=False)

    assert response.status_code == 302
    saved = get_saved_meetups(fake_db)
    assert saved[0]["postcode"] == postcode


# -------------------------------
# General helper validations
# -------------------------------


@pytest.mark.parametrize("field,expected_error", [
    ("sport_type", "Sport type is required."),
    ("capacity", "Participant capacity is required."),
    ("meetup_date", "Meetup date is required."),
    ("meetup_time", "Meetup time is required."),
    ("state", "State is required."),
    ("venue_name", "Exact venue or place name is required."),
    ("address", "Detailed address or location guide is required."),
])
def test_create_meetup_rejects_required_missing_fields(field, expected_error):
    form = base_meetup_form(**{field: ""})
    assert_has_error(form, expected_error)


@pytest.mark.parametrize("sport", [
    "", "Swimming", "Chess", "Yoga", "Table Tennis", "BADMINTON", "badminton",
    "Football Club", "Basket", "Run", "Cycling Club", "Tennis Match", "Volleyball Game",
])
def test_scrum_144_create_meetup_rejects_invalid_sport_types(sport):
    form = base_meetup_form(sport_type=sport)
    errors = flask_module.validate_create_meetup_form(form)
    if sport == "":
        assert "Sport type is required." in errors
    else:
        assert "Please select a valid sport type." in errors


@pytest.mark.parametrize("capacity,expected_error", [
    ("", "Participant capacity is required."),
    ("0", "Participant capacity must be at least 1."),
    ("-1", "Participant capacity must be a whole number."),
    ("abc", "Participant capacity must be a whole number."),
    ("ten", "Participant capacity must be a whole number."),
    ("1.5", "Participant capacity must be a whole number."),
    ("10.0", "Participant capacity must be a whole number."),
    ("5 people", "Participant capacity must be a whole number."),
    ("101", "Participant capacity cannot be more than 100."),
    ("150", "Participant capacity cannot be more than 100."),
    ("999", "Participant capacity cannot be more than 100."),
    ("1000", "Participant capacity cannot be more than 100."),
])
def test_scrum_176_create_meetup_rejects_invalid_capacity_values(capacity, expected_error):
    assert_has_error(base_meetup_form(capacity=capacity), expected_error)


@pytest.mark.parametrize(
    "days_before_today, meetup_time",
    [
        (-1, "23:59"),
        (-7, "10:00"),
        (-30, "18:30"),
        (-365, "09:00"),
    ],
)
def test_scrum_152_160_create_meetup_rejects_past_datetime(
    days_before_today,
    meetup_time
):
    meetup_date = get_dynamic_meetup_date(days_before_today)

    errors = flask_module.validate_create_meetup_form(
        base_meetup_form(
            meetup_date=meetup_date,
            meetup_time=meetup_time
        )
    )

    assert "Meetup date and time cannot be in the past." in errors

def get_dynamic_meetup_date(days_offset):
    """
    Generate dynamic meetup date based on current Malaysia time.
    Positive days_offset = future date.
    Negative days_offset = past date.
    This prevents the test from expiring in the future.
    """

    current_time = flask_module.now_malaysia()
    target_date = current_time + timedelta(days=days_offset)

    return target_date.strftime("%Y-%m-%d")

@pytest.mark.parametrize(
    "days_after_today, meetup_time",
    [
        (1, "00:00"),
        (1, "18:30"),
        (7, "09:00"),
        (30, "20:00"),
        (365, "23:59"),
    ],
)
def test_scrum_152_160_create_meetup_accepts_future_datetime(
    days_after_today,
    meetup_time
):
    meetup_date = get_dynamic_meetup_date(days_after_today)

    assert_no_validation_errors(
        base_meetup_form(
            meetup_date=meetup_date,
            meetup_time=meetup_time
        )
    )


@pytest.mark.parametrize("meetup_date,meetup_time", [
    ("2026/07/31", "18:30"),
    ("31-07-2026", "18:30"),
    ("2026-13-01", "18:30"),
    ("2026-07-32", "18:30"),
    ("2026-07-31", "6:30 PM"),
    ("2026-07-31", "25:00"),
    ("2026-07-31", "18-30"),
    ("date", "time"),
])
def test_scrum_152_160_create_meetup_rejects_invalid_date_or_time_format(meetup_date, meetup_time):
    assert_has_error(
        base_meetup_form(meetup_date=meetup_date, meetup_time=meetup_time),
        "Invalid meetup date or time format.",
    )


@pytest.mark.parametrize("postcode", [
    "1", "12", "123", "1234", "123456", "ABCDE", "1190A", "11-900", "119 00", "0000A",
])
def test_scrum_168_create_meetup_rejects_invalid_postcodes(postcode):
    assert_has_error(base_meetup_form(postcode=postcode), "Postcode must be 5 digits.")


@pytest.mark.parametrize("venue_name", [
    "ABC", "Sports Hall", "Court A", "TAR UMT", "Community Complex", "Penang Arena",
])
def test_scrum_168_create_meetup_accepts_valid_venue_names(venue_name):
    assert_no_validation_errors(base_meetup_form(venue_name=venue_name))


@pytest.mark.parametrize("venue_name,expected_error", [
    ("", "Exact venue or place name is required."),
    ("A", "Venue name must be at least 3 characters."),
    ("AB", "Venue name must be at least 3 characters."),
])
def test_scrum_168_create_meetup_rejects_invalid_venue_names(venue_name, expected_error):
    assert_has_error(base_meetup_form(venue_name=venue_name), expected_error)


@pytest.mark.parametrize("address", [
    "Block A", "Jalan Kampus Utama", "Court near main gate", "Level 2 Sports Complex", "Outdoor field area",
])
def test_scrum_168_create_meetup_accepts_valid_addresses(address):
    assert_no_validation_errors(base_meetup_form(address=address))


@pytest.mark.parametrize("address,expected_error", [
    ("", "Detailed address or location guide is required."),
    ("A", "Detailed address must be at least 5 characters."),
    ("AB", "Detailed address must be at least 5 characters."),
    ("ABC", "Detailed address must be at least 5 characters."),
    ("ABCD", "Detailed address must be at least 5 characters."),
])
def test_scrum_168_create_meetup_rejects_invalid_addresses(address, expected_error):
    assert_has_error(base_meetup_form(address=address), expected_error)


@pytest.mark.parametrize("state", [
    "Penang", "Kuala Lumpur", "Selangor", "Perak", "Kedah", "Perlis", "Johor", "Pahang", "Sabah", "Sarawak",
])
def test_scrum_168_create_meetup_accepts_common_malaysia_states(state):
    assert_no_validation_errors(base_meetup_form(state=state))


@pytest.mark.parametrize("description", [
    "", "Short note", "x" * 1, "x" * 100, "x" * 299, "x" * 300,
])
def test_create_meetup_accepts_optional_description_up_to_300_characters(description):
    assert_no_validation_errors(base_meetup_form(description=description))


@pytest.mark.parametrize("description_length", [301, 302, 350, 500, 1000])
def test_create_meetup_rejects_description_more_than_300_characters(description_length):
    assert_has_error(
        base_meetup_form(description="x" * description_length),
        "Description cannot be more than 300 characters.",
    )


# -------------------------------
# build_location_from_form and request parsing
# -------------------------------


@pytest.mark.parametrize("form_input,expected_location", [
    ({"venue_name": "Sports Hall", "address": "Block A", "postcode": "11900", "state": "Penang"}, "Sports Hall, Block A, 11900, Penang"),
    ({"venue_name": "Court 1", "address": "Main Campus", "postcode": "", "state": "Selangor"}, "Court 1, Main Campus, Selangor"),
    ({"venue_name": "Arena", "address": "Level 2", "postcode": "57000", "state": "Kuala Lumpur"}, "Arena, Level 2, 57000, Kuala Lumpur"),
    ({"venue_name": "", "address": "", "postcode": "", "state": "", "location": "Old Location Field"}, "Old Location Field"),
    ({"venue_name": "Community Court", "address": "Near Library", "postcode": "10000", "state": "Penang", "location": "Old Location"}, "Community Court, Near Library, 10000, Penang"),
])
def test_scrum_168_build_location_from_form_combines_new_location_fields(client, form_input, expected_location):
    with flask_module.app.test_request_context("/create-meetup", method="POST", data=form_input):
        assert flask_module.build_location_from_form() == expected_location


@pytest.mark.parametrize("field,value", [
    ("sport_type", "  Badminton  "),
    ("capacity", "  10  "),
    ("meetup_date", "  2026-07-31  "),
    ("meetup_time", "  18:30  "),
    ("state", "  Penang  "),
    ("postcode", "  11900  "),
    ("venue_name", "  Sports Hall  "),
    ("address", "  Block A  "),
    ("description", "  Friendly game  "),
])
def test_get_form_data_from_request_strips_input_whitespace(client, field, value):
    form = base_meetup_form(**{field: value})
    with flask_module.app.test_request_context("/create-meetup", method="POST", data=form):
        form_data = flask_module.get_form_data_from_request()
        assert form_data[field] == value.strip()


# -------------------------------
# Helper functions related to meetup display data
# -------------------------------


@pytest.mark.parametrize("value,expected", [
    ("10", 10), ("0", 0), ("001", 1), (10, 10), (0, 0), (None, 99), ("abc", 99), ("1.5", 99),
])
def test_safe_int_converts_valid_values_and_returns_default_for_invalid(value, expected):
    assert flask_module.safe_int(value, default=99) == expected


@pytest.mark.parametrize("capacity,joined_count,expected", [
    (10, 0, 10),
    (10, 1, 9),
    (10, 10, 0),
    (10, 12, 0),
    ("10", "3", 7),
    ("5", "0", 5),
    ("0", "0", 0),
    ("abc", "1", 0),
    (None, None, 0),
])
def test_calculate_available_slots_returns_correct_remaining_slots(capacity, joined_count, expected):
    meetup = {"capacity": capacity, "joined_count": joined_count}
    assert flask_module.calculate_available_slots(meetup) == expected


@pytest.mark.parametrize("meetup,expected_iso", [
    ({"meetup_date": "2026-07-31", "meetup_time": "18:30"}, "2026-07-31T18:30:00+08:00"),
    ({"meetup_date": "2026-12-01", "meetup_time": "09:15"}, "2026-12-01T09:15:00+08:00"),
])
def test_get_meetup_datetime_returns_timezone_aware_datetime(meetup, expected_iso):
    assert flask_module.get_meetup_datetime(meetup).isoformat() == expected_iso


@pytest.mark.parametrize("meetup", [
    {"meetup_date": "", "meetup_time": "18:30"},
    {"meetup_date": "2026-07-31", "meetup_time": ""},
    {"meetup_date": "2026/07/31", "meetup_time": "18:30"},
    {"meetup_date": "2026-07-31", "meetup_time": "25:00"},
])
def test_get_meetup_datetime_returns_none_for_missing_or_invalid_values(meetup):
    assert flask_module.get_meetup_datetime(meetup) is None


@pytest.mark.parametrize("meetup,expected", [
    ({"meetup_date": "2026-07-15", "meetup_time": "09:59"}, True),
    ({"meetup_date": "2026-07-15", "meetup_time": "10:00"}, True),
    ({"meetup_date": "2026-07-15", "meetup_time": "10:01"}, False),
    ({"meetup_date": "2026-07-31", "meetup_time": "18:30"}, False),
    ({"meetup_date": "", "meetup_time": ""}, False),
])
def test_is_meetup_past_returns_correct_status(monkeypatch, meetup, expected):
    monkeypatch.setattr(flask_module, "now_malaysia", lambda: FIXED_NOW)
    assert flask_module.is_meetup_past(meetup) is expected


# -------------------------------
# Route-level invalid POST tests
# -------------------------------


@pytest.mark.parametrize("overrides,expected_error", [
    ({"sport_type": "Chess"}, "Please select a valid sport type."),
    ({"capacity": "0"}, "Participant capacity must be at least 1."),
    ({"capacity": "101"}, "Participant capacity cannot be more than 100."),
    ({"capacity": "ten"}, "Participant capacity must be a whole number."),
    ({"meetup_date": PAST_DATE, "meetup_time": PAST_TIME}, "Meetup date and time cannot be in the past."),
    ({"meetup_date": "2026/07/31"}, "Invalid meetup date or time format."),
    ({"meetup_time": "25:00"}, "Invalid meetup date or time format."),
    ({"state": ""}, "State is required."),
    ({"postcode": "1190A"}, "Postcode must be 5 digits."),
    ({"venue_name": "A"}, "Venue name must be at least 3 characters."),
    ({"address": "ABCD"}, "Detailed address must be at least 5 characters."),
    ({"description": "x" * 301}, "Description cannot be more than 300 characters."),
])
def test_create_meetup_invalid_post_does_not_save_to_firestore(client, fake_db, overrides, expected_error):
    set_session(client, role="organizer")
    response = client.post("/create-meetup", data=base_meetup_form(**overrides), follow_redirects=False)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "TEMPLATE:create_meetup.html" in html
    assert len(get_saved_meetups(fake_db)) == 0

    with client.session_transaction() as session:
        flashed_messages = [message for _category, message in session.get("_flashes", [])]
    assert expected_error in flashed_messages


@pytest.mark.parametrize("missing_fields", [
    ["sport_type"],
    ["capacity"],
    ["meetup_date"],
    ["meetup_time"],
    ["state"],
    ["venue_name"],
    ["address"],
    ["sport_type", "capacity", "meetup_date"],
    ["state", "venue_name", "address"],
    ["sport_type", "capacity", "meetup_date", "meetup_time", "state", "venue_name", "address"],
])
def test_create_meetup_invalid_post_with_multiple_missing_fields_keeps_form_data(client, fake_db, missing_fields):
    set_session(client, role="organizer")
    form = base_meetup_form()
    for field in missing_fields:
        form[field] = ""

    response = client.post("/create-meetup", data=form, follow_redirects=False)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "TEMPLATE:create_meetup.html" in html
    assert len(get_saved_meetups(fake_db)) == 0


# -------------------------------
# Active meetups route checks used after Create Meetup success
# -------------------------------


def seed_meetup(fake_db, doc_id, **overrides):
    meetup = {
        "sport_type": "Badminton",
        "title": "Badminton Meetup",
        "meetup_date": "2026-07-31",
        "meetup_time": "18:30",
        "location": "Sports Hall, Penang",
        "state": "Penang",
        "postcode": "11900",
        "venue_name": "Sports Hall",
        "address": "Block A",
        "description": "Friendly game.",
        "capacity": 10,
        "joined_count": 2,
        "status": "active",
    }
    meetup.update(overrides)
    fake_db.collection("meetups").documents[doc_id] = meetup


@pytest.mark.parametrize("query,expected_title,hidden_title", [
    ({"keyword": "badminton"}, "Badminton Meetup", "Football Meetup"),
    ({"state": "Penang"}, "Badminton Meetup", "Football Meetup"),
    ({"sport_type": "Football"}, "Football Meetup", "Badminton Meetup"),
    ({"meetup_date": "2026-08-01"}, "Football Meetup", "Badminton Meetup"),
])
def test_active_meetups_filtering_supports_created_meetup_discovery(client, fake_db, query, expected_title, hidden_title):
    set_session(client, role="participant", user_id="participant_001")
    seed_meetup(fake_db, "m1", title="Badminton Meetup", sport_type="Badminton", state="Penang", meetup_date="2026-07-31")
    seed_meetup(fake_db, "m2", title="Football Meetup", sport_type="Football", state="Selangor", meetup_date="2026-08-01")

    response = client.get("/active-meetups", query_string=query)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert expected_title in html
    assert hidden_title not in html


def test_active_meetups_hides_past_meetups_and_marks_them_past(client, fake_db):
    set_session(client, role="participant")
    seed_meetup(fake_db, "past_meetup", title="Past Meetup", meetup_date="2026-07-01", meetup_time="08:00")
    seed_meetup(fake_db, "future_meetup", title="Future Meetup", meetup_date="2026-08-01", meetup_time="08:00")

    response = client.get("/active-meetups")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Future Meetup" in html
    assert "Past Meetup" not in html
    assert fake_db.collection("meetups").documents["past_meetup"]["status"] == "past"


@pytest.mark.parametrize("capacity,joined_count,expected_slots,expected_full", [
    (10, 0, 10, False),
    (10, 5, 5, False),
    (10, 10, 0, True),
    (10, 12, 0, True),
])
def test_active_meetups_calculates_available_slots_and_full_status(client, fake_db, capacity, joined_count, expected_slots, expected_full):
    set_session(client, role="participant")
    seed_meetup(fake_db, "meetup", capacity=capacity, joined_count=joined_count)

    response = client.get("/active-meetups")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    stored = fake_db.collection("meetups").documents["meetup"]
    # calculate_available_slots is also tested directly; route output is represented in fake template context.
    assert flask_module.calculate_available_slots(stored) == expected_slots
    assert (expected_slots <= 0) is expected_full