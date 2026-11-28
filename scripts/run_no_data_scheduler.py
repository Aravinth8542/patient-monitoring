
"""Run the no-data alert evaluator periodically in Docker."""
import logging
import os
import time

from scripts.run_container_api import docker_database_url


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    os.environ["DATABASE_URL"] = docker_database_url("DATABASE_URL")
    if os.environ.get("ALERT_DATABASE_URL"):
        os.environ["ALERT_DATABASE_URL"] = docker_database_url("ALERT_DATABASE_URL")

    from app.jobs.no_data import main as evaluate

    interval = int(os.getenv("NO_DATA_INTERVAL_SECONDS", "300"))
    if interval < 60:
        raise ValueError("NO_DATA_INTERVAL_SECONDS must be at least 60")

    while True:
        try:
            evaluate()
        except Exception:
            logger.exception("No-data alert evaluation failed")

        time.sleep(interval)


if __name__ == "__main__":
    main()
