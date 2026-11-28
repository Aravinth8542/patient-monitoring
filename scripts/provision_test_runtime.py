"""Provision the Compose runtime database role after migrations."""
import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from scripts.run_container_api import docker_database_url


def main():
    owner = make_url(docker_database_url("DATABASE_URL"))
    runtime = make_url(docker_database_url("RUNTIME_DATABASE_URL"))
    if owner.database != "patient_monitoring" or runtime.database != owner.database:
        raise RuntimeError("Unexpected test database configuration")
    if runtime.username != "patient_monitoring_runtime" or not runtime.password:
        raise RuntimeError("RUNTIME_DATABASE_URL must contain runtime role credentials")
    # Called by the Compose runtime-provision service after migrations.
    with psycopg.connect(owner.set(drivername="postgresql").render_as_string(hide_password=False)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("ALTER ROLE patient_monitoring_runtime LOGIN PASSWORD {}").format(
                sql.Literal(runtime.password)
            ))
            if os.environ.get("ALERT_DATABASE_URL"):
                alert = make_url(docker_database_url("ALERT_DATABASE_URL"))
                if alert.database != owner.database or alert.username != "patient_monitoring_alert_processor" or not alert.password:
                    raise RuntimeError("Invalid ALERT_DATABASE_URL")
                cur.execute(sql.SQL("ALTER ROLE patient_monitoring_alert_processor LOGIN PASSWORD {}").format(sql.Literal(alert.password)))
    print("Compose runtime roles configured")


if __name__ == "__main__":
    main()
