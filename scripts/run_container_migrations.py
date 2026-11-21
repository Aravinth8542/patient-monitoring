
"""Apply Alembic migrations using the database owner role."""
import os
import subprocess

from scripts.run_container_api import docker_database_url


def main():
    os.environ["DATABASE_URL"] = docker_database_url("DATABASE_URL")
    subprocess.run(["alembic", "upgrade", "head"], check=True)


if __name__ == "__main__":
    main()
