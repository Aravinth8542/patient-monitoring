"""Run tests against the test DB created by the default Compose startup."""
import os
import subprocess

from sqlalchemy.engine import make_url
from scripts.run_container_api import docker_database_url
from scripts.prepare_test_database import test_owner_url, TEST_DB


def main():
    test_url = test_owner_url()
    if test_url.database != TEST_DB or test_url.host != "db":
        raise RuntimeError("Refusing to run pytest against non-test database")
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    os.environ["TEST_DATABASE_URL"] = os.environ["DATABASE_URL"]
    runtime = make_url(docker_database_url("RUNTIME_DATABASE_URL")).set(database=TEST_DB)
    os.environ["RUNTIME_DATABASE_URL"] = runtime.render_as_string(hide_password=False)
    if os.environ.get("ALERT_DATABASE_URL"):
        os.environ["ALERT_DATABASE_URL"] = make_url(docker_database_url("ALERT_DATABASE_URL")).set(database=TEST_DB).render_as_string(hide_password=False)
    os.environ["TEST_MODE"] = "0"
    subprocess.run(["python", "-m", "pytest", "-q", "tests"], check=True)


if __name__ == "__main__":
    main()
