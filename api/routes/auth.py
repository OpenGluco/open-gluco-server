from flask import Blueprint, request, jsonify

from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import psycopg
import jwt
import os
from datetime import datetime, timedelta
from ..db_conn import get_conn

from email.mime.text import MIMEText
from datetime import datetime, timedelta
import smtplib

bp = Blueprint("auth", __name__)

db_conn = get_conn()

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")
DOMAIN_NAME = os.getenv("DOMAIN_NAME")


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email et password requis"}), 400

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, password, verified FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
        if result is None:
            return jsonify({"error": "Wrong email"}), 404
        user_id, stored_hash, verified = result
        if check_password_hash(stored_hash, password):
            payload = {
                "user_id": user_id,
                "email": email,
                "exp": int(
                    (datetime.now() + timedelta(hours=2)).timestamp()
                ),  # token expire dans 2h
            }
            token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
            return jsonify({"token": token, "verified": verified}), 200
        else:
            return jsonify({"error": "Wrong password"}), 401

    except Exception as e:
        return jsonify({"error": f"{str(e)}"}), 500


@bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data supplied."}), 400

    name = data.get("name")
    surname = data.get("surname")
    email = data.get("email")
    password = generate_password_hash(data.get("password"))

    send_verification_email(email, name)

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (name, surname, email, password, created_at) VALUES (%s, %s, %s, %s, %s)",
                (name, surname, email, password, datetime.now())
            )
        db_conn.commit()
        return jsonify({"message": "User registered."}), 201
    except psycopg.errors.UniqueViolation:
        db_conn.rollback()
        return jsonify({"error": "User already exists."}), 409
    except Exception as e:
        db_conn.rollback()
        return jsonify({"error": f"Internal Error : {str(e)}"}), 500


@bp.route("/verify", methods=["GET"])
def verify_email():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Missing token"}), 400

    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        email = data["email"]

        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET verified = TRUE WHERE email = %s", (email,))
        db_conn.commit()

        return jsonify({"message": "Successfully verified account."}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Expired link"}), 400
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 400


def send_verification_email(to_email, name):
    # 1️⃣ Créer un token qui expire dans 24h
    payload = {
        "email": to_email,
        "exp": datetime.now() + timedelta(hours=24)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    # 2️⃣ Lien de vérif (à adapter à ton domaine)
    verify_link = f"http://{DOMAIN_NAME}:5000/verify?token={token}"

    # 3️⃣ Préparer le mail
    subject = "[OpenGluco] Verify your account"
    body = f"Hello {name} and welcome to Opengluco!\n\nPlease follow the link below to verify your account:\n\n{verify_link}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_FROM")
    msg["To"] = to_email

    # 4️⃣ Envoi du mail
    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)

    print(f"✅ Verification email sent to {to_email}")
