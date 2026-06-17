import base64
import hashlib
import os
import uuid

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from database import add_user, get_all_users, get_user, init_db, update_last_login
from face_utils import verify_faces

app = Flask(__name__)
app.secret_key = "fr-secret-key-2024"

FACES_DIR = "faces"
os.makedirs(FACES_DIR, exist_ok=True)


def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()


def _save_b64(b64_data, path):
    if "," in b64_data:
        b64_data = b64_data.split(",")[1]
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_data))


# ------------------------------------------------------------------ pages

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/signup")
def signup():
    return render_template("signup.html")


@app.route("/login")
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/verify")
def verify():
    if "pending_user" not in session:
        return redirect(url_for("login"))
    return render_template("verify.html", username=session["pending_user"]["name"])


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    users = get_all_users()
    return render_template("dashboard.html", current_user=session["user"], users=users)


# ------------------------------------------------------------------ API

@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.json
    name = (data.get("first_name") or "").strip()
    pw = data.get("password", "")
    confirm = data.get("confirm_password", "")
    face_b64 = data.get("face_image", "")

    if not name:
        return jsonify(success=False, message="First name is required")
    if len(pw) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")
    if pw != confirm:
        return jsonify(success=False, message="Passwords do not match")
    if not face_b64:
        return jsonify(success=False, message="Please capture your face before signing up")
    if get_user(name):
        return jsonify(success=False, message=f"'{name}' is already registered")

    face_path = os.path.join(FACES_DIR, f"{name.lower()}.jpg")
    try:
        _save_b64(face_b64, face_path)
    except Exception as e:
        return jsonify(success=False, message=f"Could not save face image: {e}")

    if not add_user(name, _hash(pw), face_path):
        if os.path.exists(face_path):
            os.remove(face_path)
        return jsonify(success=False, message="Could not create account — try again")

    return jsonify(success=True, message=f"Account created for {name.title()}!", redirect="/login")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    name = (data.get("first_name") or "").strip()
    pw = data.get("password", "")

    if not name or not pw:
        return jsonify(success=False, message="Please fill in all fields")

    user = get_user(name)
    if not user or user[2] != _hash(pw):
        return jsonify(success=False, message="Invalid name or password")

    session["pending_user"] = {"id": user[0], "name": user[1], "face_path": user[3]}
    return jsonify(success=True, redirect="/verify")


@app.route("/api/verify", methods=["POST"])
def api_verify():
    if "pending_user" not in session:
        return jsonify(success=False, message="Session expired — please login again")

    face_b64 = (request.json or {}).get("face_image", "")
    if not face_b64:
        return jsonify(success=False, message="No image received")

    stored_path = session["pending_user"]["face_path"]
    tmp = f"_tmp_{uuid.uuid4().hex}.jpg"
    try:
        _save_b64(face_b64, tmp)
        verified, detail = verify_faces(tmp, stored_path)
    except Exception as e:
        verified, detail = False, str(e)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    if verified:
        u = session.pop("pending_user")
        session["user"] = {"id": u["id"], "name": u["name"]}
        update_last_login(u["name"])
        return jsonify(success=True, redirect="/dashboard")

    return jsonify(success=False, message=f"Face not recognised. {detail}")


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify(success=True, redirect="/")


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
