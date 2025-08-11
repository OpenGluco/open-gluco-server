from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from ..server import token_required
from ..db_conn import get_conn
import psycopg

bp = Blueprint("CGMCredentials", __name__)
db_conn = get_conn()


@bp.route("/CGMCredentials", methods=['POST', 'GET'])
@token_required
def credentials(payload):

    if request.method == 'POST':
        data = request.get_json()

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO connections (user_id, username, password, type, region) VALUES (%s, %s, %s, %s, %s)",
                    (payload["user_id"], data.get("username"), generate_password_hash(
                        data.get("password")), data.get("type"), data.get("region"))
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
                    "SELECT username, type, region FROM connections WHERE user_id=%s",
                    (payload["user_id"],)
                )
                result = cur.fetchall()
            if result is None:
                return jsonify({"error": "Cannot find any connection for this user."}), 204
            print(result)
            return jsonify({"message": f"Connections for user {payload['user_id']}", "data": result}), 200

        except Exception as e:
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500
