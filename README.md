# open-gluco-server

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
