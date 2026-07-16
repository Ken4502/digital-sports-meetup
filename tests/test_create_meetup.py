import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
import app as flask_module


# =========================================================
# Fake Firebase Database for Testing
# This prevents pytest from touching the real Firebase database.
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
    Example:
    valid_create_meetup_data(capacity="0")
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
        "description": "Please bring your own racket."
    }

    data.update(overrides)
    return data


# =========================================================
# Test Client Setup
# =========================================================

@pytest.fixture
def client(monkeypatch):
    fake_db = FakeDB()

    # Replace real Firebase with fake database
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


# =========================================================
# Helper Assertions
# =========================================================

def assert_meetup_not_saved(fake_db):
    assert len(fake_db.meetups.added) == 0


def assert_one_meetup_saved(fake_db):
    assert len(fake_db.meetups.added) == 1
    return fake_db.meetups.added[0]


# =========================================================
# Positive Test Cases
# =========================================================

def test_create_meetup_success_with_complete_data(client):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data()
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["sport_type"] == "Badminton"
    assert saved_meetup["title"] == "Badminton Meetup"
    assert saved_meetup["capacity"] == 10
    assert saved_meetup["joined_count"] == 0

    assert saved_meetup["meetup_date"] == "2099-07-10"
    assert saved_meetup["meetup_time"] == "20:00"

    assert saved_meetup["state"] == "Penang"
    assert saved_meetup["postcode"] == "11200"
    assert saved_meetup["venue_name"] == "TAR UMT Sports Complex"
    assert saved_meetup["address"] == "Sports complex beside Block A"

    assert saved_meetup["location"] == (
        "TAR UMT Sports Complex, Sports complex beside Block A, 11200, Penang"
    )

    assert saved_meetup["description"] == "Please bring your own racket."
    assert saved_meetup["organizer_id"] == "organizer_001"

    assert saved_meetup["status"] == "active"
    assert saved_meetup["participants"] == []
    assert saved_meetup["participant_ids"] == []


def test_create_meetup_success_with_empty_optional_description(client):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(
            sport_type="Football",
            capacity="20",
            meetup_date="2099-08-15",
            meetup_time="18:30",
            postcode="",
            venue_name="Public Football Field",
            address="Near main entrance",
            description=""
        )
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["sport_type"] == "Football"
    assert saved_meetup["title"] == "Football Meetup"
    assert saved_meetup["capacity"] == 20
    assert saved_meetup["description"] == ""
    assert saved_meetup["status"] == "active"

    assert saved_meetup["location"] == (
        "Public Football Field, Near main entrance, Penang"
    )


def test_create_meetup_accepts_description_exactly_300_characters(client):
    test_client, fake_db = client

    description_300 = "A" * 300

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(description=description_300)
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["description"] == description_300
    assert len(saved_meetup["description"]) == 300


def test_create_meetup_success_with_old_location_field_only(client):
    """
    This test checks backward compatibility.
    If the old HTML only sends 'location' without state, venue_name, and address,
    the system should still be able to create the meetup.
    """

    test_client, fake_db = client

    response = test_client.post("/create-meetup", data={
        "sport_type": "Badminton",
        "capacity": "10",
        "meetup_date": "2099-07-10",
        "meetup_time": "20:00",
        "location": "TAR UMT Sports Complex",
        "description": ""
    })

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["sport_type"] == "Badminton"
    assert saved_meetup["capacity"] == 10
    assert saved_meetup["location"] == "TAR UMT Sports Complex"
    assert saved_meetup["status"] == "active"


# =========================================================
# Role Permission Test
# =========================================================

def test_create_meetup_rejects_participant_role(client):
    test_client, fake_db = client

    with test_client.session_transaction() as session:
        session["user_id"] = "participant_001"
        session["role"] = "participant"

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data()
    )

    assert response.status_code == 302
    assert_meetup_not_saved(fake_db)


# =========================================================
# Negative Test Cases - Sport Type Validation
# =========================================================

@pytest.mark.parametrize("invalid_sport_type", [
    "",
    "Swimming",
    "Hockey",
    "123",
])
def test_create_meetup_rejects_invalid_sport_type_values(client, invalid_sport_type):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(sport_type=invalid_sport_type)
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# Negative Test Cases - Capacity Validation
# =========================================================

@pytest.mark.parametrize("invalid_capacity", [
    "",
    "0",
    "-1",
    "101",
    "abc",
    "10.5",
])
def test_create_meetup_rejects_invalid_capacity_values(client, invalid_capacity):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(capacity=invalid_capacity)
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


def test_create_meetup_accepts_capacity_one(client):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(capacity="1")
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["capacity"] == 1


def test_create_meetup_accepts_capacity_100(client):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(capacity="100")
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)
    assert saved_meetup["capacity"] == 100


# =========================================================
# Negative Test Cases - Date and Time Validation
# =========================================================

@pytest.mark.parametrize("meetup_date, meetup_time", [
    ("", "20:00"),
    ("2099-07-10", ""),
    ("2000-01-01", "10:00"),
    ("invalid-date", "20:00"),
    ("2099-07-10", "invalid-time"),
])
def test_create_meetup_rejects_invalid_date_time_values(
    client,
    meetup_date,
    meetup_time
):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(
            meetup_date=meetup_date,
            meetup_time=meetup_time
        )
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# Negative Test Cases - Location Validation
# =========================================================

@pytest.mark.parametrize("field_name, invalid_value", [
    ("state", ""),
    ("venue_name", ""),
    ("venue_name", "AB"),
    ("address", ""),
    ("address", "ABC"),
])
def test_create_meetup_rejects_invalid_location_required_fields(
    client,
    field_name,
    invalid_value
):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(**{field_name: invalid_value})
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


@pytest.mark.parametrize("invalid_postcode", [
    "abcde",
    "112",
    "112000",
    "11A00",
])
def test_create_meetup_rejects_invalid_postcode_values(client, invalid_postcode):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(postcode=invalid_postcode)
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


def test_create_meetup_accepts_empty_optional_postcode(client):
    test_client, fake_db = client

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(postcode="")
    )

    assert response.status_code == 302

    saved_meetup = assert_one_meetup_saved(fake_db)

    assert saved_meetup["postcode"] == ""
    assert saved_meetup["location"] == (
        "TAR UMT Sports Complex, Sports complex beside Block A, Penang"
    )


# =========================================================
# Negative Test Case - Description Validation
# =========================================================

def test_create_meetup_rejects_description_more_than_300_characters(client):
    test_client, fake_db = client

    long_description = "A" * 301

    response = test_client.post(
        "/create-meetup",
        data=valid_create_meetup_data(description=long_description)
    )

    assert response.status_code == 200
    assert_meetup_not_saved(fake_db)


# =========================================================
# Firebase Connection Failure Test
# =========================================================

def test_create_meetup_page_can_open_when_firebase_disconnected(monkeypatch):
    """
    This test checks whether the page can still open safely when Firebase is not connected.
    It should not crash the Flask application.
    """

    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(
        flask_module,
        "firebase_error_message",
        "Test Firebase connection failed"
    )

    flask_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-key"
    )

    with flask_module.app.test_client() as test_client:
        with test_client.session_transaction() as session:
            session["user_id"] = "organizer_001"
            session["role"] = "organizer"

        response = test_client.get("/create-meetup")

        assert response.status_code == 200