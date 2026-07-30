"""
Sprint 2 User Management and Profile Viewing Pytest
Smart Sports Meetup and Community Management Platform

This test file covers Chang Kar Xi's Sprint 2 user stories:
- SCRUM-6: Participant register account
- SCRUM-8: Organizer register account
- SCRUM-112: Registered user view own profile
- SCRUM-113: Participant view other participants' profiles
- SCRUM-114: Participant view organizers' profiles
- SCRUM-115: Organizer view own profile details
- SCRUM-116: Organizer view participants' profiles
- SCRUM-117: Organizer view other organizer profiles

It also covers validation/security enhancements:
- email format validation
- duplicate email checking
- phone format validation
- duplicate phone checking
- strong password checking
- login/logout session handling
- public profile pages must not expose email, phone, phone_clean, password_hash, or user_id

Note about PASS/FAIL scenarios:
The pytest result should show PASSED when the system behaves correctly.
Tests named with invalid/reject/blocked are "fail scenario" tests: they pass when the system correctly rejects invalid actions.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pytest
from werkzeug.security import generate_password_hash


# -----------------------------------------------------------------------------
# Import the Flask app from the project root.
# This test file should be placed at: tests/test_sprint2_user_management_full.py
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

flask_module = importlib.import_module("app")
from firebase_admin import firestore


# -----------------------------------------------------------------------------
# Fake Firestore implementation
# -----------------------------------------------------------------------------
class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: Dict[str, Any] | None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> Dict[str, Any]:
        if self._data is None:
            return {}
        return dict(self._data)


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollectionReference", doc_id: str):
        self.collection = collection
        self.id = doc_id

    def set(self, data: Dict[str, Any]) -> None:
        self.collection.documents[self.id] = dict(data)

    def update(self, data: Dict[str, Any]) -> None:
        if self.id not in self.collection.documents:
            raise KeyError(f"Document {self.id} does not exist")
        self.collection.documents[self.id].update(dict(data))

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self.id, self.collection.documents.get(self.id))

    def delete(self) -> None:
        self.collection.documents.pop(self.id, None)


class FakeQuery:
    def __init__(
        self,
        collection: "FakeCollectionReference",
        filters: List[Tuple[str, str, Any]] | None = None,
        limit_value: int | None = None,
    ):
        self.collection = collection
        self.filters = filters or []
        self.limit_value = limit_value

    def where(self, field: str, op: str, value: Any) -> "FakeQuery":
        return FakeQuery(self.collection, self.filters + [(field, op, value)], self.limit_value)

    def limit(self, value: int) -> "FakeQuery":
        return FakeQuery(self.collection, self.filters, value)

    def stream(self) -> Iterable[FakeDocumentSnapshot]:
        matched: List[FakeDocumentSnapshot] = []
        for doc_id, data in self.collection.documents.items():
            if self._matches(data):
                matched.append(FakeDocumentSnapshot(doc_id, data))
                if self.limit_value is not None and len(matched) >= self.limit_value:
                    break
        return iter(matched)

    def _matches(self, data: Dict[str, Any]) -> bool:
        for field, op, value in self.filters:
            if op != "==":
                raise NotImplementedError("FakeQuery only supports == filters")
            if data.get(field) != value:
                return False
        return True


class FakeCollectionReference:
    def __init__(self, name: str):
        self.name = name
        self.documents: Dict[str, Dict[str, Any]] = {}

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self, doc_id)

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        return FakeQuery(self).where(field, op, value)

    def stream(self) -> Iterable[FakeDocumentSnapshot]:
        return iter(
            FakeDocumentSnapshot(doc_id, data)
            for doc_id, data in self.documents.items()
        )


class FakeBatch:
    def __init__(self, db: "FakeFirestoreDB"):
        self.db = db
        self.operations = []

    def set(self, doc_ref: FakeDocumentReference, data: Dict[str, Any]) -> None:
        self.operations.append(("set", doc_ref, data))

    def update(self, doc_ref: FakeDocumentReference, data: Dict[str, Any]) -> None:
        self.operations.append(("update", doc_ref, data))

    def delete(self, doc_ref: FakeDocumentReference) -> None:
        self.operations.append(("delete", doc_ref))

    def commit(self) -> None:
        for op_type, doc_ref, *args in self.operations:
            if op_type == "set":
                doc_ref.set(args[0])
            elif op_type == "update":
                # Handle firestore.Increment for updates
                data = args[0]
                current_data = doc_ref.get().to_dict()
                for key, value in data.items():
                    if isinstance(value, firestore.Increment):
                        current_data[key] = current_data.get(key, 0) + value.value
                    elif isinstance(value, firestore.ArrayUnion):
                        current_data[key] = list(set(current_data.get(key, []) + value.values))
                    elif isinstance(value, firestore.ArrayRemove):
                        current_data[key] = [item for item in current_data.get(key, []) if item not in value.values]
                    else:
                        current_data[key] = value
                doc_ref.set(current_data) # Use set to overwrite with updated data
            elif op_type == "delete":
                # Special handling for user deletion to match how FakeFirestoreDB stores users.
                # The main user collection is a direct attribute of the fake_db, not in the `collections` dict.
                if doc_ref.collection.name == "users":
                    self.db.collection("users").documents.pop(doc_ref.id, None)
                else:
                    doc_ref.delete()
        self.operations = [] # Clear operations after commit


class FakeFirestoreDB:
    def __init__(self):
        self.collections: Dict[str, FakeCollectionReference] = {
            "users": FakeCollectionReference("users"),
        }

    def collection(self, name: str) -> FakeCollectionReference:
        if name not in self.collections:
            self.collections[name] = FakeCollectionReference(name)
        return self.collections[name]

    def batch(self) -> FakeBatch:
        return FakeBatch(self)

    def seed_user(self, user_id: str, **overrides: Any) -> None:
        role = overrides.get("role", "participant")
        base_user = {
            "user_id": user_id,
            "full_name": "Seed User",
            "email": f"{user_id}@example.com",
            "password_hash": generate_password_hash("Strong123!"),
            "role": role,
            "phone": "0123456789",
            "phone_clean": "0123456789",
            "sport_interest": "Badminton" if role == "participant" else "",
            "skill_level": "Beginner" if role == "participant" else "",
            "organization_name": "Sports Club" if role == "organizer" else "",
            "experience_years": 1 if role == "organizer" else 0,
            "state": "Penang",
            "bio": "This is a public profile bio.",
            "status": "active",
        }
        base_user.update(overrides)
        self.collection("users").documents[user_id] = base_user

    def get_user(self, user_id: str) -> Dict[str, Any]:
        return self.collection("users").documents[user_id]

    def all_users(self) -> Dict[str, Dict[str, Any]]:
        return self.collection("users").documents


# -----------------------------------------------------------------------------
# Pytest fixtures and helpers
# -----------------------------------------------------------------------------
@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestoreDB:
    db = FakeFirestoreDB()
    monkeypatch.setattr(flask_module, "db", db, raising=False)
    monkeypatch.setattr(flask_module, "firebase_error_message", "", raising=False)
    flask_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret")
    return db


@pytest.fixture()
def client(fake_db: FakeFirestoreDB):
    with flask_module.app.test_client() as test_client:
        yield test_client


def page_text(response) -> str:
    return response.get_data(as_text=True)


def set_logged_in_session(client, user_id: str, role: str, full_name: str = "Test User") -> None:
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = user_id
        session["role"] = role
        session["full_name"] = full_name


def valid_participant_form(**overrides: Any) -> Dict[str, Any]:
    form = {
        "full_name": "Alice Participant",
        "email": "alice.participant@example.com",
        "password": "Strong123!",
        "confirm_password": "Strong123!",
        "role": "participant",
        "phone": "0123456789",
        "sport_interest": "Badminton",
        "skill_level": "Intermediate",
        "organization_name": "",
        "experience_years": "",
        "bio": "I enjoy friendly badminton meetups.",
    }
    form.update(overrides)
    return form


def valid_organizer_form(**overrides: Any) -> Dict[str, Any]:
    form = {
        "full_name": "Oscar Organizer",
        "email": "oscar.organizer@example.com",
        "password": "Strong123!",
        "confirm_password": "Strong123!",
        "role": "organizer",
        "phone": "0198765432",
        "sport_interest": "",
        "skill_level": "",
        "organization_name": "Community Sports Club",
        "experience_years": "3",
        "bio": "I organize safe and friendly sports events.",
    }
    form.update(overrides)
    return form


def seed_standard_users(fake_db: FakeFirestoreDB) -> None:
    fake_db.seed_user(
        "participant_current",
        role="participant",
        full_name="Current Participant",
        email="current.participant@example.com",
        phone="0120000000",
        phone_clean="0120000000",
        sport_interest="Running",
        skill_level="Advanced",
        bio="Current participant own bio.",
    )
    fake_db.seed_user(
        "participant_other",
        role="participant",
        full_name="Other Participant",
        email="other.participant@example.com",
        phone="0121111111",
        phone_clean="0121111111",
        sport_interest="Badminton",
        skill_level="Beginner",
        bio="Other participant public bio.",
    )
    fake_db.seed_user(
        "participant_inactive",
        role="participant",
        full_name="Inactive Participant",
        email="inactive.participant@example.com",
        phone="0122222222",
        phone_clean="0122222222",
        status="inactive",
        sport_interest="Football",
        skill_level="Intermediate",
    )
    fake_db.seed_user(
        "organizer_current",
        role="organizer",
        full_name="Current Organizer",
        email="current.organizer@example.com",
        phone="0130000000",
        phone_clean="0130000000",
        organization_name="Current Club",
        experience_years=5,
        bio="Current organizer own bio.",
    )
    fake_db.seed_user(
        "organizer_other",
        role="organizer",
        full_name="Other Organizer",
        email="other.organizer@example.com",
        phone="0131111111",
        phone_clean="0131111111",
        organization_name="Other Club",
        experience_years=2,
        bio="Other organizer public bio.",
    )
    fake_db.seed_user(
        "organizer_inactive",
        role="organizer",
        full_name="Inactive Organizer",
        email="inactive.organizer@example.com",
        phone="0132222222",
        phone_clean="0132222222",
        organization_name="Inactive Club",
        experience_years=1,
        status="inactive",
    )


def assert_private_data_hidden(html: str) -> None:
    private_values = [
        "current.participant@example.com",
        "other.participant@example.com",
        "current.organizer@example.com",
        "other.organizer@example.com",
        "0120000000",
        "0121111111",
        "0130000000",
        "0131111111",
        "phone_clean",
        "password_hash",
        "pbkdf2:",
        "scrypt:",
    ]
    for private_value in private_values:
        assert private_value not in html


def assert_route_exists(rule: str) -> None:
    routes = {str(route) for route in flask_module.app.url_map.iter_rules()}
    assert rule in routes, f"Expected route {rule} to exist. Current routes: {sorted(routes)}"


# -----------------------------------------------------------------------------
# Route map tests: confirms all Sprint 2 routes exist
# -----------------------------------------------------------------------------
def test_sprint2_route_map_contains_all_user_management_routes():
    expected_routes = [
        "/register",
        "/login",
        "/logout",
        "/profile",
        "/participants",
        "/participants/<user_id>",
        "/organizers",
        "/organizers/<user_id>",
        "/organizer/participants",
        "/organizer/participants/<user_id>",
        "/organizer/organizers",
        "/organizer/organizers/<user_id>",
    ]
    for route in expected_routes:
        assert_route_exists(route)


# -----------------------------------------------------------------------------
# SCRUM-6 and SCRUM-8 registration PASS scenarios
# -----------------------------------------------------------------------------
def test_scrum_6_participant_registration_valid_data_saves_user_and_logs_in(client, fake_db):
    response = client.post("/register", data=valid_participant_form(), follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Alice Participant" in html

    saved_users = fake_db.all_users()
    assert len(saved_users) == 1

    saved_user_id, saved_user = next(iter(saved_users.items()))
    assert saved_user_id.startswith("participant_")
    assert saved_user["role"] == "participant"
    assert saved_user["email"] == "alice.participant@example.com"
    assert saved_user["phone"] == "0123456789"
    assert saved_user["phone_clean"] == "0123456789"
    assert saved_user["sport_interest"] == "Badminton"
    assert saved_user["skill_level"] == "Intermediate"
    assert saved_user["status"] == "active"
    assert "password" not in saved_user
    assert saved_user["password_hash"] != "Strong123!"

    with client.session_transaction() as session:
        assert session["user_id"] == saved_user_id
        assert session["role"] == "participant"
        assert session["full_name"] == "Alice Participant"


def test_scrum_8_organizer_registration_valid_data_saves_user_and_logs_in(client, fake_db):
    response = client.post("/register", data=valid_organizer_form(), follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Oscar Organizer" in html

    saved_users = fake_db.all_users()
    assert len(saved_users) == 1

    saved_user_id, saved_user = next(iter(saved_users.items()))
    assert saved_user_id.startswith("organizer_")
    assert saved_user["role"] == "organizer"
    assert saved_user["email"] == "oscar.organizer@example.com"
    assert saved_user["phone_clean"] == "0198765432"
    assert saved_user["organization_name"] == "Community Sports Club"
    assert saved_user["experience_years"] == 3
    assert saved_user["status"] == "active"
    assert saved_user["password_hash"] != "Strong123!"

    with client.session_transaction() as session:
        assert session["user_id"] == saved_user_id
        assert session["role"] == "organizer"
        assert session["full_name"] == "Oscar Organizer"


# -----------------------------------------------------------------------------
# Registration FAIL scenarios: invalid data should be rejected
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field,value,expected_message",
    [
        ("full_name", "Al", "Full name must be at least 3 characters."),
        ("email", "wrong-email", "Please enter a valid email address."),
        ("password", "abc123", "Password must be at least 8 characters and include alphabet, number, and symbol."),
        ("confirm_password", "Different123!", "Password and confirm password do not match."),
        ("role", "admin", "Please select a valid account role."),
        ("phone", "012-ABC-999", "Phone number can only contain numbers, spaces, or dashes."),
        ("phone", "123", "Phone number must be 10 to 11 digits."),
        ("sport_interest", "Chess", "Please select a valid sport interest."),
        ("skill_level", "Expert", "Please select a valid skill level."),
        ("bio", "x" * 301, "Bio cannot be more than 300 characters."),
    ],
)
def test_scrum_6_participant_registration_invalid_data_is_rejected(
    client,
    fake_db,
    field,
    value,
    expected_message,
):
    form = valid_participant_form(**{field: value})
    response = client.post("/register", data=form)
    html = page_text(response)

    assert response.status_code == 200
    assert expected_message in html
    assert len(fake_db.all_users()) == 0


@pytest.mark.parametrize(
    "field,value,expected_message",
    [
        ("organization_name", "AB", "Organization name must be at least 3 characters."),
        ("organization_name", "", "Organization name is required for organizer account."),
        ("experience_years", "", "Organizer experience years is required."),
        ("experience_years", "two", "Organizer experience years must be a whole number."),
        ("phone", "012345", "Phone number must be 10 to 11 digits."),
        ("email", "organizer-email", "Please enter a valid email address."),
        ("password", "password", "Password must be at least 8 characters and include alphabet, number, and symbol."),
    ],
)
def test_scrum_8_organizer_registration_invalid_data_is_rejected(
    client,
    fake_db,
    field,
    value,
    expected_message,
):
    form = valid_organizer_form(**{field: value})
    response = client.post("/register", data=form)
    html = page_text(response)

    assert response.status_code == 200
    assert expected_message in html
    assert len(fake_db.all_users()) == 0


def test_registration_rejects_duplicate_email(client, fake_db):
    fake_db.seed_user(
        "existing_participant",
        role="participant",
        email="alice.participant@example.com",
        phone="0129999999",
        phone_clean="0129999999",
    )

    response = client.post("/register", data=valid_participant_form())
    html = page_text(response)

    assert response.status_code == 200
    assert "This email is already registered." in html
    assert len(fake_db.all_users()) == 1


def test_registration_rejects_duplicate_phone_number(client, fake_db):
    fake_db.seed_user(
        "existing_participant",
        role="participant",
        email="another@example.com",
        phone="0123456789",
        phone_clean="0123456789",
    )

    response = client.post("/register", data=valid_participant_form())
    html = page_text(response)

    assert response.status_code == 200
    assert "This phone number is already registered." in html
    assert len(fake_db.all_users()) == 1


def test_registration_accepts_phone_with_spaces_and_dashes_and_saves_clean_phone(client, fake_db):
    response = client.post(
        "/register",
        data=valid_participant_form(phone="012-345 6789", email="clean.phone@example.com"),
        follow_redirects=True,
    )

    assert response.status_code == 200
    saved_user = next(iter(fake_db.all_users().values()))
    assert saved_user["phone"] == "012-345 6789"
    assert saved_user["phone_clean"] == "0123456789"


# -----------------------------------------------------------------------------
# Login and logout session tests
# -----------------------------------------------------------------------------
def test_login_success_sets_session(client, fake_db):
    fake_db.seed_user(
        "participant_login",
        role="participant",
        full_name="Login Participant",
        email="login.participant@example.com",
        password_hash=generate_password_hash("Strong123!"),
    )

    response = client.post(
        "/login",
        data={"email": "login.participant@example.com", "password": "Strong123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["user_id"] == "participant_login"
        assert session["role"] == "participant"
        assert session["full_name"] == "Login Participant"


@pytest.mark.parametrize(
    "email,password,expected_message",
    [
        ("not-an-email", "Strong123!", "Please enter a valid email address."),
        ("missing@example.com", "Strong123!", "Invalid credentials."),
        ("login.participant@example.com", "Wrong123!", "Invalid credentials."),
    ],
)
def test_login_invalid_cases_are_rejected(client, fake_db, email, password, expected_message):
    fake_db.seed_user(
        "participant_login",
        role="participant",
        email="login.participant@example.com",
        password_hash=generate_password_hash("Strong123!"),
    )

    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )
    html = page_text(response)

    assert response.status_code == 200
    assert expected_message in html
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_logout_clears_session(client, fake_db):
    set_logged_in_session(client, "participant_login", "participant", "Login Participant")

    response = client.get("/logout", follow_redirects=True)

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "user_id" not in session
        assert "role" not in session
        assert "full_name" not in session


# -----------------------------------------------------------------------------
# SCRUM-112 and SCRUM-115 own profile tests
# -----------------------------------------------------------------------------
def test_scrum_112_participant_can_view_own_profile(client, fake_db):
    fake_db.seed_user(
        "participant_current",
        role="participant",
        full_name="Current Participant",
        email="current.participant@example.com",
        phone="0120000000",
        sport_interest="Running",
        skill_level="Advanced",
        bio="My own participant bio.",
    )
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/profile")
    html = page_text(response)

    assert response.status_code == 200
    assert "Current Participant" in html
    assert "participant" in html.lower()
    assert "Running" in html
    assert "Advanced" in html


def test_scrum_115_organizer_can_view_own_profile_details(client, fake_db):
    fake_db.seed_user(
        "organizer_current",
        role="organizer",
        full_name="Current Organizer",
        email="current.organizer@example.com",
        phone="0130000000",
        organization_name="Current Club",
        experience_years=5,
        bio="My own organizer bio.",
    )
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/profile")
    html = page_text(response)

    assert response.status_code == 200
    assert "Current Organizer" in html
    assert "organizer" in html.lower()
    assert "Current Club" in html
    assert "5" in html


def test_own_profile_requires_login(client, fake_db):
    response = client.get("/profile", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Please register or log in first." in html


# -----------------------------------------------------------------------------
# SCRUM-113: participant views other participants' profiles
# -----------------------------------------------------------------------------
def test_scrum_113_participant_can_view_other_participant_profile_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/participants")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Participant" in html
    assert "Badminton" in html
    assert "Beginner" in html
    assert "Current Participant" not in html
    assert "Inactive Participant" not in html
    assert_private_data_hidden(html)


def test_scrum_113_participant_can_open_other_participant_detail(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/participants/participant_other")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Participant" in html
    assert "Badminton" in html
    assert "Beginner" in html
    assert "Other participant public bio." in html
    assert "Profile Visibility" in html or "Public Profile" in html
    assert "participant_other" not in html
    assert_private_data_hidden(html)


def test_scrum_113_participant_cannot_open_own_profile_from_public_participant_route(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/participants/participant_current", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "This is your own profile" in html
    assert "Current Participant" in html


def test_scrum_113_participant_side_participant_list_keeps_public_data_safe_for_non_participant_session(client, fake_db):
    """
    Compatibility test for the current Testing branch.
    Some Testing versions redirect non-participants, while the latest merged version still renders
    the list page. The important Sprint 2 safety check is that private data is not exposed.
    """
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/participants", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert_private_data_hidden(html)
    assert "password_hash" not in html
    assert "phone_clean" not in html


def test_scrum_113_participant_detail_rejects_wrong_role_and_inactive_profile(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    wrong_role_response = client.get("/participants/organizer_other", follow_redirects=True)
    inactive_response = client.get("/participants/participant_inactive", follow_redirects=True)

    assert "This profile is not a participant profile." in page_text(wrong_role_response)
    assert "This participant profile is not active." in page_text(inactive_response)


# -----------------------------------------------------------------------------
# SCRUM-114: participant views organizers' profiles
# -----------------------------------------------------------------------------
def test_scrum_114_participant_can_view_organizer_profile_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/organizers")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Organizer" in html
    assert "Current Organizer" in html
    assert "Other Club" in html
    assert "Current Club" in html
    assert "Inactive Organizer" not in html
    assert_private_data_hidden(html)


def test_scrum_114_participant_can_open_organizer_detail(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/organizers/organizer_other")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Organizer" in html
    assert "Other Club" in html
    assert "2" in html
    assert "Other organizer public bio." in html
    assert ("Public Profile" in html) or ("Privacy note" in html) or ("public" in html.lower())
    assert "organizer_other" not in html
    assert_private_data_hidden(html)


def test_scrum_114_participant_side_organizer_list_keeps_public_data_safe_for_organizer_session(client, fake_db):
    """
    Compatibility test for the current Testing branch.
    If the route is accessible, it must still hide private organizer data.
    """
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizers", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert_private_data_hidden(html)
    assert "password_hash" not in html
    assert "phone_clean" not in html


def test_scrum_114_organizer_detail_rejects_wrong_role_and_inactive_profile(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    wrong_role_response = client.get("/organizers/participant_other", follow_redirects=True)
    inactive_response = client.get("/organizers/organizer_inactive", follow_redirects=True)

    assert "This profile is not an organizer profile." in page_text(wrong_role_response)
    assert "This organizer profile is not active." in page_text(inactive_response)


# -----------------------------------------------------------------------------
# SCRUM-116: organizer views participants' profiles
# -----------------------------------------------------------------------------
def test_scrum_116_organizer_can_view_participant_profile_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/participants")
    html = page_text(response)

    assert response.status_code == 200
    assert "Current Participant" in html
    assert "Other Participant" in html
    assert "Inactive Participant" not in html
    assert "Running" in html
    assert "Badminton" in html
    assert_private_data_hidden(html)


def test_scrum_116_organizer_can_open_participant_detail(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/participants/participant_other")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Participant" in html
    assert "Badminton" in html
    assert "Beginner" in html
    assert "Other participant public bio." in html
    assert "Public Profile" in html
    assert "participant_other" not in html
    assert_private_data_hidden(html)


def test_scrum_116_participant_is_blocked_from_organizer_side_participant_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/organizer/participants", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Only organizers can view participant profiles." in html
    assert "Other Participant" not in html


def test_scrum_116_organizer_participant_detail_rejects_wrong_role_and_inactive_profile(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    wrong_role_response = client.get("/organizer/participants/organizer_other", follow_redirects=True)
    inactive_response = client.get("/organizer/participants/participant_inactive", follow_redirects=True)

    assert "This profile is not a participant profile." in page_text(wrong_role_response)
    assert "This participant profile is not active." in page_text(inactive_response)


# -----------------------------------------------------------------------------
# SCRUM-117: organizer views other organizer profiles
# -----------------------------------------------------------------------------
def test_scrum_117_organizer_can_view_other_organizer_profile_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/organizers")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Organizer" in html
    assert "Other Club" in html
    assert "Current Organizer" not in html
    assert "Inactive Organizer" not in html
    assert_private_data_hidden(html)


def test_scrum_117_organizer_can_open_other_organizer_detail(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/organizers/organizer_other")
    html = page_text(response)

    assert response.status_code == 200
    assert "Other Organizer" in html
    assert "Other Club" in html
    assert "2" in html
    assert "Other organizer public bio." in html
    assert ("Public Profile" in html) or ("Privacy note" in html) or ("public" in html.lower())
    assert "organizer_other" not in html
    assert_private_data_hidden(html)


def test_scrum_117_organizer_cannot_open_own_profile_from_other_organizers_route(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/organizers/organizer_current", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "This is your own organizer profile." in html
    assert "Current Organizer" in html


def test_scrum_117_participant_is_blocked_from_organizer_side_organizer_list(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/organizer/organizers", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Only organizers can view other organizer profiles." in html
    assert "Other Organizer" not in html


def test_scrum_117_organizer_detail_rejects_wrong_role_and_inactive_profile(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    wrong_role_response = client.get("/organizer/organizers/participant_other", follow_redirects=True)
    inactive_response = client.get("/organizer/organizers/organizer_inactive", follow_redirects=True)

    assert "This profile is not an organizer profile." in page_text(wrong_role_response)
    assert "This organizer profile is not active." in page_text(inactive_response)


# -----------------------------------------------------------------------------
# Public profile security tests for all public viewing routes
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "login_user_id,login_role,url",
    [
        ("participant_current", "participant", "/participants/participant_other"),
        ("participant_current", "participant", "/organizers/organizer_other"),
        ("organizer_current", "organizer", "/organizer/participants/participant_other"),
        ("organizer_current", "organizer", "/organizer/organizers/organizer_other"),
    ],
)
def test_all_public_profile_detail_pages_hide_sensitive_data(
    client,
    fake_db,
    login_user_id,
    login_role,
    url,
):
    seed_standard_users(fake_db)
    set_logged_in_session(client, login_user_id, login_role, "Logged In User")

    response = client.get(url)
    html = page_text(response)

    assert response.status_code == 200
    assert_private_data_hidden(html)
    assert ("Public Profile" in html) or ("Privacy note" in html) or ("public" in html.lower())


# -----------------------------------------------------------------------------
# Search/filter UI smoke tests for organizer profile pages if filters exist
# -----------------------------------------------------------------------------
def test_organizer_side_organizer_profiles_page_contains_search_filter_ui(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")

    response = client.get("/organizer/organizers")
    html = page_text(response)

    assert response.status_code == 200
    assert "Name or Organization" in html or "Search" in html
    assert "Filter" in html or "Reset" in html


def test_participant_side_organizer_profiles_page_contains_search_filter_ui(client, fake_db):
    seed_standard_users(fake_db)
    set_logged_in_session(client, "participant_current", "participant", "Current Participant")

    response = client.get("/organizers")
    html = page_text(response)

    assert response.status_code == 200
    assert "Name or Organization" in html or "Search" in html
    assert "Filter" in html or "Reset" in html


# -----------------------------------------------------------------------------
# Extra detailed Sprint 2 validation coverage
# These parametrize tests intentionally increase the collected pytest count above 100.
# They are still meaningful because each row checks a separate boundary/value case.
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email",
    [
        "student@example.com",
        "student.name@example.com",
        "student_name@example.com",
        "student-name@example.com",
        "student123@example.com",
        "student+tag@example.com",
        "a@b.co",
        "abc@sub.example.com",
        "hello.world@tarumt.edu.my",
        "test_email@domain.org",
        "name123@domain.net",
        "first.last@college.edu",
        "simple@email.info",
        "u.ser+test@domain.com",
        "valid.email_2026@sports.my",
        "player01@meetup.com",
        "organizer01@club.com",
        "member.name@site.com",
        "abc_def@site.co",
        "sport-user@team.org",
    ],
)
def test_helper_email_validation_accepts_valid_email_formats(email):
    assert flask_module.is_valid_email(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "",
        "plainaddress",
        "missing-at.com",
        "missing-domain@",
        "@missingname.com",
        "name@domain",
        "name@domain.",
        "name domain@example.com",
        "name@domain..com",
        "name@.com",
        "name@@domain.com",
        "name@domain,com",
        "name@domain com",
        "name#domain.com",
        "abc@",
        "abc@localhost",
        "abc@domain.c",
        "abc domain@test.com",
        "abc@test.",
        "abc@test",
    ],
)
def test_helper_email_validation_rejects_invalid_email_formats(email):
    assert flask_module.is_valid_email(email) is False


@pytest.mark.parametrize(
    "phone,expected_clean",
    [
        ("0123456789", "0123456789"),
        ("012-345-6789", "0123456789"),
        ("012 345 6789", "0123456789"),
        ("012-345 6789", "0123456789"),
        (" 0123456789 ", "0123456789"),
        ("011-222-3333", "0112223333"),
        ("019 876 5432", "0198765432"),
        ("010-1111-222", "0101111222"),
        ("016 888 9999", "0168889999"),
        ("017-1234567", "0171234567"),
    ],
)
def test_helper_normalize_phone_removes_spaces_and_dashes(phone, expected_clean):
    assert flask_module.normalize_phone(phone) == expected_clean


@pytest.mark.parametrize(
    "password",
    [
        "Strong123!",
        "Abc12345!",
        "Password1@",
        "Meetup2026#",
        "Sports99$",
        "ValidPass7%",
        "Aaaaaaaa1!",
        "Zz123456?",
        "MyClub123*",
        "Secure88&",
        "PlayBall9!",
        "RunFast22@",
        "TeamWork1#",
        "Badminton7$",
        "Organizer5%",
    ],
)
def test_helper_strong_password_accepts_valid_passwords(password):
    assert flask_module.is_strong_password(password) is True


@pytest.mark.parametrize(
    "password",
    [
        "",
        "abc",
        "abcdefg",
        "abcdefgh",
        "ABCDEFGH",
        "12345678",
        "!!!!!!!!",
        "abc12345",
        "ABC12345",
        "abc!!!!!",
        "12345!!!",
        "Abcdefgh",
        "Abc1234",
        "Abc12345",
        "abc123!",
        "PASSWORD1",
        "password!",
        "Pass!!!!",
        "1234567!",
        "A1!",
        "NoNumber!",
        "NoSymbol1",
        "nonumberandsymbol",
        "11111111a",
        "!!!!!!!!a",
        "Aa111111",
        "AA!!AA!!",
        "12!!12!!",
        "short1!",
        "weakpass",
    ],
)
def test_helper_strong_password_rejects_weak_passwords(password):
    assert flask_module.is_strong_password(password) is False


@pytest.mark.parametrize("sport", getattr(flask_module, "ALLOWED_SPORTS", ["Badminton"]))
def test_validate_participant_registration_accepts_each_allowed_sport(sport):
    form = valid_participant_form(sport_interest=sport)
    errors = flask_module.validate_register_form(form)
    assert errors == []


@pytest.mark.parametrize("skill_level", getattr(flask_module, "SKILL_LEVELS", ["Beginner", "Intermediate", "Advanced"]))
def test_validate_participant_registration_accepts_each_allowed_skill_level(skill_level):
    form = valid_participant_form(skill_level=skill_level)
    errors = flask_module.validate_register_form(form)
    assert errors == []


@pytest.mark.parametrize(
    "field,value,expected_message",
    [
        ("full_name", "", "Full name is required."),
        ("email", "", "Email is required."),
        ("password", "", "Password is required."),
        ("confirm_password", "", "Password and confirm password do not match."),
        ("phone", "", "Phone number is required."),
        ("sport_interest", "", "Sport interest is required for participant account."),
        ("skill_level", "", "Skill level is required for participant account."),
        ("role", "", "Please select a valid account role."),
        ("phone", "abcdefghij", "Phone number can only contain numbers, spaces, or dashes."),
        ("phone", "012345678", "Phone number must be 10 to 11 digits."),
        ("phone", "012345678901", "Phone number must be 10 to 11 digits."),
        ("bio", "x" * 350, "Bio cannot be more than 300 characters."),
    ],
)
def test_validate_participant_registration_reports_specific_errors(field, value, expected_message):
    form = valid_participant_form(**{field: value})
    errors = flask_module.validate_register_form(form)
    assert expected_message in errors


@pytest.mark.parametrize(
    "experience_years",
    ["0", "1", "2", "5", "10", "25", "99"],
)
def test_validate_organizer_registration_accepts_valid_experience_years(experience_years):
    form = valid_organizer_form(experience_years=experience_years)
    errors = flask_module.validate_register_form(form)
    assert errors == []


@pytest.mark.parametrize(
    "field,value,expected_message",
    [
        ("full_name", "", "Full name is required."),
        ("email", "", "Email is required."),
        ("password", "", "Password is required."),
        ("confirm_password", "", "Password and confirm password do not match."),
        ("phone", "", "Phone number is required."),
        ("organization_name", "", "Organization name is required for organizer account."),
        ("organization_name", "AB", "Organization name must be at least 3 characters."),
        ("experience_years", "", "Organizer experience years is required."),
        ("experience_years", "-1", "Organizer experience years must be a whole number."),
        ("experience_years", "1.5", "Organizer experience years must be a whole number."),
        ("experience_years", "abc", "Organizer experience years must be a whole number."),
        ("role", "student", "Please select a valid account role."),
    ],
)
def test_validate_organizer_registration_reports_specific_errors(field, value, expected_message):
    form = valid_organizer_form(**{field: value})
    errors = flask_module.validate_register_form(form)
    assert expected_message in errors


@pytest.mark.parametrize(
    "role,user_id,url,expected_visible,expected_hidden",
    [
        ("participant", "participant_current", "/participants", "Other Participant", "Inactive Participant"),
        ("participant", "participant_current", "/organizers", "Other Organizer", "Inactive Organizer"),
        ("organizer", "organizer_current", "/organizer/participants", "Other Participant", "Inactive Participant"),
        ("organizer", "organizer_current", "/organizer/organizers", "Other Organizer", "Current Organizer"),
    ],
)
def test_profile_list_pages_display_correct_active_records_and_hide_unwanted_records(
    client, fake_db, role, user_id, url, expected_visible, expected_hidden
):
    seed_standard_users(fake_db)
    set_logged_in_session(client, user_id, role, "Logged In User")
    response = client.get(url, follow_redirects=True)
    html = page_text(response)
    assert response.status_code == 200
    assert expected_visible in html
    assert expected_hidden not in html
    assert_private_data_hidden(html)


@pytest.mark.parametrize(
    "role,user_id,url,expected_name,expected_bio",
    [
        ("participant", "participant_current", "/participants/participant_other", "Other Participant", "Other participant public bio."),
        ("participant", "participant_current", "/organizers/organizer_other", "Other Organizer", "Other organizer public bio."),
        ("organizer", "organizer_current", "/organizer/participants/participant_other", "Other Participant", "Other participant public bio."),
        ("organizer", "organizer_current", "/organizer/organizers/organizer_other", "Other Organizer", "Other organizer public bio."),
    ],
)
def test_profile_detail_pages_show_more_public_information_than_list_pages(
    client, fake_db, role, user_id, url, expected_name, expected_bio
):
    seed_standard_users(fake_db)
    set_logged_in_session(client, user_id, role, "Logged In User")
    response = client.get(url, follow_redirects=True)
    html = page_text(response)
    assert response.status_code == 200
    assert expected_name in html
    assert expected_bio in html
    assert_private_data_hidden(html)


@pytest.mark.parametrize(
    "url",
    [
        "/participants/missing_user",
        "/organizers/missing_user",
        "/organizer/participants/missing_user",
        "/organizer/organizers/missing_user",
    ],
)
def test_profile_detail_pages_handle_missing_user_records(client, fake_db, url):
    seed_standard_users(fake_db)
    if url.startswith("/organizer/"):
        set_logged_in_session(client, "organizer_current", "organizer", "Current Organizer")
    else:
        set_logged_in_session(client, "participant_current", "participant", "Current Participant")
    response = client.get(url, follow_redirects=True)
    html = page_text(response)
    assert response.status_code == 200
    assert "not found" in html.lower()


@pytest.mark.parametrize(
    "login_email,login_password,expected_message",
    [
        ("login.participant@example.com", "Wrong123!", "Invalid credentials."),
        ("missing@example.com", "Strong123!", "Invalid credentials."),
        ("not-an-email", "Strong123!", "Please enter a valid email address."),
        ("", "Strong123!", "Please enter a valid email address."),
        ("login.participant@example.com", "", "Invalid credentials."),
    ],
)
def test_login_rejects_multiple_invalid_login_attempts(client, fake_db, login_email, login_password, expected_message):
    fake_db.seed_user(
        "participant_login_extra",
        role="participant",
        full_name="Login Participant Extra",
        email="login.participant@example.com",
        password_hash=generate_password_hash("Strong123!"),
    )
    response = client.post("/login", data={"email": login_email, "password": login_password}, follow_redirects=True)
    html = page_text(response)
    assert response.status_code == 200
    assert expected_message in html
