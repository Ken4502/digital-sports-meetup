from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import firebase_admin
from firebase_admin import credentials, firestore as firebase_firestore
from google.cloud import firestore
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re 
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

# Disable strict slashes to prevent 302 redirects on trailing slashes
app.url_map.strict_slashes = False

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

STATES = [
    "Penang",
    "Kuala Lumpur",
    "Selangor",
    "Perak",
    "Kedah",
    "Perlis",
    "Johor",
    "Melaka",
    "Negeri Sembilan",
    "Pahang",
    "Terengganu",
    "Kelantan",
    "Sabah",
    "Sarawak",
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
    return {
        "sport_type": request.form.get("sport_type", "").strip(),
        "capacity": request.form.get("capacity", "").strip(),
        "meetup_date": request.form.get("meetup_date", "").strip(),
        "meetup_time": request.form.get("meetup_time", "").strip(),
        "location": build_location_from_form(),
        "state": request.form.get("state", "").strip(),
        "postcode": request.form.get("postcode", "").strip(),
        "venue_name": request.form.get("venue_name", "").strip(),
        "address": request.form.get("address", "").strip(),
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
    using_new_location_fields = True # Always use new fields for validation

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

    # Optional description validation
    if len(description) > 300:
        errors.append("Description cannot be more than 300 characters.")

    return errors

# =========================================================
# Sprint 2 Stage 1 - Registration and Own Profile
# Paste these helpers below your Create Meetup helper functions.
# Also add this import at the top of app.py:
# from werkzeug.security import generate_password_hash
# import re
# =========================================================

REGISTER_ROLES = ["participant", "organizer"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced"]


def empty_register_form():
    return {
        "full_name": "",
        "email": "",
        "password": "",
        "confirm_password": "",
        "role": "participant",
        "phone": "",
        "sport_interest": "",
        "skill_level": "",
        "organization_name": "",
        "experience_years": "",
        "bio": "",
    }


def get_register_form_from_request():
    return {
        "full_name": request.form.get("full_name", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "password": request.form.get("password", ""),
        "confirm_password": request.form.get("confirm_password", ""),
        "role": request.form.get("role", "participant").strip(),
        "phone": request.form.get("phone", "").strip(),
        "sport_interest": request.form.get("sport_interest", "").strip(),
        "skill_level": request.form.get("skill_level", "").strip(),
        "organization_name": request.form.get("organization_name", "").strip(),
        "experience_years": request.form.get("experience_years", "").strip(),
        "bio": request.form.get("bio", "").strip(),
    }


def is_valid_email(email):
    if not email:
        return False

    email = email.strip()

    if ".." in email:
        return False

    email_pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

    return re.match(email_pattern, email) is not None



def normalize_phone(phone):
    return phone.replace(" ", "").replace("-", "").strip()


def is_strong_password(password):
    if not password:
        return False

    if len(password) < 8:
        return False

    has_alphabet = re.search(r"[A-Za-z]", password) is not None
    has_number = re.search(r"[0-9]", password) is not None
    has_symbol = re.search(r"[^A-Za-z0-9]", password) is not None

    return has_alphabet and has_number and has_symbol



def build_user_id(role, email):
    # Example: participant_john_20991231235959
    email_name = email.split("@")[0]
    clean_email_name = re.sub(r"[^a-zA-Z0-9]+", "_", email_name).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{role}_{clean_email_name}_{timestamp}"


def email_already_registered(email):
    if db is None:
        return False

    existing_users = db.collection("users").where("email", "==", email).limit(1).stream()
    return any(True for _ in existing_users)

def phone_already_registered(phone_clean):
    if db is None:
        return False

    existing_users = (
        db.collection("users")
        .where("phone_clean", "==", phone_clean)
        .limit(1)
        .stream()
    )

    return any(True for _ in existing_users)

def validate_register_form(form_data):
    errors = []

    full_name = form_data["full_name"]
    email = form_data["email"]
    password = form_data["password"]
    confirm_password = form_data["confirm_password"]
    role = form_data["role"]
    phone = form_data["phone"]
    sport_interest = form_data["sport_interest"]
    skill_level = form_data["skill_level"]
    organization_name = form_data["organization_name"]
    experience_years = form_data["experience_years"]
    bio = form_data["bio"]

    if not full_name:
        errors.append("Full name is required.")
    elif len(full_name) < 3:
        errors.append("Full name must be at least 3 characters.")

    if not email:
        errors.append("Email is required.")
    elif not is_valid_email(email):
        errors.append("Please enter a valid email address.")

    if not password:
        errors.append("Password is required.")
    elif not is_strong_password(password):
        errors.append("Password must be at least 8 characters and include alphabet, number, and symbol.")

    if password != confirm_password:
        errors.append("Password and confirm password do not match.")

    if role not in REGISTER_ROLES:
        errors.append("Please select a valid account role.")

    phone_clean = normalize_phone(phone)

    if not phone:
        errors.append("Phone number is required.")
    elif not phone_clean.isdigit():
        errors.append("Phone number can only contain numbers, spaces, or dashes.")
    elif len(phone_clean) < 10 or len(phone_clean) > 11:
        errors.append("Phone number must be 10 to 11 digits.")

    if role == "participant":
        if not sport_interest:
            errors.append("Sport interest is required for participant account.")
        elif sport_interest not in ALLOWED_SPORTS:
            errors.append("Please select a valid sport interest.")

        if not skill_level:
            errors.append("Skill level is required for participant account.")
        elif skill_level not in SKILL_LEVELS:
            errors.append("Please select a valid skill level.")

    if role == "organizer":
        if not organization_name:
            errors.append("Organization name is required for organizer account.")
        elif len(organization_name) < 3:
            errors.append("Organization name must be at least 3 characters.")

        if not experience_years:
            errors.append("Organizer experience years is required.")
        elif not experience_years.isdigit():
            errors.append("Organizer experience years must be a whole number.")
        elif int(experience_years) < 0:
            errors.append("Organizer experience years cannot be negative.")

    if len(bio) > 300:
        errors.append("Bio cannot be more than 300 characters.")

    return errors


# =========================================================
# Paste these routes below index() or below create_meetup().
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if not require_firebase():
        return render_template(
            "register.html",
            form_data=empty_register_form(),
            sport_options=ALLOWED_SPORTS,
            skill_levels=SKILL_LEVELS,
        )

    form_data = empty_register_form()

    if request.method == "POST":
        form_data = get_register_form_from_request()
        errors = validate_register_form(form_data)

        phone_clean = normalize_phone(form_data["phone"])

        if form_data.get("email") and email_already_registered(form_data["email"]):
            errors.append("This email is already registered.")

        if phone_clean and phone_already_registered(phone_clean):
            errors.append("This phone number is already registered.")

        if errors:
            for error in errors:
                flash(error, "error")
            # Clear password fields before returning to page.
            form_data["password"] = ""
            form_data["confirm_password"] = ""
            return render_template(
                "register.html",
                form_data=form_data,
                sport_options=ALLOWED_SPORTS,
                skill_levels=SKILL_LEVELS,
            )

        user_role = form_data["role"]
        user_id = build_user_id(user_role, form_data["email"])

        user_data = {
            "user_id": user_id,
            "full_name": form_data["full_name"],
            "email": form_data["email"],
            "password_hash": generate_password_hash(form_data["password"]),
            "role": user_role,
            "phone": form_data["phone"],
            "phone_clean": phone_clean,
            "sport_interest": form_data["sport_interest"],
            "skill_level": form_data["skill_level"],
            "organization_name": form_data["organization_name"],
            "experience_years": int(form_data["experience_years"]) if form_data["experience_years"] else 0,
            "bio": form_data["bio"],
            "status": "active",
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        db.collection("users").document(user_id).set(user_data)

        session["user_id"] = user_id
        session["role"] = user_role
        session["full_name"] = form_data["full_name"]

        flash("Account registered successfully.", "success")
        return redirect(url_for("my_profile"))

    return render_template(
        "register.html",
        form_data=form_data,
        sport_options=ALLOWED_SPORTS,
        skill_levels=SKILL_LEVELS,
    )


@app.route("/profile")
def my_profile():
    if not require_firebase():
        return render_template("profile.html", user=None, is_own_profile=True)

    user_id = session.get("user_id")

    if not user_id:
        flash("Please register or log in first.", "error")
        return redirect(url_for("register"))

    user_doc = db.collection("users").document(user_id).get()

    if not user_doc.exists:
        flash("Profile not found. Please register an account first.", "error")
        return redirect(url_for("register"))

    user = user_doc.to_dict()
    user["id"] = user_doc.id

    return render_template("profile.html", user=user, is_own_profile=True, sport_options=ALLOWED_SPORTS)

@app.route("/profile/edit", methods=["POST"])
def edit_profile():
    user_id = session.get("user_id")

    if not user_id:
        flash("Please register or log in first.", "error")
        return redirect(url_for("login"))

    if not require_firebase():
        return redirect(url_for("my_profile"))

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        flash("User not found.", "error")
        session.clear()
        return redirect(url_for("login"))

    user = user_doc.to_dict()

    # Get form data
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    bio = request.form.get("bio", "").strip()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_new_password = request.form.get("confirm_new_password", "")

    errors = []
    update_data = {"updated_at": firestore.SERVER_TIMESTAMP}

    # Validate Full Name
    # Validate Full Name
    if not full_name or len(full_name) < 3:
        errors.append("Full name must be at least 3 characters.")
    else:
        update_data["full_name"] = full_name

    # Validate Email
    # Validate Email
    if not email or not is_valid_email(email):
        errors.append("Please enter a valid email address.")
    elif email != user.get("email") and email_already_registered(email):
        errors.append("This email is already registered by another user.")
    else:
        update_data["email"] = email
        # If email changes, update session email if it's stored there
        if session.get("email") == user.get("email"):
            session["email"] = email


    # Validate Phone
    phone_clean = normalize_phone(phone)
    if not phone:
        errors.append("Phone number is required.")
    elif not phone_clean.isdigit():
        errors.append("Phone number can only contain numbers, spaces, or dashes.")
    elif len(phone_clean) < 10 or len(phone_clean) > 11:
        errors.append("Phone number must be 10 to 11 digits.")
    elif phone_clean != user.get("phone_clean") and phone_already_registered(phone_clean):
        errors.append("This phone number is already registered by another user.")
    else:
        update_data["phone"] = phone
        update_data["phone_clean"] = phone_clean

    # Validate Bio
    # Validate Bio
    if len(bio) > 300:
        errors.append("Bio cannot be more than 300 characters.")
    else:
        update_data["bio"] = bio

    # --- Password Change Validation (only if a new password is provided) ---
    if new_password:
        password_errors = []
        # The test for an incorrect current password runs first.
        if not check_password_hash(user.get("password_hash", ""), current_password):
            password_errors.append("Current password is incorrect.")

        # The test for a short password expects this exact message without a period.
        if len(new_password) < 8:
            password_errors.append("New password must be at least 8 characters")
        # Check for other password criteria if length is okay.
        elif not is_strong_password(new_password):
            password_errors.append("New password must include alphabet, number, and symbol.")

        if new_password != confirm_new_password:
            password_errors.append("New password and confirmation do not match.")

        # If there are any password-related errors, add them to the main error list.
        if password_errors:
            errors.extend(password_errors)
        else:
            # Only if all password checks pass, do we update the hash.
            update_data["password_hash"] = generate_password_hash(new_password)

    # Role-specific fields
    if session.get("role") == "participant":
        sport_interest = request.form.get("sport_interest", "").strip()
        if sport_interest not in ALLOWED_SPORTS:
            errors.append("Please select a valid sport interest.")
        else:
            update_data["sport_interest"] = sport_interest

    if errors:
        for error in errors:
            flash(error, "error")
        user["id"] = user_id # Ensure user object has 'id' for template rendering
        return render_template("profile.html", user=user, is_own_profile=True, sport_options=ALLOWED_SPORTS, skill_levels=SKILL_LEVELS)

    user_ref.update(update_data)
    session["full_name"] = full_name # Update session if name changes
    flash("Profile updated successfully.", "success")
    return redirect(url_for("my_profile"))

@app.route("/profile/delete", methods=["POST"])
def delete_account():
    user_id = session.get("user_id")

    if not user_id:
        flash("Please register or log in first.", "error")
        return redirect(url_for("login"))

    if not require_firebase():
        return redirect(url_for("my_profile"))

    try:
        user_ref = db.collection("users").document(user_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            flash("Account not found.", "error")
            session.clear()
            return redirect(url_for("index"))

        user_role = user_doc.to_dict().get("role")

        # Use a batch for atomic deletion to ensure data integrity
        batch = db.batch()

        # If the user is an organizer, find all their meetups to delete them and their RSVPs
        if user_role == "organizer":
            meetup_docs = db.collection("meetups").where("organizer_id", "==", user_id).stream()
            for meetup_doc in meetup_docs:
                # For each of the organizer's meetups, find and queue all its RSVPs for deletion
                rsvp_docs = db.collection("rsvps").where("meetup_id", "==", meetup_doc.id).stream()
                for rsvp_doc in rsvp_docs:
                    batch.delete(rsvp_doc.reference)
                # After handling the RSVPs, queue the meetup document for deletion
                batch.delete(meetup_doc.reference)

        # For any user (participant or organizer), delete all RSVPs they made
        rsvp_docs = db.collection("rsvps").where("participant_id", "==", user_id).stream()
        for rsvp_doc in rsvp_docs:
            batch.delete(rsvp_doc.reference)

        # Finally, delete the user document itself
        batch.delete(user_ref)
        batch.commit()

        session.clear()
        flash("Your account has been permanently deleted.", "success")
        return redirect(url_for("index"))

    except Exception as e:
        flash(f"An error occurred while deleting your account: {e}", "error")
        return redirect(url_for("my_profile"))

def validate_edit_meetup_form(form_data):
    """
    Sprint 3 Stage 1 Fix
    SCRUM-194: Organizer edit meetup information.
    SCRUM-432: Only valid editable meetup information should be saved.

    This validation prevents organizers from updating a meetup to a past date or time.
    """

    errors = []

    sport_type = form_data["sport_type"]
    capacity = form_data["capacity"]
    meetup_date = form_data["meetup_date"]
    meetup_time = form_data["meetup_time"]
    state = form_data["state"]
    postcode = form_data["postcode"]
    venue_name = form_data["venue_name"]
    address = form_data["address"]
    description = form_data["description"]

    # Sport type validation
    if not sport_type:
        errors.append("Sport type is required.")
    elif sport_type not in ALLOWED_SPORTS:
        errors.append("Please select a valid sport type.")

    # Capacity validation
    if not capacity:
        errors.append("Participant capacity is required.")
    elif not capacity.isdigit():
        errors.append("Participant capacity must be a whole number.")
    elif int(capacity) < 1:
        errors.append("Participant capacity must be at least 1.")
    elif int(capacity) > 100:
        errors.append("Participant capacity cannot be more than 100.")

    # Date and time validation
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

    # Location validation
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

    # Description validation
    if len(description) > 300:
        errors.append("Description cannot be more than 300 characters.")

    return errors
    """
    A more lenient validation for the edit form.
    It skips date-in-the-past validation, allowing admins to modify
    details of meetups that may have already occurred.
    """
    errors = []

    sport_type = form_data["sport_type"]
    capacity = form_data["capacity"]
    meetup_date = form_data["meetup_date"]
    meetup_time = form_data["meetup_time"]
    state = form_data["state"]
    postcode = form_data["postcode"]
    venue_name = form_data["venue_name"]
    address = form_data["address"]
    description = form_data["description"]

    # Sport type validation
    if not sport_type:
        errors.append("Sport type is required.")
    elif sport_type not in ALLOWED_SPORTS:
        errors.append("Please select a valid sport type.")

    # Capacity validation
    if not capacity:
        errors.append("Participant capacity is required.")
    elif not capacity.isdigit():
        errors.append("Participant capacity must be a whole number.")
    elif int(capacity) < 1:
        errors.append("Participant capacity must be at least 1.")
    elif int(capacity) > 100:
        errors.append("Participant capacity cannot be more than 100.")

    # Location validation
    if not state:
        errors.append("State is required.")
    if postcode and (not postcode.isdigit() or len(postcode) != 5):
        errors.append("Postcode must be 5 digits.")
    if not venue_name or len(venue_name) < 3:
        errors.append("Venue name must be at least 3 characters.")
    if not address or len(address) < 5:
        errors.append("Detailed address must be at least 5 characters.")

    # Description validation
    if len(description) > 300:
        errors.append("Description cannot be more than 300 characters.")

    return errors


# =========================================================
# Pages
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not require_firebase():
            return redirect(url_for("login"))

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("login"))

        users_ref = db.collection("users").where("email", "==", email).limit(1).stream()
        user_list = list(users_ref)

        if not user_list:
            flash("Invalid credentials.", "error")
            return redirect(url_for("login"))

        user_doc = user_list[0]
        user = user_doc.to_dict()

        if not check_password_hash(user.get("password_hash", ""), password):
            flash("Invalid credentials.", "error")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user_doc.id
        session["role"] = user.get("role")
        session["full_name"] = user.get("full_name", "")
        flash("Logged in successfully.", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


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
            return render_template("create_meetup.html", form_data=form_data, sport_options=ALLOWED_SPORTS)

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

    return render_template("create_meetup.html", form_data=form_data, sport_options=ALLOWED_SPORTS)


# =========================================================
# Sprint 3 Stage 2
# SCRUM-230: Participant search meetups by keyword
# SCRUM-239: Participant filter meetups by sport type
# SCRUM-249: Participant filter meetups by date
# SCRUM-461: Meetup listings load quickly
# =========================================================

def get_active_meetup_filters():
    """
    Get search and filter values from the active meetup listing page.
    This keeps the active_meetups route cleaner.
    """

    return {
        "keyword": request.args.get("keyword", "").strip(),
        "state": request.args.get("state", "").strip(),
        "sport_type": request.args.get("sport_type", "").strip(),
        "meetup_date": request.args.get("meetup_date", "").strip(),
    }


def normalize_search_text(value):
    """
    Convert text into a clean lowercase format for keyword searching.
    Extra spaces are removed so searching is more consistent.
    """

    return " ".join(str(value or "").strip().lower().split())


def build_meetup_search_text(meetup):
    """
    Build searchable text for SCRUM-230.
    Keyword can match title, sport type, location, state, venue, address,
    date, time, and description.
    """

    searchable_parts = [
        meetup.get("title", ""),
        meetup.get("sport_type", ""),
        meetup.get("location", ""),
        meetup.get("state", ""),
        meetup.get("venue_name", ""),
        meetup.get("address", ""),
        meetup.get("meetup_date", ""),
        meetup.get("meetup_time", ""),
        meetup.get("description", ""),
    ]

    return normalize_search_text(" ".join(searchable_parts))


def meetup_matches_active_filters(meetup, filters):
    """
    Apply Sprint 3 Stage 2 search and filter rules.

    SCRUM-230: keyword search
    SCRUM-239: sport type filter
    SCRUM-249: meetup date filter
    """

    keyword = normalize_search_text(filters.get("keyword", ""))
    state_filter = filters.get("state", "")
    sport_type_filter = filters.get("sport_type", "")
    date_filter = filters.get("meetup_date", "")

    # SCRUM-230: Keyword search
    if keyword:
        searchable_text = build_meetup_search_text(meetup)
        keyword_terms = keyword.split()

        for term in keyword_terms:
            if term not in searchable_text:
                return False

    # Existing state filter
    if state_filter and state_filter != meetup.get("state", ""):
        return False

    # SCRUM-239: Sport type filter
    if sport_type_filter and sport_type_filter != meetup.get("sport_type", ""):
        return False

    # SCRUM-249: Date filter
    if date_filter and date_filter != meetup.get("meetup_date", ""):
        return False

    return True


def prepare_active_meetup_listing_item(meetup):
    """
    Prepare meetup data before sending it to active_meetups.html.
    This supports SCRUM-461 by calculating display values once only.
    """

    capacity = safe_int(meetup.get("capacity"), 0)
    joined_count = safe_int(meetup.get("joined_count"), 0)
    available_slots = calculate_available_slots(meetup)

    meetup["capacity"] = capacity
    meetup["joined_count"] = joined_count
    meetup["available_slots"] = available_slots
    meetup["is_full"] = available_slots <= 0

    if not meetup.get("title"):
        meetup["title"] = f"{meetup.get('sport_type', 'Sports')} Meetup"

    if not meetup.get("location"):
        meetup["location"] = build_location_from_meetup(meetup)

    return meetup


def build_location_from_meetup(meetup):
    """
    Build a readable location text if the meetup location field is missing.
    """

    location_parts = [
        meetup.get("venue_name", ""),
        meetup.get("address", ""),
        meetup.get("postcode", ""),
        meetup.get("state", ""),
    ]

    clean_parts = [part for part in location_parts if part]

    return ", ".join(clean_parts)

@app.route("/active-meetups")
def active_meetups():
    """
    Sprint 3 Stage 2

    SCRUM-230:
    Participant can search active meetups by keyword.

    SCRUM-239:
    Participant can filter active meetups by sport type.

    SCRUM-249:
    Participant can filter active meetups by meetup date.

    SCRUM-461:
    Meetup listings load quickly by loading only active meetups,
    excluding past meetups, applying filters in memory, and preparing
    display values once before rendering.
    """

    filters = get_active_meetup_filters()

    if db is None:
        return render_template(
            "active_meetups.html",
            meetups=[],
            filters=filters,
            sport_options=ALLOWED_SPORTS,
            firebase_error_message=firebase_error_message,
            db_connection_failed=True
        )

    filtered_meetups = []

    try:
        # SCRUM-461:
        # Load only active meetups from Firestore instead of loading all meetups.
        meetup_docs = db.collection("meetups").where("status", "==", "active").stream()

        for doc in meetup_docs:
            meetup = doc.to_dict() or {}
            meetup["id"] = doc.id

            # Hide and update past meetups before showing listing.
            if is_meetup_past(meetup):
                mark_meetup_as_past(doc.id)
                continue

            # SCRUM-230, SCRUM-239, SCRUM-249
            if not meetup_matches_active_filters(meetup, filters):
                continue

            meetup = prepare_active_meetup_listing_item(meetup)
            filtered_meetups.append(meetup)

    except Exception as e:
        flash(f"An error occurred while fetching meetups: {e}", "error")
        filtered_meetups = []

    # SCRUM-461:
    # Sort after filtering so the page displays upcoming meetups clearly.
    filtered_meetups.sort(
        key=lambda meetup: (
            meetup.get("meetup_date", ""),
            meetup.get("meetup_time", "")
        )
    )

    return render_template(
        "active_meetups.html",
        meetups=filtered_meetups,
        filters=filters,
        sport_options=ALLOWED_SPORTS,
        db_connection_failed=False
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


@app.route("/manage-meetups")
def manage_meetups():
    """
    Admin page to view all meetups (active, past, etc.).
    This is a new route to fix the BuildError.
    """
    if session.get("role") != "admin":
        flash("You must be an admin to access this page.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return render_template("manage_meetups.html", meetups=[])

    all_meetups = []
    try:
        meetup_docs = db.collection("meetups").stream()
        for doc in meetup_docs:
            meetup = doc.to_dict()
            meetup["id"] = doc.id
            all_meetups.append(meetup)
    except Exception as e:
        flash(f"An error occurred: {e}", "error")

    return render_template("manage_meetups.html", meetups=all_meetups)


@app.route("/meetup/<meetup_id>/edit", methods=["GET", "POST"])
def edit_meetup(meetup_id):

    current_role = session.get("role")
    current_user_id = session.get("user_id")

    if current_role not in ["organizer", "admin"]:
        flash("You do not have permission to edit meetups.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        if current_role == "admin":
            return redirect(url_for("manage_meetups"))
        return redirect(url_for("active_meetups"))

    meetup_ref = db.collection("meetups").document(meetup_id)
    meetup_doc = meetup_ref.get()

    if not meetup_doc.exists:
        flash("Meetup not found.", "error")
        if current_role == "admin":
            return redirect(url_for("manage_meetups"))
        return redirect(url_for("active_meetups"))

    meetup_data = meetup_doc.to_dict()
    meetup_data["id"] = meetup_id

    # SCRUM-432: Organizer can only edit own meetup.
    if current_role == "organizer" and current_user_id != meetup_data.get("organizer_id"):
        flash("You can only edit meetups that you have organized.", "error")
        return redirect(url_for("active_meetups"))

    # Organizer should only edit active meetups.
    if current_role == "organizer" and meetup_data.get("status") != "active":
        flash("Only active meetups can be edited by the organizer.", "error")
        return redirect(url_for("active_meetups"))

    if request.method == "POST":
        form_data = get_form_data_from_request()
        errors = validate_edit_meetup_form(form_data)

        if errors:
            for error in errors:
                flash(error, "error")

            form_data["id"] = meetup_id
            return render_template(
                "edit_meetup.html",
                form_data=form_data,
                meetup=meetup_data,
                sport_options=ALLOWED_SPORTS
            )

        updated_available_slots = int(form_data["capacity"]) - safe_int(meetup_data.get("joined_count"), 0)
        if updated_available_slots < 0:
            updated_available_slots = 0

        updated_data = {
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
            "available_slots": updated_available_slots,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        meetup_ref.update(updated_data)

        flash("Meetup updated successfully.", "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    return render_template(
        "edit_meetup.html",
        form_data=meetup_data,
        meetup=meetup_data,
        sport_options=ALLOWED_SPORTS
    )


@app.route("/meetup/<meetup_id>/cancel", methods=["POST"])
def cancel_meetup(meetup_id):
    """
    Sprint 3 Stage 1
    SCRUM-203: Organizer cancel my meetup.
    The meetup is not permanently deleted. It is marked as cancelled.
    """

    if session.get("role") != "organizer":
        flash("Only organizers can cancel their own meetups.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("active_meetups"))

    meetup_ref = db.collection("meetups").document(meetup_id)
    meetup_doc = meetup_ref.get()

    if not meetup_doc.exists:
        flash("Meetup not found.", "error")
        return redirect(url_for("active_meetups"))

    meetup = meetup_doc.to_dict()

    if meetup.get("organizer_id") != session.get("user_id"):
        flash("You can only cancel meetups that you have organized.", "error")
        return redirect(url_for("active_meetups"))

    if meetup.get("status") != "active":
        flash("Only active meetups can be cancelled.", "error")
        return redirect(url_for("active_meetups"))

    cancellation_reason = request.form.get("cancellation_reason", "").strip()

    meetup_ref.update({
        "status": "cancelled",
        "cancelled_by": session.get("user_id"),
        "cancelled_at": firestore.SERVER_TIMESTAMP,
        "cancellation_reason": cancellation_reason,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })

    flash("Meetup cancelled successfully. Participants will no longer see it as active.", "success")
    return redirect(url_for("active_meetups"))


@app.route("/meetup/<meetup_id>/participants")
def meetup_participants(meetup_id):
    """
    Sprint 3 Stage 1
    SCRUM-212: Organizer view participant list.
    SCRUM-432: Only the organizer who owns the meetup can view the participant list.
    Admin can also view it for moderation.
    """

    current_role = session.get("role")
    current_user_id = session.get("user_id")

    if current_role not in ["organizer", "admin"]:
        flash("Only organizers can view the participant list for a meetup.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("active_meetups"))

    meetup_ref = db.collection("meetups").document(meetup_id)
    meetup_doc = meetup_ref.get()

    if not meetup_doc.exists:
        flash("Meetup not found.", "error")
        return redirect(url_for("active_meetups"))

    meetup = meetup_doc.to_dict()
    meetup["id"] = meetup_id

    if current_role == "organizer" and meetup.get("organizer_id") != current_user_id:
        flash("You can only view participants for meetups that you have organized.", "error")
        return redirect(url_for("active_meetups"))

    participant_ids = []

    for participant_id in meetup.get("participant_ids", []) or []:
        if participant_id and participant_id not in participant_ids:
            participant_ids.append(participant_id)

    try:
        rsvp_docs = db.collection("rsvps").where("meetup_id", "==", meetup_id).stream()

        for rsvp_doc in rsvp_docs:
            rsvp = rsvp_doc.to_dict()
            rsvp_status = rsvp.get("status", "confirmed")
            participant_id = rsvp.get("participant_id")

            if rsvp_status in ["cancelled", "withdrawn", "removed"]:
                continue

            if participant_id and participant_id not in participant_ids:
                participant_ids.append(participant_id)

    except Exception:
        pass

    participants = []

    for participant_id in participant_ids:
        user_doc = db.collection("users").document(participant_id).get()

        if not user_doc.exists:
            continue

        user = user_doc.to_dict()

        if user.get("role") != "participant":
            continue

        if user.get("status", "active") != "active":
            continue

        participants.append({
            "user_id": user_doc.id,
            "full_name": user.get("full_name", ""),
            "sport_interest": user.get("sport_interest", ""),
            "skill_level": user.get("skill_level", ""),
            "state": user.get("state", ""),
            "status": user.get("status", "active"),
        })

    participants.sort(key=lambda participant: participant.get("full_name", "").lower())

    meetup["joined_count"] = len(participants)
    meetup["available_slots"] = calculate_available_slots(meetup)

    return render_template(
        "meetup_participants.html",
        meetup=meetup,
        participants=participants,
        participant_count=len(participants)
    )
    """

    Admin/Organizer page to edit an existing meetup.
    """
    if session.get("role") not in ["admin", "organizer"]:
        flash("You do not have permission to edit meetups.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("manage_meetups"))

    meetup_ref = db.collection("meetups").document(meetup_id)
    meetup_doc = meetup_ref.get()

    if not meetup_doc.exists:
        flash("Meetup not found.", "error")
        return redirect(url_for("manage_meetups"))

    meetup_data = meetup_doc.to_dict()

    # Security: Only allow an organizer to edit their own meetups
    if (session.get("role") == "organizer" and
            session.get("user_id") != meetup_data.get("organizer_id")):
        flash("You can only edit meetups that you have organized.", "error")
        return redirect(url_for("active_meetups"))

    if request.method == "POST":
        form_data = get_form_data_from_request()
        errors = validate_edit_meetup_form(form_data)

        if errors:
            for error in errors:
                flash(error, "error")
            # On validation error, we must repopulate the form with the
            # original, complete data from Firestore, not just the submitted data.
            # This prevents fields from appearing blank.
            original_meetup_data = meetup_doc.to_dict()
            original_meetup_data["id"] = meetup_id
            return render_template("edit_meetup.html", form_data=original_meetup_data, meetup=original_meetup_data, sport_options=ALLOWED_SPORTS)


        # Prepare data for update
        updated_data = {
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
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        meetup_ref.update(updated_data)
        flash("Meetup updated successfully.", "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    # For GET request, populate form with existing data
    form_data = meetup_doc.to_dict()
    form_data["id"] = meetup_id
    return render_template("edit_meetup.html", form_data=form_data, meetup=form_data, sport_options=ALLOWED_SPORTS)


@app.route("/meetup/<meetup_id>/delete", methods=["POST"])
def delete_meetup(meetup_id):
    """
    Admin-only route to permanently delete a meetup and its RSVPs.
    """
    if session.get("role") != "admin":
        flash("You do not have permission to delete meetups.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("manage_meetups"))

    try:
        meetup_ref = db.collection("meetups").document(meetup_id)
        if not meetup_ref.get().exists:
            flash("Meetup not found or already deleted.", "error")
            return redirect(url_for("manage_meetups"))

        # Best practice: Delete associated data in a batch operation.
        # This finds all RSVPs for the meetup and deletes them along with the meetup itself.
        batch = db.batch()
        rsvp_docs = db.collection("rsvps").where("meetup_id", "==", meetup_id).stream()
        for doc in rsvp_docs:
            batch.delete(doc.reference)

        batch.delete(meetup_ref)
        batch.commit()

        flash("Meetup and all associated RSVPs deleted successfully.", "success")

    except Exception as e:
        flash(f"An error occurred while deleting the meetup: {e}", "error")

    return redirect(url_for("manage_meetups"))

# =========================================================
# Admin Routes
# =========================================================

@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get("role") != "admin":
        flash("You must be an admin to access this page.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return render_template("admin_dashboard.html", users=[])

    all_users = []
    try:
        user_docs = db.collection("users").stream()
        for doc in user_docs:
            user = doc.to_dict()
            # Exclude admins from the list
            if user.get("role") != "admin":
                user["id"] = doc.id
                all_users.append(user)
    except Exception as e:
        flash(f"An error occurred while fetching users: {e}", "error")

    return render_template("admin_dashboard.html", users=all_users)


@app.route("/admin/manage-user/<user_id>")
def manage_user(user_id):
    if session.get("role") != "admin":
        flash("You must be an admin to access this page.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("admin_dashboard"))

    user_doc = db.collection("users").document(user_id).get()
    if not user_doc.exists:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    user = user_doc.to_dict()
    user["id"] = user_doc.id

    # Prevent editing of admin accounts
    if user.get("role") == "admin":
        flash("Admin accounts cannot be managed from this page.", "error")
        return redirect(url_for("admin_dashboard"))

    upcoming_meetups = []
    past_meetups = []

    try:
        # Find all meetups this user has joined
        meetup_docs = db.collection("meetups").where("participant_ids", "array_contains", user_id).stream()

        for doc in meetup_docs:
            meetup = doc.to_dict()
            meetup["id"] = doc.id

            if is_meetup_past(meetup):
                past_meetups.append(meetup)
            else:
                upcoming_meetups.append(meetup)

        # Sort meetups by date
        upcoming_meetups.sort(key=lambda m: (m.get("meetup_date", ""), m.get("meetup_time", "")))
        past_meetups.sort(key=lambda m: (m.get("meetup_date", ""), m.get("meetup_time", "")), reverse=True)

    except Exception as e:
        flash(f"An error occurred while fetching user's meetups: {e}", "error")

    return render_template("manage_user.html", user=user, upcoming_meetups=upcoming_meetups, past_meetups=past_meetups)


@app.route("/admin/toggle-user-status/<user_id>", methods=["POST"])
def toggle_user_status(user_id):
    if session.get("role") != "admin":
        flash("You do not have permission to perform this action.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("admin_dashboard"))

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()
    if user_doc.exists:
        user_data = user_doc.to_dict()

        if user_data.get("role") == "admin":
            flash("Admin account status cannot be changed.", "error")
            return redirect(url_for("admin_dashboard"))

        current_status = user_data.get("status", "active")
        new_status = "disabled" if current_status == "active" else "active"
        user_ref.update({"status": new_status, "updated_at": firestore.SERVER_TIMESTAMP})
        flash(f"User status changed to {new_status}.", "success")

    return redirect(url_for("manage_user", user_id=user_id))

@app.route("/admin/edit-user/<user_id>", methods=["POST"])
def admin_edit_user(user_id):
    if session.get("role") != "admin":
        flash("You do not have permission to perform this action.", "error")
        return redirect(url_for("index"))

    if not require_firebase():
        return redirect(url_for("manage_user", user_id=user_id))

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    user = user_doc.to_dict()

    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()

    errors = []
    update_data = {"updated_at": firestore.SERVER_TIMESTAMP}

    # Validate Email
    if not email or not is_valid_email(email):
        errors.append("Please enter a valid email address.")
    elif email != user.get("email") and email_already_registered(email):
        errors.append("This email is already registered by another user.")
    else:
        update_data["email"] = email

    # Validate Phone
    phone_clean = normalize_phone(phone)
    if not phone:
        errors.append("Phone number is required.")
    elif not phone_clean.isdigit():
        errors.append("Phone number can only contain numbers, spaces, or dashes.")
    elif len(phone_clean) < 10 or len(phone_clean) > 11:
        errors.append("Phone number must be 10 to 11 digits.")
    elif phone_clean != user.get("phone_clean") and phone_already_registered(phone_clean):
        errors.append("This phone number is already registered by another user.")
    else:
        update_data["phone"] = phone
        update_data["phone_clean"] = phone_clean

    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for("manage_user", user_id=user_id))

    user_ref.update(update_data)
    flash("User details updated successfully.", "success")
    return redirect(url_for("manage_user", user_id=user_id))


# =========================================================
# Sprint 2 Stage 2
# SCRUM-113: Participant View Other Participants' Profiles
# SCRUM-114: Participant View Organizers' Profiles
# SCRUM-115: Organizer View Own Profile Details
# =========================================================

def get_demo_other_participants():
    return [
        {
            "user_id": "participant_002",
            "role": "participant",
            "full_name": "Sport Member",
            "state": "Selangor",
            "sport_interest": "Football",
            "skill_level": "Intermediate",
            "status": "active",
        },
        {
            "user_id": "participant_003",
            "role": "participant",
            "full_name": "Badminton Player",
            "state": "Penang",
            "sport_interest": "Badminton",
            "skill_level": "Beginner",
            "status": "active",
        },
        {
            "user_id": "participant_004",
            "role": "participant",
            "full_name": "Running Buddy",
            "state": "Kuala Lumpur",
            "sport_interest": "Running",
            "skill_level": "Advanced",
            "status": "active",
        },
    ]


@app.route("/participants")
def participant_profiles():
    """
    SCRUM-113:
    Allow a registered participant to view other participants' profiles.
    Only public information is shown.
    """
    current_user_id = session.get("user_id")
    current_role = session.get("role")

    if not current_user_id or current_role != "participant":
        flash("Only participants can view this page.", "error")
        return render_template("message.html", message="Only participants can view this page.")

    if not require_firebase():
        demo_participants = get_demo_other_participants()
        return render_template(
            "participant_profiles.html",
            participants=demo_participants,
            filters={},
            sport_options=ALLOWED_SPORTS,
            skill_levels=SKILL_LEVELS
        )

    # Filter logic
    keyword = request.args.get("keyword", "").strip().lower()
    sport_interest = request.args.get("sport_interest", "").strip()
    skill_level = request.args.get("skill_level", "").strip()

    participants = []

    try:
        users_ref = db.collection("users").where("role", "==", "participant").stream()

        for user_doc in users_ref:
            participant = user_doc.to_dict()
            participant["user_id"] = user_doc.id

            # Do not show current user's own profile in the "other participants" list
            if participant["user_id"] == current_user_id:
                continue

            # Only show active participant profiles
            if participant.get("status") != "active":
                continue

            # Apply filters
            name = participant.get("full_name", "").lower()

            if keyword and keyword not in name:
                continue
            if sport_interest and sport_interest != participant.get("sport_interest"):
                continue
            if skill_level and skill_level != participant.get("skill_level"):
                continue

            # Only expose public profile information
            public_participant = {
                "user_id": participant.get("user_id", ""),
                "role": participant.get("role", "participant"),
                "full_name": participant.get("full_name", ""),
                "state": participant.get("state", ""),
                "sport_interest": participant.get("sport_interest", ""),
                "skill_level": participant.get("skill_level", ""),
                "status": participant.get("status", "active"),
            }

            participants.append(public_participant)

    except Exception as e:
        flash(f"Unable to load participant profiles: {e}", "error")

    filters = {
        "keyword": request.args.get("keyword", ""),
        "sport_interest": sport_interest,
        "skill_level": skill_level,
    }

    return render_template(
        "participant_profiles.html",
        participants=participants,
        filters=filters,
        sport_options=ALLOWED_SPORTS, skill_levels=SKILL_LEVELS
    )


@app.route("/participants/<user_id>", strict_slashes=False)
def view_participant_profile(user_id):
    """
    SCRUM-113:
    Allow participant to open and view another participant's public profile.
    """

    current_user_id = session.get("user_id")
    if not current_user_id:
        flash("You must be logged in to view participant profiles.", "error")
        return redirect(url_for("login", next=request.path))

    if user_id == current_user_id:
        flash("This is your own profile. Redirected to My Profile.", "warning")
        return render_template("message.html", message="This is your own profile. Please use the 'My Profile' page to view or edit it.")

    if not require_firebase():
        demo_profile = get_demo_other_participants()[0]
        return render_template(
            "public_participant_profile.html",
            profile=demo_profile,
            is_demo=True
        )

    try:
        user_doc = db.collection("users").document(user_id).get()

        if not user_doc.exists:
            flash("Participant profile not found.", "error")
            return render_template("message.html", message="Participant profile not found."), 200 # Explicitly return 200

        participant = user_doc.to_dict()
        participant["user_id"] = user_doc.id

        if participant.get("role") != "participant":
            flash("This profile is not a participant profile.", "error")
            return render_template("message.html", message="This profile is not a participant profile.")

        if participant.get("status") != "active":
            flash("This participant profile is not active.", "error")
            return render_template("message.html", message="This participant profile is not active.")

        # Only show public information
        public_profile = {
            "user_id": participant.get("user_id", user_doc.id),
            "role": "participant",
            "full_name": participant.get("full_name", ""),
            "state": participant.get("state", ""),
            "sport_interest": participant.get("sport_interest", ""),
            "skill_level": participant.get("skill_level", ""),
            "bio": participant.get("bio", ""),
            "status": participant.get("status", "active"),
        }

        return render_template(
            "public_profile.html",
            user=public_profile,
            is_demo=False
        )

    except Exception as e:
        flash(f"Unable to load participant profile: {e}", "error")
        return render_template("message.html", message=f"Unable to load participant profile: {e}"), 200


@app.route("/organizers")
def participant_organizer_profiles():
    """
    Allow a registered user (participant or organizer) to view a list of public organizer profiles.
    """
    if session.get("role") not in ["participant", "organizer"]: # Keep redirect for not logged in
        flash("You must be logged in to view organizer profiles.", "error") # This flash is redundant if redirecting to login
        return redirect(url_for("login", next=request.path))
    # Filter logic
    keyword = request.args.get("keyword", "").strip().lower()

    if not require_firebase():
        return render_template("participant_organizer_profiles.html", organizers=[], filters={})

    organizers = []
    try:
        users_ref = db.collection("users").where("role", "==", "organizer").stream()
        for user_doc in users_ref:
            organizer = user_doc.to_dict()

            if organizer.get("status") != "active":
                continue

            # Apply filters
            name = organizer.get("full_name", "").lower()
            org_name = organizer.get("organization_name", "").lower()

            if keyword and not (keyword in name or keyword in org_name):
                continue

            public_organizer = {
                "user_id": user_doc.id,
                "full_name": organizer.get("full_name", ""),
                "organization_name": organizer.get("organization_name", ""),
                "experience_years": organizer.get("experience_years", 0),
                "state": organizer.get("state", ""),
                "status": organizer.get("status", "active"),
            }
            organizers.append(public_organizer)

    except Exception as e:
        flash(f"Unable to load organizer profiles: {e}", "error")

    filters = {
        "keyword": request.args.get("keyword", ""),
    }

    return render_template("participant_organizer_profiles.html", organizers=organizers, filters=filters)


@app.route("/organizers/<user_id>", strict_slashes=False)
def participant_view_organizer_profile(user_id):
    """
    Allow a participant to view a single organizer's public profile.
    """
    if not session.get("user_id"):
        flash("You must be logged in to view this profile.", "error")
        return redirect(url_for("login", next=request.path))

    if not require_firebase():
        return render_template("message.html", message="Database connection failed.")

    try:
        user_doc = db.collection("users").document(user_id).get()

        if not user_doc.exists:
            flash("Organizer profile not found.", "error")
            return render_template("message.html", message="Organizer profile not found."), 200 # Explicitly return 200

        organizer = user_doc.to_dict()

        if organizer.get("role") != "organizer": # Changed flash to be more generic
            flash("This profile is not an organizer profile.", "error") # This flash is redundant if rendering message
            return render_template("message.html", message="This profile is not an organizer profile.")

        if organizer.get("status") != "active":
            flash("This organizer profile is not active.", "error") # This flash is redundant if rendering message
            return render_template("message.html", message="This organizer profile is not active.")

        public_profile = {
            "user_id": user_doc.id,
            "full_name": organizer.get("full_name", ""),
            "organization_name": organizer.get("organization_name", ""),
            "experience_years": organizer.get("experience_years", 0),
            "state": organizer.get("state", ""),
            "bio": organizer.get("bio", ""),
            "status": organizer.get("status", "active"),
        }

        return render_template(
            "public_profile.html",
            user=public_profile
        )

    except Exception as e:
        flash(f"Unable to load organizer profile: {e}", "error")
        return render_template("message.html", message=f"Unable to load organizer profile: {e}"), 200


# =========================================================
# Sprint 2 Stage 3
# SCRUM-116: Organizer View Participants' Profiles
# SCRUM-117: Organizer View Other Organizer Profiles
# =========================================================

@app.route("/organizer/participants")
def organizer_participant_profiles():
    """
    SCRUM-116:
    Allow organizer to view registered participants' public profiles.
    """

    if session.get("role") != "organizer":
        flash("Only organizers can view participant profiles.", "error")
        return redirect(url_for("login", next=request.path))

    if not require_firebase():
        return render_template("organizer_participant_profiles.html", participants=[], filters={}, sport_options=ALLOWED_SPORTS, skill_levels=SKILL_LEVELS)

    # Filter logic
    keyword = request.args.get("keyword", "").strip().lower()
    sport_interest = request.args.get("sport_interest", "").strip()
    skill_level = request.args.get("skill_level", "").strip()

    participants = []

    try:
        users_ref = db.collection("users").where("role", "==", "participant").stream()

        for user_doc in users_ref:
            participant = user_doc.to_dict()
            participant["user_id"] = user_doc.id

            if participant.get("status") != "active":
                continue

            # Apply filters
            name = participant.get("full_name", "").lower()

            if keyword and keyword not in name:
                continue
            if sport_interest and sport_interest != participant.get("sport_interest"):
                continue
            if skill_level and skill_level != participant.get("skill_level"):
                continue

            public_participant = {
                "user_id": participant.get("user_id", user_doc.id),
                "role": "participant",
                "full_name": participant.get("full_name", ""),
                "state": participant.get("state", ""),
                "sport_interest": participant.get("sport_interest", ""),
                "skill_level": participant.get("skill_level", ""),
                "status": participant.get("status", "active"),
            }

            participants.append(public_participant)

    except Exception as e:
        flash(f"Unable to load participant profiles: {e}", "error")

    filters = {
        "keyword": request.args.get("keyword", ""),
        "sport_interest": sport_interest,
        "skill_level": skill_level,
    }

    return render_template(
        "organizer_participant_profiles.html",
        participants=participants,
        filters=filters, sport_options=ALLOWED_SPORTS, skill_levels=SKILL_LEVELS
    )


@app.route("/organizer/participants/<user_id>", strict_slashes=False)
def organizer_view_participant_profile(user_id):
    """
    SCRUM-116:
    Allow organizer to open one participant's public profile.
    """
    if session.get("role") != "organizer": # This flash is redundant if redirecting to login
        flash("Only organizers can view participant profiles.", "error") # Changed flash to be more generic
        return redirect(url_for("login", next=request.path))

    if not require_firebase():
        return render_template("message.html", message="Database connection failed.")

    try:
        user_doc = db.collection("users").document(user_id).get()

        if not user_doc.exists:
            flash("Participant profile not found.", "error")
            return render_template("message.html", message="Participant profile not found."), 200 # Explicitly return 200

        participant = user_doc.to_dict()
        participant["user_id"] = user_doc.id
        
        if participant.get("role") != "participant": # Changed flash to be more generic
            flash("This profile is not a participant profile.", "error")
            return render_template("message.html", message="This profile is not a participant profile.")

        if participant.get("status") != "active":
            flash("This participant profile is not active.", "error")
            return render_template("message.html", message="This participant profile is not active.")

        public_profile = {
            "user_id": participant.get("user_id", user_doc.id),
            "role": "participant",
            "full_name": participant.get("full_name", ""),
            "state": participant.get("state", ""),
            "sport_interest": participant.get("sport_interest", ""),
            "skill_level": participant.get("skill_level", ""),
            "bio": participant.get("bio", ""),
            "status": participant.get("status", "active"),
        }

        return render_template(
            "public_profile.html",
            user=public_profile
        )

    except Exception as e:
        flash(f"Unable to load participant profile: {e}", "error")
        return render_template("message.html", message=f"Unable to load participant profile: {e}"), 200


@app.route("/organizer/organizers")
def organizer_organizer_profiles():
    """
    SCRUM-117:
    Allow organizer to view other organizers' public profiles.
    Current organizer's own profile is not shown.
    """

    if session.get("role") != "organizer":
        flash("Only organizers can view other organizer profiles.", "error")
        return redirect(url_for("login", next=request.path))

    if not require_firebase():
        return render_template("organizer_organizer_profiles.html", organizers=[], filters={})

    current_user_id = session.get("user_id")
    organizers = []

    # Filter logic
    keyword = request.args.get("keyword", "").strip().lower()

    try:
        users_ref = db.collection("users").where("role", "==", "organizer").stream()

        for user_doc in users_ref:
            organizer = user_doc.to_dict()
            organizer["user_id"] = user_doc.id

            if organizer["user_id"] == current_user_id:
                continue

            if organizer.get("status") != "active":
                continue

            # Apply filters
            name = organizer.get("full_name", "").lower()
            org_name = organizer.get("organization_name", "").lower()

            if keyword and not (keyword in name or keyword in org_name):
                continue

            public_organizer = {
                "user_id": organizer.get("user_id", user_doc.id),
                "role": "organizer",
                "full_name": organizer.get("full_name", ""),
                "state": organizer.get("state", ""),
                "organization_name": organizer.get("organization_name", ""),
                "experience_years": organizer.get("experience_years", 0),
                "bio": organizer.get("bio", ""),
                "status": organizer.get("status", "active"),
            }

            organizers.append(public_organizer)

    except Exception as e:
        flash(f"Unable to load organizer profiles: {e}", "error")

    filters = {
        "keyword": request.args.get("keyword", ""),
    }

    return render_template(
        "organizer_organizer_profiles.html",
        organizers=organizers, filters=filters
    )


@app.route("/organizer/organizers/<user_id>", strict_slashes=False)
def organizer_view_organizer_profile(user_id):
    """
    SCRUM-117:
    Allow organizer to open another organizer's public profile.
    """
    if session.get("role") != "organizer": # This flash is redundant if redirecting to login
        flash("Only organizers can view other organizer profiles.", "error")
        return redirect(url_for("login", next=request.path))

    current_user_id = session.get("user_id")

    if user_id == current_user_id:
        flash("This is your own organizer profile.", "warning")
        return render_template("message.html", message="This is your own organizer profile. Please use the 'My Profile' page to view or edit it.")

    if not require_firebase():
        return render_template("message.html", message="Database connection failed."), 200 # Changed redirect to render_template with 200

    try:
        user_doc = db.collection("users").document(user_id).get()

        if not user_doc.exists:
            flash("Organizer profile not found.", "error")
            return render_template("message.html", message="Organizer profile not found."), 200

        organizer = user_doc.to_dict()
        organizer["user_id"] = user_doc.id

        if organizer.get("role") != "organizer": # Changed flash to be more generic
            flash("This profile is not an organizer profile.", "error")
            return render_template("message.html", message="This profile is not an organizer profile.")

        if organizer.get("status") != "active": # Changed flash to be more generic
            flash("This organizer profile is not active.", "error")
            return render_template("message.html", message="This organizer profile is not active.")

        public_profile = {
            "user_id": organizer.get("user_id", user_doc.id),
            "role": "organizer",
            "full_name": organizer.get("full_name", ""),
            "state": organizer.get("state", ""),
            "organization_name": organizer.get("organization_name", ""),
            "experience_years": organizer.get("experience_years", 0),
            "bio": organizer.get("bio", ""),
            "status": organizer.get("status", "active"),
        }

        return render_template(
            "public_profile.html",
            user=public_profile
        )

    except Exception as e:
        flash(f"Unable to load organizer profile: {e}", "error")
        return render_template("message.html", message=f"Unable to load organizer profile: {e}"), 200

if __name__ == "__main__":
    app.run(debug=True)
