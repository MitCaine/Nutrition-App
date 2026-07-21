from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.api.v1.routers import foods, health, logs, nutrients, ocr, recipes, targets, usda
from app.core.config import ProcessMode, Settings, settings
from app.core.database import engine
from app.core.database_errors import (
    RuntimeDatabaseErrorCategory,
    classify_runtime_database_error,
)
from app.dependencies.user import get_current_user
from app.operators.phase5c4_prerequisites import (
    CANARY_FENCE_MODES,
    validate_local_admission,
)
from app.operators.phase5c4_contracts import CANARY_GET_ALLOWLIST_V1


CANARY_ROUTE_ALLOWLIST = frozenset(("GET", path) for path in CANARY_GET_ALLOWLIST_V1)


def create_app(
    *,
    config: Settings = settings,
    database_engine: Engine = engine,
) -> FastAPI:
    lifespan = (
        _canary_lifespan(config, database_engine)
        if config.process_mode is ProcessMode.CANARY
        else None
    )
    app = FastAPI(title="Nutrition App API", version="0.1.0", lifespan=lifespan)
    authenticated = [Depends(get_current_user)]
    included_canary_routes: set[tuple[str, str]] = set()

    def include(
        router: APIRouter,
        *,
        prefix: str,
        tags: list[str],
        dependencies: list[Any] | None = None,
    ) -> None:
        selected_router = router
        if config.process_mode is ProcessMode.CANARY:
            selected_router = APIRouter()
            for route in router.routes:
                full_path = f"{prefix}{getattr(route, 'path', '')}"
                methods = getattr(route, "methods", set())
                if any((method, full_path) in CANARY_ROUTE_ALLOWLIST for method in methods):
                    selected_router.routes.append(route)
                    included_canary_routes.update(
                        (method, full_path)
                        for method in methods
                        if (method, full_path) in CANARY_ROUTE_ALLOWLIST
                    )
        app.include_router(
            selected_router,
            prefix=prefix,
            tags=tags,
            dependencies=dependencies or [],
        )

    include(health.router, prefix="/api/v1", tags=["health"])
    include(
        nutrients.router,
        prefix="/api/v1/nutrients",
        tags=["nutrients"],
        dependencies=authenticated,
    )
    include(
        foods.router,
        prefix="/api/v1/foods",
        tags=["foods"],
        dependencies=authenticated,
    )
    include(
        logs.router,
        prefix="/api/v1/logs",
        tags=["logs"],
        dependencies=authenticated,
    )
    include(
        targets.router,
        prefix="/api/v1/targets",
        tags=["targets"],
        dependencies=authenticated,
    )
    include(
        recipes.router,
        prefix="/api/v1/recipes",
        tags=["recipes"],
        dependencies=authenticated,
    )
    include(
        usda.router,
        prefix="/api/v1/usda",
        tags=["usda"],
        dependencies=authenticated,
    )
    include(
        ocr.router,
        prefix="/api/v1/ocr/nutrition-label",
        tags=["ocr"],
        dependencies=authenticated,
    )
    if config.process_mode is ProcessMode.CANARY:
        if frozenset(included_canary_routes) != CANARY_ROUTE_ALLOWLIST:
            raise RuntimeError("canary_route_allowlist_mismatch")
        app.state.canary_route_allowlist = CANARY_ROUTE_ALLOWLIST

    @app.middleware("http")
    async def map_write_fence_failure(request: Any, call_next: Any) -> Any:
        try:
            return await call_next(request)
        except DBAPIError as exc:
            classification = classify_runtime_database_error(exc)
            if classification.category is RuntimeDatabaseErrorCategory.WRITE_FENCE_CLOSED:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Service is not ready"},
                )
            if classification.category in {
                RuntimeDatabaseErrorCategory.SERIALIZATION_FAILURE,
                RuntimeDatabaseErrorCategory.DEADLOCK_DETECTED,
            }:
                return JSONResponse(
                    status_code=409,
                    headers={"Retry-After": "1"},
                    content={
                        "detail": {
                            "code": "database_transaction_conflict",
                            "message": (
                                "The request conflicted with another database transaction. "
                                "Retry the request."
                            ),
                            "retryable": True,
                        }
                    },
                )
            if classification.category is RuntimeDatabaseErrorCategory.CONNECTION_FAILURE:
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": {
                                "code": "database_write_outcome_unknown",
                                "message": (
                                    "The database connection was lost before the write outcome "
                                    "could be confirmed. Reconcile by reading the resource or "
                                    "reusing its idempotency key before retrying."
                                ),
                                "retryable": False,
                            }
                        },
                    )
                return JSONResponse(
                    status_code=503,
                    headers={"Retry-After": "1"},
                    content={
                        "detail": {
                            "code": "database_unavailable",
                            "message": "The database is temporarily unavailable. Try again later.",
                            "retryable": True,
                        }
                    },
                )
            # 55P03 is classified centrally but is not a public runtime contract
            # until a specific NOWAIT/lock-timeout operation deliberately opts in.
            raise

    return app


def _canary_lifespan(config: Settings, database_engine: Engine):
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _admit_canary_startup(config, database_engine)
        yield

    return lifespan


def _admit_canary_startup(config: Settings, database_engine: Engine) -> None:
    if database_engine.dialect.name != "postgresql":
        raise RuntimeError("canary_startup_admission_failed")
    try:
        with database_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock_shared(5542018)"))
                identity = connection.execute(
                    text(
                        "SELECT session_user, current_user, "
                        "current_setting('default_transaction_read_only'), "
                        "current_setting('transaction_read_only')"
                    )
                ).one()
                if tuple(identity) != (
                    "nutrition_canary",
                    "nutrition_canary",
                    "on",
                    "on",
                ):
                    raise RuntimeError("canary_startup_admission_failed")
                reader_available = connection.execute(
                    text("SELECT pg_catalog.to_regprocedure('public.phase5c_local_admission_v1()')")
                ).scalar_one()
                if reader_available is None:
                    raise RuntimeError("canary_startup_admission_failed")
                raw = (
                    connection.execute(text("SELECT * FROM public.phase5c_local_admission_v1()"))
                    .mappings()
                    .one()
                )
                admission = validate_local_admission(dict(raw))
                if (
                    admission.schema_revision != "0018_phase5c_promotion_prerequisites"
                    or not admission.identity_present
                    or not admission.identity_valid
                    or not admission.composite_bindings_valid
                    or not admission.fence_state_present
                    or not admission.fence_state_valid
                    or not admission.event_chain_valid
                    or admission.fence_mode not in CANARY_FENCE_MODES
                    or not admission.session_role_valid
                    or not admission.role_topology_valid
                    or not admission.gate_trigger_coverage_valid
                    or not admission.immutability_valid
                ):
                    raise RuntimeError("canary_startup_admission_failed")
                if config.private_user_id is None or config.private_user_email is None:
                    raise RuntimeError("canary_startup_admission_failed")
                user_count = connection.execute(
                    text(
                        "SELECT count(*) FROM public.users WHERE id = :user_id AND email = :email"
                    ),
                    {
                        "user_id": config.private_user_id,
                        "email": config.private_user_email,
                    },
                ).scalar_one()
                if user_count != 1:
                    raise RuntimeError("canary_startup_admission_failed")
            finally:
                transaction.rollback()
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("canary_startup_admission_failed") from None


app = create_app()
