# OpenGluco API server

REST API server application for open-gluco.

## First run

### 1. Generate a FERNET key

In order to keep some data secret, this API is using cryptography through FERNET encryption.
You'll need to generate it using this python script:

```python
from cryptography.fernet import Fernet

key = Fernet.generate_key()
print(key.decode()) # Copy this result
```

Of course, this script requires to install the cryptography lib: `pip install cryptography`

### 2. Fill in .env

Create a copy the `.env.example` file named `.env` and fill in the different variables.
Don't forget to copy the key you got in the previous step into the `FERNET_KEY` variable.

### 3. Run the project

Now you can just run the command : `docker compose up -d --build` and everything should work fine!

## Later usage

If you want to cut all the services, just type `docker compose down`.
After having cut the services, you can make them up again by using `docker compose up -d`.

## About the InfluxDB

You can notice gathered data is registered every 60 seconds to the database. An initial estimate indicates a potential of `50 MB` per year per user occupied on the disk.

## Endpoints

### Basic routes

- `/` [GET]: returns a welcome message
- `/user` [GET]: returns data from logged in user

### Authentication routes

- `/signup` [POST]: allows signing up with JSON data `email` (string), `name` (string), `surname` (string), `password` (string)
- `/login` [POST]: allows logging in with JSON data `email` (string), `password` (string), `remember_me` (boolean)
- `/logout` [POST]: ends session
- `/forgot_password` [GET]: triggers reset password email with GET parameter `email`
- `/password` [PATCH]: update password with token got from reset password email
- `/verify` [GET]: checks email verification with GET parameter `email`
- `/ask_verify` [GET]: sends verification email again, in case the token has expired

### CGM routes

- `/CGMCredentials` [POST, GET, DELETE]: allows you to send, get or delete credentials for CGM providers apps
- `/CGMData` [GET]: allows you to get glucose data with optional GET parameter`period` (values: 'w' (week), 'm' (month), 'y' (year))
