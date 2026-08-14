"""
Detailed acceptance tests for Create Sports Meetup module.
These tests follow the Sprint 1 user stories for the organizer's Create Meetup function.

Run:
python -m pytest tests/test_create_meetup.py -v --tb=short --html=reports/create_meetup_test_report.html --self-contained-html
"""

import pytest
import app as flask_module


# =========================================================
# Fake Firebase Database for Testing
# Prevents pytest from touching the real Firebase database.
# =========================================================

class FakeMeetupCollection:
    def __init__(self):
        self.added = []

    def add(self, data):
        self.added.append(data)
        return None


class FakeDB:
    def __init__(self):
        self.meetups = FakeMeetupCollection()

    def collection(self, name):
        if name == "meetups":
            return self.meetups
        return FakeMeetupCollection()


# =========================================================
# Reusable Test Data
# =========================================================

def valid_create_meetup_data(**overrides):
    """
    Default valid form data for Create Meetup.
    Any field can be changed using overrides.
    """
    data = {
        "sport_type": "Badminton",
        "capacity": "10",
        "meetup_date": "2099-07-10",
        "meetup_time": "20:00",
        "state": "Penang",
        "postcode": "11200",
        "venue_name": "TAR UMT Sports Complex",
        "address": "Sports complex beside Block A",
        "description": "Please bring your own racket.",
    }
    data.update(overrides)
    return data


# =========================================================
# Test Client Setup
# =========================================================

@pytest.fixture
def client(monkeypatch):
    fake_db = FakeDB()

    # Replace real Firebase with fake database.
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")

    flask_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-key"
    )

    with flask_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["user_id"] = "organizer_001"
            session["role"] = "organizer"

        yield test_client, fake_db


def post_create_meetup(test_client, **overrides):
    return test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(**overrides)
    )


def assert_meetup_not_saved(fake_db):
    assert len(fake_db.meetups.added) == 0


def assert_one_meetup_saved(fake_db):
    assert len(fake_db.meetups.added) == 1
    return fake_db.meetups.added[0]


# =========================================================
# MS-01: Create a Sports Meetup
# User Story:
# As a meetup organizer, I want to create a sports meetup
# so that participants can join my event.
# =========================================================

def test_ms01_ac01_organizer_can_open_create_meetup_page(client):
    """AC-MS01-01: Organizer can access the Create Meetup page."""
    test_client, fake_db = client

    response = test_client.get("/create-meetup")

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


def test_ms01_ac02_participant_cannot_create_meetup(client):
    """AC-MS01-02: Participant role is not allowed to create a meetup."""
    test_client, fake_db = client

    with test_client.session_transaction() as session:
        session["user_id"] = "participant_001"
        session["role"] = "participant"

    response = post_create_meetup(test_client)

    assert response.status_code == 302
    assert_meetup_not_saved(fake_db)


# =========================================================
# MS-02: Enter Sport Type
# User Story:
# As a meetup organizer, I want to enter/select the sport type
# so that participants know what activity the meetup is for.
# =========================================================

@pytest.mark.parametrize(
    "sport_type",
    [
        pytest.param("Badminton", id="AC-MS02-01-valid-badminton"),
        pytest.param("Football", id="AC-MS02-02-valid-football"),
        pytest.param("Basketball", id="AC-MS02-03-valid-basketball"),
        pytest.param("Futsal", id="AC-MS02-04-valid-futsal"),
        pytest.param("Running", id="AC-MS02-05-valid-running"),
        pytest.param("Cycling", id="AC-MS02-06-valid-cycling"),
        pytest.param("Tennis", id="AC-MS02-07-valid-tennis"),
        pytest.param("Volleyball", id="AC-MS02-08-valid-volleyball"),
    ]
)
def test_ms02_ac01_allowed_sport_type_is_saved(client, sport_type):
    """AC-MS02: Valid sport type should be accepted and saved."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, sport_type=sport_type)

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["sport_type"] == sport_type
    assert saved_meetup["title"] == f"{sport_type} Meetup"


@pytest.mark.parametrize(
    "invalid_sport_type",
    [
        pytest.param("", id="AC-MS02-09-empty-sport-type"),
        pytest.param("Swimming", id="AC-MS02-10-not-in-allowed-list"),
        pytest.param("Hockey", id="AC-MS02-11-invalid-sport"),
        pytest.param("123", id="AC-MS02-12-number-as-sport-type"),
    ]
)
def test_ms02_ac02_invalid_sport_type_is_rejected(client, invalid_sport_type):
    """AC-MS02: Empty or invalid sport type should be rejected."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, sport_type=invalid_sport_type)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# MS-03: Enter Meetup Date
# User Story:
# As a meetup organizer, I want to enter the meetup date
# so that participants know when the event will happen.
# =========================================================

def test_ms03_ac01_valid_meetup_date_is_saved(client):
    """AC-MS03-01: Future meetup date should be accepted and saved."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, meetup_date="2099-12-25")

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["meetup_date"] == "2099-12-25"


@pytest.mark.parametrize(
    "invalid_date",
    [
        pytest.param("", id="AC-MS03-02-empty-date"),
        pytest.param("2000-01-01", id="AC-MS03-03-past-date"),
        pytest.param("invalid-date", id="AC-MS03-04-invalid-date-format"),
    ]
)
def test_ms03_ac02_invalid_meetup_date_is_rejected(client, invalid_date):
    """AC-MS03: Empty, past, or invalid date should be rejected."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, meetup_date=invalid_date)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# MS-04: Enter Meetup Time
# User Story:
# As a meetup organizer, I want to enter the meetup time
# so that participants can plan their schedule.
# =========================================================

def test_ms04_ac01_valid_meetup_time_is_saved(client):
    """AC-MS04-01: Valid meetup time should be accepted and saved."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, meetup_time="18:30")

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["meetup_time"] == "18:30"


@pytest.mark.parametrize(
    "invalid_time",
    [
        pytest.param("", id="AC-MS04-02-empty-time"),
        pytest.param("invalid-time", id="AC-MS04-03-invalid-time-format"),
    ]
)
def test_ms04_ac02_invalid_meetup_time_is_rejected(client, invalid_time):
    """AC-MS04: Empty or invalid time should be rejected."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, meetup_time=invalid_time)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# MS-05: Enter Meetup Location
# User Story:
# As a meetup organizer, I want to enter the meetup location
# so that participants know where to attend.
# =========================================================

def test_ms05_ac01_valid_location_fields_are_saved_and_combined(client):
    """AC-MS05-01: Valid state, postcode, venue, and address should be saved."""
    test_client, fake_db = client

    response = post_create_meetup(
        test_client,
        state="Penang",
        postcode="11200",
        venue_name="TAR UMT Sports Complex",
        address="Sports complex beside Block A"
    )

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["state"] == "Penang"
    assert saved_meetup["postcode"] == "11200"
    assert saved_meetup["venue_name"] == "TAR UMT Sports Complex"
    assert saved_meetup["address"] == "Sports complex beside Block A"
    assert saved_meetup["location"] == (
        "TAR UMT Sports Complex, Sports complex beside Block A, 11200, Penang"
    )


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        pytest.param("state", "", id="AC-MS05-02-empty-state"),
        pytest.param("venue_name", "", id="AC-MS05-03-empty-venue-name"),
        pytest.param("venue_name", "AB", id="AC-MS05-04-short-venue-name"),
        pytest.param("address", "", id="AC-MS05-05-empty-address"),
        pytest.param("address", "ABC", id="AC-MS05-06-short-address"),
    ]
)
def test_ms05_ac02_required_location_fields_are_validated(client, field_name, invalid_value):
    """AC-MS05: Required location fields should not be empty or too short."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, **{field_name: invalid_value})

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


@pytest.mark.parametrize(
    "invalid_postcode",
    [
        pytest.param("abcde", id="AC-MS05-07-postcode-letters"),
        pytest.param("112", id="AC-MS05-08-postcode-too-short"),
        pytest.param("112000", id="AC-MS05-09-postcode-too-long"),
        pytest.param("11A00", id="AC-MS05-10-postcode-mixed-character"),
    ]
)
def test_ms05_ac03_invalid_postcode_is_rejected(client, invalid_postcode):
    """AC-MS05: Postcode should contain exactly 5 digits if entered."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, postcode=invalid_postcode)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


def test_ms05_ac04_empty_postcode_is_allowed_because_optional(client):
    """AC-MS05-11: Postcode is optional, so empty postcode should be accepted."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, postcode="")

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["postcode"] == ""
    assert saved_meetup["location"] == (
        "TAR UMT Sports Complex, Sports complex beside Block A, Penang"
    )


# =========================================================
# MS-07: Set Participant Capacity
# User Story:
# As a meetup organizer, I want to set participant capacity
# so that the number of participants can be controlled.
# =========================================================

@pytest.mark.parametrize(
    "valid_capacity, expected_capacity",
    [
        pytest.param("1", 1, id="AC-MS07-01-minimum-capacity"),
        pytest.param("10", 10, id="AC-MS07-02-normal-capacity"),
        pytest.param("100", 100, id="AC-MS07-03-maximum-capacity"),
    ]
)
def test_ms07_ac01_valid_capacity_is_saved_as_integer(client, valid_capacity, expected_capacity):
    """AC-MS07: Valid capacity from 1 to 100 should be accepted."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, capacity=valid_capacity)

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["capacity"] == expected_capacity
    assert isinstance(saved_meetup["capacity"], int)


@pytest.mark.parametrize(
    "invalid_capacity",
    [
        pytest.param("", id="AC-MS07-04-empty-capacity"),
        pytest.param("0", id="AC-MS07-05-zero-capacity"),
        pytest.param("-1", id="AC-MS07-06-negative-capacity"),
        pytest.param("101", id="AC-MS07-07-over-maximum-capacity"),
        pytest.param("abc", id="AC-MS07-08-non-number-capacity"),
        pytest.param("10.5", id="AC-MS07-09-decimal-capacity"),
    ]
)
def test_ms07_ac02_invalid_capacity_is_rejected(client, invalid_capacity):
    """AC-MS07: Invalid capacity should be rejected and not saved."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, capacity=invalid_capacity)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# MS-08: Save Created Meetup
# User Story:
# As a meetup organizer, I want to save a created meetup
# so that it can be published on the platform.
# =========================================================

def test_ms08_ac01_complete_valid_meetup_is_saved_to_fake_firebase(client):
    """AC-MS08-01: Complete valid meetup should be saved into the meetup collection."""
    test_client, fake_db = client

    response = post_create_meetup(test_client)

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["sport_type"] == "Badminton"
    assert saved_meetup["title"] == "Badminton Meetup"
    assert saved_meetup["capacity"] == 10
    assert saved_meetup["joined_count"] == 0
    assert saved_meetup["meetup_date"] == "2099-07-10"
    assert saved_meetup["meetup_time"] == "20:00"
    assert saved_meetup["location"] == (
        "TAR UMT Sports Complex, Sports complex beside Block A, 11200, Penang"
    )
    assert saved_meetup["description"] == "Please bring your own racket."
    assert saved_meetup["organizer_id"] == "organizer_001"
    assert saved_meetup["participants"] == []
    assert saved_meetup["participant_ids"] == []
    assert saved_meetup["status"] == "active"
    assert "created_at" in saved_meetup
    assert "updated_at" in saved_meetup


def test_ms08_ac02_empty_optional_description_is_accepted(client):
    """AC-MS08-02: Optional description may be empty."""
    test_client, fake_db = client

    response = post_create_meetup(test_client, description="")

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["description"] == ""


def test_ms08_ac03_description_with_exactly_300_characters_is_accepted(client):
    """AC-MS08-03: Description with exactly 300 characters should be accepted."""
    test_client, fake_db = client
    description_300 = "A" * 300

    response = post_create_meetup(test_client, description=description_300)

    assert response.status_code == 302
    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["description"] == description_300
    assert len(saved_meetup["description"]) == 300


def test_ms08_ac04_description_more_than_300_characters_is_rejected(client):
    """AC-MS08-04: Description with more than 300 characters should be rejected."""
    test_client, fake_db = client
    description_301 = "A" * 301

    response = post_create_meetup(test_client, description=description_301)

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


def test_ms08_ac05_create_meetup_page_does_not_crash_when_firebase_disconnected(monkeypatch):
    """AC-MS08-05: Page should open safely when Firebase is disconnected."""
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(
        flask_module,
        "firebase_error_message",
        "Test Firebase connection failed"
    )

    flask_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-key")

    with flask_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["user_id"] = "organizer_001"
            session["role"] = "organizer"

        response = test_client.get("/create-meetup")

        assert response.status_code == 200