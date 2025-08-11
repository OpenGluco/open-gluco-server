from flask import Blueprint, request, jsonify

from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import psycopg
import jwt
import os
from datetime import datetime, timedelta
from ..db_conn import get_conn

bp = Blueprint("auth", __name__)

db_conn = get_conn()

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")


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
                "SELECT id, password FROM users WHERE email = %s", (email,))
            result = cur.fetchone()
        if result is None:
            return jsonify({"error": "Nom d'utilisateur incorrect"}), 404
        user_id, stored_hash = result
        if check_password_hash(stored_hash, password):
            payload = {
                "user_id": user_id,
                "email": email,
                "exp": int(
                    (datetime.now() + timedelta(hours=2)).timestamp()
                ),  # token expire dans 2h
            }
            token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
            return jsonify({"token": token}), 200
        else:
            return jsonify({"error": "Mot de passe incorrect"}), 401

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
