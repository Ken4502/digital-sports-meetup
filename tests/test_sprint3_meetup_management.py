"""
Sprint 3 pytest file for Smart Sports Meetup and Community Management Platform.

Save this file as:
    tests/test_sprint3_meetup_management.py

Covered Sprint 3 user stories:
- SCRUM-194: Organizer edit meetup information
- SCRUM-203: Organizer cancel own meetup
- SCRUM-212: Organizer view participant list
- SCRUM-230: Participant search meetups by keyword
- SCRUM-239: Participant filter meetups by sport type
- SCRUM-249: Participant filter meetups by date
- SCRUM-432: Only own meetups are editable
- SCRUM-461: Meetup listings load quickly and exclude invalid past meetups

These tests use fake Firestore data. They do not need the real serviceAccountKey.json.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

import app as flask_module


# =========================================================
# Fake Firestore helpers
# =========================================================

class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: dict[str, Any] | None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        if self._data is None:
            return None
        return dict(self._data)


class FakeDocumentReference:
    def __init__(self, fake_db: "FakeDB", collection_name: str, doc_id: str):
        self.fake_db = fake_db
        self.collection_name = collection_name
        self.doc_id = doc_id

    def get(self):
        data = self.fake_db.data.get(self.collection_name, {}).get(self.doc_id)
        return FakeDocumentSnapshot(self.doc_id, data)

    def update(self, values: dict[str, Any]):
        self.fake_db.update_calls.append((self.collection_name, self.doc_id, dict(values)))
        collection = self.fake_db.data.setdefault(self.collection_name, {})
        if self.doc_id not in collection:
            collection[self.doc_id] = {}
        collection[self.doc_id].update(values)

    def set(self, values: dict[str, Any]):
        self.fake_db.set_calls.append((self.collection_name, self.doc_id, dict(values)))
        self.fake_db.data.setdefault(self.collection_name, {})[self.doc_id] = dict(values)


class FakeQuery:
    def __init__(self, fake_db: "FakeDB", collection_name: str, filters=None):
        self.fake_db = fake_db
        self.collection_name = collection_name
        self.filters = filters or []

    def where(self, field: str, op: str, value: Any):
        return FakeQuery(
            self.fake_db,
            self.collection_name,
            self.filters + [(field, op, value)],
        )

    def stream(self):
        docs = []
        for doc_id, data in self.fake_db.data.get(self.collection_name, {}).items():
            if self._matches(data):
                docs.append(FakeDocumentSnapshot(doc_id, data))
        return docs

    def _matches(self, data: dict[str, Any]):
        for field, op, value in self.filters:
            current = data.get(field)
            if op == "==" and current != value:
                return False
            if op == "array_contains" and value not in (current or []):
                return False
        return True


class FakeCollection:
    def __init__(self, fake_db: "FakeDB", collection_name: str):
        self.fake_db = fake_db
        self.collection_name = collection_name

    def document(self, doc_id: str):
        return FakeDocumentReference(self.fake_db, self.collection_name, doc_id)

    def where(self, field: str, op: str, value: Any):
        return FakeQuery(self.fake_db, self.collection_name).where(field, op, value)

    def stream(self):
        return FakeQuery(self.fake_db, self.collection_name).stream()


class FakeDB:
    def __init__(self, data: dict[str, dict[str, dict[str, Any]]] | None = None):
        self.data = data or {}
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.set_calls: list[tuple[str, str, dict[str, Any]]] = []

    def collection(self, collection_name: str):
        return FakeCollection(self, collection_name)


# =========================================================
# Fixtures
# =========================================================

@pytest.fixture(autouse=True)
def configure_app():
    flask_module.app.config.update(TESTING=True, SECRET_KEY="pytest-secret")


@pytest.fixture
def client():
    with flask_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def captured_templates(monkeypatch):
    calls = []

    def fake_render_template(template_name, **context):
        calls.append({"template": template_name, "context": context})
        return f"TEMPLATE:{template_name}"

    monkeypatch.setattr(flask_module, "render_template", fake_render_template)
    return calls


def login_as(client, role="organizer", user_id="org1"):
    with client.session_transaction() as session:
        session.clear()
        session["role"] = role
        session["user_id"] = user_id
        session["name"] = f"{role.title()} User"


def future_date(days=7):
    return (flask_module.now_malaysia() + timedelta(days=days)).strftime("%Y-%m-%d")


def past_date(days=7):
    return (flask_module.now_malaysia() - timedelta(days=days)).strftime("%Y-%m-%d")


def valid_edit_form(**overrides):
    data = {
        "sport_type": "Badminton",
        "capacity": "10",
        "meetup_date": future_date(7),
        "meetup_time": "18:30",
        "location": "Penang Sports Arena, Penang",
        "state": "Penang",
        "postcode": "10000",
        "venue_name": "Penang Sports Arena",
        "address": "Jalan Sports Arena",
        "description": "Friendly badminton meetup.",
    }
    data.update(overrides)
    return data


def base_meetup(**overrides):
    data = {
        "sport_type": "Badminton",
        "title": "Badminton Meetup",
        "capacity": 10,
        "joined_count": 2,
        "meetup_date": future_date(7),
        "meetup_time": "18:30",
        "location": "Penang Sports Arena, Penang",
        "state": "Penang",
        "postcode": "10000",
        "venue_name": "Penang Sports Arena",
        "address": "Jalan Sports Arena",
        "description": "Friendly badminton meetup.",
        "organizer_id": "org1",
        "participant_ids": ["p1", "p2"],
        "status": "active",
    }
    data.update(overrides)
    return data


def fake_db_with_meetups():
    return FakeDB(
        {
            "meetups": {
                "m1": base_meetup(
                    sport_type="Badminton",
                    title="Badminton Meetup",
                    state="Penang",
                    meetup_date=future_date(5),
                    meetup_time="18:00",
                    location="Penang Sports Arena",
                    capacity=10,
                    joined_count=2,
                ),
                "m2": base_meetup(
                    sport_type="Football",
                    title="Football Meetup",
                    state="Selangor",
                    meetup_date=future_date(6),
                    meetup_time="20:00",
                    location="Selangor Field",
                    postcode="47800",
                    venue_name="Selangor Field",
                    address="Jalan Selangor Field",
                    description="Friendly football meetup.",
                    capacity=5,
                    joined_count=5,
                ),
                "m3": base_meetup(
                    sport_type="Tennis",
                    title="Tennis Meetup",
                    state="Penang",
                    meetup_date=past_date(2),
                    meetup_time="10:00",
                    location="Old Court",
                    capacity=8,
                    joined_count=1,
                    status="active",
                ),
                "m4": base_meetup(
                    sport_type="Cycling",
                    title="Cancelled Cycling Meetup",
                    state="Penang",
                    meetup_date=future_date(8),
                    meetup_time="08:00",
                    location="Gurney Drive",
                    status="cancelled",
                ),
            },
            "rsvps": {},
            "users": {},
        }
    )


def patch_db(monkeypatch, fake_db):
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")
    return fake_db


def keyword_query(keyword):
    """
    Send common keyword parameter names together.

    Some versions of the active meetup page use "keyword",
    while some earlier versions may use "search", "search_query", or "q".
    Sending all of them makes the pytest file compatible with the latest
    Testing branch and older local branches.
    """

    return {
        "keyword": keyword,
        "search": keyword,
        "search_query": keyword,
        "q": keyword,
    }


# =========================================================
# SCRUM-194 validation tests: edit meetup information
# =========================================================

def test_scrum_194_validate_edit_meetup_accepts_valid_future_data():
    errors = flask_module.validate_edit_meetup_form(valid_edit_form())
    assert errors == []


@pytest.mark.parametrize("sport_type", ["", "Swimming", "Chess", "Badminton "])
def test_scrum_194_validate_edit_meetup_rejects_invalid_sport_type(sport_type):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(sport_type=sport_type))
    assert any("sport" in error.lower() for error in errors)


@pytest.mark.parametrize(
    "capacity",
    ["", "0", "-1", "abc", "1.5", "101", "five"],
)
def test_scrum_194_validate_edit_meetup_rejects_invalid_capacity(capacity):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(capacity=capacity))
    assert any("capacity" in error.lower() for error in errors)


@pytest.mark.parametrize("postcode", ["1234", "123456", "abcde", "12a45"])
def test_scrum_194_validate_edit_meetup_rejects_invalid_postcode(postcode):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(postcode=postcode))
    assert any("postcode" in error.lower() for error in errors)


@pytest.mark.parametrize("venue_name", ["", "A", "AB"])
def test_scrum_194_validate_edit_meetup_rejects_short_or_empty_venue(venue_name):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(venue_name=venue_name))
    assert any("venue" in error.lower() for error in errors)


@pytest.mark.parametrize("address", ["", "A", "ABCD"])
def test_scrum_194_validate_edit_meetup_rejects_short_or_empty_address(address):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(address=address))
    assert any("address" in error.lower() for error in errors)


def test_scrum_194_validate_edit_meetup_rejects_long_description():
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(description="a" * 301))
    assert any("description" in error.lower() for error in errors)


def test_scrum_194_validate_edit_meetup_rejects_past_date_and_time():
    errors = flask_module.validate_edit_meetup_form(
        valid_edit_form(meetup_date=past_date(1), meetup_time="18:30")
    )
    assert "Meetup date and time cannot be in the past." in errors


def test_scrum_194_validate_edit_meetup_rejects_current_or_past_datetime_today():
    current_time = flask_module.now_malaysia() - timedelta(minutes=10)
    errors = flask_module.validate_edit_meetup_form(
        valid_edit_form(
            meetup_date=current_time.strftime("%Y-%m-%d"),
            meetup_time=current_time.strftime("%H:%M"),
        )
    )
    assert "Meetup date and time cannot be in the past." in errors


# =========================================================
# SCRUM-461 helper tests: available slot calculation
# =========================================================

@pytest.mark.parametrize(
    "capacity, joined_count, expected",
    [
        (10, 0, 10),
        (10, 3, 7),
        (5, 5, 0),
        (5, 8, 0),
        ("10", "2", 8),
        (None, 2, 0),
    ],
)
def test_scrum_461_calculate_available_slots(capacity, joined_count, expected):
    meetup = {"capacity": capacity, "joined_count": joined_count}
    assert flask_module.calculate_available_slots(meetup) == expected


# =========================================================
# SCRUM-230, SCRUM-239, SCRUM-249, SCRUM-461: active meetup listing
# =========================================================

def test_active_meetups_returns_empty_when_firebase_not_connected(client, captured_templates, monkeypatch):
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(flask_module, "firebase_error_message", "missing service account")

    response = client.get("/active-meetups")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "active_meetups.html"
    assert captured_templates[-1]["context"]["meetups"] == []
    assert captured_templates[-1]["context"]["db_connection_failed"] is True


def test_scrum_461_active_meetups_loads_only_active_upcoming_meetups(client, captured_templates, monkeypatch):
    fake_db = patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups")

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    meetup_ids = [meetup["id"] for meetup in meetups]

    assert "m1" in meetup_ids
    assert "m2" in meetup_ids
    assert "m3" not in meetup_ids
    assert "m4" not in meetup_ids
    assert fake_db.data["meetups"]["m3"]["status"] == "past"


@pytest.mark.parametrize(
    "keyword, expected_ids",
    [
        ("Badminton", ["m1"]),
        ("Penang", ["m1"]),
        ("Football", ["m2"]),
        ("Selangor", ["m2"]),
        ("Badminton Penang", ["m1"]),
        ("NoSuchKeyword", []),
    ],
)
def test_scrum_230_active_meetups_keyword_search(client, captured_templates, monkeypatch, keyword, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string=keyword_query(keyword))

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


@pytest.mark.parametrize(
    "sport_type, expected_ids",
    [
        ("Badminton", ["m1"]),
        ("Football", ["m2"]),
        ("Tennis", []),
        ("", ["m1", "m2"]),
    ],
)
def test_scrum_239_active_meetups_sport_type_filter(client, captured_templates, monkeypatch, sport_type, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string={"sport_type": sport_type})

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


@pytest.mark.parametrize(
    "meetup_date, expected_ids",
    [
        (future_date(5), ["m1"]),
        (future_date(6), ["m2"]),
        (past_date(2), []),
    ],
)
def test_scrum_249_active_meetups_date_filter(client, captured_templates, monkeypatch, meetup_date, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string={"meetup_date": meetup_date})

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


@pytest.mark.parametrize(
    "state, expected_ids",
    [
        ("Penang", ["m1"]),
        ("Selangor", ["m2"]),
        ("Kedah", []),
    ],
)
def test_active_meetups_state_filter(client, captured_templates, monkeypatch, state, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string={"state": state})

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


def test_active_meetups_combined_keyword_sport_and_date_filters(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get(
        "/active-meetups",
        query_string={
            "keyword": "Badminton Penang",
            "sport_type": "Badminton",
            "meetup_date": future_date(5),
            "state": "Penang",
        },
    )

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == ["m1"]


def test_active_meetups_sets_available_slots_and_full_status(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, fake_db_with_meetups())

    client.get("/active-meetups")
    meetups = {meetup["id"]: meetup for meetup in captured_templates[-1]["context"]["meetups"]}

    assert meetups["m1"]["available_slots"] == 8
    assert meetups["m1"]["is_full"] is False
    assert meetups["m2"]["available_slots"] == 0
    assert meetups["m2"]["is_full"] is True


def test_active_meetups_sorts_by_date_then_time(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "late": base_meetup(meetup_date=future_date(10), meetup_time="18:00"),
                "early": base_meetup(meetup_date=future_date(2), meetup_time="20:00"),
                "same_day_early": base_meetup(meetup_date=future_date(2), meetup_time="08:00"),
            }
        }
    )
    patch_db(monkeypatch, fake_db)

    client.get("/active-meetups")
    meetups = captured_templates[-1]["context"]["meetups"]

    assert [meetup["id"] for meetup in meetups] == ["same_day_early", "early", "late"]


# =========================================================
# SCRUM-194 and SCRUM-432: edit meetup route and ownership control
# =========================================================

def test_edit_meetup_blocks_participant_user(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.get("/meetup/m1/edit")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_edit_meetup_redirects_when_meetup_not_found(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/missing/edit")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


def test_scrum_432_edit_meetup_blocks_other_organizer(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org2")

    response = client.get("/meetup/m1/edit")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


@pytest.mark.parametrize("status", ["cancelled", "past", "deleted", "completed"])
def test_edit_meetup_blocks_organizer_editing_non_active_meetup(client, monkeypatch, status):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status=status)}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/edit")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


def test_scrum_194_edit_meetup_owner_can_open_edit_page(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/edit")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_meetup.html"
    assert captured_templates[-1]["context"]["meetup"]["id"] == "m1"


def test_scrum_194_edit_meetup_admin_can_open_any_edit_page(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/meetup/m1/edit")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_meetup.html"


def test_scrum_194_edit_meetup_owner_can_update_valid_meetup(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(joined_count=2)}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/edit", data=valid_edit_form(capacity="12"))

    assert response.status_code == 302
    updated_meetup = fake_db.data["meetups"]["m1"]
    assert updated_meetup["sport_type"] == "Badminton"
    assert updated_meetup["capacity"] == 12
    assert updated_meetup["available_slots"] == 10
    assert updated_meetup["venue_name"] == "Penang Sports Arena"


def test_edit_meetup_available_slots_never_negative(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(joined_count=8)}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/edit", data=valid_edit_form(capacity="5"))

    assert response.status_code == 302
    assert fake_db.data["meetups"]["m1"]["available_slots"] == 0


def test_scrum_194_edit_meetup_rejects_invalid_form_without_update(client, captured_templates, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(capacity=10)}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/edit", data=valid_edit_form(capacity="abc"))

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_meetup.html"
    assert fake_db.data["meetups"]["m1"]["capacity"] == 10


def test_scrum_194_edit_meetup_rejects_past_datetime_without_update(client, captured_templates, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(meetup_date=future_date(8))}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post(
        "/meetup/m1/edit",
        data=valid_edit_form(meetup_date=past_date(1), meetup_time="18:30"),
    )

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_meetup.html"
    assert fake_db.data["meetups"]["m1"]["meetup_date"] == future_date(8)


# =========================================================
# SCRUM-203 and SCRUM-432: cancel meetup route
# =========================================================

def test_cancel_meetup_blocks_non_organizer(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/meetup/m1/cancel")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_cancel_meetup_redirects_when_meetup_not_found(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/missing/cancel")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


def test_scrum_432_cancel_meetup_blocks_other_organizer(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org2")

    response = client.post("/meetup/m1/cancel")

    assert response.status_code == 302
    assert "/active-meetups" in response.location
    assert fake_db.data["meetups"]["m1"]["status"] == "active"


@pytest.mark.parametrize("status", ["cancelled", "past", "deleted", "completed"])
def test_cancel_meetup_blocks_non_active_meetups(client, monkeypatch, status):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status=status)}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/cancel")

    assert response.status_code == 302
    assert fake_db.data["meetups"]["m1"]["status"] == status


def test_scrum_203_cancel_meetup_owner_marks_meetup_cancelled(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status="active")}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post(
        "/meetup/m1/cancel",
        data={"cancellation_reason": "Heavy rain"},
    )

    assert response.status_code == 302
    updated_meetup = fake_db.data["meetups"]["m1"]
    assert updated_meetup["status"] == "cancelled"
    assert updated_meetup["cancelled_by"] == "org1"
    assert updated_meetup["cancellation_reason"] == "Heavy rain"


def test_cancel_meetup_allows_empty_cancellation_reason(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status="active")}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/cancel", data={})

    assert response.status_code == 302
    assert fake_db.data["meetups"]["m1"]["status"] == "cancelled"
    assert fake_db.data["meetups"]["m1"]["cancellation_reason"] == ""


# =========================================================
# SCRUM-212 and SCRUM-432: organizer view participant list
# =========================================================

def participant_user(full_name, **overrides):
    data = {
        "full_name": full_name,
        "role": "participant",
        "sport_interest": "Badminton",
        "skill_level": "Beginner",
        "state": "Penang",
        "status": "active",
    }
    data.update(overrides)
    return data


def test_meetup_participants_blocks_participant_role(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_meetup_participants_redirects_when_meetup_not_found(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/missing/participants")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


def test_scrum_432_meetup_participants_blocks_other_organizer(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org2")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 302
    assert "/active-meetups" in response.location


def test_scrum_212_meetup_participants_owner_can_view_confirmed_participants(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(participant_ids=["p2", "p1"]),
            },
            "rsvps": {
                "rsvp1": {"meetup_id": "m1", "participant_id": "p3", "status": "confirmed"},
                "rsvp2": {"meetup_id": "m1", "participant_id": "p4", "status": "withdrawn"},
                "rsvp3": {"meetup_id": "m2", "participant_id": "p5", "status": "confirmed"},
            },
            "users": {
                "p1": participant_user("Alice", skill_level="Beginner"),
                "p2": participant_user("Bob", skill_level="Advanced"),
                "p3": participant_user("Charlie", skill_level="Intermediate"),
                "p4": participant_user("Withdrawn User"),
                "p5": participant_user("Other Meetup User"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "meetup_participants.html"
    participants = captured_templates[-1]["context"]["participants"]
    assert [participant["full_name"] for participant in participants] == ["Alice", "Bob", "Charlie"]
    assert captured_templates[-1]["context"]["participant_count"] == 3


def test_meetup_participants_excludes_inactive_users_and_non_participants(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(participant_ids=["p1", "p2", "org2", "missing"]),
            },
            "rsvps": {},
            "users": {
                "p1": participant_user("Active Participant", status="active"),
                "p2": participant_user("Inactive Participant", status="inactive"),
                "org2": {"full_name": "Organizer Two", "role": "organizer", "status": "active"},
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    participants = captured_templates[-1]["context"]["participants"]
    assert [participant["full_name"] for participant in participants] == ["Active Participant"]


def test_meetup_participants_admin_can_view_any_meetup(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(organizer_id="org1", participant_ids=["p1"]),
            },
            "rsvps": {},
            "users": {
                "p1": participant_user("Alice"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    assert captured_templates[-1]["context"]["participant_count"] == 1


def test_meetup_participants_handles_empty_participant_list(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(participant_ids=[]),
            },
            "rsvps": {},
            "users": {},
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    assert captured_templates[-1]["context"]["participants"] == []
    assert captured_templates[-1]["context"]["participant_count"] == 0


# =========================================================
# Extra regression checks for Sprint 3 stability
# =========================================================

def test_active_meetups_preserves_filter_values_in_template(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, fake_db_with_meetups())

    client.get(
        "/active-meetups",
        query_string={
            "keyword": "Badminton",
            "state": "Penang",
            "sport_type": "Badminton",
            "meetup_date": future_date(5),
        },
    )

    filters = captured_templates[-1]["context"]["filters"]
    assert filters["keyword"] == "Badminton"
    assert filters["state"] == "Penang"
    assert filters["sport_type"] == "Badminton"
    assert filters["meetup_date"] == future_date(5)


def test_edit_meetup_does_not_change_organizer_id(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org1")

    client.post("/meetup/m1/edit", data=valid_edit_form())

    assert fake_db.data["meetups"]["m1"]["organizer_id"] == "org1"


def test_cancel_meetup_does_not_delete_meetup_document(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status="active")}}))
    login_as(client, role="organizer", user_id="org1")

    client.post("/meetup/m1/cancel")

    assert "m1" in fake_db.data["meetups"]
    assert fake_db.data["meetups"]["m1"]["status"] == "cancelled"


def test_meetup_participants_updates_joined_count_based_on_visible_participants(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(capacity=5, joined_count=10, participant_ids=["p1", "p2"]),
            },
            "rsvps": {},
            "users": {
                "p1": participant_user("Alice"),
                "p2": participant_user("Bob"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    client.get("/meetup/m1/participants")

    meetup = captured_templates[-1]["context"]["meetup"]
    assert meetup["joined_count"] == 2
    assert meetup["available_slots"] == 3


# =========================================================
# Additional comprehensive tests for Sprint 3 coverage
# =========================================================

@pytest.mark.parametrize(
    "field_name, invalid_value, expected_keyword",
    [
        ("sport_type", "", "sport"),
        ("capacity", "", "capacity"),
        ("meetup_date", "", "date"),
        ("meetup_time", "", "time"),
        ("state", "", "state"),
        ("venue_name", "", "venue"),
        ("address", "", "address"),
    ],
)
def test_scrum_194_validate_edit_meetup_rejects_missing_required_fields(field_name, invalid_value, expected_keyword):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(**{field_name: invalid_value}))
    assert any(expected_keyword in error.lower() for error in errors)


@pytest.mark.parametrize("capacity", ["1", "2", "50", "99", "100"])
def test_scrum_194_validate_edit_meetup_accepts_valid_capacity_boundaries(capacity):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(capacity=capacity))
    assert errors == []


@pytest.mark.parametrize("postcode", ["", "10000", "11500", "47800", "81100"])
def test_scrum_194_validate_edit_meetup_accepts_empty_or_valid_postcode(postcode):
    errors = flask_module.validate_edit_meetup_form(valid_edit_form(postcode=postcode))
    assert errors == []


@pytest.mark.parametrize(
    "meetup_date, meetup_time",
    [
        ("not-a-date", "18:30"),
        ("2026/08/18", "18:30"),
        ("2026-13-18", "18:30"),
        (future_date(5), "not-a-time"),
        (future_date(5), "25:00"),
        (future_date(5), "18:99"),
    ],
)
def test_scrum_194_validate_edit_meetup_rejects_invalid_datetime_format(meetup_date, meetup_time):
    errors = flask_module.validate_edit_meetup_form(
        valid_edit_form(meetup_date=meetup_date, meetup_time=meetup_time)
    )
    assert any("date" in error.lower() or "time" in error.lower() or "format" in error.lower() for error in errors)


@pytest.mark.parametrize(
    "keyword, expected_ids",
    [
        ("badminton", ["m1"]),
        ("BADMINTON", ["m1"]),
        ("penang sports", ["m1"]),
        ("football", ["m2"]),
        ("selangor field", ["m2"]),
        (future_date(5), ["m1"]),
        (future_date(6), ["m2"]),
    ],
)
def test_scrum_230_keyword_search_supports_case_and_multiple_terms(client, captured_templates, monkeypatch, keyword, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string=keyword_query(keyword))

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


@pytest.mark.parametrize(
    "query_string, expected_ids",
    [
        ({"state": "Penang", "sport_type": "Badminton"}, ["m1"]),
        ({"state": "Selangor", "sport_type": "Football"}, ["m2"]),
        ({"state": "Penang", "sport_type": "Football"}, []),
        ({"state": "Selangor", "meetup_date": future_date(6)}, ["m2"]),
        ({"state": "Penang", "meetup_date": future_date(5)}, ["m1"]),
        ({"sport_type": "Badminton", "meetup_date": future_date(5)}, ["m1"]),
        ({"sport_type": "Football", "meetup_date": future_date(6)}, ["m2"]),
        ({"sport_type": "Badminton", "meetup_date": future_date(6)}, []),
    ],
)
def test_active_meetups_combined_filter_matrix(client, captured_templates, monkeypatch, query_string, expected_ids):
    patch_db(monkeypatch, fake_db_with_meetups())

    response = client.get("/active-meetups", query_string=query_string)

    assert response.status_code == 200
    meetups = captured_templates[-1]["context"]["meetups"]
    assert [meetup["id"] for meetup in meetups] == expected_ids


@pytest.mark.parametrize(
    "capacity, joined_count, expected_slots, expected_full",
    [
        (1, 0, 1, False),
        (1, 1, 0, True),
        (2, 1, 1, False),
        (20, 19, 1, False),
        (20, 20, 0, True),
        (20, 21, 0, True),
    ],
)
def test_scrum_461_active_meetups_full_status_boundaries(client, captured_templates, monkeypatch, capacity, joined_count, expected_slots, expected_full):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(
                    capacity=capacity,
                    joined_count=joined_count,
                    meetup_date=future_date(5),
                    meetup_time="18:00",
                )
            },
            "rsvps": {},
            "users": {},
        }
    )
    patch_db(monkeypatch, fake_db)

    response = client.get("/active-meetups")

    assert response.status_code == 200
    meetup = captured_templates[-1]["context"]["meetups"][0]
    assert meetup["available_slots"] == expected_slots
    assert meetup["is_full"] is expected_full


@pytest.mark.parametrize("status", ["cancelled", "past", "completed", "deleted", "draft"])
def test_scrum_461_active_meetups_excludes_non_active_statuses(client, captured_templates, monkeypatch, status):
    fake_db = FakeDB(
        {
            "meetups": {
                "m1": base_meetup(status=status, meetup_date=future_date(5)),
                "m2": base_meetup(status="active", meetup_date=future_date(6)),
            },
            "rsvps": {},
            "users": {},
        }
    )
    patch_db(monkeypatch, fake_db)

    response = client.get("/active-meetups")

    assert response.status_code == 200
    meetup_ids = [meetup["id"] for meetup in captured_templates[-1]["context"]["meetups"]]
    assert "m1" not in meetup_ids
    assert "m2" in meetup_ids


@pytest.mark.parametrize("new_sport", ["Badminton", "Football", "Basketball"])
def test_scrum_194_edit_meetup_updates_sport_type(client, monkeypatch, new_sport):
    if new_sport not in getattr(flask_module, "ALLOWED_SPORTS", []):
        pytest.skip(f"{new_sport} is not listed in ALLOWED_SPORTS.")

    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/edit", data=valid_edit_form(sport_type=new_sport))

    assert response.status_code in [302, 303]
    assert fake_db.data["meetups"]["m1"]["sport_type"] == new_sport


@pytest.mark.parametrize("new_capacity, joined_count, expected_slots", [
    ("5", 2, 3),
    ("10", 2, 8),
    ("20", 5, 15),
    ("3", 5, 0),
])
def test_scrum_194_edit_meetup_recalculates_available_slots(client, monkeypatch, new_capacity, joined_count, expected_slots):
    fake_db = patch_db(
        monkeypatch,
        FakeDB({"meetups": {"m1": base_meetup(organizer_id="org1", joined_count=joined_count)}}),
    )
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/edit", data=valid_edit_form(capacity=new_capacity))

    assert response.status_code in [302, 303]
    assert fake_db.data["meetups"]["m1"]["capacity"] == int(new_capacity)
    assert fake_db.data["meetups"]["m1"]["available_slots"] == expected_slots


@pytest.mark.parametrize("reason", ["", "Weather issue", "Venue unavailable", "Organizer emergency"])
def test_scrum_203_cancel_meetup_saves_reason_variants(client, monkeypatch, reason):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup(status="active", organizer_id="org1")}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/meetup/m1/cancel", data={"cancellation_reason": reason})

    assert response.status_code in [302, 303]
    meetup = fake_db.data["meetups"]["m1"]
    assert meetup["status"] == "cancelled"
    assert meetup["cancellation_reason"] == reason


@pytest.mark.parametrize("rsvp_status", ["confirmed", "active", "joined", ""])
def test_scrum_212_meetup_participants_includes_allowed_rsvp_statuses(client, captured_templates, monkeypatch, rsvp_status):
    fake_db = FakeDB(
        {
            "meetups": {"m1": base_meetup(organizer_id="org1", participant_ids=[])},
            "rsvps": {
                "r1": {"meetup_id": "m1", "participant_id": "p1", "status": rsvp_status},
            },
            "users": {
                "p1": participant_user("Alice"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    participants = captured_templates[-1]["context"]["participants"]
    assert [participant["user_id"] for participant in participants] == ["p1"]


@pytest.mark.parametrize("rsvp_status", ["cancelled", "withdrawn", "removed"])
def test_scrum_212_meetup_participants_excludes_removed_rsvp_statuses(client, captured_templates, monkeypatch, rsvp_status):
    fake_db = FakeDB(
        {
            "meetups": {"m1": base_meetup(organizer_id="org1", participant_ids=[])},
            "rsvps": {
                "r1": {"meetup_id": "m1", "participant_id": "p1", "status": rsvp_status},
            },
            "users": {
                "p1": participant_user("Alice"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    assert captured_templates[-1]["context"]["participants"] == []


def test_scrum_212_meetup_participants_removes_duplicate_participant_sources(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "meetups": {"m1": base_meetup(organizer_id="org1", participant_ids=["p1", "p1"])},
            "rsvps": {
                "r1": {"meetup_id": "m1", "participant_id": "p1", "status": "confirmed"},
            },
            "users": {
                "p1": participant_user("Alice"),
            },
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="organizer", user_id="org1")

    response = client.get("/meetup/m1/participants")

    assert response.status_code == 200
    participants = captured_templates[-1]["context"]["participants"]
    assert len(participants) == 1
    assert participants[0]["user_id"] == "p1"


@pytest.mark.parametrize(
    "role, user_id, expected_status",
    [
        ("participant", "p1", 302),
        ("organizer", "org2", 302),
        ("organizer", "org1", 200),
        ("admin", "admin1", 200),
    ],
)
def test_route_access_matrix_for_meetup_participant_list(client, captured_templates, monkeypatch, role, user_id, expected_status):
    fake_db = FakeDB(
        {
            "meetups": {"m1": base_meetup(organizer_id="org1", participant_ids=["p1"])},
            "rsvps": {},
            "users": {"p1": participant_user("Alice")},
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role=role, user_id=user_id)

    response = client.get("/meetup/m1/participants")

    assert response.status_code == expected_status
