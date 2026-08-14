"""
Pytest file for the Admin Review/Rating Management use case:

    "As an admin, I want to remove participant ratings so that fake,
    duplicated, inappropriate, or unfair ratings can be deleted from
    the system."

Save this file as:
    tests/test_admin_review_management.py

Covered routes in app.py:
- GET  /manage-reviews                       -> manage_reviews()
- GET  /admin/review/<review_id>/edit        -> edit_review()
- POST /admin/review/<review_id>/edit        -> edit_review()
- POST /admin/review/<review_id>/delete      -> delete_review()

These tests use fake Firestore data. They do not need the real
serviceAccountKey.json.
"""

from __future__ import annotations

from typing import Any

import pytest

import app as flask_module


# =========================================================
# Fake Firestore helpers
# (mirrors tests/test_sprint3_meetup_management.py so this file
# can run standalone without importing from that module)
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

    def delete(self):
        self.fake_db.delete_calls.append((self.collection_name, self.doc_id))
        collection = self.fake_db.data.get(self.collection_name, {})
        if self.doc_id in collection:
            del collection[self.doc_id]


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
        self.delete_calls: list[tuple[str, str]] = []

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


def login_as(client, role="admin", user_id="admin1"):
    with client.session_transaction() as session:
        session.clear()
        session["role"] = role
        session["user_id"] = user_id
        session["name"] = f"{role.title()} User"


def patch_db(monkeypatch, fake_db):
    monkeypatch.setattr(flask_module, "db", fake_db)
    monkeypatch.setattr(flask_module, "firebase_error_message", "")
    return fake_db


def base_rating(**overrides):
    data = {
        "meetup_id": "m1",
        "meetup_title": "Badminton Meetup",
        "meetup_date": "2026-01-10",
        "meetup_time": "18:30",
        "sport_type": "Badminton",
        "rater_id": "p1",
        "rater_name": "Alice",
        "rated_user_id": "p2",
        "rated_user_name": "Bob",
        "attendance_rating": 5,
        "teamwork_rating": 4,
        "sportsmanship_rating": 5,
        "reliability_rating": 4,
        "average_rating": 4.5,
        "comment": "Great teammate, always on time.",
        "status": "active",
        "created_at": "2026-01-11T10:00:00",
        "updated_at": "2026-01-11T10:00:00",
    }
    data.update(overrides)
    return data


def valid_rating_form(**overrides):
    data = {
        "attendance_rating": "5",
        "teamwork_rating": "4",
        "sportsmanship_rating": "5",
        "reliability_rating": "4",
        "comment": "Updated comment after review.",
    }
    data.update(overrides)
    return data


# =========================================================
# manage_reviews(): access control
# =========================================================

def test_manage_reviews_blocks_non_admin(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.get("/manage-reviews")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_manage_reviews_blocks_anonymous_user(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))

    response = client.get("/manage-reviews")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_manage_reviews_handles_firebase_not_connected(client, captured_templates, monkeypatch):
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(flask_module, "firebase_error_message", "missing service account")
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "manage_reviews.html"
    assert captured_templates[-1]["context"]["reviews"] == []


# =========================================================
# manage_reviews(): listing and keyword filtering
# =========================================================

def test_manage_reviews_admin_can_view_all_reviews(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "ratings": {
                "r1": base_rating(rater_name="Alice", rated_user_name="Bob"),
                "r2": base_rating(rater_name="Charlie", rated_user_name="Dave"),
            }
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "manage_reviews.html"
    review_ids = [review["id"] for review in captured_templates[-1]["context"]["reviews"]]
    assert set(review_ids) == {"r1", "r2"}


def test_manage_reviews_handles_empty_ratings_collection(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews")

    assert response.status_code == 200
    assert captured_templates[-1]["context"]["reviews"] == []


@pytest.mark.parametrize(
    "keyword, expected_ids",
    [
        ("alice", ["r1"]),
        ("bob", ["r1"]),
        ("charlie", ["r2"]),
        ("badminton", ["r1"]),
        ("football", ["r2"]),
        ("nosuchreviewer", []),
    ],
)
def test_manage_reviews_keyword_filter(client, captured_templates, monkeypatch, keyword, expected_ids):
    fake_db = FakeDB(
        {
            "ratings": {
                "r1": base_rating(
                    rater_name="Alice",
                    rated_user_name="Bob",
                    sport_type="Badminton",
                    meetup_title="Badminton Meetup",
                    comment="Solid attendance.",
                ),
                "r2": base_rating(
                    rater_name="Charlie",
                    rated_user_name="Dave",
                    sport_type="Football",
                    meetup_title="Football Meetup",
                    comment="Missed the match.",
                ),
            }
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews", query_string={"keyword": keyword})

    assert response.status_code == 200
    review_ids = [review["id"] for review in captured_templates[-1]["context"]["reviews"]]
    assert review_ids == expected_ids


def test_manage_reviews_keyword_filter_matches_comment_text(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "ratings": {
                "r1": base_rating(comment="This rating looks fake and duplicated."),
                "r2": base_rating(comment="Genuinely a great teammate."),
            }
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/manage-reviews", query_string={"keyword": "fake"})

    assert response.status_code == 200
    review_ids = [review["id"] for review in captured_templates[-1]["context"]["reviews"]]
    assert review_ids == ["r1"]


def test_manage_reviews_preserves_keyword_in_filters_context(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    client.get("/manage-reviews", query_string={"keyword": "Alice"})

    filters = captured_templates[-1]["context"]["filters"]
    assert filters["keyword"] == "alice"


# =========================================================
# delete_review(): access control
# =========================================================

def test_delete_review_blocks_non_admin(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert response.location.endswith("/")
    assert "r1" in fake_db.data["ratings"]


def test_delete_review_blocks_organizer(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="organizer", user_id="org1")

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert response.location.endswith("/")
    assert "r1" in fake_db.data["ratings"]


def test_delete_review_blocks_anonymous_user(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert "r1" in fake_db.data["ratings"]


def test_delete_review_rejects_get_method(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/admin/review/r1/delete")

    # Route is POST-only.
    assert response.status_code == 405


def test_delete_review_handles_firebase_not_connected(client, monkeypatch):
    monkeypatch.setattr(flask_module, "db", None)
    monkeypatch.setattr(flask_module, "firebase_error_message", "missing service account")
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert "/manage-reviews" in response.location


# =========================================================
# delete_review(): core behaviour
# =========================================================

def test_delete_review_admin_can_delete_existing_review(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert "/manage-reviews" in response.location
    assert "r1" not in fake_db.data["ratings"]
    assert ("ratings", "r1") in fake_db.delete_calls


def test_delete_review_only_removes_targeted_review(client, monkeypatch):
    fake_db = patch_db(
        monkeypatch,
        FakeDB(
            {
                "ratings": {
                    "r1": base_rating(rater_name="Alice"),
                    "r2": base_rating(rater_name="Charlie"),
                }
            }
        ),
    )
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/r1/delete")

    assert response.status_code == 302
    assert "r1" not in fake_db.data["ratings"]
    assert "r2" in fake_db.data["ratings"]


def test_delete_review_missing_review_redirects_without_error(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.post("/admin/review/does-not-exist/delete")

    assert response.status_code == 302
    assert "/manage-reviews" in response.location
    assert ("ratings", "does-not-exist") not in fake_db.delete_calls


def test_delete_review_is_idempotent_when_called_twice(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    first_response = client.post("/admin/review/r1/delete")
    second_response = client.post("/admin/review/r1/delete")

    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert "r1" not in fake_db.data["ratings"]
    # Only one real delete call should have been made against Firestore.
    assert fake_db.delete_calls.count(("ratings", "r1")) == 1


# =========================================================
# edit_review(): access control
# =========================================================

def test_edit_review_blocks_non_admin(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="participant", user_id="p1")

    response = client.get("/admin/review/r1/edit")

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_edit_review_redirects_when_review_not_found(client, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/admin/review/missing/edit")

    assert response.status_code == 302
    assert "/manage-reviews" in response.location


# =========================================================
# edit_review(): core behaviour
# =========================================================

def test_edit_review_admin_can_open_edit_page(client, captured_templates, monkeypatch):
    patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.get("/admin/review/r1/edit")

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_review.html"
    assert captured_templates[-1]["context"]["review"]["id"] == "r1"


def test_edit_review_admin_can_update_valid_review(client, monkeypatch):
    fake_db = patch_db(monkeypatch, FakeDB({"ratings": {"r1": base_rating()}}))
    login_as(client, role="admin", user_id="admin1")

    response = client.post(
        "/admin/review/r1/edit",
        data=valid_rating_form(
            attendance_rating="3",
            teamwork_rating="3",
            sportsmanship_rating="3",
            reliability_rating="3",
            comment="Corrected after admin review.",
        ),
    )

    assert response.status_code == 302
    assert "/manage-reviews" in response.location
    updated = fake_db.data["ratings"]["r1"]
    assert updated["attendance_rating"] == 3
    assert updated["comment"] == "Corrected after admin review."
    assert updated["average_rating"] == 3.0


def test_edit_review_rejects_invalid_rating_without_update(client, captured_templates, monkeypatch):
    fake_db = patch_db(
        monkeypatch,
        FakeDB({"ratings": {"r1": base_rating(attendance_rating=5)}}),
    )
    login_as(client, role="admin", user_id="admin1")

    response = client.post(
        "/admin/review/r1/edit",
        data=valid_rating_form(attendance_rating="9"),
    )

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_review.html"
    assert fake_db.data["ratings"]["r1"]["attendance_rating"] == 5


def test_edit_review_rejects_empty_comment_without_update(client, captured_templates, monkeypatch):
    fake_db = patch_db(
        monkeypatch,
        FakeDB({"ratings": {"r1": base_rating(comment="Original comment.")}}),
    )
    login_as(client, role="admin", user_id="admin1")

    response = client.post(
        "/admin/review/r1/edit",
        data=valid_rating_form(comment=""),
    )

    assert response.status_code == 200
    assert captured_templates[-1]["template"] == "edit_review.html"
    assert fake_db.data["ratings"]["r1"]["comment"] == "Original comment."


# =========================================================
# End-to-end style checks combining manage/delete
# =========================================================

def test_deleted_review_no_longer_appears_in_manage_reviews_listing(client, captured_templates, monkeypatch):
    fake_db = FakeDB(
        {
            "ratings": {
                "r1": base_rating(rater_name="Alice", rated_user_name="Bob"),
                "r2": base_rating(rater_name="Charlie", rated_user_name="Dave"),
            }
        }
    )
    patch_db(monkeypatch, fake_db)
    login_as(client, role="admin", user_id="admin1")

    client.post("/admin/review/r1/delete")
    client.get("/manage-reviews")

    review_ids = [review["id"] for review in captured_templates[-1]["context"]["reviews"]]
    assert review_ids == ["r2"]