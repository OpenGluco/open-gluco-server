import importlib
import os
import pkgutil
import threading
from functools import wraps
from time import time

import jwt
from dotenv import load_dotenv
from flask import Blueprint, Flask, jsonify, request
from flask_cors import CORS

from . import routes
from .db_conn import get_conn, init_db

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")

package = routes


def run(users: [], ip: str = "0.0.0.0", port: int = 5000):
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
                    f"✅ Blueprint '{obj.name}' enregistré depuis {module_name}.py")

    init_db()
    db_conn = get_conn()
    print(users)
    actual_data = []
    last_check_time = int(time())
    for libre_user in users[1]:
        for libre_key in libre_user:
            libre_user[libre_key].login()

    @app.route("/")
    def hello_world():
        return {'message': "Welcome to the OpenGluco API!"}

    # @app.route("/getCGMData")
    # def getCGMData():
    #     global actual_data,last_check_time
    #     return {'time':last_check_time,
    #             'data':actual_data}

    @app.route("/getCGMData")
    def getCGMData():
        global actual_data, last_check_time
        # user_id = request.args.get("user_id")
        # account_type = request.args.get("type")
        # auth_header = request.headers.get("Authorization")

        # try:
        #     with db_conn.cursor() as cur:
        #         cur.execute(
        #             "SELECT username, source, timestamp FROM glucose_data WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s",
        #             (user, limit)
        #         )
        #         rows = cur.fetchall()
        #     db_conn.commit()
        #     return jsonify({"message": "Utilisateur enregistré"}), 201

        # except psycopg.errors.UniqueViolation:
        #     db_conn.rollback()
        #     return jsonify({"error": "Nom d'utilisateur déjà utilisé"}), 409

        # except Exception as e:
        #     db_conn.rollback()
        #     return jsonify({"error": f"Erreur interne : {str(e)}"}), 500

        return {'time': last_check_time,
                'data': actual_data}

    def actualize_CGM():
        print(f"new data approaching %s" % (int(time())))
        global actual_data, last_check_time
        last_check_time = int(time())
        actual_data = []
        for dexcom_users in users[0]:
            for account_id in dexcom_users:
                glucose_data = dexcom_users[account_id].get_current_glucose_reading(
                )
                if glucose_data != None:
                    actual_data.append({account_id: glucose_data.mmol})
                else:
                    actual_data.append({account_id: -1})
        for libre_users in users[1]:
            for account_id in libre_users:
                glucose_data = libre_users[account_id].get_raw_connection()
                actual_data.append(
                    {account_id: glucose_data['glucoseMeasurement']['Value']})
        threading.Timer(60, actualize_CGM).start()

    actualize_CGM()

    app.run(ip, port)


# Décorateur pour protéger une route
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # On récupère le header "Authorization: Bearer <token>"
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

        # On passe la payload au handler de la route
        return f(payload, *args, **kwargs)
    return decorated
