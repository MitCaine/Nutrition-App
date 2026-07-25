from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from app.operators.phase5c_contracts import canonical_digest
from app.operators.resource_membership_contracts import (
    CURRENT_RUNTIME_SCHEMA_REVISION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    PREFLIGHT_CATEGORIES,
)
from app.operators.resource_membership_preflight import (
    BLOCKING_ERROR_MESSAGE,
    SCHEMA_ERROR_MESSAGE,
    ResourceMembershipPreflightBlockedError,
    ResourceMembershipPreflightError,
    classify_resource_membership,
    require_resource_membership_preflight,
    run_resource_membership_operator_preflight,
)
from scripts import preflight_resource_membership as cli


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one(self) -> dict[str, Any]:
        assert len(self.rows) == 1
        return self.rows[0]


class _Scalars:
    def __init__(self, values: list[Any]):
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class _ClassificationConnection:
    def __init__(self, rows_by_query: list[list[dict[str, Any]]]):
        self.rows_by_query = list(rows_by_query)
        self.executed = 0

    def execute(self, _statement) -> _Rows:
        rows = self.rows_by_query[self.executed]
        self.executed += 1
        return _Rows(rows)


class _CapturingClassificationConnection(_ClassificationConnection):
    def __init__(self, rows_by_query: list[list[dict[str, Any]]]):
        super().__init__(rows_by_query)
        self.statements: list[str] = []

    def execute(self, statement) -> _Rows:
        self.statements.append(str(statement))
        return super().execute(statement)


def _empty_rows() -> list[list[dict[str, Any]]]:
    return [[] for _category in PREFLIGHT_CATEGORIES]


def _category_index(code: str) -> int:
    return next(
        index for index, category in enumerate(PREFLIGHT_CATEGORIES) if category.code == code
    )


def test_classification_is_canonical_deterministic_and_redacts_unselected_values() -> None:
    rows = _empty_rows()
    rows[_category_index("recipe_ingredient_owner_mismatch")] = [
        {
            "recipe_ingredient_id": "ingredient-b",
            "recipe_id": "recipe-b",
            "food_item_id": "food-b",
            "name": "DO_NOT_DISCLOSE_NAME",
            "request_fingerprint": "DO_NOT_DISCLOSE_FINGERPRINT",
        },
        {
            "recipe_ingredient_id": "ingredient-a",
            "recipe_id": "recipe-a",
            "food_item_id": "food-a",
            "trace_snapshot": "DO_NOT_DISCLOSE_OCR_PAYLOAD",
        },
    ]
    first = classify_resource_membership(_ClassificationConnection(rows))
    second = classify_resource_membership(
        _ClassificationConnection(
            [
                list(reversed(value))
                if index == _category_index("recipe_ingredient_owner_mismatch")
                else value
                for index, value in enumerate(rows)
            ]
        )
    )

    assert first.to_json() == second.to_json()
    payload = first.to_dict()
    assert [row["category"] for row in payload["category_counts"]] == [
        category.code for category in PREFLIGHT_CATEGORIES
    ]
    assert payload["finding_count"] == 2
    assert payload["blocking"] is True
    assert [row["identifiers"]["recipe_ingredient_id"] for row in payload["findings"]] == [
        "ingredient-a",
        "ingredient-b",
    ]
    assert payload["report_digest"] == canonical_digest(
        {key: value for key, value in payload.items() if key != "report_digest"}
    )
    rendered = first.to_json()
    assert rendered == json.dumps(payload, separators=(",", ":"), sort_keys=True)
    assert "DO_NOT_DISCLOSE" not in rendered
    assert "name" not in rendered
    assert "request_fingerprint" not in rendered
    assert "trace_snapshot" not in rendered


class _MigrationConnection(_ClassificationConnection):
    def __init__(
        self,
        rows_by_query: list[list[dict[str, Any]]],
        *,
        revisions: list[str] | None = None,
    ):
        super().__init__(rows_by_query)
        self.transaction_attempted = False
        self.revisions = revisions or [HISTORICAL_PHASE5_SCHEMA_REVISION]

    def scalars(self, _statement) -> _Scalars:
        return _Scalars(self.revisions)

    def begin(self):
        self.transaction_attempted = True
        raise AssertionError("migration wrapper must not begin a transaction")


def test_migration_wrapper_reuses_classifier_without_owning_transaction() -> None:
    connection = _MigrationConnection(_empty_rows())

    report = require_resource_membership_preflight(connection)

    assert report.blocking is False
    assert report.finding_count == 0
    assert connection.executed == len(PREFLIGHT_CATEGORIES)
    assert connection.transaction_attempted is False


def test_migration_wrapper_raises_stable_blocking_error_with_report() -> None:
    rows = _empty_rows()
    rows[_category_index("daily_log_food_owner_mismatch")] = [
        {"daily_log_id": "log-1", "food_item_id": "food-1"}
    ]
    connection = _MigrationConnection(rows)

    with pytest.raises(ResourceMembershipPreflightBlockedError) as exc_info:
        require_resource_membership_preflight(connection)

    assert str(exc_info.value) == BLOCKING_ERROR_MESSAGE
    assert exc_info.value.report.finding_count == 1
    assert exc_info.value.report.to_dict()["findings"][0]["category"] == (
        "daily_log_food_owner_mismatch"
    )


def test_migration_wrapper_requires_exact_0018_before_classification() -> None:
    connection = _MigrationConnection(
        _empty_rows(),
        revisions=["0017_phase5c_indexes"],
    )

    with pytest.raises(ResourceMembershipPreflightError) as exc_info:
        require_resource_membership_preflight(connection)

    assert str(exc_info.value) == SCHEMA_ERROR_MESSAGE
    assert connection.executed == 0


def test_current_schema_owner_inventory_includes_denormalized_ingredient_owner() -> None:
    historical = _CapturingClassificationConnection(_empty_rows())
    current = _CapturingClassificationConnection(_empty_rows())

    classify_resource_membership(historical)
    classify_resource_membership(
        current,
        observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
        required_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
    )

    ingredient_index = _category_index("recipe_ingredient_owner_mismatch")
    assert "ri.user_id" not in historical.statements[ingredient_index]
    assert "ri.user_id" in current.statements[ingredient_index]


def test_all_queries_execute_against_minimal_sqlite_membership_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS public"))
        for statement in (
            "CREATE TABLE public.recipes (id TEXT PRIMARY KEY, user_id TEXT, "
            "published_food_item_id TEXT, active_publication_revision_id TEXT)",
            "CREATE TABLE public.food_items (id TEXT PRIMARY KEY, user_id TEXT, source_type TEXT, "
            "source_id TEXT, is_recipe BOOLEAN, recipe_publication_revision_id TEXT)",
            "CREATE TABLE public.serving_definitions (id TEXT PRIMARY KEY, food_item_id TEXT)",
            "CREATE TABLE public.recipe_ingredients (id TEXT PRIMARY KEY, recipe_id TEXT, "
            "food_item_id TEXT, serving_definition_id TEXT)",
            "CREATE TABLE public.recipe_publication_revisions "
            "(id TEXT PRIMARY KEY, recipe_id TEXT, user_id TEXT)",
            "CREATE TABLE public.recipe_publication_amount_definitions "
            "(id TEXT PRIMARY KEY, revision_id TEXT)",
            "CREATE TABLE public.daily_logs "
            "(id TEXT PRIMARY KEY, user_id TEXT, food_item_id TEXT, "
            "serving_definition_id TEXT, recipe_publication_revision_id TEXT, "
            "recipe_publication_amount_definition_id TEXT)",
            "CREATE TABLE public.ocr_nutrition_confirmation_traces "
            "(id TEXT PRIMARY KEY, user_id TEXT, food_item_id TEXT)",
            "CREATE TABLE public.food_nutrients "
            "(id TEXT PRIMARY KEY, food_item_id TEXT, nutrient_id TEXT)",
            "CREATE TABLE public.daily_log_nutrient_snapshots "
            "(id TEXT PRIMARY KEY, daily_log_id TEXT, source_food_item_id TEXT, "
            "source_food_nutrient_id TEXT, serving_definition_id TEXT, nutrient_id TEXT)",
        ):
            connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO public.recipes "
                "(id, user_id, published_food_item_id, active_publication_revision_id) "
                "VALUES ('recipe-1', 'owner-a', NULL, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO public.recipes "
                "(id, user_id, published_food_item_id, active_publication_revision_id) "
                "VALUES ('recipe-unpaired', 'owner-a', NULL, 'revision-missing')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO public.food_items "
                "(id, user_id, source_type, source_id, is_recipe, "
                "recipe_publication_revision_id) "
                "VALUES ('food-1', 'owner-b', 'manual', NULL, FALSE, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO public.recipe_ingredients "
                "(id, recipe_id, food_item_id, serving_definition_id) "
                "VALUES ('ingredient-1', 'recipe-1', 'food-1', NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO public.daily_logs "
                "(id, user_id, food_item_id, serving_definition_id, "
                "recipe_publication_revision_id, recipe_publication_amount_definition_id) "
                "VALUES ('log-1', 'owner-a', 'food-1', NULL, NULL, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO public.daily_log_nutrient_snapshots "
                "(id, daily_log_id, source_food_item_id, source_food_nutrient_id, "
                "serving_definition_id, nutrient_id) VALUES "
                "('snapshot-stale-nutrient', 'log-1', 'food-1', "
                "'missing-nutrient', NULL, 'calories')"
            )
        )

        report = classify_resource_membership(connection)

    engine.dispose()
    assert report.to_dict()["finding_count"] == 5
    assert [finding["category"] for finding in report.to_dict()["findings"]] == [
        "daily_log_food_owner_mismatch",
        "log_snapshot_source_nutrient_food_mismatch",
        "recipe_ingredient_owner_mismatch",
        "recipe_projection_active_revision_mismatch",
        "recipe_projection_missing_active_revision",
    ]


@dataclass
class _Transaction:
    rolled_back: bool = False

    def rollback(self) -> None:
        self.rolled_back = True


class _OperatorConnection(_MigrationConnection):
    def __init__(self):
        super().__init__(_empty_rows())
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.isolation_level: str | None = None
        self.transaction = _Transaction()
        self.in_context = False

    def __enter__(self):
        self.in_context = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.in_context = False

    def execution_options(self, *, isolation_level: str):
        self.isolation_level = isolation_level
        return self

    def begin(self) -> _Transaction:
        return self.transaction

    def execute(self, statement) -> _Rows:
        sql = str(statement)
        if "current_setting('transaction_read_only')" in sql:
            return _Rows([{"read_only": "on", "isolation": "repeatable read"}])
        if sql.strip().startswith("SET TRANSACTION"):
            return _Rows([])
        return super().execute(statement)


class _OperatorEngine:
    def __init__(self):
        self.connection = _OperatorConnection()

    def connect(self) -> _OperatorConnection:
        return self.connection


def test_operator_wrapper_owns_verified_repeatable_read_only_transaction() -> None:
    engine = _OperatorEngine()

    report = run_resource_membership_operator_preflight(engine)

    assert report.finding_count == 0
    assert engine.connection.isolation_level == "REPEATABLE READ"
    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.in_context is False


def test_cli_requires_explicit_database_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NUTRITION_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert str(exc_info.value) == (
        "NUTRITION_DATABASE_URL must be explicitly set for resource membership preflight"
    )


def test_cli_configuration_error_redacts_database_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SENSITIVE_DATABASE_CONFIGURATION_TOKEN"
    monkeypatch.setenv("NUTRITION_DATABASE_URL", f"invalid-{secret}")
    monkeypatch.setattr(sys, "argv", ["preflight_resource_membership"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert str(exc_info.value) == (
        "Unable to run resource membership preflight on the configured database"
    )
    assert secret not in str(exc_info.value)


class _DisposableEngine:
    def __init__(self):
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_cli_emits_canonical_blocking_report_and_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = _empty_rows()
    rows[14] = [{"ocr_trace_id": "trace-1", "food_item_id": "food-1"}]
    report = classify_resource_membership(_ClassificationConnection(rows))
    engine = _DisposableEngine()
    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        "postgresql+psycopg://operator:secret@db.example/nutrition",
    )
    monkeypatch.setattr(cli, "create_engine", lambda *_args, **_kwargs: engine)

    def blocked(_engine):
        raise ResourceMembershipPreflightBlockedError(report)

    monkeypatch.setattr(cli, "run_resource_membership_operator_preflight", blocked)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert capsys.readouterr().out == report.to_json() + "\n"
    assert engine.disposed is True
