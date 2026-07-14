from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url


@dataclass(frozen=True)
class DatabaseIdentity:
    driver_family: str
    host: str | None
    port: int | None
    database: str | None


def database_identity(value: str | URL) -> DatabaseIdentity:
    url = make_url(value)
    return DatabaseIdentity(
        driver_family=url.get_backend_name(),
        host=url.host,
        port=url.port,
        database=url.database,
    )


def redacted_database_url(value: str | URL) -> str:
    """Return an operationally useful identity without credentials or query values."""
    identity = database_identity(value)
    authority = identity.host or "local"
    if identity.port is not None:
        authority = f"{authority}:{identity.port}"
    database = identity.database or ""
    return f"{identity.driver_family}://{authority}/{database}"


def database_connect_args(value: str | URL, *, timeout_seconds: int = 5) -> dict[str, object]:
    """Keep readiness/startup database establishment bounded where the driver supports it."""
    if database_identity(value).driver_family == "postgresql":
        return {"connect_timeout": timeout_seconds}
    return {}
