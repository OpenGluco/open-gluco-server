import logging
import sys


def setup_logging():
    # logging config
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)  # Docker logs
        ]
    )

    # Redirect print to logging
    class PrintToLogger:
        def write(self, message):
            if message.strip():  # ignore empty lines
                logging.info(message.strip())

        def flush(self):
            pass

    sys.stdout = PrintToLogger()
    sys.stderr = PrintToLogger()
