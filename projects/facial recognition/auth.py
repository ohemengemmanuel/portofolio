import hashlib
import os
from database import add_user, get_user
from face_utils import capture_face, capture_and_verify


def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()


def sign_up(first_name, password, confirm_password):
    """
    Returns (success: bool, message: str).
    Validates inputs → enrolls face → saves user to DB.
    """
    first_name = first_name.strip()
    if not first_name:
        return False, "First name cannot be empty"
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    if password != confirm_password:
        return False, "Passwords do not match"
    if get_user(first_name):
        return False, f"'{first_name}' is already registered"

    face_path, msg = capture_face(first_name)
    if not face_path:
        return False, f"Face enrollment failed: {msg}"

    if not add_user(first_name, _hash(password), face_path):
        if os.path.exists(face_path):
            os.remove(face_path)
        return False, "Could not save account — please try again"

    return True, f"Account created for {first_name.title()}!"


def login(first_name, password):
    """
    Returns (success: bool, message: str, user_row | None).

    Step 1 — credential check (name + password).
    Step 2 — face verification only for the matched user.
    This avoids scanning the whole database.
    """
    first_name = first_name.strip()
    if not first_name or not password:
        return False, "Please fill in all fields", None

    # Step 1: lightweight DB lookup
    user = get_user(first_name)
    if not user or user[2] != _hash(password):
        return False, "Invalid name or password", None

    # Step 2: 1-to-1 face verification for this specific user
    face_path = user[3]
    if not os.path.exists(face_path):
        return False, "Enrolled face image not found — contact admin", None

    verified, detail = capture_and_verify(face_path)
    if verified:
        return True, f"Welcome back, {user[1].title()}!", user

    return False, f"Face not recognised. {detail}", None
