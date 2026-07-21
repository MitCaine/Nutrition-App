from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import DeploymentMode, Settings
from app.core.database_errors import (
    RuntimeDatabaseErrorCategory,
    classify_runtime_database_error,
    extract_sqlstate,
)
from app.main import create_app
from app.models.recipe import Recipe
from app.models.user import User
from app.services.recipe_service import RecipeService


class DriverDatabaseError(Exception):
    def __init__(self, sqlstate: str, message: str = "private database detail"):
        super().__init__(message)
        self.sqlstate = sqlstate


def _wrapped_error(sqlstate: str, message: str = "private database detail") -> DBAPIError:
    return DBAPIError(None, None, DriverDatabaseError(sqlstate, message))


def _error_app(method: str, sqlstate: str) -> FastAPI:
    config = Settings(
        deployment_mode=DeploymentMode.TEST,
        database_url="sqlite+pysqlite:///:memory:",
    )
    test_app = create_app(config=config)

    def fail() -> None:
        raise _wrapped_error(
            sqlstate,
            "SELECT secret FROM private_db ON secret-host AS nutrition_runtime password=hunter2",
        )

    test_app.add_api_route("/database-error", fail, methods=[method])
    return test_app


def test_sqlstate_extraction_traverses_sqlalchemy_cause_context_and_arguments() -> None:
    driver = DriverDatabaseError("40p01")
    argument_wrapper = RuntimeError("argument wrapper", driver)
    context_wrapper = RuntimeError("context wrapper")
    context_wrapper.__context__ = argument_wrapper
    cause_wrapper = RuntimeError("cause wrapper")
    cause_wrapper.__cause__ = context_wrapper
    sqlalchemy_wrapper = DBAPIError(None, None, cause_wrapper)

    assert extract_sqlstate(sqlalchemy_wrapper) == "40P01"


@pytest.mark.parametrize(
    ("sqlstate", "category"),
    [
        ("P5C01", RuntimeDatabaseErrorCategory.WRITE_FENCE_CLOSED),
        ("40001", RuntimeDatabaseErrorCategory.SERIALIZATION_FAILURE),
        ("40P01", RuntimeDatabaseErrorCategory.DEADLOCK_DETECTED),
        ("55P03", RuntimeDatabaseErrorCategory.LOCK_NOT_AVAILABLE),
        ("08006", RuntimeDatabaseErrorCategory.CONNECTION_FAILURE),
        ("23505", RuntimeDatabaseErrorCategory.UNRELATED),
        (None, RuntimeDatabaseErrorCategory.UNRELATED),
    ],
)
def test_runtime_database_error_classification(
    sqlstate: str | None,
    category: RuntimeDatabaseErrorCategory,
) -> None:
    error = RuntimeError("not a database error") if sqlstate is None else _wrapped_error(sqlstate)

    classified = classify_runtime_database_error(error)

    assert classified.category is category
    assert classified.sqlstate == sqlstate


@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_transaction_contention_has_stable_retryable_non_leaking_api_contract(
    sqlstate: str,
) -> None:
    response = TestClient(_error_app("PATCH", sqlstate)).patch("/database-error")

    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"
    assert response.json() == {
        "detail": {
            "code": "database_transaction_conflict",
            "message": "The request conflicted with another database transaction. Retry the request.",
            "retryable": True,
        }
    }
    for secret in ("SELECT", "private_db", "secret-host", "nutrition_runtime", "hunter2"):
        assert secret not in response.text


def test_connection_loss_on_write_reports_unknown_outcome_without_blind_retry() -> None:
    response = TestClient(_error_app("POST", "08006")).post("/database-error")

    assert response.status_code == 503
    assert "Retry-After" not in response.headers
    assert response.json() == {
        "detail": {
            "code": "database_write_outcome_unknown",
            "message": (
                "The database connection was lost before the write outcome could be confirmed. "
                "Reconcile by reading the resource or reusing its idempotency key before retrying."
            ),
            "retryable": False,
        }
    }
    assert "secret-host" not in response.text


def test_connection_loss_on_read_is_retryable_and_distinct_from_unknown_write() -> None:
    response = TestClient(_error_app("GET", "08001")).get("/database-error")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json() == {
        "detail": {
            "code": "database_unavailable",
            "message": "The database is temporarily unavailable. Try again later.",
            "retryable": True,
        }
    }


@pytest.mark.parametrize("sqlstate", ["55P03", "23505"])
def test_unrelated_and_non_opted_in_lock_errors_keep_default_internal_contract(
    sqlstate: str,
) -> None:
    response = TestClient(
        _error_app("PATCH", sqlstate),
        raise_server_exceptions=False,
    ).patch("/database-error")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "private_db" not in response.text


def test_write_fence_contract_is_unchanged() -> None:
    response = TestClient(_error_app("POST", "P5C01")).post("/database-error")

    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready"}


def test_service_rolls_back_before_contention_response_and_session_can_be_reused(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/recipes",
        json={"name": "Stable Recipe", "serving_count_yield": "1", "ingredients": []},
    )
    assert created.status_code == 201
    recipe_id = UUID(created.json()["id"])

    def fail_after_flush(_service, _recipe: Recipe) -> None:
        raise _wrapped_error("40001", "secret SQL and database role")

    monkeypatch.setattr(RecipeService, "_after_recipe_update_flush", fail_after_flush)
    response = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"name": "Partial Recipe"},
    )

    assert response.status_code == 409
    assert not db_session.in_transaction()
    marker = User(id=uuid4(), email=f"post-error-{uuid4()}@example.test")
    db_session.add(marker)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Recipe, recipe_id).name == "Stable Recipe"
    assert db_session.get(User, marker.id) is not None
