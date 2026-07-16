import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
import app as flask_module
from datetime import datetime, timedelta


# =========================================================
# Fake Firebase Database for Testing
# =========================================================

class FakeDocument:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class FakeMeetupCollection:
    def __init__(self, initial_data=None):
        self._docs = {}
        if initial_data:
            for doc_id, data in initial_data.items():
                self._docs[doc_id] = FakeDocument(doc_id, data)

    def where(self, field, op, value):
        # Simplified 'where' that only supports status == 'active' for this test
        if field == "status" and op == "==" and value == "active":
            return self
        return FakeMeetupCollection() # Return empty for other queries

    def stream(self):
        # Return documents that are not marked as 'past'
        return [
            doc for doc in self._docs.values()
            if doc.to_dict().get("status") != "past"
        ]

    def document(self, doc_id):
        return self._docs.get(doc_id)


class FakeDB:
    def __init__(self, initial_meetups):
        self.meetups = FakeMeetupCollection(initial_meetups)

    def collection(self, name):
        if name == "meetups":
            return self.meetups
        return FakeMeetupCollection()


# =========================================================
# Reusable Test Data
# =========================================================

def create_meetup_doc(doc_id, overrides):
    """Helper to create a meetup document dictionary."""
    future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    data = {
        "id": doc_id,
        "sport_type": "Badminton",
        "location": "Kuala Lumpur",
        "meetup_date": future_date,
        "meetup_time": "20:00",
        "status": "active",
        "capacity": 10,
        "joined_count": 5,
    }
    data.update(overrides)
    return data


MEETUPS_DATA = {
    "meetup_01": create_meetup_doc("meetup_01", {
        "sport_type": "Badminton",
        "location": "KL Sports Centre, Kuala Lumpur",
        "meetup_date": "2099-07-10",
    }),
    "meetup_02": create_meetup_doc("meetup_02", {
        "sport_type": "Football",
        "location": "Penang National Park, Penang",
        "meetup_date": "2099-07-11",
    }),
    "meetup_03": create_meetup_doc("meetup_03", {
        "sport_type": "Basketball",
        "location": "Johor Bahru Community Hall, Johor",
        "meetup_date": "2099-07-12",
    }),
    "meetup_04": create_meetup_doc("meetup_04", {
        "sport_type": "Badminton",
        "location": "Georgetown Badminton Court, Penang",
        "meetup_date": "2099-07-10", # Same date as meetup_01
    }),
    "meetup_05": create_meetup_doc("meetup_05", {
        "sport_type": "Running",
        "location": "Bukit Jalil Park, Kuala Lumpur",
        "meetup_date": "2099-08-01",
    }),
    "meetup_past": create_meetup_doc("meetup_past", {
        "sport_type": "Tennis",
        "location": "Old Tennis Court, Melaka",
        "meetup_date": "2020-01-01", # In the past
    }),
}


# =========================================================
# Test Client Setup
# =========================================================

@pytest.fixture
def client(monkeypatch):
    # Use a deep copy of the data for each test to ensure isolation
    import copy
    fake_db = FakeDB(copy.deepcopy(MEETUPS_DATA))

    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")

    flask_module.app.config.update(TESTING=True)

    with flask_module.app.test_client() as test_client:
        yield test_client


# =========================================================
# Helper Assertions
# =========================================================

def assert_meetups_in_response(response, expected_ids):
    """Asserts that the response contains exactly the meetups with the given IDs."""
    assert response.status_code == 200
    # The meetups are passed to the template in the context
    # We can't directly check the rendered HTML easily without a library like BeautifulSoup
    # but we can check the number of results if it were passed.
    # For now, we'll assume the template renders what it's given.
    # A more robust way is to check the HTML content.
    
    # A simple check for now:
    for meetup_id in expected_ids:
        assert bytes(f'href="/meetup/{meetup_id}"', 'utf-8') in response.data

    # Check that no other meetups are present
    all_ids = set(MEETUPS_DATA.keys())
    unexpected_ids = all_ids - set(expected_ids)
    for meetup_id in unexpected_ids:
         assert bytes(f'href="/meetup/{meetup_id}"', 'utf-8') not in response.data


# =========================================================
# Positive Test Cases - Individual Filters
# =========================================================

def test_no_filters_shows_all_active_meetups(client):
    response = client.get("/active-meetups")
    # All meetups except the one in the past
    expected = ["meetup_01", "meetup_02", "meetup_03", "meetup_04", "meetup_05"]
    assert_meetups_in_response(response, expected)


@pytest.mark.parametrize("keyword, expected_ids", [
    ("badminton", ["meetup_01", "meetup_04"]), # Matches sport_type
    ("penang", ["meetup_02", "meetup_04"]),    # Matches location
    ("2099-07-10", ["meetup_01", "meetup_04"]),# Matches date
    ("kuala lumpur", ["meetup_01", "meetup_05"]), # Matches multi-word location
    ("nonexistent", []),                      # No match
    ("", ["meetup_01", "meetup_02", "meetup_03", "meetup_04", "meetup_05"]), # Empty keyword
])
def test_filter_by_keyword(client, keyword, expected_ids):
    response = client.get(f"/active-meetups?keyword={keyword}")
    assert_meetups_in_response(response, expected_ids)


@pytest.mark.parametrize("location, expected_ids", [
    ("kuala lumpur", ["meetup_01", "meetup_05"]),
    ("penang", ["meetup_02", "meetup_04"]),
    ("johor", ["meetup_03"]),
    ("georgetown", ["meetup_04"]), # Partial match
    ("nonexistent", []),
])
def test_filter_by_location(client, location, expected_ids):
    response = client.get(f"/active-meetups?location={location}")
    assert_meetups_in_response(response, expected_ids)


@pytest.mark.parametrize("sport, expected_ids", [
    ("Badminton", ["meetup_01", "meetup_04"]),
    ("Football", ["meetup_02"]),
    ("Running", ["meetup_05"]),
    ("Tennis", []), # This one is in the past
    ("Cycling", []), # No meetups for this sport
])
def test_filter_by_sport_type(client, sport, expected_ids):
    response = client.get(f"/active-meetups?sport_type={sport}")
    assert_meetups_in_response(response, expected_ids)


@pytest.mark.parametrize("date, expected_ids", [
    ("2099-07-10", ["meetup_01", "meetup_04"]),
    ("2099-07-11", ["meetup_02"]),
    ("2099-01-01", []), # No meetups on this date
])
def test_filter_by_date(client, date, expected_ids):
    response = client.get(f"/active-meetups?meetup_date={date}")
    assert_meetups_in_response(response, expected_ids)


# =========================================================
# Positive Test Cases - Combined Filters
# =========================================================

def test_filter_by_sport_and_location(client):
    # Find Badminton meetups in Penang
    response = client.get("/active-meetups?sport_type=Badminton&location=penang")
    assert_meetups_in_response(response, ["meetup_04"])


def test_filter_by_sport_and_date(client):
    # Find Badminton meetups on 2099-07-10
    response = client.get("/active-meetups?sport_type=Badminton&meetup_date=2099-07-10")
    assert_meetups_in_response(response, ["meetup_01", "meetup_04"])


def test_filter_by_keyword_and_sport(client):
    # Find meetups with "penang" in them that are for "Football"
    response = client.get("/active-meetups?keyword=penang&sport_type=Football")
    assert_meetups_in_response(response, ["meetup_02"])


def test_all_filters_combined_for_specific_result(client):
    # Find a very specific meetup
    response = client.get(
        "/active-meetups?keyword=georgetown&location=penang&sport_type=Badminton&meetup_date=2099-07-10"
    )
    assert_meetups_in_response(response, ["meetup_04"])


def test_combined_filters_with_no_results(client):
    # Find Football meetups in Kuala Lumpur (none exist in test data)
    response = client.get("/active-meetups?sport_type=Football&location=kuala lumpur")
    assert_meetups_in_response(response, [])


# =========================================================
# Edge Case and Validation Tests
# =========================================================

def test_filter_is_case_insensitive(client):
    # Keyword filter
    response_keyword = client.get("/active-meetups?keyword=kL SpOrTs CeNtRe")
    assert_meetups_in_response(response_keyword, ["meetup_01"])

    # Location filter
    response_location = client.get("/active-meetups?location=kL SpOrTs CeNtRe")
    assert_meetups_in_response(response_location, ["meetup_01"])


def test_past_meetups_are_not_shown(client):
    # Try to find the past tennis meetup by its specific sport
    response = client.get("/active-meetups?sport_type=Tennis")
    assert_meetups_in_response(response, [])

    # Try to find it by its specific location
    response = client.get("/active-meetups?location=melaka")
    assert_meetups_in_response(response, [])


def test_firebase_connection_failure(monkeypatch):
    """
    The active meetups page should still load gracefully (showing no meetups)
    if the database connection fails.
    """
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(
        flask_module,
        "firebase_error_message",
        "Test Firebase connection failed"
    )
    flask_module.app.config.update(TESTING=True)

    with flask_module.app.test_client() as client:
        response = client.get("/active-meetups")
        assert response.status_code == 200
        # Check for the empty state message or lack of meetups
        assert b"No active meetups found" in response.data