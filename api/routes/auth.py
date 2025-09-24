import hashlib
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import jwt
import psycopg
from dotenv import load_dotenv
from flask import Blueprint, jsonify, make_response, request
from werkzeug.security import check_password_hash, generate_password_hash

from ..db_conn import get_conn
from ..server import token_required

bp = Blueprint("auth", __name__)

db_conn = get_conn()

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")
DOMAIN_NAME = os.getenv("DOMAIN_NAME")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173/")

HTTPS_ENABLED = os.getenv("HTTPS", "false").lower() == "true"


@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    remember_me = data.get("remember_me", False)

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
                "iat": int(datetime.now().timestamp()),
                "exp": int(
                    (datetime.now() + timedelta(hours=2)).timestamp()
                ),  # token expire dans 2h
            }
            token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
            resp = make_response(
                jsonify({"message": "Login successful", "verified": verified}))
            resp.set_cookie(
                "opengluco_token",
                token,
                httponly=True,
                secure=HTTPS_ENABLED,
                samesite="Strict"
            )

            if remember_me:
                raw_token = os.urandom(32).hex()
                token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

                expires = datetime.now() + timedelta(days=91)
                with db_conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO remember_tokens (user_id, token_hash, expires_at, user_agent, ip_address) VALUES (%s, %s, %s, %s, %s)",
                        (user_id, token_hash, expires,
                         request.user_agent.string, request.remote_addr)
                    )
                db_conn.commit()

                resp.set_cookie(
                    "opengluco_remember_me",
                    raw_token,
                    httponly=True,
                    secure=True,
                    samesite="Strict",
                    expires=expires
                )

            return resp, 200
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

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
        if result is not None:
            return jsonify({"error": "Email already in use"}), 409

    except Exception as e:
        return jsonify({"error": f"{str(e)}"}), 500

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


@bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"message": "logged out"}))
    resp.delete_cookie("opengluco_token", samesite="Strict",
                       secure=HTTPS_ENABLED)
    raw_token = request.cookies.get("opengluco_remember_me")

    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM remember_tokens WHERE token_hash = %s",
                    (token_hash,)
                )
                # TODO: fix bug, suppression marche pas
            db_conn.commit()
        except Exception as e:
            db_conn.rollback()
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500

    resp.delete_cookie("opengluco_remember_me",
                       samesite="Strict", secure=HTTPS_ENABLED)
    return resp, 200


@bp.route("/forgot_password", methods=["GET"])
def forgot_password():
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Missing email"}), 400

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT name, surname, email, id FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
        if result is None:
            return jsonify({"error": "User does not exist"}), 404

        name, surname, email, user_id = result

        send_password_reset_email(email, user_id, name)

        return jsonify({"message": "✅ Email sent."}), 200

    except Exception as e:
        return jsonify({"error": f"Internal error: {e}"}), 500


@bp.route("/password", methods=["PATCH"])
def update_password():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data supplied."}), 400

    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Missing token"}), 400

    try:
        jwt_data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = jwt_data["user_id"]
        password = generate_password_hash(data.get("password"))

        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password = %s, last_password_change = %s WHERE id = %s", (password, datetime.now(), user_id))
        db_conn.commit()

        return jsonify({"message": "Successfully changed password."}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Expired link"}), 400
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 400


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


@bp.route("/ask_verify", methods=["GET"])
@token_required
def ask_verify(payload):

    try:
        user_id = payload["user_id"]

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT name, email FROM users WHERE id = %s", (user_id,))
            result = cur.fetchone()
        if result is None:
            return jsonify({"error": "User does not exist"}), 404

        name, email = result

        send_verification_email(email, name)

        return jsonify({"message": "Successfully sent verification email."}), 200

    except Exception as e:
        return jsonify({"error": f"Internal error: {e}"}), 500


def send_verification_email(to_email, name):
    payload = {
        "email": to_email,
        "exp": datetime.now() + timedelta(hours=24)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    verify_link = f"{FRONTEND_URL}/verify-email?token={token}"

    subject = "[OpenGluco] Verify your account"
    body = f"Hello {name} and welcome to Opengluco!\n\nPlease follow the link below to verify your account:\n\n{verify_link}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_FROM")
    msg["To"] = to_email

    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as server:
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)

    # print(f"✅ Verification email sent to {to_email}")


def send_password_reset_email(to_email, user_id, name):
    payload = {
        "email": to_email,
        "user_id": user_id,
        "iat": int(datetime.now().timestamp()),
        "exp": datetime.now() + timedelta(hours=24)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    reset_link = f"{FRONTEND_URL}/password?token={token}"

    subject = "[OpenGluco] Reset your password"
    body = f"Hello {name}!\n\nPlease follow the link below to reset your password:\n\n{reset_link}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_FROM")
    msg["To"] = to_email

    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT"))) as server:
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        server.send_message(msg)

    # print(f"✅ Verification email sent to {to_email}")
