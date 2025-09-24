import hashlib
import importlib
import os
import pkgutil
import threading
from datetime import datetime, timedelta
from functools import wraps
from time import time

import jwt
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Blueprint, Flask, g, jsonify, make_response, request
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
        global actual_data, last_check_time
        last_check_time = int(time())
        actual_data = []

        raw_dexcom_users = get_connections_by_type("Dexcom")
        raw_libre_users = get_connections_by_type("LibreLinkUp")

        # Removing users not in database anymore
        for user in dexcom_users:
            if not any(u["user_id"] == user["user_id"] for u in raw_dexcom_users):
                dexcom_users.remove(user)
        for user in libre_users:
            if not any(u["user_id"] == user["user_id"] for u in raw_libre_users):
                libre_users.remove(user)

        # Adding new users to actualization list
        for user in raw_dexcom_users:
            if not any(u["user_id"] == user["user_id"] for u in dexcom_users):
                region = user['region']
                if not (user['region'] == 'us' and user['region'] == 'jp'):
                    region = 'ous'
                dexcom_users.append({user['id']: Dexcom(
                    username=user['username'],
                    password=f.decrypt(user['password'].encode()).decode(),
                    region=region), "user_id": user["user_id"]})
        for user in raw_libre_users:
            if not any(u["user_id"] == user["user_id"] for u in libre_users):
                libre_users.append({user['id']: LibreLinkUpClient(
                    username=user['username'],
                    password=f.decrypt(user['password'].encode()).decode(),
                    url=f"https://api-{user['region']}.libreview.io",
                    version="4.14.0",
                ), "user_id": user["user_id"]})

        # Actualize CGM Data
        for libre_user in libre_users:
            for libre_key in libre_user:
                if type(libre_user[libre_key]) is LibreLinkUpClient:
                    data = fetch_data_with_relogin(libre_user[libre_key])
                    if data is not None:
                        write_to_influx(
                            measurement="glucose",
                            tags={
                                "user_id": libre_user["user_id"], "device": "LibreLinkUp"},
                            fields={"value": data},
                        )
        for dexcom_user in dexcom_users:
            for dexcom_key in dexcom_user:
                if type(dexcom_user[dexcom_key]) is Dexcom:
                    glucose_reading = None
                    try:
                        glucose_reading = dexcom_user[dexcom_key].get_current_glucose_reading(
                        )
                    except Exception as e:
                        glucose_reading = None
                    if glucose_reading is not None:
                        write_to_influx(
                            measurement="glucose",
                            tags={
                                "user_id": dexcom_user["user_id"], "device": "Dexcom"},
                            fields={
                                "value": glucose_reading.mmol},
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

    def fetch_data_with_relogin(client: LibreLinkUpClient):
        try:
            connection = client.get_raw_connection()
            return client.get_raw_connection()['glucoseMeasurement']['Value']
        except Exception as e:
            if type(e) is requests.HTTPError:
                if e.response.status_code in (400, 401, 403):
                    client.login()
                    try:
                        connection = client.get_raw_connection()
                        return connection['glucoseMeasurement']['Value']
                    except Exception as e:
                        return None
                else:
                    print(e)
            else:
                print(e)

    @app.before_request
    def auto_refresh_from_remember_me():
        # on ignore certains endpoints
        if request.endpoint in ("login", "signup", "forgot_password", "password", "verify"):
            return

        # Si déjà un JWT présent, on ne touche pas
        if "opengluco_token" in request.cookies:
            return

        # Sinon, on regarde s’il y a un cookie remember_me
        raw_token = request.cookies.get("opengluco_remember_me")
        if not raw_token:
            return  # pas de session persistante

        try:
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT r.user_id, r.expires_at, u.email, r.id, r.expires_at FROM remember_tokens r JOIN users u ON r.user_id = u.id WHERE r.token_hash=%s", (token_hash,))
                result = cur.fetchone()
            if result is None:
                return jsonify({"error": "User or token does not exist"}), 404
        except Exception as e:
            print(e)
            return jsonify({"error": "Internal server error"}), 500

        user_id, expires_at, email, r_id, r_expires_at = result

        if result and expires_at > datetime.now():
            # On recrée un nouveau JWT
            payload = {
                "user_id": user_id,
                "email": email,
                "iat": int(datetime.now().timestamp()),
                "exp": int(
                    (datetime.now() + timedelta(hours=2)).timestamp()
                ),  # token expire dans 2h
            }
            new_jwt = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

            # rotation du remember_me pour éviter la réutilisation
            raw_new_remember = os.urandom(32).hex()
            new_remember = hashlib.sha256(
                raw_new_remember.encode()).hexdigest()
            try:
                with db_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE remember_tokens SET token_hash = %s WHERE id = %s", (new_remember, r_id))
                db_conn.commit()
            except Exception as e:
                print(e)
                return jsonify({"error": "Internal server error"}), 500

            request.cookies = request.cookies.to_dict()
            request.cookies["opengluco_token"] = new_jwt

            g.refresh_cookies = {
                "opengluco_token": {"value": new_jwt, "max_age": None, "expires": None, "samesite": "Lax"},
                "opengluco_remember_me": {"value": raw_new_remember, "expires": expires_at, "samesite": "Strict"}
            }

        return None

    @app.after_request
    def attach_refresh_cookies(response):
        HTTPS_ENABLED = os.getenv("HTTPS", "false").lower() == "true"
        cookies = getattr(g, "refresh_cookies", None)
        if not cookies:
            return response

        # Cookie JWT
        tk = cookies["opengluco_token"]
        response.set_cookie(
            "opengluco_token",
            tk["value"],
            httponly=True,
            secure=HTTPS_ENABLED,
            samesite="Strict"
        )

        # Cookie remember_me
        rm = cookies["opengluco_remember_me"]
        response.set_cookie(
            "opengluco_remember_me",
            rm["value"],
            httponly=True,
            secure=HTTPS_ENABLED,
            samesite="Strict",
            expires=rm.get("expires")
        )

        return response

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
