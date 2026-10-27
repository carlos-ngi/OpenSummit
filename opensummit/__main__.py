import logging
import sys

from dotenv import load_dotenv

from . import config
from .bot import OpenSummit


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        cfg = config.load()
    except config.ConfigError as e:
        sys.exit(f"config error: {e}")

    # log_handler=None because logging is already set up above
    OpenSummit(cfg).run(cfg.token, log_handler=None)


if __name__ == "__main__":
    main()
