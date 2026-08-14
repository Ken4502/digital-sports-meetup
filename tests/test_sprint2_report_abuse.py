"""
Pytest file covering the "Report Abuse" feature for meetups and profiles.

Save this file as:
    tests/test_report_abuse.py

Covers:
- report_meetup(meetup_id): participants/organizers reporting a meetup
- report_profile(): participants/organizers reporting a user profile

These tests use fake Firestore data. They do not need the real serviceAccountKey.json.
"""

from __future__ import annotations

from typing import Any

import pytest

import app as flask_module


# =========================================================
# Fake Firestore helpers
# (Same pattern as tests/test_sprint3_meetup_management.py,
# extended with add() support for db.collection(...).add({...}))
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

    def add(self, values: dict[str, Any]):
        collection = self.fake_db.data.setdefault(self.collection_name, {})
        new_id = f"auto_{len(collection) + 1}"
        collection[new_id] = dict(values)
        self.fake_db.add_calls.append((self.collection_name, new_id, dict(values)))
        return (None, FakeDocumentReference(self.fake_db, self.collection_name, new_id))


class FakeDB:
    def __init__(self, data: dict[str, dict[str, dict[str, Any]]] | None = None):
        self.data = data or {}
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.set_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.add_calls: list[tuple[str, str, dict[str, Any]]] = []

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


def login_as(client, role="participant", user_id="p1"):
    with client.session_transaction() as session:
        session.clear()
        session["role"] = role
        session["user_id"] = user_id
        session["name"] = f"{role.title()} User"


def set_report_target(client, target_id):
    """
    Simulates having previously loaded a profile detail page, which stores
    the viewed user's id in session["report_target_id"].
    """
    with client.session_transaction() as session:
        session["report_target_id"] = target_id


def patch_db(monkeypatch, fake_db):
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")
    return fake_db


def base_meetup(**overrides):
    data = {
        "sport_type": "Badminton",
        "title": "Badminton Meetup",
        "organizer_id": "org1",
        "status": "active",
    }
    data.update(overrides)
    return data


# =========================================================
# report_meetup(meetup_id)
# =========================================================

def test_report_meetup_requires_login(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    # No login_as() call - no role in session

    response = client.post("/meetup/m1/report", data={"reason": "Inappropriate content"})

    assert response.status_code == 403


def test_report_meetup_requires_reason(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/meetup/m1/report", data={"reason": ""})

    assert response.status_code == 302
    assert "/meetup/m1" in response.location
    assert fake_db.data.get("reports", {}) == {}


def test_report_meetup_rejects_whitespace_only_reason(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/meetup/m1/report", data={"reason": "   "})

    assert response.status_code == 302
    assert fake_db.data.get("reports", {}) == {}


def test_report_meetup_creates_report_with_correct_fields(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/meetup/m1/report", data={"reason": "Spam meetup"})

    assert response.status_code == 302
    assert "/meetup/m1" in response.location

    assert len(fake_db.add_calls) == 1
    collection_name, _doc_id, values = fake_db.add_calls[0]

    assert collection_name == "reports"
    assert values["type"] == "meetup"
    assert values["target_id"] == "m1"
    assert values["reported_by"] == "p1"
    assert values["reporter_role"] == "participant"
    assert values["reason"] == "Spam meetup"
    assert values["status"] == "pending"


def test_report_meetup_allows_organizer_role_too(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="organizer", user_id="org2")

    response = client.post("/meetup/m1/report", data={"reason": "Fraudulent listing"})

    assert response.status_code == 302
    assert len(fake_db.add_calls) == 1
    _collection_name, _doc_id, values = fake_db.add_calls[0]
    assert values["reporter_role"] == "organizer"
    assert values["reported_by"] == "org2"


def test_report_meetup_redirects_to_meetup_detail_on_success(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/meetup/m1/report", data={"reason": "Valid reason"})

    assert response.status_code == 302
    assert response.location.endswith("/meetup/m1") or "/meetup/m1" in response.location


def test_report_meetup_trims_whitespace_from_reason(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"meetups": {"m1": base_meetup()}}))
    login_as(client, role="participant", user_id="p1")

    client.post("/meetup/m1/report", data={"reason": "   Needs review   "})

    _collection_name, _doc_id, values = fake_db.add_calls[0]
    assert values["reason"] == "Needs review"


# =========================================================
# report_profile()
# =========================================================

def test_report_profile_requires_login(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({}))
    # No login_as() call - no role in session

    response = client.post("/profile/report", data={"reason": "Fake profile"})

    assert response.status_code == 403


def test_report_profile_requires_target_in_session(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({}))
    login_as(client, role="participant", user_id="p1")
    # Deliberately not calling set_report_target()

    response = client.post("/profile/report", data={"reason": "Fake profile"})

    assert response.status_code == 302
    assert fake_db.data.get("reports", {}) == {}


def test_report_profile_requires_reason(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({}))
    login_as(client, role="participant", user_id="p1")
    set_report_target(client, "participant_other")

    response = client.post("/profile/report", data={"reason": ""})

    assert response.status_code == 302
    assert fake_db.data.get("reports", {}) == {}


def test_report_profile_creates_report_with_correct_fields(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({}))
    login_as(client, role="participant", user_id="p1")
    set_report_target(client, "participant_other")

    response = client.post("/profile/report", data={"reason": "Offensive bio"})

    assert response.status_code == 302
    assert len(fake_db.add_calls) == 1
    collection_name, _doc_id, values = fake_db.add_calls[0]

    assert collection_name == "reports"
    assert values["type"] == "profile"
    assert values["target_id"] == "participant_other"
    assert values["reported_by"] == "p1"
    assert values["reporter_role"] == "participant"
    assert values["reason"] == "Offensive bio"
    assert values["status"] == "pending"


def test_report_profile_allows_organizer_reporting_participant(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({}))
    login_as(client, role="organizer", user_id="org1")
    set_report_target(client, "participant_other")

    response = client.post("/profile/report", data={"reason": "Suspicious activity"})

    assert response.status_code == 302
    _collection_name, _doc_id, values = fake_db.add_calls[0]
    assert values["reporter_role"] == "organizer"
    assert values["reported_by"] == "org1"
    assert values["target_id"] == "participant_other"


def test_report_profile_never_exposes_target_id_in_url_or_form_action(client, monkeypatch):
    """
    Regression test: the report form must not accept user_id via the URL,
    since that previously leaked the target's internal id into rendered HTML.
    """
    patch_db(monkeypatch, FakeDB({}))
    login_as(client, role="participant", user_id="p1")
    set_report_target(client, "participant_other")

    # The route should not accept a user_id path segment at all.
    response = client.post("/profile/participant_other/report", data={"reason": "test"})

    assert response.status_code == 404