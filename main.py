from api.logging_setup import setup_logging
from api.server import create_app

setup_logging()


app = create_app()
