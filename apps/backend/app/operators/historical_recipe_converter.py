from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Iterator
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from app.domain.nutrition import AggregatedNutrientTotal, NutrientSnapshot
from app.models.food import FoodItem
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import RecipePublicationRevision
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.resolution import (
    NutritionResolutionError,
    ResolvedNutrition,
    resolve_nutrition,
)
from app.operators.historical_database_inventory import REPORT_SCHEMA_VERSION
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    _archive_checksums,
    _current_revision,
    _qualified,
    load_bridge_metadata,
    phase5c_advisory_lock,
    planning_source_payload,
    planning_subject_source_payload,
    require_supported_legacy_schema,
)
from app.operators.historical_recipe_planner import (
    _by_food,
    _by_id,
    _by_recipe,
    _recipe_source_checksum,
)
from app.operators.phase5c_contracts import (
    CONVERSION_PLAN_VERSION,
    CONVERTER_VERSION,
    EXECUTION_RECEIPT_VERSION,
    EXECUTION_REVISION,
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    canonical_digest,
    canonical_json,
    validate_conversion_plan_contract,
    validate_inventory_contract,
)
from app.operators.phase5c_isolation import (
    assert_database_session_isolation,
    phase5c_maintenance_session,
    verify_clone_isolation_evidence,
)
from app.publication.recipe_revision import (
    build_revision,
    content_from_projection,
    content_from_recipe_output,
    projection_matches_revision,
    revision_content_digest,
    validate_revision_resolver_input,
)


_RUN_TABLE = "phase5c_conversion_runs"
_OUTCOME_TABLE = "phase5c_conversion_outcomes"
_RUN_NAMESPACE = UUID("1ec4b984-0c7a-4c70-8cb3-c698f664669d")
_DECIMAL_PLACES = Decimal("0.000001")
_RETRYABLE_SQLSTATES = {"40001", "40P01"}
_RETRY_LIMIT = 3
_DAILY_LOG_TABLES = ("daily_logs", "daily_log_nutrient_snapshots")
_OCR_TABLES = (
    "ocr_scans",
    "parse_results",
    "parser_corrections",
    "ocr_nutrition_confirmation_traces",
)
_RUN_BINDING_COLUMNS = (
    "id",
    "archive_identity",
    "plan_version",
    "plan_digest",
    "inventory_digest",
    "schema_signature",
    "schema_signature_digest",
    "conversion_rules_version",
    "recipes_checksum",
    "ingredients_checksum",
    "archive_checksum",
    "planning_source_checksum",
    "clone_marker_digest",
    "operator_attestation_digest",
    "execution_isolation_contract_version",
    "execution_attestation_version",
    "execution_attestation_identity",
    "execution_attestation_scope",
    "execution_attestation_digest",
    "converter_version",
    "daily_log_state_digest",
    "ocr_state_digest",
)
FailureHook = Callable[[str, UUID], None]
PerformanceObserver = Callable[[str, UUID | None, str | None, int | None], None]


class Phase5CSubjectError(RuntimeError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ConversionExecutionReport:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        counts = self.payload["counts"]
        return "\n".join(
            (
                "Phase 5C historical Recipe conversion execution",
                f"Run: {self.payload['run_id']}",
                f"Plan: {self.payload['plan_digest']}",
                f"Converted: {counts['converted']}",
                f"Quarantined: {counts['quarantined']}",
                f"Blocked: {counts['blocked']}",
                f"Failed: {counts['failed']}",
                f"Pending: {counts['pending']}",
                f"Verification: {self.payload['verification_result']}",
                f"Receipt digest: {self.payload['report_digest']}",
            )
        )


def execute_historical_recipe_conversion(
    engine: Engine,
    *,
    plan_payload: dict[str, Any],
    inventory_payload: dict[str, Any],
    archive_schema: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
    attestation_payload: dict[str, Any],
    failure_hook: FailureHook | None = None,
    performance_observer: PerformanceObserver | None = None,
) -> ConversionExecutionReport:
    plan = validate_conversion_plan_contract(plan_payload)
    inventory = validate_inventory_contract(inventory_payload)
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("The Phase 5C converter supports PostgreSQL only")
    inventory_digest = canonical_digest(inventory)
    if plan["inventory_digest"] != inventory_digest:
        raise Phase5CAdmissionError("Conversion plan and inventory digest differ")
    if plan["source_identity"]["archive_schema"] != archive_schema:
        raise Phase5CAdmissionError("Conversion plan archive schema differs from command")

    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection:
        source_schema = str(connection.scalar(text("SELECT current_schema()")))
        with _isolated_conversion_operation(
            connection,
            plan=plan,
            source_schema=source_schema,
            inventory_digest=inventory_digest,
            conversion_clone_id=conversion_clone_id,
            clone_marker_identity=clone_marker_identity,
            attestation_payload=attestation_payload,
        ) as isolation_evidence:
            with connection.begin():
                source_payload, metadata = _admit_execution(
                    connection,
                    plan=plan,
                    archive_schema=archive_schema,
                    source_schema=source_schema,
                    isolation_evidence=isolation_evidence,
                )
                order, dependencies = _dependency_order(plan, source_payload)
                run = _create_or_validate_run(
                    connection,
                    plan=plan,
                    metadata=metadata,
                    isolation_evidence=isolation_evidence,
                )

            decisions = {
                UUID(decision["source_recipe_id"]): decision
                for decision in plan["decisions"]
            }
            nonconverts = sorted(
                (
                    recipe_id
                    for recipe_id, decision in decisions.items()
                    if decision["intended_disposition"] != "convert"
                ),
                key=str,
            )
            for recipe_id in (*nonconverts, *order):
                decision = decisions[recipe_id]
                with _observed_operation(
                    performance_observer,
                    "subject",
                    recipe_id=recipe_id,
                    disposition=decision["intended_disposition"],
                ):
                    with connection.begin():
                        outcome = _load_outcome(connection, run["id"], recipe_id)
                    if outcome["checkpoint_state"] == "completed":
                        _verify_completed_outcome(
                            connection,
                            run=run,
                            outcome=outcome,
                            decision=decision,
                            plan=plan,
                            archive_schema=archive_schema,
                        )
                        continue
                    if outcome["checkpoint_state"] == "failed":
                        continue
                    if decision["intended_disposition"] != "convert":
                        _persist_nonconvert_outcome(
                            connection,
                            run=run,
                            decision=decision,
                            archive_schema=archive_schema,
                            plan=plan,
                        )
                        continue
                    with connection.begin():
                        dependencies_completed = _dependencies_completed(
                            connection,
                            run_id=run["id"],
                            dependencies=dependencies[recipe_id],
                        )
                    if not dependencies_completed:
                        _record_subject_failure(
                            connection,
                            run_id=run["id"],
                            recipe_id=recipe_id,
                            reason_code="dependency_execution_incomplete",
                        )
                        continue
                    if outcome["checkpoint_state"] == "domain_committed":
                        _post_commit_verify(
                            connection,
                            run=run,
                            decision=decision,
                            plan=plan,
                            archive_schema=archive_schema,
                        )
                        continue
                    _execute_convert_with_retry(
                        connection,
                        run=run,
                        decision=decision,
                        plan=plan,
                        archive_schema=archive_schema,
                        failure_hook=failure_hook,
                        performance_observer=performance_observer,
                    )

            with connection.begin():
                try:
                    _verify_run_level_state(
                        connection,
                        run=run,
                        plan=plan,
                        archive_schema=archive_schema,
                    )
                except Phase5CSubjectError:
                    _fail_run_level_verification(connection, run["id"])
                else:
                    _finalize_run(connection, run["id"])
                with _observed_operation(
                    performance_observer,
                    "execution_receipt",
                ):
                    report = _build_report(connection, run["id"])
            return ConversionExecutionReport(report)


@contextmanager
def _isolated_conversion_operation(
    connection: Connection,
    *,
    plan: dict[str, Any],
    source_schema: str,
    inventory_digest: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
    attestation_payload: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    evidence = verify_clone_isolation_evidence(
        connection,
        attestation_payload=attestation_payload,
        clone_marker_identity=clone_marker_identity,
        conversion_clone_id=conversion_clone_id,
        inventory_digest=inventory_digest,
        schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
        schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
        operation="execution",
        conversion_plan_payload=plan,
    )
    with phase5c_maintenance_session(connection, evidence["clone_marker_digest"]):
        assert_database_session_isolation(connection, evidence["clone_marker_digest"])
        connection.commit()
        with phase5c_advisory_lock(connection, source_schema):
            evidence = verify_clone_isolation_evidence(
                connection,
                attestation_payload=attestation_payload,
                clone_marker_identity=clone_marker_identity,
                conversion_clone_id=conversion_clone_id,
                inventory_digest=inventory_digest,
                schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
                schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
                operation="execution",
                conversion_plan_payload=plan,
            )
            assert_database_session_isolation(connection, evidence["clone_marker_digest"])
            connection.commit()
            yield evidence


def _admit_execution(
    connection: Connection,
    *,
    plan: dict[str, Any],
    archive_schema: str,
    source_schema: str,
    isolation_evidence: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if _current_revision(connection, source_schema) != EXECUTION_REVISION:
        raise Phase5CAdmissionError(f"Converter target must be at {EXECUTION_REVISION}")
    if not {_RUN_TABLE, _OUTCOME_TABLE} <= set(inspect(connection).get_table_names()):
        raise Phase5CAdmissionError("Phase 5C execution-control tables are absent")
    metadata = load_bridge_metadata(connection, archive_schema)
    required_metadata = {
        "archive_identity": plan["source_identity"]["archive_identity"],
        "source_driver_family": plan["source_identity"]["driver_family"],
        "source_host": plan["source_identity"]["host"],
        "source_port": plan["source_identity"]["port"],
        "source_database": plan["source_identity"]["database"],
        "conversion_clone_identity_digest": plan["source_identity"][
            "conversion_clone_identity_digest"
        ],
        "inventory_contract_version": REPORT_SCHEMA_VERSION,
        "inventory_digest": plan["inventory_digest"],
        "schema_signature": plan["supported_schema_signature"]["name"],
        "schema_signature_digest": plan["supported_schema_signature"]["digest"],
        "source_schema": source_schema,
        "archive_schema": archive_schema,
        "conversion_rules_version": plan["conversion_rules_version"],
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "marker_format_version": plan["isolation_evidence"][
            "marker_format_version"
        ],
        "isolation_evidence_contract_version": plan["isolation_evidence"][
            "contract_version"
        ],
        "clone_marker_identity": plan["isolation_evidence"][
            "clone_marker_identity"
        ],
        "clone_database_identity_digest": plan["isolation_evidence"][
            "clone_database_identity_digest"
        ],
        "source_production_identity_digest": plan["isolation_evidence"][
            "source_production_identity_digest"
        ],
        "operator_attestation_digest": plan["isolation_evidence"][
            "operator_attestation_digest"
        ],
        "operator_attestation_version": plan["isolation_evidence"][
            "operator_attestation_version"
        ],
        "operator_attestation_identity": plan["isolation_evidence"][
            "operator_attestation_identity"
        ],
        "operator_attestation_scope": plan["isolation_evidence"][
            "operator_attestation_scope"
        ],
    }
    if any(metadata.get(key) != value for key, value in required_metadata.items()):
        raise Phase5CAdmissionError("Conversion plan does not match bridge metadata")
    evidence_requirements = {
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "clone_database_identity_digest": plan["isolation_evidence"][
            "clone_database_identity_digest"
        ],
        "source_production_identity_digest": plan["isolation_evidence"][
            "source_production_identity_digest"
        ],
    }
    if any(isolation_evidence.get(key) != value for key, value in evidence_requirements.items()):
        raise Phase5CAdmissionError("Conversion plan isolation evidence changed")
    control = connection.execute(
        text(
            "SELECT manifest_version, manifest_digest FROM phase5c_conversion_metadata "
            "WHERE archive_identity = :archive_identity"
        ),
        {"archive_identity": metadata["archive_identity"]},
    ).mappings().one_or_none()
    if control is None or dict(control) != {
        "manifest_version": CONVERSION_PLAN_VERSION,
        "manifest_digest": plan["manifest_digest"],
    }:
        raise Phase5CAdmissionError("Approved conversion manifest metadata differs")
    require_supported_legacy_schema(connection, archive_schema)
    payload = planning_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=source_schema,
    )
    checksums = _archive_checksums(payload)
    expected_checksums = {
        "recipes_checksum": plan["source_checksums"]["archived_recipes"],
        "ingredients_checksum": plan["source_checksums"][
            "archived_recipe_ingredients"
        ],
        "archive_checksum": plan["source_checksums"]["archive"],
        "planning_source_checksum": plan["source_checksums"]["planning_source"],
    }
    comparable = {key: checksums[key] for key in expected_checksums}
    if comparable != expected_checksums:
        raise Phase5CAdmissionError("Conversion source checksums changed after planning")
    if any(metadata.get(key) != checksums[key] for key in checksums):
        raise Phase5CAdmissionError("Conversion archive no longer matches bridge metadata")
    return payload, metadata


def _dependency_order(
    plan: dict[str, Any],
    payload: dict[str, list[dict[str, Any]]],
) -> tuple[list[UUID], dict[UUID, set[UUID]]]:
    decisions = {
        UUID(row["source_recipe_id"]): row["intended_disposition"]
        for row in plan["decisions"]
    }
    recipe_by_projection = {
        row["food_item_id"]: row["id"] for row in payload["recipes"]
    }
    ingredients = _by_recipe(payload["recipe_ingredients"])
    dependencies: dict[UUID, set[UUID]] = {recipe_id: set() for recipe_id in decisions}
    for recipe_id in decisions:
        for ingredient in ingredients.get(recipe_id, []):
            dependency = recipe_by_projection.get(ingredient["ingredient_food_item_id"])
            if dependency is not None:
                dependencies[recipe_id].add(dependency)
    convert_ids = {
        recipe_id for recipe_id, disposition in decisions.items() if disposition == "convert"
    }
    for recipe_id in convert_ids:
        if any(decisions.get(value) != "convert" for value in dependencies[recipe_id]):
            raise Phase5CAdmissionError(
                "Conversion plan permits a parent whose dependency will not convert"
            )
    remaining = set(convert_ids)
    completed: set[UUID] = set()
    order: list[UUID] = []
    while remaining:
        ready = sorted(
            (
                recipe_id
                for recipe_id in remaining
                if dependencies[recipe_id] <= completed
            ),
            key=str,
        )
        if not ready:
            raise Phase5CAdmissionError("Conversion plan contains a source graph cycle")
        for recipe_id in ready:
            remaining.remove(recipe_id)
            completed.add(recipe_id)
            order.append(recipe_id)
    return order, dependencies


def _create_or_validate_run(
    connection: Connection,
    *,
    plan: dict[str, Any],
    metadata: dict[str, Any],
    isolation_evidence: dict[str, Any],
) -> dict[str, Any]:
    existing = connection.execute(
        text(f"SELECT * FROM {_RUN_TABLE} WHERE archive_identity = :archive_identity"),
        {"archive_identity": metadata["archive_identity"]},
    ).mappings().one_or_none()
    state = {
        "id": uuid5(_RUN_NAMESPACE, plan["manifest_digest"]),
        "archive_identity": metadata["archive_identity"],
        "plan_version": plan["manifest_version"],
        "plan_digest": plan["manifest_digest"],
        "inventory_digest": plan["inventory_digest"],
        "schema_signature": plan["supported_schema_signature"]["name"],
        "schema_signature_digest": plan["supported_schema_signature"]["digest"],
        "conversion_rules_version": plan["conversion_rules_version"],
        "recipes_checksum": plan["source_checksums"]["archived_recipes"],
        "ingredients_checksum": plan["source_checksums"]["archived_recipe_ingredients"],
        "archive_checksum": plan["source_checksums"]["archive"],
        "planning_source_checksum": plan["source_checksums"]["planning_source"],
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "operator_attestation_digest": plan["isolation_evidence"][
            "operator_attestation_digest"
        ],
        "execution_isolation_contract_version": isolation_evidence[
            "execution_isolation_evidence_contract_version"
        ],
        "execution_attestation_version": isolation_evidence[
            "execution_operator_attestation_version"
        ],
        "execution_attestation_identity": isolation_evidence[
            "execution_operator_attestation_identity"
        ],
        "execution_attestation_scope": isolation_evidence[
            "execution_operator_attestation_scope"
        ],
        "execution_attestation_digest": isolation_evidence[
            "execution_operator_attestation_digest"
        ],
        "converter_version": CONVERTER_VERSION,
    }
    if existing is None:
        if connection.scalar(text("SELECT count(*) FROM recipes")):
            raise Phase5CAdmissionError("Current Recipe rows exist before the first conversion run")
        if connection.scalar(text("SELECT count(*) FROM recipe_publication_revisions")):
            raise Phase5CAdmissionError(
                "Current publication revisions exist before the first conversion run"
            )
        state.update(
            {
                "daily_log_state_digest": _relation_state_digest(
                    connection, _DAILY_LOG_TABLES
                ),
                "ocr_state_digest": _relation_state_digest(connection, _OCR_TABLES),
            }
        )
        connection.execute(
            text(
                f"INSERT INTO {_RUN_TABLE} "
                f"({', '.join(state)}, execution_state, verification_state) VALUES "
                f"({', '.join(':' + key for key in state)}, 'running', 'pending')"
            ),
            state,
        )
        for decision in plan["decisions"]:
            connection.execute(
                text(
                    f"INSERT INTO {_OUTCOME_TABLE} "
                    "(run_id, source_recipe_id, planned_disposition, "
                    "planned_reason_code, source_checksum, checkpoint_state, "
                    "verification_state) VALUES "
                    "(:run_id, :source_recipe_id, :planned_disposition, "
                    ":planned_reason_code, :source_checksum, 'pending', 'pending')"
                ),
                {
                    "run_id": state["id"],
                    "source_recipe_id": UUID(decision["source_recipe_id"]),
                    "planned_disposition": decision["intended_disposition"],
                    "planned_reason_code": decision["reason_code"],
                    "source_checksum": decision["source_checksum"],
                },
            )
        return {**state, "execution_state": "running", "verification_state": "pending"}

    existing_dict = dict(existing)
    if any(existing_dict.get(key) != value for key, value in state.items()):
        raise Phase5CAdmissionError(
            "Existing conversion run or execution authorization evidence differs"
        )
    if (
        _relation_state_digest(connection, _DAILY_LOG_TABLES)
        != existing_dict["daily_log_state_digest"]
        or _relation_state_digest(connection, _OCR_TABLES)
        != existing_dict["ocr_state_digest"]
    ):
        raise Phase5CAdmissionError(
            "Existing conversion run or execution authorization evidence differs"
        )
    outcomes = connection.execute(
        text(f"SELECT * FROM {_OUTCOME_TABLE} WHERE run_id = :run_id"),
        {"run_id": state["id"]},
    ).mappings().all()
    planned = {
        UUID(row["source_recipe_id"]): (
            row["intended_disposition"],
            row["reason_code"],
            row["source_checksum"],
        )
        for row in plan["decisions"]
    }
    stored = {
        row["source_recipe_id"]: (
            row["planned_disposition"],
            row["planned_reason_code"],
            row["source_checksum"],
        )
        for row in outcomes
    }
    if stored != planned:
        raise Phase5CAdmissionError("Existing conversion outcomes differ from plan")
    _validate_existing_domain_scope(connection, outcomes)
    return existing_dict


def _validate_existing_domain_scope(
    connection: Connection,
    outcomes: list[Any],
) -> None:
    expected_recipes = {
        row["target_recipe_id"]
        for row in outcomes
        if row["target_recipe_id"] is not None
    }
    expected_revisions = {
        row["created_revision_id"]
        for row in outcomes
        if row["created_revision_id"] is not None
    }
    current_recipes = set(connection.scalars(text("SELECT id FROM recipes")).all())
    current_revisions = set(
        connection.scalars(text("SELECT id FROM recipe_publication_revisions")).all()
    )
    if current_recipes != expected_recipes or current_revisions != expected_revisions:
        raise Phase5CAdmissionError("Current Recipe domain is not explained by checkpoints")


def _persist_nonconvert_outcome(
    connection: Connection,
    *,
    run: dict[str, Any],
    decision: dict[str, Any],
    archive_schema: str,
    plan: dict[str, Any],
) -> None:
    recipe_id = UUID(decision["source_recipe_id"])
    with connection.begin():
        _verify_subject_source(
            connection,
            run=run,
            recipe_id=recipe_id,
            expected_checksum=decision["source_checksum"],
            archive_schema=archive_schema,
        )
        execution = (
            "quarantined"
            if decision["intended_disposition"] == "quarantine"
            else "blocked"
        )
        result = connection.execute(
            text(
                f"UPDATE {_OUTCOME_TABLE} SET execution_disposition = :execution, "
                "checkpoint_state = 'completed', verification_state = 'verified' "
                "WHERE run_id = :run_id AND source_recipe_id = :recipe_id "
                "AND checkpoint_state = 'pending'"
            ),
            {"execution": execution, "run_id": run["id"], "recipe_id": recipe_id},
        )
        if result.rowcount != 1:
            raise Phase5CAdmissionError("Non-convert checkpoint changed concurrently")


def _execute_convert_with_retry(
    connection: Connection,
    *,
    run: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
    failure_hook: FailureHook | None,
    performance_observer: PerformanceObserver | None,
) -> None:
    recipe_id = UUID(decision["source_recipe_id"])
    for attempt in range(1, _RETRY_LIMIT + 1):
        try:
            with connection.begin():
                _convert_subject(
                    connection,
                    run=run,
                    decision=decision,
                    plan=plan,
                    archive_schema=archive_schema,
                    failure_hook=failure_hook,
                )
            break
        except DBAPIError as exc:
            if _sqlstate(exc) not in _RETRYABLE_SQLSTATES:
                _record_subject_failure(
                    connection,
                    run_id=run["id"],
                    recipe_id=recipe_id,
                    reason_code="subject_database_failure",
                )
                return
            if attempt == _RETRY_LIMIT:
                _record_subject_failure(
                    connection,
                    run_id=run["id"],
                    recipe_id=recipe_id,
                    reason_code="subject_retry_exhausted",
                )
                return
            _notify_performance_observer(
                performance_observer,
                "subject_retry",
                recipe_id=recipe_id,
                disposition="convert",
                attempt=attempt + 1,
            )
        except Phase5CAdmissionError:
            raise
        except Phase5CSubjectError as exc:
            _record_subject_failure(
                connection,
                run_id=run["id"],
                recipe_id=recipe_id,
                reason_code=exc.reason_code,
            )
            return
        except Exception:
            _record_subject_failure(
                connection,
                run_id=run["id"],
                recipe_id=recipe_id,
                reason_code="subject_execution_failure",
            )
            return
    _post_commit_verify(
        connection,
        run=run,
        decision=decision,
        plan=plan,
        archive_schema=archive_schema,
    )


def _convert_subject(
    connection: Connection,
    *,
    run: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
    failure_hook: FailureHook | None,
) -> None:
    recipe_id = UUID(decision["source_recipe_id"])
    source_schema = str(connection.scalar(text("SELECT current_schema()")))
    initial_payload = planning_subject_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=source_schema,
        recipe_id=recipe_id,
    )
    source_recipe, source_ingredients = _subject_source(
        initial_payload, recipe_id, decision["source_checksum"]
    )
    _require_subject_owner(initial_payload, source_recipe)
    food_ids = {source_recipe["food_item_id"]}
    food_ids.update(row["ingredient_food_item_id"] for row in source_ingredients)

    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="rollback_only",
    )
    try:
        foods = list(
            session.scalars(
                select(FoodItem)
                .where(FoodItem.id.in_(sorted(food_ids, key=str)))
                .order_by(FoodItem.id)
                .options(
                    selectinload(FoodItem.nutrients),
                    selectinload(FoodItem.serving_definitions),
                    selectinload(FoodItem.sources),
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            ).all()
        )
        food_by_id = {food.id: food for food in foods}
        if set(food_by_id) != food_ids:
            raise Phase5CSubjectError("referenced_food_missing")

        archived_recipe = _qualified(connection, archive_schema, "recipes")
        archived_ingredients = _qualified(
            connection, archive_schema, "recipe_ingredients"
        )
        connection.execute(
            text(f"SELECT id FROM {archived_recipe} WHERE id = :id FOR UPDATE"),
            {"id": recipe_id},
        ).one()
        connection.execute(
            text(
                f"SELECT id FROM {archived_ingredients} WHERE recipe_id = :id "
                "ORDER BY sort_order, id FOR UPDATE"
            ),
            {"id": recipe_id},
        ).all()

        payload = planning_subject_source_payload(
            connection,
            recipe_schema=archive_schema,
            supporting_schema=source_schema,
            recipe_id=recipe_id,
        )
        _verify_run_binding(connection, run)
        source_recipe, source_ingredients = _subject_source(
            payload, recipe_id, decision["source_checksum"]
        )
        _require_subject_owner(payload, source_recipe)
        projection = food_by_id[source_recipe["food_item_id"]]
        _validate_locked_subject(
            source_recipe=source_recipe,
            source_ingredients=source_ingredients,
            foods=food_by_id,
            projection=projection,
        )

        existing = session.scalars(
            select(Recipe).where(Recipe.id == recipe_id).with_for_update()
        ).first()
        if existing is not None:
            raise Phase5CSubjectError("unexpected_existing_target_recipe")
        _call_hook(failure_hook, "before_domain_writes", recipe_id)
        recipe = Recipe(
            id=recipe_id,
            user_id=source_recipe["user_id"],
            published_food_item_id=projection.id,
            name=projection.name,
            notes=projection.notes,
            serving_count_yield=source_recipe["serving_count"],
            final_cooked_weight_grams=source_recipe["final_yield_quantity"],
            needs_republish=False,
            created_at=source_recipe["created_at"],
            updated_at=source_recipe["updated_at"],
        )
        session.add(recipe)
        session.flush()
        _call_hook(failure_hook, "after_recipe_insert", recipe_id)

        current_ingredients = []
        for row in source_ingredients:
            ingredient = RecipeIngredient(
                id=row["id"],
                recipe_id=recipe.id,
                food_item_id=row["ingredient_food_item_id"],
                position=row["sort_order"],
                amount_quantity=row["quantity"],
                amount_unit=row["unit"],
                serving_definition_id=row["serving_definition_id"],
                resolved_gram_amount=row["gram_amount"],
                preparation_note=row["preparation_note"],
            )
            ingredient.food_item = food_by_id[ingredient.food_item_id]
            session.add(ingredient)
            current_ingredients.append(ingredient)
        session.flush()
        recipe.ingredients = current_ingredients
        _call_hook(failure_hook, "after_ingredient_insert", recipe_id)

        revision = build_revision(
            recipe_id=recipe.id,
            user_id=recipe.user_id,
            revision_number=1,
            creation_origin="legacy_projection_capture",
            provenance_confidence="transition_baseline",
            content=content_from_projection(projection),
        )
        validate_revision_resolver_input(revision)
        session.add(revision)
        session.flush()
        _call_hook(failure_hook, "after_revision_children", recipe_id)

        recipe.active_publication_revision_id = revision.id
        projection.recipe_publication_revision_id = revision.id
        recipe.needs_republish = _authored_content_differs(recipe, revision)
        session.flush()
        _call_hook(failure_hook, "after_projection_link", recipe_id)
        if not projection_matches_revision(projection, revision):
            raise Phase5CSubjectError("projection_revision_mismatch")
        result = connection.execute(
            text(
                f"UPDATE {_OUTCOME_TABLE} SET execution_disposition = 'converted', "
                "target_recipe_id = :recipe_id, "
                "reused_projection_food_item_id = :projection_id, "
                "created_revision_id = :revision_id, "
                "created_revision_digest = :revision_digest, "
                "checkpoint_state = 'domain_committed', verification_state = 'pending' "
                "WHERE run_id = :run_id AND source_recipe_id = :recipe_id "
                "AND checkpoint_state = 'pending'"
            ),
            {
                "run_id": run["id"],
                "recipe_id": recipe.id,
                "projection_id": projection.id,
                "revision_id": revision.id,
                "revision_digest": revision.content_digest,
            },
        )
        if result.rowcount != 1:
            raise Phase5CSubjectError("subject_checkpoint_changed")
    finally:
        session.close()


def _post_commit_verify(
    connection: Connection,
    *,
    run: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
) -> None:
    recipe_id = UUID(decision["source_recipe_id"])
    try:
        with connection.begin():
            outcome = _load_outcome(connection, run["id"], recipe_id)
            _verify_converted_outcome(
                connection,
                run=run,
                outcome=outcome,
                decision=decision,
                plan=plan,
                archive_schema=archive_schema,
            )
            connection.execute(
                text(
                    f"UPDATE {_OUTCOME_TABLE} SET checkpoint_state = 'completed', "
                    "verification_state = 'verified' WHERE run_id = :run_id "
                    "AND source_recipe_id = :recipe_id "
                    "AND checkpoint_state = 'domain_committed'"
                ),
                {"run_id": run["id"], "recipe_id": recipe_id},
            )
    except Phase5CAdmissionError:
        raise
    except Exception:
        _record_verification_failure(
            connection,
            run_id=run["id"],
            recipe_id=recipe_id,
            reason_code="post_commit_verification_failed",
        )


def _verify_completed_outcome(
    connection: Connection,
    *,
    run: dict[str, Any],
    outcome: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
) -> None:
    expected_execution = {
        "convert": "converted",
        "quarantine": "quarantined",
        "block": "blocked",
    }[decision["intended_disposition"]]
    if outcome["execution_disposition"] != expected_execution:
        raise Phase5CAdmissionError("Completed checkpoint disposition differs from plan")
    try:
        if decision["intended_disposition"] == "convert":
            with connection.begin():
                _verify_converted_outcome(
                    connection,
                    run=run,
                    outcome=outcome,
                    decision=decision,
                    plan=plan,
                    archive_schema=archive_schema,
                )
        else:
            with connection.begin():
                _verify_subject_source(
                    connection,
                    run=run,
                    recipe_id=UUID(decision["source_recipe_id"]),
                    expected_checksum=decision["source_checksum"],
                    archive_schema=archive_schema,
                )
    except Phase5CSubjectError:
        raise Phase5CAdmissionError(
            "Completed conversion checkpoint verification failed"
        ) from None


def _verify_converted_outcome(
    connection: Connection,
    *,
    run: dict[str, Any],
    outcome: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
) -> None:
    recipe_id = UUID(decision["source_recipe_id"])
    payload = _verify_subject_source(
        connection,
        run=run,
        recipe_id=recipe_id,
        expected_checksum=decision["source_checksum"],
        archive_schema=archive_schema,
        require_owner=True,
    )
    source_recipe, source_ingredients = _subject_source(
        payload, recipe_id, decision["source_checksum"]
    )
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="rollback_only",
    )
    try:
        recipe = session.scalars(
            select(Recipe)
            .where(Recipe.id == recipe_id)
            .options(
                selectinload(Recipe.ingredients)
                .selectinload(RecipeIngredient.food_item)
                .selectinload(FoodItem.nutrients),
                selectinload(Recipe.ingredients)
                .selectinload(RecipeIngredient.food_item)
                .selectinload(FoodItem.serving_definitions),
                selectinload(Recipe.ingredients)
                .selectinload(RecipeIngredient.food_item)
                .selectinload(FoodItem.sources),
            )
        ).first()
        revision = session.scalars(
            select(RecipePublicationRevision)
            .where(RecipePublicationRevision.id == outcome["created_revision_id"])
            .options(
                selectinload(RecipePublicationRevision.amount_definitions),
                selectinload(RecipePublicationRevision.nutrients),
            )
        ).first()
        projection = session.scalars(
            select(FoodItem)
            .where(FoodItem.id == source_recipe["food_item_id"])
            .options(
                selectinload(FoodItem.nutrients),
                selectinload(FoodItem.serving_definitions),
                selectinload(FoodItem.sources),
            )
        ).first()
        if recipe is None or revision is None or projection is None:
            raise Phase5CSubjectError("converted_target_missing")
        if (
            recipe.id != source_recipe["id"]
            or recipe.user_id != source_recipe["user_id"]
            or recipe.published_food_item_id != projection.id
            or recipe.name != projection.name
            or recipe.notes != projection.notes
            or recipe.serving_count_yield != source_recipe["serving_count"]
            or recipe.final_cooked_weight_grams != source_recipe["final_yield_quantity"]
            or recipe.created_at != source_recipe["created_at"]
            or recipe.updated_at != source_recipe["updated_at"]
        ):
            raise Phase5CSubjectError("converted_recipe_mismatch")
        actual_ingredients = sorted(recipe.ingredients, key=lambda row: (row.position, str(row.id)))
        expected_ingredients = sorted(
            source_ingredients, key=lambda row: (row["sort_order"], str(row["id"]))
        )
        if len(actual_ingredients) != len(expected_ingredients):
            raise Phase5CSubjectError("converted_ingredient_count_mismatch")
        for actual, expected in zip(actual_ingredients, expected_ingredients, strict=True):
            if (
                actual.id != expected["id"]
                or actual.food_item_id != expected["ingredient_food_item_id"]
                or actual.position != expected["sort_order"]
                or actual.amount_quantity != expected["quantity"]
                or actual.amount_unit != expected["unit"]
                or actual.serving_definition_id != expected["serving_definition_id"]
                or actual.resolved_gram_amount != expected["gram_amount"]
                or actual.preparation_note != expected["preparation_note"]
            ):
                raise Phase5CSubjectError("converted_ingredient_mismatch")
        revision_count = session.scalar(
            select(func.count())
            .select_from(RecipePublicationRevision)
            .where(RecipePublicationRevision.recipe_id == recipe.id)
        )
        if revision_count != 1:
            raise Phase5CSubjectError("converted_revision_cardinality_mismatch")
        if (
            revision.recipe_id != recipe.id
            or revision.user_id != recipe.user_id
            or revision.revision_number != 1
            or revision.creation_origin != "legacy_projection_capture"
            or revision.provenance_confidence != "transition_baseline"
            or revision.content_digest != outcome["created_revision_digest"]
            or revision_content_digest(revision) != revision.content_digest
            or recipe.active_publication_revision_id != revision.id
            or projection.recipe_publication_revision_id != revision.id
            or not projection_matches_revision(projection, revision)
        ):
            raise Phase5CSubjectError("converted_revision_mismatch")
        if recipe.needs_republish != _authored_content_differs(recipe, revision):
            raise Phase5CSubjectError("converted_staleness_mismatch")
    finally:
        session.close()


def _verify_subject_source(
    connection: Connection,
    *,
    run: dict[str, Any],
    recipe_id: UUID,
    expected_checksum: str,
    archive_schema: str,
    require_owner: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    _verify_run_binding(connection, run)
    payload = planning_subject_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=str(connection.scalar(text("SELECT current_schema()"))),
        recipe_id=recipe_id,
    )
    source_recipe, _ = _subject_source(payload, recipe_id, expected_checksum)
    if require_owner:
        _require_subject_owner(payload, source_recipe)
    return payload


def _verify_run_binding(connection: Connection, run: dict[str, Any]) -> None:
    columns = ", ".join(_RUN_BINDING_COLUMNS)
    stored = connection.execute(
        text(f"SELECT {columns} FROM {_RUN_TABLE} WHERE id = :run_id"),
        {"run_id": run["id"]},
    ).mappings().one_or_none()
    expected = {column: run[column] for column in _RUN_BINDING_COLUMNS}
    if stored is None or dict(stored) != expected:
        raise Phase5CAdmissionError("Conversion run binding changed")


def _verify_run_level_state(
    connection: Connection,
    *,
    run: dict[str, Any],
    plan: dict[str, Any],
    archive_schema: str,
) -> None:
    _verify_run_binding(connection, run)
    payload = planning_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=str(connection.scalar(text("SELECT current_schema()"))),
    )
    _verify_payload_checksums(payload, plan)
    if (
        _relation_state_digest(connection, _DAILY_LOG_TABLES)
        != run["daily_log_state_digest"]
    ):
        raise Phase5CSubjectError("daily_log_state_changed")
    if _relation_state_digest(connection, _OCR_TABLES) != run["ocr_state_digest"]:
        raise Phase5CSubjectError("ocr_state_changed")


def _verify_payload_checksums(
    payload: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any],
) -> None:
    checksums = _archive_checksums(payload)
    expected = {
        "recipes_checksum": plan["source_checksums"]["archived_recipes"],
        "ingredients_checksum": plan["source_checksums"][
            "archived_recipe_ingredients"
        ],
        "archive_checksum": plan["source_checksums"]["archive"],
        "planning_source_checksum": plan["source_checksums"]["planning_source"],
    }
    if any(checksums[key] != value for key, value in expected.items()):
        raise Phase5CSubjectError("conversion_source_checksum_changed")


def _subject_source(
    payload: dict[str, list[dict[str, Any]]],
    recipe_id: UUID,
    expected_checksum: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recipes = _by_id(payload["recipes"])
    ingredients = _by_recipe(payload["recipe_ingredients"])
    foods = _by_id(payload["food_items"])
    servings_by_food = _by_food(payload["serving_definitions"])
    serving_by_id = _by_id(payload["serving_definitions"])
    nutrients_by_food = _by_food(payload["food_nutrients"])
    sources_by_food = _by_food(payload["food_sources"])
    recipe = recipes.get(recipe_id)
    if recipe is None:
        raise Phase5CSubjectError("archived_recipe_missing")
    rows = ingredients.get(recipe_id, [])
    actual = _recipe_source_checksum(
        recipe,
        ingredients=rows,
        foods=foods,
        servings_by_food=servings_by_food,
        serving_by_id=serving_by_id,
        nutrients_by_food=nutrients_by_food,
        sources_by_food=sources_by_food,
    )
    if actual != expected_checksum:
        raise Phase5CSubjectError("subject_source_checksum_changed")
    return recipe, rows


def _require_subject_owner(
    payload: dict[str, list[dict[str, Any]]], recipe: dict[str, Any]
) -> None:
    if recipe["user_id"] not in {row["id"] for row in payload["users"]}:
        raise Phase5CSubjectError("subject_owner_missing")


def _validate_locked_subject(
    *,
    source_recipe: dict[str, Any],
    source_ingredients: list[dict[str, Any]],
    foods: dict[UUID, FoodItem],
    projection: FoodItem,
) -> None:
    owner_id = source_recipe["user_id"]
    if (
        projection.user_id != owner_id
        or projection.deleted_at is not None
        or projection.source_type != "recipe"
        or projection.source_id not in {None, str(source_recipe["id"])}
        or not projection.is_recipe
        or projection.recipe_publication_revision_id is not None
    ):
        raise Phase5CSubjectError("projection_linkage_changed")
    if source_recipe["serving_count"] is not None and source_recipe["serving_count"] <= 0:
        raise Phase5CSubjectError("recipe_serving_count_invalid")
    if source_recipe["final_yield_quantity"] is not None:
        if (
            source_recipe["final_yield_quantity"] <= 0
            or str(source_recipe["final_yield_unit"]).strip().casefold() != "g"
        ):
            raise Phase5CSubjectError("recipe_final_yield_invalid")
    for ingredient in source_ingredients:
        food = foods[ingredient["ingredient_food_item_id"]]
        if food.user_id != owner_id or food.deleted_at is not None:
            raise Phase5CSubjectError("ingredient_ownership_changed")
        serving_id = ingredient["serving_definition_id"]
        if serving_id is not None and not any(
            serving.id == serving_id and serving.food_item_id == food.id
            for serving in food.serving_definitions
        ):
            raise Phase5CSubjectError("ingredient_serving_membership_changed")


def _authored_content_differs(
    recipe: Recipe,
    captured_revision: RecipePublicationRevision,
) -> bool:
    snapshots: list[NutrientSnapshot] = []
    try:
        for ingredient in recipe.ingredients:
            resolved = _resolve_preserved_legacy_amount(ingredient)
            for nutrient in resolved.nutrients:
                snapshots.append(
                    NutrientSnapshot(
                        nutrient_id=nutrient.nutrient_id,
                        amount=nutrient.amount,
                        unit=nutrient.unit,
                        data_status=nutrient.data_status,
                    )
                )
    except (NutritionResolutionError, ValueError) as exc:
        raise Phase5CSubjectError("publication_equivalence_unavailable") from exc
    totals = [
        AggregatedNutrientTotal(
            nutrient_id=total.nutrient_id,
            amount_known=total.amount_known.quantize(_DECIMAL_PLACES),
            amount_estimated=total.amount_estimated.quantize(_DECIMAL_PLACES),
            unit=total.unit,
            has_unknown_contributors=total.has_unknown_contributors,
            unknown_contributor_count=total.unknown_contributor_count,
        )
        for total in aggregate_snapshots(snapshots)
    ]
    per_serving = _divide_totals(totals, recipe.serving_count_yield)
    per_100g = _divide_totals(
        totals,
        (
            recipe.final_cooked_weight_grams / Decimal("100")
            if recipe.final_cooked_weight_grams is not None
            else None
        ),
    )
    comparison = build_revision(
        recipe_id=recipe.id,
        user_id=recipe.user_id,
        revision_number=1,
        creation_origin="legacy_projection_capture",
        provenance_confidence="transition_baseline",
        content=content_from_recipe_output(
            published_name=recipe.name,
            published_notes=recipe.notes,
            serving_count_yield=recipe.serving_count_yield,
            final_cooked_weight_grams=recipe.final_cooked_weight_grams,
            per_serving=per_serving,
            per_100g=per_100g,
        ),
    )
    return comparison.content_digest != captured_revision.content_digest


def _resolve_preserved_legacy_amount(
    ingredient: RecipeIngredient,
) -> ResolvedNutrition:
    """Resolve an exact legacy amount without rewriting its persisted authored fields."""
    unit = ingredient.amount_unit.strip().casefold()
    if unit in {"serving", "g"}:
        return resolve_nutrition(
            ingredient.food_item,
            ingredient.amount_quantity,
            unit,
            ingredient.serving_definition_id,
        )
    serving = next(
        (
            candidate
            for candidate in ingredient.food_item.serving_definitions
            if candidate.id == ingredient.serving_definition_id
        ),
        None,
    )
    if (
        serving is None
        or unit != serving.unit.strip().casefold()
        or serving.quantity <= 0
    ):
        raise Phase5CSubjectError("publication_equivalence_unavailable")
    return resolve_nutrition(
        ingredient.food_item,
        ingredient.amount_quantity / serving.quantity,
        "serving",
        serving.id,
    )


def _divide_totals(
    totals: list[AggregatedNutrientTotal],
    divisor: Decimal | None,
) -> list[AggregatedNutrientTotal] | None:
    if divisor is None or divisor <= 0:
        return None
    return [
        AggregatedNutrientTotal(
            nutrient_id=total.nutrient_id,
            amount_known=(total.amount_known / divisor).quantize(_DECIMAL_PLACES),
            amount_estimated=(total.amount_estimated / divisor).quantize(
                _DECIMAL_PLACES
            ),
            unit=total.unit,
            has_unknown_contributors=total.has_unknown_contributors,
            unknown_contributor_count=total.unknown_contributor_count,
        )
        for total in totals
    ]


def _load_outcome(connection: Connection, run_id: UUID, recipe_id: UUID) -> dict[str, Any]:
    row = connection.execute(
        text(
            f"SELECT * FROM {_OUTCOME_TABLE} WHERE run_id = :run_id "
            "AND source_recipe_id = :recipe_id"
        ),
        {"run_id": run_id, "recipe_id": recipe_id},
    ).mappings().one_or_none()
    if row is None:
        raise Phase5CAdmissionError("Planned conversion outcome is absent")
    return dict(row)


def _dependencies_completed(
    connection: Connection,
    *,
    run_id: UUID,
    dependencies: set[UUID],
) -> bool:
    if not dependencies:
        return True
    rows = connection.execute(
        text(
            f"SELECT source_recipe_id, execution_disposition, checkpoint_state "
            f"FROM {_OUTCOME_TABLE} WHERE run_id = :run_id "
            "AND source_recipe_id = ANY(:ids)"
        ),
        {"run_id": run_id, "ids": list(dependencies)},
    ).mappings().all()
    return len(rows) == len(dependencies) and all(
        row["execution_disposition"] == "converted"
        and row["checkpoint_state"] == "completed"
        for row in rows
    )


def _record_subject_failure(
    connection: Connection,
    *,
    run_id: UUID,
    recipe_id: UUID,
    reason_code: str,
) -> None:
    with connection.begin():
        connection.execute(
            text(
                f"UPDATE {_OUTCOME_TABLE} SET execution_disposition = 'failed', "
                "failure_reason_code = :reason, checkpoint_state = 'failed', "
                "verification_state = 'failed' WHERE run_id = :run_id "
                "AND source_recipe_id = :recipe_id AND checkpoint_state = 'pending'"
            ),
            {"reason": reason_code, "run_id": run_id, "recipe_id": recipe_id},
        )


def _record_verification_failure(
    connection: Connection,
    *,
    run_id: UUID,
    recipe_id: UUID,
    reason_code: str,
) -> None:
    with connection.begin():
        connection.execute(
            text(
                f"UPDATE {_OUTCOME_TABLE} SET failure_reason_code = :reason, "
                "checkpoint_state = 'failed', verification_state = 'failed' "
                "WHERE run_id = :run_id AND source_recipe_id = :recipe_id "
                "AND execution_disposition = 'converted'"
            ),
            {"reason": reason_code, "run_id": run_id, "recipe_id": recipe_id},
        )


def _finalize_run(connection: Connection, run_id: UUID) -> None:
    states = connection.execute(
        text(
            f"SELECT checkpoint_state FROM {_OUTCOME_TABLE} WHERE run_id = :run_id"
        ),
        {"run_id": run_id},
    ).scalars().all()
    if any(state == "failed" for state in states):
        execution, verification, reason = "failed", "failed", "subject_failure"
    elif all(state == "completed" for state in states):
        execution, verification, reason = "completed", "verified", None
    else:
        execution, verification, reason = "running", "pending", None
    connection.execute(
        text(
            f"UPDATE {_RUN_TABLE} SET execution_state = :execution, "
            "verification_state = :verification, failure_reason_code = :reason "
            "WHERE id = :run_id"
        ),
        {
            "execution": execution,
            "verification": verification,
            "reason": reason,
            "run_id": run_id,
        },
    )


def _fail_run_level_verification(connection: Connection, run_id: UUID) -> None:
    connection.execute(
        text(
            f"UPDATE {_RUN_TABLE} SET execution_state = 'failed', "
            "verification_state = 'failed', "
            "failure_reason_code = 'run_level_verification_failed' "
            "WHERE id = :run_id"
        ),
        {"run_id": run_id},
    )


def _build_report(connection: Connection, run_id: UUID) -> dict[str, Any]:
    run = dict(
        connection.execute(
            text(f"SELECT * FROM {_RUN_TABLE} WHERE id = :run_id"),
            {"run_id": run_id},
        ).mappings().one()
    )
    rows = connection.execute(
        text(
            f"SELECT * FROM {_OUTCOME_TABLE} WHERE run_id = :run_id "
            "ORDER BY source_recipe_id"
        ),
        {"run_id": run_id},
    ).mappings().all()
    counts = {"converted": 0, "quarantined": 0, "blocked": 0, "failed": 0, "pending": 0}
    subjects = []
    for row in rows:
        disposition = row["execution_disposition"] or "pending"
        if row["checkpoint_state"] == "failed":
            count_key = "failed"
            report_disposition = "failed"
            reason = row["failure_reason_code"]
        else:
            count_key = disposition
            report_disposition = disposition
            reason = row["planned_reason_code"]
        counts[count_key] += 1
        subject = {
            "source_recipe_id": str(row["source_recipe_id"]),
            "disposition": report_disposition,
            "reason_code": reason,
        }
        if row["target_recipe_id"] is not None:
            subject["target_recipe_id"] = str(row["target_recipe_id"])
            subject["projection_food_item_id"] = str(
                row["reused_projection_food_item_id"]
            )
            subject["revision_id"] = str(row["created_revision_id"])
            subject["revision_digest"] = row["created_revision_digest"]
        subjects.append(subject)
    unsigned = {
        "receipt_version": EXECUTION_RECEIPT_VERSION,
        "run_id": str(run["id"]),
        "plan_digest": run["plan_digest"],
        "converter_version": run["converter_version"],
        "counts": counts,
        "subjects": subjects,
        "verification_result": run["verification_state"],
    }
    return {**unsigned, "report_digest": canonical_digest(unsigned)}


def _relation_state_digest(connection: Connection, tables: tuple[str, ...]) -> str:
    existing = set(inspect(connection).get_table_names())
    payload: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        if table not in existing:
            payload[table] = []
            continue
        rows = [dict(row) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()]
        payload[table] = sorted(rows, key=canonical_json)
    return canonical_digest(payload)


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


def _call_hook(hook: FailureHook | None, stage: str, recipe_id: UUID) -> None:
    if hook is not None:
        hook(stage, recipe_id)


def _notify_performance_observer(
    observer: PerformanceObserver | None,
    event: str,
    *,
    recipe_id: UUID | None = None,
    disposition: str | None = None,
    attempt: int | None = None,
) -> None:
    if observer is not None:
        observer(event, recipe_id, disposition, attempt)


@contextmanager
def _observed_operation(
    observer: PerformanceObserver | None,
    operation: str,
    *,
    recipe_id: UUID | None = None,
    disposition: str | None = None,
) -> Iterator[None]:
    _notify_performance_observer(
        observer,
        f"{operation}_start",
        recipe_id=recipe_id,
        disposition=disposition,
    )
    try:
        yield
    finally:
        _notify_performance_observer(
            observer,
            f"{operation}_end",
            recipe_id=recipe_id,
            disposition=disposition,
        )
