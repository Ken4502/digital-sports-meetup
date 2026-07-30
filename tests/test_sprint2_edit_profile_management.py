"""
Sprint 3 Pytest Test Suite: Edit Profile and User Management
Smart Sports Meetup and Community Management Platform

This test file covers user stories related to editing user information:
- Participant: Edit own profile details and change password.
- Organizer: Edit own profile details and change password.
- Admin: Edit a user's details (email, phone).
- All Users: Delete their own account.

The tests are designed for CI/CD pipelines, using a fake Firestore database
to ensure isolated and repeatable test runs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

# -----------------------------------------------------------------------------
# Import the Flask app from the project root.
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app as flask_module
from tests.test_sprint2_user_management_100plus import (
    FakeFirestoreDB,
    assert_private_data_hidden,
    page_text,
    set_logged_in_session,
)

# -----------------------------------------------------------------------------
# Pytest fixtures and helpers
# -----------------------------------------------------------------------------


@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestoreDB:
    """Sets up a fake Firestore database for testing."""
    db = FakeFirestoreDB()
    monkeypatch.setattr(flask_module, "db", db, raising=False)
    monkeypatch.setattr(flask_module, "firebase_error_message", "", raising=False)
    flask_module.app.config.update(
        TESTING=True, WTF_CSRF_ENABLED=False, SECRET_KEY="test-secret"
    )
    return db


@pytest.fixture()
def client(fake_db: FakeFirestoreDB):
    """Provides a test client for the Flask application."""
    with flask_module.app.test_client() as test_client:
        yield test_client


def seed_test_users(db: FakeFirestoreDB):
    """Seeds the fake database with a standard set of users for testing."""
    db.seed_user(
        "participant_test",
        role="participant",
        full_name="Participant User",
        email="participant@example.com",
        phone="0121112222",
        phone_clean="0121112222",
        password_hash=generate_password_hash("Participant123!"),
        sport_interest="Badminton",
        skill_level="Beginner",
    )
    db.seed_user(
        "organizer_test",
        role="organizer",
        full_name="Organizer User",
        email="organizer@example.com",
        phone="0133334444",
        phone_clean="0133334444",
        password_hash=generate_password_hash("Organizer123!"),
        organization_name="Org Club",
        experience_years=2,
    )
    db.seed_user(
        "admin_test",
        role="admin",
        full_name="Admin User",
        email="admin@example.com",
        phone="0199998888",
        phone_clean="0199998888",
        password_hash=generate_password_hash("Admin123!"),
    )
    db.seed_user(
        "other_user",
        role="participant",
        full_name="Other User",
        email="other@example.com",
        phone="0177778888",
        phone_clean="0177778888",
    )


def get_valid_edit_form(user_type: str) -> Dict[str, Any]:
    """Returns a dictionary of valid form data for editing a profile."""
    if user_type == "participant":
        return {
            "full_name": "Participant Updated",
            "email": "participant.updated@example.com",
            "phone": "0129998888",
            "bio": "Updated bio for participant.",
            "sport_interest": "Football",
            "current_password": "",
            "new_password": "",
            "confirm_new_password": "",
        }
    if user_type == "organizer":
        return {
            "full_name": "Organizer Updated",
            "email": "organizer.updated@example.com",
            "phone": "0137776666",
            "bio": "Updated bio for organizer.",
            "current_password": "",
            "new_password": "",
            "confirm_new_password": "",
        }
    return {}


# -----------------------------------------------------------------------------
# Participant Edit Profile Tests
# -----------------------------------------------------------------------------


def test_participant_can_successfully_edit_profile(client, fake_db):
    """A participant can update their own profile with valid data."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "participant_test", "participant")

    form_data = get_valid_edit_form("participant")
    response = client.post("/profile/edit", data=form_data, follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Profile updated successfully." in html
    assert "Participant Updated" in html
    assert "participant.updated@example.com" in html
    assert "0129998888" in html
    assert "Football" in html

    updated_user = fake_db.get_user("participant_test")
    assert updated_user["full_name"] == "Participant Updated"
    assert updated_user["phone_clean"] == "0129998888"


def test_participant_can_change_password(client, fake_db):
    """A participant can change their password with the correct current password."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "participant_test", "participant")

    form_data = get_valid_edit_form("participant")
    form_data.update({
        "current_password": "Participant123!",
        "new_password": "NewPassword456$",
        "confirm_new_password": "NewPassword456$",
    })

    response = client.post("/profile/edit", data=form_data, follow_redirects=True)
    assert "Profile updated successfully." in page_text(response)

    updated_user = fake_db.get_user("participant_test")
    assert check_password_hash(updated_user["password_hash"], "NewPassword456$")
    assert not check_password_hash(updated_user["password_hash"], "Participant123!")


@pytest.mark.parametrize(
    "field, value, error_message",
    [
        ("full_name", "A", "Full name must be at least 3 characters."),
        ("email", "invalid-email", "Please enter a valid email address."),
        ("email", "other@example.com", "This email is already registered by another user."),
        ("phone", "123", "Phone number must be 10 to 11 digits."),
        ("phone", "0177778888", "This phone number is already registered by another user."),
        ("new_password", "short", "New password must be at least 8 characters"),
    ],
)
def test_participant_edit_profile_invalid_data_is_rejected(
    client, fake_db, field, value, error_message
):
    """The system rejects invalid data when a participant edits their profile."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "participant_test", "participant")

    form_data = get_valid_edit_form("participant")
    form_data[field] = value
    # If testing password, need to provide all password fields
    if "password" in field:
        form_data["new_password"] = form_data.get("new_password", "NewPassword456$")
        form_data["confirm_new_password"] = form_data.get("new_password")

    response = client.post("/profile/edit", data=form_data, follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert error_message in html


# -----------------------------------------------------------------------------
# Organizer Edit Profile Tests
# -----------------------------------------------------------------------------


def test_organizer_can_successfully_edit_profile(client, fake_db):
    """An organizer can update their own profile with valid data."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "organizer_test", "organizer")

    form_data = get_valid_edit_form("organizer")
    response = client.post("/profile/edit", data=form_data, follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Profile updated successfully." in html
    assert "Organizer Updated" in html
    assert "organizer.updated@example.com" in html
    assert "0137776666" in html

    updated_user = fake_db.get_user("organizer_test")
    assert updated_user["full_name"] == "Organizer Updated"
    assert updated_user["phone_clean"] == "0137776666"


def test_organizer_edit_profile_invalid_data_is_rejected(client, fake_db):
    """The system rejects invalid data when an organizer edits their profile."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "organizer_test", "organizer")

    form_data = get_valid_edit_form("organizer")
    form_data["email"] = "other@example.com"  # Duplicate email

    response = client.post("/profile/edit", data=form_data, follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "This email is already registered by another user." in html


# -----------------------------------------------------------------------------
# Admin Edit User Tests
# -----------------------------------------------------------------------------


def test_admin_can_edit_user_details(client, fake_db):
    """An admin can successfully edit a user's email and phone."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "admin_test", "admin")

    target_user_id = "participant_test"
    form_data = {"email": "admin.edited@example.com", "phone": "0191234567"}

    response = client.post(
        f"/admin/edit-user/{target_user_id}", data=form_data, follow_redirects=True
    )
    html = page_text(response)

    assert response.status_code == 200
    assert "User details updated successfully." in html
    assert "admin.edited@example.com" in html
    assert "0191234567" in html

    updated_user = fake_db.get_user(target_user_id)
    assert updated_user["email"] == "admin.edited@example.com"
    assert updated_user["phone_clean"] == "0191234567"


@pytest.mark.parametrize(
    "role_to_block",
    [
        ("participant", "participant_test"),
        ("organizer", "organizer_test"),
    ],
)
def test_non_admins_cannot_access_admin_edit_user(client, fake_db, role_to_block):
    """Only admins can access the admin edit user functionality."""
    seed_test_users(fake_db)
    role, user_id = role_to_block
    set_logged_in_session(client, user_id, role)

    target_user_id = "other_user"
    form_data = {"email": "hacker@example.com", "phone": "0111111111"}

    response = client.post(
        f"/admin/edit-user/{target_user_id}", data=form_data, follow_redirects=True
    )
    html = page_text(response)

    assert response.status_code == 200
    assert "You do not have permission" in html
    original_user = fake_db.get_user(target_user_id)
    assert original_user["email"] == "other@example.com"


def test_admin_edit_user_invalid_data_is_rejected(client, fake_db):
    """Admin edit is rejected if the new email or phone is already taken."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "admin_test", "admin")

    target_user_id = "participant_test"
    form_data = {"email": "other@example.com", "phone": "0121112222"}

    response = client.post(
        f"/admin/edit-user/{target_user_id}", data=form_data, follow_redirects=True
    )
    html = page_text(response)

    assert response.status_code == 200
    assert "This email is already registered by another user." in html


# -----------------------------------------------------------------------------
# Delete Account Tests
# -----------------------------------------------------------------------------


def test_user_can_delete_own_account(client, fake_db):
    """A logged-in user can permanently delete their own account."""
    seed_test_users(fake_db)
    set_logged_in_session(client, "participant_test", "participant")

    assert "participant_test" in fake_db.all_users()

    response = client.post("/profile/delete", follow_redirects=True)
    html = page_text(response)

    assert response.status_code == 200
    assert "Your account has been permanently deleted." in html
    assert "participant_test" not in fake_db.all_users()

    # Check that session is cleared
    with client.session_transaction() as session:
        assert "user_id" not in session