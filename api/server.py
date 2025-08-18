import importlib
import os
import pkgutil
import threading
from functools import wraps
from time import time

import jwt
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Blueprint, Flask, jsonify, request
from flask_cors import CORS
from libre_link_up import LibreLinkUpClient
from pydexcom import Dexcom

from . import routes
from .db_conn import get_conn, init_db
from .influx import init_influx_bucket, write_to_influx

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")
FERNET_KEY = os.getenv("FERNET_KEY").encode()
f = Fernet(FERNET_KEY)

package = routes


def create_app(ip: str = "0.0.0.0", port: int = 5000):
    app = Flask(__name__)
    CORS(app, resources={
         r"/*": {"origins": [os.getenv("FRONTEND_URL", "http://localhost:5173/")]}}, supports_credentials=True)
    global db_conn

    for loader, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_name}")
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, Blueprint):
                app.register_blueprint(obj)
                print(
                    f"✅ Routes '{obj.name}' registered from {module_name}.py")

    init_db()
    init_influx_bucket()
    db_conn = get_conn()
    actual_data = []
    last_check_time = int(time())

    dexcom_users = []
    libre_users = []

    # print(read_from_influx("123", "glucose"))

    @app.route("/")
    def hello_world():
        return {'message': "Welcome to the OpenGluco API!"}, 200

    # @app.route("/getCGMData")
    # def getCGMData():
    #     global actual_data,last_check_time
    #     return {'time':last_check_time,
    #             'data':actual_data}

    def actualize_CGM():
        print("new data approaching %s" % (int(time())))
        global actual_data, last_check_time
        last_check_time = int(time())
        actual_data = []

        raw_dexcom_users = get_connections_by_type("Dexcom")
        raw_libre_users = get_connections_by_type("LibreLinkUp")

        for user in raw_dexcom_users:
            if user['id'] not in raw_dexcom_users:
                dexcom_users.append({user['id']: Dexcom(
                    username=user['username'],
                    password=f.decrypt(user['password'].encode()).decode(),
                    region=user['region']), "user_id": user["user_id"]})
        for user in raw_libre_users:
            if not any(u["user_id"] == user["user_id"] for u in libre_users):
                libre_users.append({user['id']: LibreLinkUpClient(
                    username=user['username'],
                    password=f.decrypt(user['password'].encode()).decode(),
                    url=f"https://api-{user['region']}.libreview.io",
                    version="4.14.0",
                ), "user_id": user["user_id"]})

        for libre_user in libre_users:
            print("user", libre_user["user_id"])
            for libre_key in libre_user:
                if type(libre_user[libre_key]) is LibreLinkUpClient:
                    write_to_influx(
                        measurement="glucose",
                        tags={
                            "user_id": libre_user["user_id"], "device": "LibreLinkUp"},
                        fields={"value": fetch_data_with_relogin(
                            libre_user[libre_key])},
                    )
        for dexcom_user in dexcom_users:
            for dexcom_key in dexcom_user:
                if type(dexcom_user[dexcom_key]) is Dexcom:
                    write_to_influx(
                        measurement="glucose",
                        tags={
                            "user_id": dexcom_user["user_id"], "device": "Dexcom"},
                        fields={
                            "value": dexcom_users[dexcom_key].get_current_glucose_reading().mmol},
                    )

        threading.Timer(60, actualize_CGM).start()

    def get_connections_by_type(conn_type):
        """
        Get all the connections coming from the "connections" table that are of the specified type.
        :param conn_type: string, connection type (ex: "Dexcom", "LibreLinkUp", "Medtronics")
        :return: dict list
        """
        try:
            with db_conn.cursor() as cur:
                cur.execute("""
                    SELECT id, user_id, username, password, type, region
                    FROM connections
                    WHERE type = %s
                """, (conn_type,))

                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]

                results = [dict(zip(columns, row)) for row in rows]
                return results

        except Exception as e:
            print(f"❌ Reading error: {e}")
            return []

    def fetch_data_with_relogin(client):
        try:
            return client.get_raw_connection()['glucoseMeasurement']['Value']
        except requests.HTTPError as e:
            if e.response.status_code in (400, 401, 403):
                print("Expired token, trying to reconnect...")
                client.login()
                return client.get_raw_connection()['glucoseMeasurement']['Value']
            else:
                raise

    actualize_CGM()

    return app


# Route token protection
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'opengluco_token' in request.cookies:
            token = request.cookies.get('opengluco_token')

        if not token:
            return jsonify({"error": "Missing token"}), 401

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Expired token"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT last_password_change FROM users WHERE id=%s", (payload["user_id"],))
            last_pwd_change = cur.fetchone()[0]

        # print(int(last_pwd_change.timestamp()), payload["iat"])
        if last_pwd_change and payload["iat"] < int(last_pwd_change.timestamp()):
            return jsonify({"error": "Token invalid due to password change"}), 401

        # Get the payload to the route handler
        return f(payload, *args, **kwargs)
    return decorated
