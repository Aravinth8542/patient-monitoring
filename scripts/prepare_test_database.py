"""Create and migrate patient_monitoring_test during normal Compose startup."""
import os
import subprocess

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from scripts.run_container_api import docker_database_url

TEST_DB = "patient_monitoring_test"


def test_owner_url():
    owner = make_url(docker_database_url("DATABASE_URL"))
    if owner.database != "patient_monitoring" or owner.host != "db":
        raise RuntimeError("Unexpected development database target")
    return owner.set(database=TEST_DB)


def main():
    test_url = test_owner_url()
    admin_url = test_url.set(database="postgres", drivername="postgresql")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
                print("Created", TEST_DB)
            else:
                print(TEST_DB, "already exists")

    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    os.environ["TEST_DATABASE_URL"] = os.environ["DATABASE_URL"]
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    print("Test database migrated")


if __name__ == "__main__":
    main()
