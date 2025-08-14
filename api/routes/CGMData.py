from flask import Blueprint, jsonify, request

from ..db_conn import get_conn
from ..influx import read_from_influx
from ..server import token_required

bp = Blueprint("CGMData", __name__)
db_conn = get_conn()


@bp.route("/CGMData", methods=['GET'])
@token_required
def cgm_data(payload):
    try:
        data = read_from_influx(f"{payload["user_id"]}", "glucose")
        return jsonify({"message": f"CGM Data for user {payload['user_id']}", "data": data}), 200

    except Exception as e:
        return jsonify({"error": f"Internal Error : {str(e)}"}), 500
