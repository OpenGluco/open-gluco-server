from flask import Blueprint, jsonify, request

from ..db_conn import get_conn
from ..server import token_required

bp = Blueprint("user", __name__)

db_conn = get_conn()


@bp.route("/user", methods=["GET"])
@token_required
def user(payload):
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT name, surname, email FROM users WHERE id = %s", (payload["user_id"],))
            result = cur.fetchone()

        if result is None:
            return jsonify({"error": "Wrong user_id"}), 404
        name, surname, email = result

        return jsonify({"message": "Successfully verified account.", "data": {"name": name, "surname": surname, "email": email}}), 200

    except Exception as e:
        return jsonify({"error": f"Internal Error : {str(e)}"}), 500
