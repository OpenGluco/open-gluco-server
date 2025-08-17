import os

import psycopg
from cryptography.fernet import Fernet
from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from ..db_conn import get_conn
from ..server import token_required

bp = Blueprint("CGMCredentials", __name__)
db_conn = get_conn()

FERNET_KEY = os.getenv("FERNET_KEY").encode()
f = Fernet(FERNET_KEY)


@bp.route("/CGMCredentials", methods=['POST', 'GET', 'DELETE'])
@token_required
def credentials(payload):

    if request.method == 'POST':
        data = request.get_json()

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO connections (user_id, username, password, type, region) VALUES (%s, %s, %s, %s, %s)",
                    (payload["user_id"], data.get("username"), f.encrypt(data.get("password").encode()).decode(),
                     data.get("type"), data.get("region"))
                )
            db_conn.commit()
            return jsonify({"message": f"Connection added to user {payload['user_id']}."}), 201

        except psycopg.errors.UniqueViolation:
            db_conn.rollback()
            return jsonify({"error": "Connection already exists."}), 409

        except Exception as e:
            db_conn.rollback()
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500

    elif request.method == 'GET':
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, type, region FROM connections WHERE user_id=%s",
                    (payload["user_id"],)
                )
                result = cur.fetchall()
            if result is None:
                return jsonify({"error": "Cannot find any connection for this user."}), 204
            return jsonify({"message": f"Connections for user {payload['user_id']}", "data": result}), 200

        except Exception as e:
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500

    elif request.method == 'DELETE':
        try:
            data = request.get_json()

            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT c.type, u.name FROM connections c JOIN users u ON c.user_id = u.id WHERE c.id=%s",
                    (data.get("id"),)
                )
                result = cur.fetchone()
                if result is None:
                    return jsonify({"error": "Cannot find any connection for user."}), 204

                c_type, c_name = result

                cur.execute(
                    "DELETE FROM connections WHERE id=%s",
                    (data.get("id"),)
                )
            db_conn.commit()
            return jsonify({"message": f"Connection {c_type} deleted for user {c_name}."}), 200

        except Exception as e:
            db_conn.rollback()
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500
