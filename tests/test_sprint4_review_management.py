"""
Sprint 4 Pytest Test Suite: Admin Review Management
Smart Sports Meetup and Community Management Platform

This test file covers user stories related to an admin's ability to manage player reviews:
- Admin can view a list of all reviews.
- Admin can search for reviews using keywords.
- Admin can edit the ratings and comments of any review.
- Admin can delete any review deemed inappropriate.

These tests use a fake Firestore database to ensure they can run in a CI/CD environment
without needing a real service account key.
"""

from __future__ import annotations

from typing import Any

import pytest

import app as flask_module
from tests.test_sprint3_meetup_management import (
    FakeDB,
    captured_templates,
    client,
    login_as,
    patch_db,
    future_date,
)

# =========================================================
# Fixtures and Test Data
# =========================================================


def base_review(review_id: str, **overrides: Any) -> dict[str, Any]:
    """Creates a base review dictionary for seeding the fake database."""
    data = {
        "rater_id": "participant_rater_1",
        "rater_name": "Rater One",
        "rated_user_id": "participant_reviewee_1",
        "rated_user_name": "Reviewee One",
        "meetup_id": "meetup1",
        "meetup_title": "Football Fun Game",
        "comment": "Good game, well played.",
        "attendance_rating": 5,
        "teamwork_rating": 4,
        "sportsmanship_rating": 5,
        "reliability_rating": 5,
        "average_rating": 4.75,
        "status": "active",
        "created_at": future_date(1),
        "updated_at": future_date(1),
    }
    data.update(overrides)
    return data


def fake_db_with_reviews() -> FakeDB:
    """Creates a FakeDB instance seeded with users and reviews."""
    return FakeDB(
        {
            "users": {
                "admin1": {"role": "admin", "full_name": "Admin User"},
                "org1": {"role": "organizer", "full_name": "Organizer User"},
                "p1": {"role": "participant", "full_name": "Participant User"},
                "rater1": {"role": "participant", "full_name": "Rater One"},
                "reviewee1": {"role": "participant", "full_name": "Reviewee One"},
                "reviewee2": {"role": "participant", "full_name": "Reviewee Two"},
            },
            "ratings": {
                "review1": base_review(
                    "review1",
                    rater_name="Rater One",
                    rated_user_name="Reviewee One",
                    comment="Great teamwork and always on time.",
                    average_rating=5.0,
                    created_at=future_date(2),
                ),
                "review2": base_review(
                    "review2",
                    rater_name="Rater One",
                    rated_user_name="Reviewee Two",
                    comment="A bit late, but a good player.",
                    average_rating=4.0,
                    reliability_rating=3,
                    created_at=future_date(3),
                ),
                "review3": base_review(
                    "review3",
                    rater_name="Reviewee Two",
                    rated_user_name="Reviewee One",
                    comment="Excellent sportsmanship!",
                    average_rating=5.0,
                    created_at=future_date(1),
                ),
            },
        }
    )


def valid_edit_review_form(**overrides: Any) -> dict[str, str]:
    """Returns a dictionary of valid form data for editing a review."""
    data = {
        "attendance_rating": "5",
        "teamwork_rating": "5",
        "sportsmanship_rating": "5",
        "reliability_rating": "5",
        "comment": "Updated comment by admin.",
    }
    data.update(overrides)
    return data


# =========================================================
# Manage Reviews Page Tests (/manage-reviews)
# =========================================================


@pytest.mark.parametrize(
    "role, user_id, expected_status",
    [
        ("admin", "admin1", 200),
        ("organizer", "org1", 302),
        ("participant", "p1", 302),
    ],
)
def test_manage_reviews_access_control(client, monkeypatch, role, user_id, expected_status):
    """Tests that only admins can access the manage reviews page."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role=role, user_id=user_id)

    response = client.get("/manage-reviews")

    assert response.status_code == expected_status
    if expected_status == 302:
        assert response.location.endswith("/")


def test_manage_reviews_lists_all_reviews_for_admin(client, captured_templates, monkeypatch):
    """Admin should see a list of all reviews in the system."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "manage_reviews.html"
    reviews_in_context = captured_templates[-1]["context"]["reviews"]
    assert len(reviews_in_context) == 3
    assert {r["id"] for r in reviews_in_context} == {"review1", "review2", "review3"}


def test_manage_reviews_sorts_reviews_by_creation_date_descending(client, captured_templates, monkeypatch):
    """The manage reviews page should display the newest reviews first."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    reviews_in_context = captured_templates[-1]["context"]["reviews"]
    assert len(reviews_in_context) == 3
    # review2 is newest (future_date(3)), then review1 (2), then review3 (1)
    review_ids = [r["id"] for r in reviews_in_context]
    assert review_ids == ["review2", "review1", "review3"]


def test_manage_reviews_handles_no_reviews(client, captured_templates, monkeypatch):
    """The page should display a message when no reviews exist."""
    patch_db(monkeypatch, FakeDB({"users": {"admin1": {"role": "admin"}}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "manage_reviews.html"
    assert captured_templates[-1]["context"]["reviews"] == []


@pytest.mark.parametrize(
    "keyword, expected_ids",
    [
        ("teamwork", {"review1"}),
        ("late player", {"review2"}),
        ("sportsmanship", {"review3"}),
        ("Reviewee One", {"review1", "review3"}),
        ("Rater One", {"review1", "review2"}),
        ("nonexistent", set()),
        ("", {"review1", "review2", "review3"}),
    ],
)
def test_manage_reviews_filters_by_keyword(client, captured_templates, monkeypatch, keyword, expected_ids):
    """Admin should be able to filter reviews by keyword."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews", query_string={"keyword": keyword})

    assert response.status_code == 200
    assert {r["id"] for r in captured_templates[-1]["context"]["reviews"]} == expected_ids


# =========================================================
# Edit Review Page Tests (/admin/review/<review_id>/edit)
# =========================================================


@pytest.mark.parametrize(
    "role, user_id, expected_status",
    [
        ("admin", "admin1", 200),
        ("organizer", "org1", 302),
        ("participant", "p1", 302),
    ],
)
def test_edit_review_access_control(client, monkeypatch, role, user_id, expected_status):
    """Tests that only admins can access the edit review page."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role=role, user_id=user_id)

    response = client.get("/admin/review/review1/edit")

    assert response.status_code == expected_status


def test_edit_review_get_redirects_for_nonexistent_review(client, monkeypatch):
    """Attempting to edit a review that does not exist should redirect the admin."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/admin/review/nonexistent-review/edit")

    assert response.status_code == 302
    assert response.location == "/manage-reviews"


def test_edit_review_get_populates_form_with_existing_data(client, captured_templates, monkeypatch):
    """The edit form should be pre-filled with the review's current data."""
    patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/admin/review/review1/edit")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_review.html"
    review_data = captured_templates[-1]["context"]["review"]
    assert review_data["id"] == "review1"
    assert review_data["comment"] == "Great teamwork and always on time."
    assert review_data["teamwork_rating"] == 4


def test_edit_review_post_updates_review_successfully(client, monkeypatch):
    """A valid POST request should update the review in the database."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    form_data = valid_edit_review_form(
        teamwork_rating="3", comment="This comment has been updated by an admin."
    )
    response = client.post("/admin/review/review1/edit", data=form_data)

    assert response.status_code == 302
    assert response.location == "/manage-reviews"

    updated_review = fake_db.data["ratings"]["review1"]
    assert updated_review["teamwork_rating"] == 3
    assert updated_review["comment"] == "This comment has been updated by an admin."
    assert updated_review["average_rating"] == 4.5  # (5+3+5+5)/4
    assert updated_review["updated_at"] != fake_db.data["ratings"]["review1"]["created_at"]


@pytest.mark.parametrize(
    "field, value, error_message",
    [
        ("attendance_rating", "", "rating is required"),
        ("teamwork_rating", "abc", "must be a number"),
        ("sportsmanship_rating", "6", "must be between 1 and 5"),
        ("reliability_rating", "0", "must be between 1 and 5"),
        ("comment", "c" * 301, "cannot be more than 300 characters"),
        ("comment", "", "Comment cannot be empty."),
    ],
)
def test_edit_review_post_rejects_invalid_data(client, captured_templates, monkeypatch, field, value, error_message):
    """Invalid data should result in an error message and no database update."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    original_comment = fake_db.data["ratings"]["review2"]["comment"]
    form_data = valid_edit_review_form(**{field: value})

    response = client.post("/admin/review/review2/edit", data=form_data)

    assert response.status_code == 200  # Should re-render the form with errors
    assert captured_templates[-1]["template"] == "edit_review.html"
    # Check for flashed error message
    with client.session_transaction() as session:
        flashed_messages = [msg for _, msg in session.get("_flashes", [])]
        assert any(error_message in msg.lower() for msg in flashed_messages)

    # Verify the data was not changed
    assert fake_db.data["ratings"]["review2"]["comment"] == original_comment


def test_edit_review_post_redirects_for_nonexistent_review(client, monkeypatch):
    """A POST request to a nonexistent review should redirect without making changes."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/nonexistent-review/edit", data=valid_edit_review_form())

    assert response.status_code == 302
    assert response.location == "/manage-reviews"
    assert len(fake_db.update_calls) == 0

# =========================================================
# Delete Review Tests (/admin/review/<review_id>/delete)
# =========================================================


@pytest.mark.parametrize(
    "role, user_id, expected_status",
    [
        ("admin", "admin1", 302),
        ("organizer", "org1", 302),
        ("participant", "p1", 302),
    ],
)
def test_delete_review_access_control(client, monkeypatch, role, user_id, expected_status):
    """Only admins should be able to trigger the delete action."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role=role, user_id=user_id)

    response = client.post("/admin/review/review1/delete")

    # Non-admins are blocked by the role check in the route, so the review should still exist
    if role != "admin":
        assert "review1" in fake_db.data["ratings"]


def test_delete_review_removes_review_from_database(client, monkeypatch):
    """A POST request from an admin should delete the specified review."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    assert "review3" in fake_db.data["ratings"]

    response = client.post("/admin/review/review3/delete")

    assert response.status_code == 302
    assert response.location == "/manage-reviews"
    assert "review3" not in fake_db.data["ratings"]


def test_delete_review_handles_nonexistent_review_gracefully(client, monkeypatch):
    """Attempting to delete a review that doesn't exist should not crash."""
    fake_db = patch_db(monkeypatch, fake_db_with_reviews())
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/nonexistent-review/delete")

    assert response.status_code == 302
    assert response.location == "/manage-reviews"