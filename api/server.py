from flask import Flask, request, jsonify
from time import time
import threading
from .db_conn import init_db, get_conn
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import psycopg
import jwt
import os
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")

def run(users:[], ip:str="0.0.0.0", port:int=5000):
    app = Flask(__name__)
    global db_conn
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
        return {'message':"Welcome to the OpenGluco API!"}
    
    # @app.route("/getCGMData")
    # def getCGMData():
    #     global actual_data,last_check_time
    #     return {'time':last_check_time,
    #             'data':actual_data}
    
    @app.route("/getCGMData")
    def getCGMData():
        global actual_data,last_check_time
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
        
        return {'time':last_check_time,
                'data':actual_data}
        
    @app.route("/signup", methods=["POST"])
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
        
    @app.route('/login', methods=['POST'])
    def login():
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "email et password requis"}), 400

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT id, password FROM users WHERE email = %s",
                    (email,)
                )
                result = cur.fetchone()

            if result is None:
                return jsonify({"error": "Nom d'utilisateur incorrect"}), 404

            user_id, stored_hash = result

            if check_password_hash(stored_hash, password):
                payload = {
                    "user_id": user_id,
                    "email": email,
                    "exp": int((datetime.now() + timedelta(hours=2)).timestamp())  # token expire dans 2h
                }
                token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

                return jsonify({"token": token}), 200

            else:
                return jsonify({"error": "Mot de passe incorrect"}), 401

        except Exception as e:
            return jsonify({"error": f"{str(e)}"}), 500
        
    @app.route("/postCGMCredentials", methods=['POST'])
    @token_required
    def postCredentials(payload):
        data = request.get_json()
        
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO connections (user_id, username, password, type, region) VALUES (%s, %s, %s, %s, %s)",
                    (payload["user_id"], data.get("username"), generate_password_hash(data.get("password")), data.get("type"), data.get("region"))
                )
            db_conn.commit()
            return jsonify({"message": f"Connection added to user {payload['user_id']}."}), 201
        
        except psycopg.errors.UniqueViolation:
            db_conn.rollback()
            return jsonify({"error": "Connection already exists."}), 409
        
        except Exception as e:
            db_conn.rollback()
            return jsonify({"error": f"Internal Error : {str(e)}"}), 500
    
    
    def actualize_CGM():
        print(f"new data approaching %s"%(int(time())))
        global actual_data, last_check_time
        last_check_time = int(time())
        actual_data = []
        for dexcom_users in users[0]:
            for account_id in dexcom_users:
                glucose_data = dexcom_users[account_id].get_current_glucose_reading()
                if glucose_data != None:
                    actual_data.append({account_id: glucose_data.mmol})
                else:
                    actual_data.append({account_id: -1})
        for libre_users in users[1]:
            for account_id in libre_users:
                glucose_data = libre_users[account_id].get_raw_connection()
                actual_data.append({account_id: glucose_data['glucoseMeasurement']['Value']})
        threading.Timer(60, actualize_CGM).start()

    actualize_CGM()
    
    app.run(ip, port)
    
    


# Décorateur pour protéger une route
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # On récupère le header "Authorization: Bearer <token>"
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                   
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