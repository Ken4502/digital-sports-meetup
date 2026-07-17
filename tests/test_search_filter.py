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

    def update(self, data):
        """Update the document with new data."""
        self._data.update(data)


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
        "state": "Kuala Lumpur",
        "meetup_date": "2099-07-10",
    }),
    "meetup_02": create_meetup_doc("meetup_02", {
        "sport_type": "Football",
        "location": "Penang National Park, Penang",
        "state": "Penang",
        "meetup_date": "2099-07-11",
    }),
    "meetup_03": create_meetup_doc("meetup_03", {
        "sport_type": "Basketball",
        "location": "Johor Bahru Community Hall, Johor",
        "state": "Johor",
        "meetup_date": "2099-07-12",
    }),
    "meetup_04": create_meetup_doc("meetup_04", {
        "sport_type": "Badminton",
        "location": "Georgetown Badminton Court, Penang",
        "state": "Penang",
        "meetup_date": "2099-07-10", # Same date as meetup_01
    }),
    "meetup_05": create_meetup_doc("meetup_05", {
        "sport_type": "Running",
        "location": "Bukit Jalil Park, Kuala Lumpur",
        "state": "Kuala Lumpur",
        "meetup_date": "2099-08-01",
    }),
    "meetup_past": create_meetup_doc("meetup_past", {
        "sport_type": "Tennis",
        "location": "Old Tennis Court, Melaka",
        "state": "Melaka",
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

    # Capture the context passed to render_template instead of parsing HTML
    captured_contexts = []
    original_render_template = flask_module.render_template

    def capture_context_wrapper(template_name, **context):
        captured_contexts.append(context)
        # Return a dummy string as we only need to check the context
        return f"Template: {template_name}"

    monkeypatch.setattr(flask_module, "render_template", capture_context_wrapper)
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")

    flask_module.app.config.update(TESTING=True)

    with flask_module.app.test_client() as test_client:
        # Yield both client and the context capture list
        yield test_client, captured_contexts


# =========================================================
# Helper Assertions
# =========================================================

def get_meetup_ids_from_context(captured_contexts):
    """Asserts that the response contains exactly the meetups with the given IDs."""
    assert len(captured_contexts) > 0, "render_template was not called."
    context = captured_contexts[0]
    assert "meetups" in context, "Meetups not found in template context."
    return {meetup["id"] for meetup in context["meetups"]}


# =========================================================
# Positive Test Cases - Individual Filters
# =========================================================

def test_no_filters_shows_all_active_meetups(client):
    """When no filters are applied, all active meetups should be shown."""
    test_client, captured_contexts = client
    response = test_client.get("/active-meetups")

    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    # All meetups except the one in the past
    expected_ids = {"meetup_01", "meetup_02", "meetup_03", "meetup_04", "meetup_05"}
    assert found_ids == expected_ids


@pytest.mark.parametrize("keyword, expected_ids", [
    pytest.param("badminton", {"meetup_01", "meetup_04"}, id="keyword-sport"),
    pytest.param("penang", {"meetup_02", "meetup_04"}, id="keyword-location"),
    pytest.param("2099-07-10", {"meetup_01", "meetup_04"}, id="keyword-date"),
    pytest.param("kuala lumpur", {"meetup_01", "meetup_05"}, id="keyword-multi-word-location"),
    pytest.param("kl badminton", {"meetup_01"}, id="keyword-multi-word-sport-and-location"),
    pytest.param("nonexistent", set(), id="keyword-no-match"),
    pytest.param("", {"meetup_01", "meetup_02", "meetup_03", "meetup_04", "meetup_05"}, id="keyword-empty"),
])
def test_filter_by_keyword(client, keyword, expected_ids):
    """Test filtering by a single keyword."""
    test_client, captured_contexts = client
    response = test_client.get(f"/active-meetups?keyword={keyword}")

    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == expected_ids


@pytest.mark.parametrize("state, expected_ids", [
    pytest.param("Kuala Lumpur", {"meetup_01", "meetup_05"}, id="state-kl"),
    pytest.param("Penang", {"meetup_02", "meetup_04"}, id="state-penang"),
    pytest.param("Johor", {"meetup_03"}, id="state-johor"),
    pytest.param("Selangor", set(), id="state-no-match"),
])
def test_filter_by_state(client, state, expected_ids):
    """Test filtering by the state dropdown."""
    test_client, captured_contexts = client
    response = test_client.get(f"/active-meetups?state={state}")

    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == expected_ids, f"Failed on state filter: {state}"


@pytest.mark.parametrize("sport, expected_ids", [
    pytest.param("Badminton", {"meetup_01", "meetup_04"}, id="sport-badminton"),
    pytest.param("Football", {"meetup_02"}, id="sport-football"),
    pytest.param("Running", {"meetup_05"}, id="sport-running"),
    pytest.param("Tennis", set(), id="sport-tennis-is-past"),
    pytest.param("Cycling", set(), id="sport-no-meetups"),
])
def test_filter_by_sport_type(client, sport, expected_ids):
    """Test filtering by the sport_type dropdown."""
    test_client, captured_contexts = client
    response = test_client.get(f"/active-meetups?sport_type={sport}")

    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == expected_ids


@pytest.mark.parametrize("date, expected_ids", [
    pytest.param("2099-07-10", {"meetup_01", "meetup_04"}, id="date-multiple-meetups"),
    pytest.param("2099-07-11", {"meetup_02"}, id="date-single-meetup"),
    pytest.param("2099-01-01", set(), id="date-no-meetups"),
])
def test_filter_by_date(client, date, expected_ids):
    """Test filtering by an exact date."""
    test_client, captured_contexts = client
    response = test_client.get(f"/active-meetups?meetup_date={date}")

    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == expected_ids


# =========================================================
# Positive Test Cases - Combined Filters
# =========================================================

def test_filter_by_sport_and_location(client):
    test_client, captured_contexts = client
    # Find Badminton meetups in Penang
    response = test_client.get("/active-meetups?sport_type=Badminton&state=Penang")
    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == {"meetup_04"}


def test_filter_by_sport_and_date(client):
    test_client, captured_contexts = client
    # Find Badminton meetups on 2099-07-10
    response = test_client.get("/active-meetups?sport_type=Badminton&meetup_date=2099-07-10")
    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == {"meetup_01", "meetup_04"}


def test_filter_by_keyword_and_sport(client):
    test_client, captured_contexts = client
    # Find meetups with "penang" in them that are for "Football"
    response = test_client.get("/active-meetups?keyword=penang&sport_type=Football")
    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == {"meetup_02"}


def test_all_filters_combined_for_specific_result(client):
    test_client, captured_contexts = client
    # Find a very specific meetup
    response = test_client.get(
        "/active-meetups?keyword=georgetown&state=Penang&sport_type=Badminton&meetup_date=2099-07-10"
    )
    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == {"meetup_04"}


def test_combined_filters_with_no_results(client):
    test_client, captured_contexts = client
    # Find Football meetups in Kuala Lumpur (none exist in test data)
    response = test_client.get("/active-meetups?sport_type=Football&state=Kuala Lumpur")
    assert response.status_code == 200
    found_ids = get_meetup_ids_from_context(captured_contexts)
    assert found_ids == set()


# =========================================================
# Edge Case and Validation Tests
# =========================================================

def test_filter_is_case_insensitive(client):
    test_client, captured_contexts = client
    # Keyword filter
    response = test_client.get("/active-meetups?keyword=kL SpOrTs CeNtRe")
    assert response.status_code == 200
    found_ids_keyword = get_meetup_ids_from_context(captured_contexts)
    assert found_ids_keyword == {"meetup_01"}

    # Keyword filter should still work on the full location string
    captured_contexts.clear() # Reset for next request
    response = test_client.get("/active-meetups?keyword=kL SpOrTs CeNtRe")
    assert response.status_code == 200
    found_ids_keyword_again = get_meetup_ids_from_context(captured_contexts)
    assert found_ids_keyword_again == {"meetup_01"}


def test_past_meetups_are_not_shown(client):
    test_client, captured_contexts = client
    # Try to find the past tennis meetup by its specific sport
    response = test_client.get("/active-meetups?sport_type=Tennis")
    assert response.status_code == 200
    found_ids_sport = get_meetup_ids_from_context(captured_contexts)
    assert found_ids_sport == set()

    # Try to find it by its specific location
    captured_contexts.clear()
    response = test_client.get("/active-meetups?state=Melaka")
    assert response.status_code == 200
    found_ids_location = get_meetup_ids_from_context(captured_contexts)
    assert found_ids_location == set()


def test_firebase_connection_failure(monkeypatch):
    """
    The active meetups page should still load gracefully and show an empty list
    if the database connection fails.
    """
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(flask_module, "firebase_error_message", "Test connection error")

    flask_module.app.config.update(TESTING=True)

    with flask_module.app.test_client() as client:
        response = client.get("/active-meetups")
        assert response.status_code == 200
        # The real render_template is not called, but we can check the context
        # that would have been passed if it were.
        # In this case, the view function returns early, so we check the HTML.
        assert b"Could not connect to the database" in response.data