"""Run the API in Compose while preserving the owner/runtime DB roles."""
import os

from sqlalchemy.engine import make_url


def docker_database_url(name: str) -> str:
    raw = os.environ.get(name)
    if not raw:
        raise RuntimeError(f"{name} is required for the API container")
    url = make_url(raw)
    # The host-mapped localhost:5433 URLs are for Windows. Compose uses db:5432.
    return url.set(host="db", port=5432).render_as_string(hide_password=False)


def main() -> None:
    os.environ["DATABASE_URL"] = docker_database_url("DATABASE_URL")
    os.environ["RUNTIME_DATABASE_URL"] = docker_database_url("RUNTIME_DATABASE_URL")
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
