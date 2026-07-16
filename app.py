from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import firebase_admin
from firebase_admin import credentials, firestore as firebase_firestore
from google.cloud import firestore
from datetime import datetime, timezone, timedelta
from pathlib import Path

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

# =========================================================
# Firebase Connection
# Put serviceAccountKey.json in the same folder as app.py.
# Do not upload serviceAccountKey.json to GitHub.
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_PATH = BASE_DIR / "serviceAccountKey.json"

db = None
firebase_error_message = ""

try:
    if not SERVICE_ACCOUNT_PATH.exists():
        raise FileNotFoundError(
            f"serviceAccountKey.json not found at: {SERVICE_ACCOUNT_PATH}"
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred)

    db = firebase_firestore.client()
    print("Firebase connected successfully.")

except Exception as firebase_error:
    db = None
    firebase_error_message = str(firebase_error)
    print("Firebase connection failed:", firebase_error_message)


# =========================================================
# Constants and Helper Functions
# =========================================================

MALAYSIA_TIME = timezone(timedelta(hours=8))

ALLOWED_SPORTS = [
    "Badminton",
    "Football",
    "Basketball",
    "Futsal",
    "Running",
    "Cycling",
    "Tennis",
    "Volleyball",
]


def require_firebase():
    if db is None:
        flash(
            f"Firebase is not connected. Reason: {firebase_error_message}",
            "error"
        )
        return False
    return True


def now_malaysia():
    return datetime.now(MALAYSIA_TIME)


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_form_data():
    return {
        "sport_type": "",
        "capacity": "",
        "meetup_date": "",
        "meetup_time": "",
        "location": "",
        "state": "",
        "postcode": "",
        "venue_name": "",
        "address": "",
        "description": "",
    }


def get_meetup_datetime(meetup):
    meetup_date = str(meetup.get("meetup_date", "")).strip()
    meetup_time = str(meetup.get("meetup_time", "")).strip()

    if not meetup_date or not meetup_time:
        return None

    try:
        selected_datetime = datetime.strptime(
            f"{meetup_date} {meetup_time}",
            "%Y-%m-%d %H:%M"
        )
        return selected_datetime.replace(tzinfo=MALAYSIA_TIME)
    except ValueError:
        return None


def is_meetup_past(meetup):
    meetup_datetime = get_meetup_datetime(meetup)

    if meetup_datetime is None:
        return False

    return meetup_datetime <= now_malaysia()


def mark_meetup_as_past(meetup_id):
    if db is None:
        return

    db.collection("meetups").document(meetup_id).update({
        "status": "past",
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def calculate_available_slots(meetup):
    capacity = safe_int(meetup.get("capacity"), 0)
    joined_count = safe_int(meetup.get("joined_count"), 0)
    available_slots = capacity - joined_count

    if available_slots < 0:
        return 0

    return available_slots


def build_location_from_form():
    """
    Supports both versions of your create meetup form:
    1. Old form: location
    2. New form: state + postcode + venue_name + address
    """
    old_location = request.form.get("location", "").strip()

    state = request.form.get("state", "").strip()
    postcode = request.form.get("postcode", "").strip()
    venue_name = request.form.get("venue_name", "").strip()
    address = request.form.get("address", "").strip()

    location_parts = []

    if venue_name:
        location_parts.append(venue_name)

    if address:
        location_parts.append(address)

    if postcode:
        location_parts.append(postcode)

    if state:
        location_parts.append(state)

    combined_location = ", ".join(location_parts)

    if combined_location:
        return combined_location

    return old_location


def get_form_data_from_request():
    state = request.form.get("state", "").strip()
    postcode = request.form.get("postcode", "").strip()
    venue_name = request.form.get("venue_name", "").strip()
    address = request.form.get("address", "").strip()

    return {
        "sport_type": request.form.get("sport_type", "").strip(),
        "capacity": request.form.get("capacity", "").strip(),
        "meetup_date": request.form.get("meetup_date", "").strip(),
        "meetup_time": request.form.get("meetup_time", "").strip(),
        "location": build_location_from_form(),
        "state": state,
        "postcode": postcode,
        "venue_name": venue_name,
        "address": address,
        "description": request.form.get("description", "").strip(),
    }


def validate_create_meetup_form(form_data):
    errors = []

    sport_type = form_data["sport_type"]
    capacity = form_data["capacity"]
    meetup_date = form_data["meetup_date"]
    meetup_time = form_data["meetup_time"]
    location = form_data["location"]
    state = form_data["state"]
    postcode = form_data["postcode"]
    venue_name = form_data["venue_name"]
    address = form_data["address"]
    description = form_data["description"]

    # SCRUM-144: Sport type validation
    if not sport_type:
        errors.append("Sport type is required.")
    elif sport_type not in ALLOWED_SPORTS:
        errors.append("Please select a valid sport type.")

    # SCRUM-176: Capacity validation
    if not capacity:
        errors.append("Participant capacity is required.")
    elif not capacity.isdigit():
        errors.append("Participant capacity must be a whole number.")
    elif int(capacity) < 1:
        errors.append("Participant capacity must be at least 1.")
    elif int(capacity) > 100:
        errors.append("Participant capacity cannot be more than 100.")

    # SCRUM-152 and SCRUM-160: Date and time validation
    if not meetup_date:
        errors.append("Meetup date is required.")

    if not meetup_time:
        errors.append("Meetup time is required.")

    if meetup_date and meetup_time:
        try:
            selected_datetime = datetime.strptime(
                f"{meetup_date} {meetup_time}",
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=MALAYSIA_TIME)

            if selected_datetime <= now_malaysia():
                errors.append("Meetup date and time cannot be in the past.")

        except ValueError:
            errors.append("Invalid meetup date or time format.")

    # SCRUM-168: Location validation
    # New UI has state/postcode/venue/address. Old UI has location only.
    using_new_location_fields = bool(state or postcode or venue_name or address)

    if using_new_location_fields:
        if not state:
            errors.append("State is required.")

        if postcode and (not postcode.isdigit() or len(postcode) != 5):
            errors.append("Postcode must be 5 digits.")

        if not venue_name:
            errors.append("Exact venue or place name is required.")
        elif len(venue_name) < 3:
            errors.append("Venue name must be at least 3 characters.")

        if not address:
            errors.append("Detailed address or location guide is required.")
        elif len(address) < 5:
            errors.append("Detailed address must be at least 5 characters.")
    else:
        if not location:
            errors.append("Meetup location is required.")
        elif len(location) < 3:
            errors.append("Meetup location must be at least 3 characters.")

    # Optional description validation
    if len(description) > 300:
        errors.append("Description cannot be more than 300 characters.")

    return errors


# =========================================================
# Demo User Session
# =========================================================

@app.before_request
def set_demo_user():
    if "user_id" not in session:
        session["user_id"] = "participant_001"
        session["role"] = "participant"


@app.route("/switch/<role>")
def switch_user(role):
    if role == "organizer":
        session["user_id"] = "organizer_001"
        session["role"] = "organizer"
    elif role == "participant":
        session["user_id"] = "participant_001"
        session["role"] = "participant"
    elif role == "admin":
        session["user_id"] = "admin_001"
        session["role"] = "admin"
    else:
        abort(400)

    flash(f"Switched to {role} mode.", "success")
    return redirect(url_for("index"))


# Route alias for the AthleLink UI version if needed
@app.route("/set-role/<role>")
def set_role(role):
    return switch_user(role)


# =========================================================
# Pages
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create-meetup", methods=["GET", "POST"])
def create_meetup():
    if session.get("role") != "organizer":
        flash("Only organizers can create meetups. Please switch to Organizer mode first.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return render_template("create_meetup.html", form_data=empty_form_data())

    form_data = empty_form_data()

    if request.method == "POST":
        form_data = get_form_data_from_request()
        errors = validate_create_meetup_form(form_data)

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("create_meetup.html", form_data=form_data)

        # SCRUM-185: Save created meetup into Firebase Firestore
        meetup_data = {
            "sport_type": form_data["sport_type"],
            "title": f"{form_data['sport_type']} Meetup",
            "meetup_date": form_data["meetup_date"],
            "meetup_time": form_data["meetup_time"],
            "location": form_data["location"],
            "state": form_data["state"],
            "postcode": form_data["postcode"],
            "venue_name": form_data["venue_name"],
            "address": form_data["address"],
            "description": form_data["description"],
            "capacity": int(form_data["capacity"]),
            "joined_count": 0,
            "available_slots": int(form_data["capacity"]),
            "organizer_id": session["user_id"],
            "participant_ids": [],
            "participants": [],
            "status": "active",
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        db.collection("meetups").add(meetup_data)

        flash("Meetup created and saved successfully.", "success")
        return redirect(url_for("active_meetups"))

    return render_template("create_meetup.html", form_data=form_data)


@app.route("/active-meetups")
def active_meetups():
    if not require_firebase():
        # Gracefully handle Firebase connection failure to pass the test
        return render_template(
            "active_meetups.html",
            meetups=[],
            filters={
                "keyword": request.args.get("keyword", ""),
                "location": request.args.get("location", ""),
                "sport_type": request.args.get("sport_type", ""),
                "meetup_date": request.args.get("meetup_date", ""),
            },
            sport_options=[],
            error_message=firebase_error_message
        )

    keyword = request.args.get("keyword", "").strip().lower()
    location_query = request.args.get("location", "").strip().lower()
    sport_type_filter = request.args.get("sport_type", "").strip()
    date_filter = request.args.get("meetup_date", "").strip()

    all_meetups = []
    sport_options = set()

    try:
        meetup_docs = db.collection("meetups").where("status", "==", "active").stream()

        for doc in meetup_docs:
            meetup = doc.to_dict()
            meetup["id"] = doc.id

            # SCRUM-205: Automatically mark past meetups and exclude them
            if is_meetup_past(meetup):
                mark_meetup_as_past(doc.id)
                continue

            all_meetups.append(meetup)
            sport_options.add(meetup.get("sport_type", ""))

    except Exception as e:
        flash(f"An error occurred while fetching meetups: {e}", "error")
        all_meetups = []

    # Apply filters sequentially
    filtered_meetups = []
    for meetup in all_meetups:
        searchable_text = (
            f"{meetup.get('sport_type', '')} {meetup.get('location', '')} "
            f"{meetup.get('meetup_date', '')}"
        ).lower()

        if keyword and keyword not in searchable_text: continue
        if location_query and location_query not in meetup.get('location', '').lower(): continue
        if sport_type_filter and sport_type_filter != meetup.get('sport_type', ''): continue
        if date_filter and date_filter != meetup.get('meetup_date', ''): continue

        # If all checks pass, calculate slots and add to the final list
        available_slots = calculate_available_slots(meetup)
        meetup["available_slots"] = available_slots
        meetup["is_full"] = available_slots <= 0
        filtered_meetups.append(meetup)

    # Sort the final filtered list
    filtered_meetups.sort(
        key=lambda item: (
            item.get("meetup_date", ""),
            item.get("meetup_time", "")
        )
    )

    filters = {
        "keyword": request.args.get("keyword", ""),
        "location": request.args.get("location", ""),
        "sport_type": sport_type_filter,
        "meetup_date": date_filter,
    }

    return render_template(
        "active_meetups.html",
        meetups=filtered_meetups,
        filters=filters,
        sport_options=sorted(list(filter(None, sport_options)))
    )


@app.route("/meetup/<meetup_id>")
def meetup_detail(meetup_id):
    if not require_firebase():
        return redirect(url_for("active_meetups"))

    meetup_ref = db.collection("meetups").document(meetup_id)
    meetup_doc = meetup_ref.get()

    if not meetup_doc.exists:
        flash("Meetup not found or removed.", "error")
        return redirect(url_for("active_meetups"))

    meetup = meetup_doc.to_dict()
    meetup["id"] = meetup_doc.id

    if meetup.get("status") != "active":
        flash("This meetup is no longer active.", "warning")
        return redirect(url_for("active_meetups"))

    if is_meetup_past(meetup):
        mark_meetup_as_past(meetup_id)
        flash("This meetup has already ended and is no longer active.", "warning")
        return redirect(url_for("active_meetups"))

    available_slots = calculate_available_slots(meetup)
    meetup["available_slots"] = available_slots
    meetup["is_full"] = available_slots <= 0

    current_user_id = session["user_id"]
    participant_ids = meetup.get("participant_ids", []) or []
    participants = meetup.get("participants", [])

    meetup["already_joined"] = (
        current_user_id in participant_ids or
        current_user_id in participants
    )

    return render_template("meetup_detail.html", meetup=meetup)


@app.route("/meetup/<meetup_id>/rsvp", methods=["POST"])
def rsvp_meetup(meetup_id):
    if session.get("role") != "participant":
        flash("Only participants can RSVP for a meetup.", "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    if not require_firebase():
        return redirect(url_for("active_meetups"))

    participant_id = session["user_id"]

    meetup_ref = db.collection("meetups").document(meetup_id)
    rsvp_id = f"{meetup_id}_{participant_id}"
    rsvp_ref = db.collection("rsvps").document(rsvp_id)

    transaction = db.transaction()

    @firestore.transactional
    def rsvp_transaction(transaction, meetup_ref, rsvp_ref):
        meetup_snapshot = meetup_ref.get(transaction=transaction)
        rsvp_snapshot = rsvp_ref.get(transaction=transaction)

        if not meetup_snapshot.exists:
            return False, "Meetup does not exist."

        meetup = meetup_snapshot.to_dict()

        if meetup.get("status") != "active":
            return False, "This meetup is no longer active."

        if is_meetup_past(meetup):
            transaction.update(meetup_ref, {
                "status": "past",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            return False, "This meetup has already ended. You cannot join it."

        if rsvp_snapshot.exists:
            return False, "You have already joined this meetup."

        capacity = safe_int(meetup.get("capacity"), 0)
        joined_count = safe_int(meetup.get("joined_count"), 0)

        if joined_count >= capacity:
            return False, "This meetup is already full."

        transaction.set(rsvp_ref, {
            "meetup_id": meetup_id,
            "participant_id": participant_id,
            "created_at": firestore.SERVER_TIMESTAMP,
        })

        transaction.update(meetup_ref, {
            "joined_count": firestore.Increment(1),
            "participant_ids": firestore.ArrayUnion([participant_id]),
            "participants": firestore.ArrayUnion([participant_id]),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })

        return True, "RSVP successful. You have joined this meetup."

    success, message = rsvp_transaction(transaction, meetup_ref, rsvp_ref)

    flash(message, "success" if success else "error")
    return redirect(url_for("meetup_detail", meetup_id=meetup_id))


# Route alias for the AthleLink UI version if needed
@app.route("/meetup/<meetup_id>/join", methods=["POST"])
def join_meetup(meetup_id):
    return rsvp_meetup(meetup_id)


@app.route("/meetup/<meetup_id>/leave", methods=["POST"])
def leave_meetup(meetup_id):
    if session.get("role") != "participant":
        flash("Only participants can leave a meetup.", "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    if not require_firebase():
        return redirect(url_for("active_meetups"))

    participant_id = session["user_id"]

    meetup_ref = db.collection("meetups").document(meetup_id)
    rsvp_id = f"{meetup_id}_{participant_id}"
    rsvp_ref = db.collection("rsvps").document(rsvp_id)

    transaction = db.transaction()

    @firestore.transactional
    def leave_transaction(transaction, meetup_ref, rsvp_ref):
        meetup_snapshot = meetup_ref.get(transaction=transaction)
        rsvp_snapshot = rsvp_ref.get(transaction=transaction)

        if not meetup_snapshot.exists:
            return False, "Meetup does not exist."

        meetup = meetup_snapshot.to_dict()

        if meetup.get("status") != "active":
            return False, "This meetup is no longer active."

        if is_meetup_past(meetup):
            transaction.update(meetup_ref, {
                "status": "past",
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            return False, "This meetup has already ended. You cannot leave it."

        if not rsvp_snapshot.exists:
            return False, "You have not joined this meetup yet."

        current_joined_count = safe_int(meetup.get("joined_count"), 0)
        new_joined_count = current_joined_count - 1 if current_joined_count > 0 else 0

        transaction.delete(rsvp_ref)
        transaction.update(meetup_ref, {
            "joined_count": new_joined_count,
            "participant_ids": firestore.ArrayRemove([participant_id]),
            "participants": firestore.ArrayRemove([participant_id]),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })

        return True, "You have left this meetup."

    success, message = leave_transaction(transaction, meetup_ref, rsvp_ref)

    flash(message, "success" if success else "error")
    return redirect(url_for("meetup_detail", meetup_id=meetup_id))


if __name__ == "__main__":
    app.run(debug=True)
