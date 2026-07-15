from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, inspect, select, text
from sqlalchemy.orm import Session, selectinload

from app.domain.nutrition import AggregatedNutrientTotal, NutrientSnapshot
from app.models.food import FoodItem
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import RecipePublicationRevision
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.resolution import NutritionResolutionError, ResolvedNutrition, resolve_nutrition
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    _archive_checksums,
    _current_revision,
    _qualified,
    load_bridge_metadata,
    phase5c_advisory_lock,
    planning_source_payload,
)
from app.operators.historical_recipe_planner import _recipe_source_checksum
from app.operators.phase5c_contracts import (
    EXECUTION_RECEIPT_VERSION,
    EXECUTION_REVISION,
    QUALIFICATION_DIAGNOSTIC_VERSION,
    QUALIFICATION_RECEIPT_VERSION,
    QUALIFIER_VERSION,
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
    validate_operator_attestation,
    verify_clone_isolation_evidence,
)
from app.publication.recipe_revision import (
    build_revision,
    content_from_recipe_output,
    projection_matches_revision,
    revision_content_digest,
)


_RUN_TABLE = "phase5c_conversion_runs"
_OUTCOME_TABLE = "phase5c_conversion_outcomes"
_DAILY_LOG_TABLES = ("daily_logs", "daily_log_nutrient_snapshots")
_OCR_TABLES = (
    "ocr_scans",
    "parse_results",
    "parser_corrections",
    "ocr_nutrition_confirmation_traces",
)
_DECIMAL_PLACES = Decimal("0.000001")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_FAILURE_CODES = {
    "qualification_evidence_mismatch",
    "qualification_archive_checksum_changed",
    "qualification_outcome_cardinality_invalid",
    "qualification_converted_mapping_invalid",
    "qualification_revision_digest_invalid",
    "qualification_projection_snapshot_invalid",
    "qualification_staleness_invalid",
    "qualification_dependency_cycle",
    "qualification_dependency_invalid",
    "qualification_nonconvert_domain_row_exists",
    "qualification_daily_log_state_changed",
    "qualification_ocr_state_changed",
    "qualification_unexplained_current_domain_row",
    "qualification_execution_receipt_mismatch",
    "qualification_run_incomplete",
    "qualification_snapshot_unstable",
}


class Phase5CQualificationError(RuntimeError):
    def __init__(self, reason_code: str):
        if reason_code not in _FAILURE_CODES:
            reason_code = "qualification_evidence_mismatch"
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class QualificationReceipt:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        return "\n".join(
            (
                "Phase 5C independent conversion qualification",
                f"Run: {self.payload['conversion_run_id']}",
                f"Plan: {self.payload['plan']['digest']}",
                f"Result: {self.payload['verification_result']}",
                f"Converted: {self.payload['observed_counts']['converted']}",
                f"Quarantined: {self.payload['observed_counts']['quarantined']}",
                f"Blocked: {self.payload['observed_counts']['blocked']}",
                f"Outcome ledger: {self.payload['outcome_ledger_digest']}",
                f"Receipt digest: {self.payload['receipt_digest']}",
            )
        )


@dataclass(frozen=True)
class QualificationDiagnostic:
    reason_code: str

    @property
    def payload(self) -> dict[str, str]:
        unsigned = {
            "diagnostic_version": QUALIFICATION_DIAGNOSTIC_VERSION,
            "verification_result": "not_qualified",
            "reason_code": self.reason_code,
        }
        return {**unsigned, "diagnostic_digest": canonical_digest(unsigned)}

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        return "\n".join(
            (
                "Phase 5C independent conversion qualification",
                "Result: not_qualified",
                f"Reason: {self.reason_code}",
                f"Diagnostic digest: {self.payload['diagnostic_digest']}",
            )
        )


def validate_qualification_receipt_contract(payload: Any) -> dict[str, Any]:
    expected = {
        "receipt_version",
        "verifier_version",
        "plan",
        "execution_attestation",
        "conversion_run_id",
        "execution_receipt",
        "clone_marker_digest",
        "archive_identity_digest",
        "inventory_digest",
        "schema_signature_digest",
        "conversion_rules_version",
        "planned_counts",
        "observed_counts",
        "reason_code_counts",
        "source_roots",
        "daily_log_state_digest",
        "ocr_state_digest",
        "outcome_ledger_digest",
        "verification_result",
        "receipt_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    if (
        payload.get("receipt_version") != QUALIFICATION_RECEIPT_VERSION
        or payload.get("verifier_version") != QUALIFIER_VERSION
        or payload.get("verification_result") != "qualified"
    ):
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    for field in (
        "clone_marker_digest",
        "archive_identity_digest",
        "inventory_digest",
        "schema_signature_digest",
        "daily_log_state_digest",
        "ocr_state_digest",
        "outcome_ledger_digest",
        "receipt_digest",
    ):
        if not _is_digest(payload.get(field)):
            raise Phase5CQualificationError("qualification_evidence_mismatch")
    for field in ("plan", "execution_attestation", "execution_receipt"):
        evidence = payload.get(field)
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"contract_version", "digest"}
            or not isinstance(evidence["contract_version"], str)
            or not _is_digest(evidence["digest"])
        ):
            raise Phase5CQualificationError("qualification_evidence_mismatch")
    try:
        UUID(str(payload.get("conversion_run_id")))
    except (TypeError, ValueError):
        raise Phase5CQualificationError("qualification_evidence_mismatch") from None
    if set(payload.get("source_roots", {})) != {
        "archived_recipes",
        "archived_recipe_ingredients",
        "archive",
        "planning_source",
    } or any(not _is_digest(value) for value in payload["source_roots"].values()):
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    for field in ("planned_counts", "observed_counts"):
        counts = payload.get(field)
        if not isinstance(counts, dict) or any(
            not isinstance(value, int) or value < 0 for value in counts.values()
        ):
            raise Phase5CQualificationError("qualification_evidence_mismatch")
    reason_counts = payload.get("reason_code_counts")
    if not isinstance(reason_counts, dict) or set(reason_counts) != {
        "planned",
        "observed",
    }:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    for values in reason_counts.values():
        if not isinstance(values, dict) or any(
            not isinstance(code, str)
            or not _REASON_CODE.fullmatch(code)
            or not isinstance(count, int)
            or count < 0
            for code, count in values.items()
        ):
            raise Phase5CQualificationError("qualification_evidence_mismatch")
    unsigned = {key: value for key, value in payload.items() if key != "receipt_digest"}
    if canonical_digest(unsigned) != payload["receipt_digest"]:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    return payload


def load_execution_receipt_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CQualificationError(
            "qualification_execution_receipt_mismatch"
        ) from None
    return validate_execution_receipt_contract(payload)


def validate_execution_receipt_contract(payload: Any) -> dict[str, Any]:
    expected = {
        "receipt_version",
        "run_id",
        "plan_digest",
        "converter_version",
        "counts",
        "subjects",
        "verification_result",
        "report_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    if payload.get("receipt_version") != EXECUTION_RECEIPT_VERSION:
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    try:
        UUID(str(payload.get("run_id")))
    except (TypeError, ValueError):
        raise Phase5CQualificationError(
            "qualification_execution_receipt_mismatch"
        ) from None
    if not _is_digest(payload.get("plan_digest")) or not _is_digest(
        payload.get("report_digest")
    ):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    if not isinstance(payload.get("converter_version"), str):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    counts = payload.get("counts")
    if not isinstance(counts, dict) or set(counts) != {
        "converted",
        "quarantined",
        "blocked",
        "failed",
        "pending",
    }:
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    if any(not isinstance(value, int) or value < 0 for value in counts.values()):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    subjects = payload.get("subjects")
    if not isinstance(subjects, list) or sum(counts.values()) != len(subjects):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    seen: set[UUID] = set()
    for subject in subjects:
        base = {"source_recipe_id", "disposition", "reason_code"}
        converted = subject.get("disposition") == "converted" if isinstance(subject, dict) else False
        expected_subject = base | (
            {"target_recipe_id", "projection_food_item_id", "revision_id", "revision_digest"}
            if converted
            else set()
        )
        if not isinstance(subject, dict) or set(subject) != expected_subject:
            raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
        try:
            recipe_id = UUID(str(subject["source_recipe_id"]))
            if converted:
                UUID(str(subject["target_recipe_id"]))
                UUID(str(subject["projection_food_item_id"]))
                UUID(str(subject["revision_id"]))
        except (TypeError, ValueError):
            raise Phase5CQualificationError(
                "qualification_execution_receipt_mismatch"
            ) from None
        if recipe_id in seen:
            raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
        seen.add(recipe_id)
        if subject["disposition"] not in {
            "converted",
            "quarantined",
            "blocked",
            "failed",
            "pending",
        }:
            raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
        if not isinstance(subject["reason_code"], str) or not _REASON_CODE.fullmatch(
            subject["reason_code"]
        ):
            raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
        if converted and not _is_digest(subject["revision_digest"]):
            raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    unsigned = {key: value for key, value in payload.items() if key != "report_digest"}
    if canonical_digest(unsigned) != payload["report_digest"]:
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    return payload


def qualify_historical_recipe_conversion(
    engine: Engine,
    *,
    plan_payload: dict[str, Any],
    inventory_payload: dict[str, Any],
    execution_attestation_payload: dict[str, Any],
    execution_receipt_payload: dict[str, Any],
    archive_schema: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
) -> QualificationReceipt:
    try:
        plan = validate_conversion_plan_contract(plan_payload)
        inventory = validate_inventory_contract(inventory_payload)
        attestation = validate_operator_attestation(execution_attestation_payload)
        execution_receipt = validate_execution_receipt_contract(
            execution_receipt_payload
        )
    except Phase5CQualificationError:
        raise
    except Phase5CAdmissionError:
        raise Phase5CQualificationError("qualification_evidence_mismatch") from None
    if engine.dialect.name != "postgresql":
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    inventory_digest = canonical_digest(inventory)
    if plan["inventory_digest"] != inventory_digest:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    if plan["source_identity"]["archive_schema"] != archive_schema:
        raise Phase5CQualificationError("qualification_evidence_mismatch")

    with engine.connect() as connection:
        source_schema = str(connection.scalar(text("SELECT current_schema()")))
        connection.rollback()
        try:
            with _qualification_operation(
                connection,
                plan=plan,
                inventory_digest=inventory_digest,
                execution_attestation=attestation,
                source_schema=source_schema,
                conversion_clone_id=conversion_clone_id,
                clone_marker_identity=clone_marker_identity,
            ) as isolation_evidence:
                transaction = connection.begin()
                try:
                    connection.execute(
                        text(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                        )
                    )
                    if connection.scalar(text("SHOW transaction_read_only")) != "on":
                        raise Phase5CQualificationError(
                            "qualification_snapshot_unstable"
                        )
                    before = _database_state_digest(
                        connection,
                        source_schema=source_schema,
                        archive_schema=archive_schema,
                    )
                    receipt = _qualify_snapshot(
                        connection,
                        plan=plan,
                        execution_attestation=attestation,
                        execution_receipt=execution_receipt,
                        archive_schema=archive_schema,
                        source_schema=source_schema,
                        isolation_evidence=isolation_evidence,
                    )
                    after = _database_state_digest(
                        connection,
                        source_schema=source_schema,
                        archive_schema=archive_schema,
                    )
                    if before != after:
                        raise Phase5CQualificationError(
                            "qualification_snapshot_unstable"
                        )
                    return QualificationReceipt(receipt)
                finally:
                    transaction.rollback()
        except Phase5CQualificationError:
            raise
        except (Phase5CAdmissionError, LookupError, ValueError, TypeError):
            raise Phase5CQualificationError("qualification_evidence_mismatch") from None
        except Exception:
            raise Phase5CQualificationError("qualification_evidence_mismatch") from None


@contextmanager
def _qualification_operation(
    connection: Connection,
    *,
    plan: dict[str, Any],
    inventory_digest: str,
    execution_attestation: dict[str, Any],
    source_schema: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
) -> Iterator[dict[str, Any]]:
    evidence = _verify_isolation(
        connection,
        plan=plan,
        inventory_digest=inventory_digest,
        execution_attestation=execution_attestation,
        conversion_clone_id=conversion_clone_id,
        clone_marker_identity=clone_marker_identity,
    )
    with phase5c_maintenance_session(connection, evidence["clone_marker_digest"]):
        assert_database_session_isolation(connection, evidence["clone_marker_digest"])
        connection.commit()
        with phase5c_advisory_lock(connection, source_schema):
            evidence = _verify_isolation(
                connection,
                plan=plan,
                inventory_digest=inventory_digest,
                execution_attestation=execution_attestation,
                conversion_clone_id=conversion_clone_id,
                clone_marker_identity=clone_marker_identity,
            )
            assert_database_session_isolation(
                connection, evidence["clone_marker_digest"]
            )
            connection.commit()
            yield evidence


def _verify_isolation(
    connection: Connection,
    *,
    plan: dict[str, Any],
    inventory_digest: str,
    execution_attestation: dict[str, Any],
    conversion_clone_id: str,
    clone_marker_identity: str,
) -> dict[str, Any]:
    try:
        return verify_clone_isolation_evidence(
            connection,
            attestation_payload=execution_attestation,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
            inventory_digest=inventory_digest,
            schema_signature=SUPPORTED_SCHEMA_SIGNATURE,
            schema_signature_digest=SCHEMA_SIGNATURE_DIGEST,
            operation="execution",
            conversion_plan_payload=plan,
        )
    except Phase5CAdmissionError:
        raise Phase5CQualificationError("qualification_evidence_mismatch") from None


def _qualify_snapshot(
    connection: Connection,
    *,
    plan: dict[str, Any],
    execution_attestation: dict[str, Any],
    execution_receipt: dict[str, Any],
    archive_schema: str,
    source_schema: str,
    isolation_evidence: dict[str, Any],
) -> dict[str, Any]:
    if _current_revision(connection, source_schema) != EXECUTION_REVISION:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    run = _load_run(connection, execution_receipt["run_id"])
    metadata = load_bridge_metadata(connection, archive_schema)
    payload = planning_source_payload(
        connection,
        recipe_schema=archive_schema,
        supporting_schema=source_schema,
    )
    checksums = _archive_checksums(payload)
    _verify_run_and_roots(
        plan=plan,
        execution_attestation=execution_attestation,
        execution_receipt=execution_receipt,
        isolation_evidence=isolation_evidence,
        run=run,
        metadata=metadata,
        checksums=checksums,
    )
    outcomes = _load_outcomes(connection, UUID(str(run["id"])))
    _verify_outcome_cardinality(plan, outcomes)
    _verify_graph(connection, plan=plan, outcomes=outcomes, source_payload=payload)
    ledger = _verify_subjects(
        connection,
        plan=plan,
        run=run,
        outcomes=outcomes,
        source_payload=payload,
    )
    _verify_unexplained_state(connection, plan=plan, outcomes=outcomes)
    daily_digest = _relation_state_digest(connection, _DAILY_LOG_TABLES)
    if daily_digest != run["daily_log_state_digest"]:
        raise Phase5CQualificationError("qualification_daily_log_state_changed")
    ocr_digest = _relation_state_digest(connection, _OCR_TABLES)
    if ocr_digest != run["ocr_state_digest"]:
        raise Phase5CQualificationError("qualification_ocr_state_changed")
    observed_counts = _observed_counts(outcomes)
    _verify_execution_receipt(
        execution_receipt,
        run=run,
        outcomes=outcomes,
        observed_counts=observed_counts,
    )
    return _qualification_receipt(
        plan=plan,
        execution_attestation=execution_attestation,
        execution_receipt=execution_receipt,
        run=run,
        checksums=checksums,
        observed_counts=observed_counts,
        outcomes=outcomes,
        daily_digest=daily_digest,
        ocr_digest=ocr_digest,
        ledger=ledger,
    )


def _load_run(connection: Connection, run_id: str) -> dict[str, Any]:
    rows = connection.execute(
        text(f"SELECT * FROM {_RUN_TABLE} WHERE id = :run_id"),
        {"run_id": UUID(str(run_id))},
    ).mappings().all()
    if len(rows) != 1:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    return dict(rows[0])


def _load_outcomes(connection: Connection, run_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                f"SELECT * FROM {_OUTCOME_TABLE} WHERE run_id = :run_id "
                "ORDER BY source_recipe_id"
            ),
            {"run_id": run_id},
        ).mappings()
    ]


def _verify_run_and_roots(
    *,
    plan: dict[str, Any],
    execution_attestation: dict[str, Any],
    execution_receipt: dict[str, Any],
    isolation_evidence: dict[str, Any],
    run: dict[str, Any],
    metadata: dict[str, Any],
    checksums: dict[str, Any],
) -> None:
    source_checksums = plan["source_checksums"]
    expected_run = {
        "archive_identity": plan["source_identity"]["archive_identity"],
        "plan_version": plan["manifest_version"],
        "plan_digest": plan["manifest_digest"],
        "inventory_digest": plan["inventory_digest"],
        "schema_signature": plan["supported_schema_signature"]["name"],
        "schema_signature_digest": plan["supported_schema_signature"]["digest"],
        "conversion_rules_version": plan["conversion_rules_version"],
        "recipes_checksum": source_checksums["archived_recipes"],
        "ingredients_checksum": source_checksums["archived_recipe_ingredients"],
        "archive_checksum": source_checksums["archive"],
        "planning_source_checksum": source_checksums["planning_source"],
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "operator_attestation_digest": plan["isolation_evidence"][
            "operator_attestation_digest"
        ],
        "execution_isolation_contract_version": execution_attestation[
            "isolation_evidence_contract_version"
        ],
        "execution_attestation_version": execution_attestation[
            "attestation_version"
        ],
        "execution_attestation_identity": execution_attestation[
            "operator_attestation_identity"
        ],
        "execution_attestation_scope": execution_attestation["scope"],
        "execution_attestation_digest": execution_attestation[
            "attestation_digest"
        ],
    }
    if any(run.get(key) != value for key, value in expected_run.items()):
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    if run.get("execution_state") != "completed" or run.get(
        "verification_state"
    ) != "verified" or run.get("failure_reason_code") is not None:
        raise Phase5CQualificationError("qualification_run_incomplete")
    if execution_receipt["converter_version"] != run.get("converter_version"):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    if isolation_evidence["clone_marker_digest"] != run["clone_marker_digest"]:
        raise Phase5CQualificationError("qualification_evidence_mismatch")
    expected_roots = {
        "recipes_checksum": source_checksums["archived_recipes"],
        "ingredients_checksum": source_checksums["archived_recipe_ingredients"],
        "archive_checksum": source_checksums["archive"],
        "planning_source_checksum": source_checksums["planning_source"],
    }
    if any(checksums.get(key) != value for key, value in expected_roots.items()):
        raise Phase5CQualificationError("qualification_archive_checksum_changed")
    metadata_expectations = {
        "archive_identity": plan["source_identity"]["archive_identity"],
        "inventory_digest": plan["inventory_digest"],
        "schema_signature": plan["supported_schema_signature"]["name"],
        "schema_signature_digest": plan["supported_schema_signature"]["digest"],
        "recipes_checksum": source_checksums["archived_recipes"],
        "ingredients_checksum": source_checksums["archived_recipe_ingredients"],
        "archive_checksum": source_checksums["archive"],
        "planning_source_checksum": source_checksums["planning_source"],
        "conversion_rules_version": plan["conversion_rules_version"],
    }
    if any(metadata.get(key) != value for key, value in metadata_expectations.items()):
        raise Phase5CQualificationError("qualification_archive_checksum_changed")


def _verify_subjects(
    connection: Connection,
    *,
    plan: dict[str, Any],
    run: dict[str, Any],
    outcomes: list[dict[str, Any]],
    source_payload: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    decisions = {UUID(row["source_recipe_id"]): row for row in plan["decisions"]}
    if len(outcomes) != len(decisions):
        raise Phase5CQualificationError("qualification_outcome_cardinality_invalid")
    outcome_by_id: dict[UUID, dict[str, Any]] = {}
    for outcome in outcomes:
        recipe_id = UUID(str(outcome["source_recipe_id"]))
        if recipe_id in outcome_by_id or recipe_id not in decisions:
            raise Phase5CQualificationError(
                "qualification_outcome_cardinality_invalid"
            )
        outcome_by_id[recipe_id] = outcome
    if set(outcome_by_id) != set(decisions):
        raise Phase5CQualificationError("qualification_outcome_cardinality_invalid")

    recipes = {row["id"]: row for row in source_payload["recipes"]}
    ingredients: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in source_payload["recipe_ingredients"]:
        ingredients[row["recipe_id"]].append(row)
    foods = {row["id"]: row for row in source_payload["food_items"]}
    servings_by_food = _group_by_food(source_payload["serving_definitions"])
    serving_by_id = {row["id"]: row for row in source_payload["serving_definitions"]}
    nutrients_by_food = _group_by_food(source_payload["food_nutrients"])
    sources_by_food = _group_by_food(source_payload["food_sources"])

    ledger: list[dict[str, Any]] = []
    for recipe_id in sorted(decisions, key=str):
        decision = decisions[recipe_id]
        outcome = outcome_by_id[recipe_id]
        source_recipe = recipes.get(recipe_id)
        if source_recipe is None:
            raise Phase5CQualificationError("qualification_archive_checksum_changed")
        source_ingredients = sorted(
            ingredients.get(recipe_id, []),
            key=lambda row: (row["sort_order"], str(row["id"])),
        )
        actual_source_checksum = _recipe_source_checksum(
            source_recipe,
            ingredients=source_ingredients,
            foods=foods,
            servings_by_food=servings_by_food,
            serving_by_id=serving_by_id,
            nutrients_by_food=nutrients_by_food,
            sources_by_food=sources_by_food,
        )
        if actual_source_checksum != decision["source_checksum"] or outcome[
            "source_checksum"
        ] != decision["source_checksum"]:
            raise Phase5CQualificationError("qualification_archive_checksum_changed")
        expected_execution = {
            "convert": "converted",
            "quarantine": "quarantined",
            "block": "blocked",
        }[decision["intended_disposition"]]
        if (
            outcome["planned_disposition"] != decision["intended_disposition"]
            or outcome["planned_reason_code"] != decision["reason_code"]
            or outcome["execution_disposition"] != expected_execution
            or outcome["checkpoint_state"] != "completed"
            or outcome["verification_state"] != "verified"
            or outcome["failure_reason_code"] is not None
        ):
            if outcome["checkpoint_state"] in {"pending", "failed", "domain_committed"}:
                raise Phase5CQualificationError("qualification_run_incomplete")
            raise Phase5CQualificationError(
                "qualification_outcome_cardinality_invalid"
            )
        if expected_execution == "converted":
            _verify_converted_subject(
                connection,
                source_recipe=source_recipe,
                source_ingredients=source_ingredients,
                outcome=outcome,
            )
        else:
            _verify_nonconvert_subject(connection, recipe_id=recipe_id, outcome=outcome)
        ledger.append(_ledger_row(decision, outcome))
    return ledger


def _verify_outcome_cardinality(
    plan: dict[str, Any], outcomes: list[dict[str, Any]]
) -> None:
    planned = {UUID(row["source_recipe_id"]) for row in plan["decisions"]}
    observed = [UUID(str(row["source_recipe_id"])) for row in outcomes]
    if len(observed) != len(planned) or len(set(observed)) != len(observed):
        raise Phase5CQualificationError("qualification_outcome_cardinality_invalid")
    if set(observed) != planned:
        raise Phase5CQualificationError("qualification_outcome_cardinality_invalid")


def _verify_converted_subject(
    connection: Connection,
    *,
    source_recipe: dict[str, Any],
    source_ingredients: list[dict[str, Any]],
    outcome: dict[str, Any],
) -> None:
    recipe_id = source_recipe["id"]
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
        projection = session.scalars(
            select(FoodItem)
            .where(FoodItem.id == source_recipe["food_item_id"])
            .options(
                selectinload(FoodItem.nutrients),
                selectinload(FoodItem.serving_definitions),
                selectinload(FoodItem.sources),
            )
        ).first()
        revisions = list(
            session.scalars(
                select(RecipePublicationRevision)
                .where(RecipePublicationRevision.recipe_id == recipe_id)
                .options(
                    selectinload(RecipePublicationRevision.amount_definitions),
                    selectinload(RecipePublicationRevision.nutrients),
                )
            ).all()
        )
        if recipe is None or projection is None or len(revisions) != 1:
            raise Phase5CQualificationError(
                "qualification_converted_mapping_invalid"
            )
        revision = revisions[0]
        if (
            recipe.id != outcome["target_recipe_id"]
            or projection.id != outcome["reused_projection_food_item_id"]
            or revision.id != outcome["created_revision_id"]
            or recipe.id != source_recipe["id"]
            or recipe.user_id != source_recipe["user_id"]
            or recipe.published_food_item_id != source_recipe["food_item_id"]
            or recipe.name != projection.name
            or recipe.notes != projection.notes
            or recipe.serving_count_yield != source_recipe["serving_count"]
            or recipe.final_cooked_weight_grams
            != source_recipe["final_yield_quantity"]
            or recipe.final_cooked_weight_display_quantity is not None
            or recipe.final_cooked_weight_display_unit is not None
            or recipe.created_at != source_recipe["created_at"]
            or recipe.updated_at != source_recipe["updated_at"]
            or recipe.deleted_at is not None
        ):
            raise Phase5CQualificationError(
                "qualification_converted_mapping_invalid"
            )
        actual_ingredients = sorted(
            recipe.ingredients, key=lambda row: (row.position, str(row.id))
        )
        if len(actual_ingredients) != len(source_ingredients):
            raise Phase5CQualificationError(
                "qualification_converted_mapping_invalid"
            )
        for actual, expected in zip(
            actual_ingredients, source_ingredients, strict=True
        ):
            if (
                actual.id != expected["id"]
                or actual.recipe_id != recipe.id
                or actual.food_item_id != expected["ingredient_food_item_id"]
                or actual.position != expected["sort_order"]
                or actual.amount_quantity != expected["quantity"]
                or actual.amount_unit != expected["unit"]
                or actual.amount_display_quantity is not None
                or actual.amount_display_unit is not None
                or actual.serving_definition_id
                != expected["serving_definition_id"]
                or actual.resolved_gram_amount != expected["gram_amount"]
                or actual.preparation_note != expected["preparation_note"]
            ):
                raise Phase5CQualificationError(
                    "qualification_converted_mapping_invalid"
                )
        if (
            revision.recipe_id != recipe.id
            or revision.user_id != recipe.user_id
            or revision.revision_number != 1
            or revision.creation_origin != "legacy_projection_capture"
            or revision.provenance_confidence != "transition_baseline"
            or revision.content_digest != outcome["created_revision_digest"]
            or revision_content_digest(revision) != revision.content_digest
        ):
            raise Phase5CQualificationError("qualification_revision_digest_invalid")
        if (
            recipe.active_publication_revision_id != revision.id
            or projection.recipe_publication_revision_id != revision.id
            or projection.user_id != recipe.user_id
            or projection.source_type != "recipe"
            or projection.source_id not in {None, str(recipe.id)}
            or not projection.is_recipe
            or projection.deleted_at is not None
            or not projection_matches_revision(projection, revision)
        ):
            raise Phase5CQualificationError(
                "qualification_projection_snapshot_invalid"
            )
        if recipe.needs_republish != _authored_content_differs(recipe, revision):
            raise Phase5CQualificationError("qualification_staleness_invalid")
    except Phase5CQualificationError:
        raise
    except (NutritionResolutionError, ValueError, KeyError):
        raise Phase5CQualificationError("qualification_staleness_invalid") from None
    finally:
        session.close()


def _verify_nonconvert_subject(
    connection: Connection,
    *,
    recipe_id: UUID,
    outcome: dict[str, Any],
) -> None:
    counts = connection.execute(
        text(
            "SELECT "
            "(SELECT count(*) FROM recipes WHERE id = :recipe_id) AS recipes, "
            "(SELECT count(*) FROM recipe_ingredients WHERE recipe_id = :recipe_id) "
            "AS ingredients, "
            "(SELECT count(*) FROM recipe_publication_revisions "
            " WHERE recipe_id = :recipe_id) AS revisions"
        ),
        {"recipe_id": recipe_id},
    ).mappings().one()
    linked_projection_count = connection.scalar(
        text(
            "SELECT count(*) FROM food_items food "
            "JOIN recipe_publication_revisions revision "
            "ON revision.id = food.recipe_publication_revision_id "
            "WHERE revision.recipe_id = :recipe_id"
        ),
        {"recipe_id": recipe_id},
    )
    if (
        any(int(value) for value in counts.values())
        or linked_projection_count
        or any(
            outcome.get(key) is not None
            for key in (
                "target_recipe_id",
                "reused_projection_food_item_id",
                "created_revision_id",
                "created_revision_digest",
            )
        )
    ):
        raise Phase5CQualificationError(
            "qualification_nonconvert_domain_row_exists"
        )


def _verify_unexplained_state(
    connection: Connection,
    *,
    plan: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> None:
    converted = [
        row for row in outcomes if row["execution_disposition"] == "converted"
    ]
    expected_recipes = {row["target_recipe_id"] for row in converted}
    expected_revisions = {row["created_revision_id"] for row in converted}
    expected_projections = {row["reused_projection_food_item_id"] for row in converted}
    current_recipes = set(connection.scalars(text("SELECT id FROM recipes")).all())
    current_revisions = set(
        connection.scalars(text("SELECT id FROM recipe_publication_revisions")).all()
    )
    managed = connection.execute(
        text(
            "SELECT id, recipe_publication_revision_id FROM food_items "
            "WHERE recipe_publication_revision_id IS NOT NULL"
        )
    ).mappings().all()
    if (
        current_recipes != expected_recipes
        or current_revisions != expected_revisions
        or {row["id"] for row in managed} != expected_projections
        or {row["recipe_publication_revision_id"] for row in managed}
        != expected_revisions
    ):
        raise Phase5CQualificationError(
            "qualification_unexplained_current_domain_row"
        )
    ingredient_recipe_ids = set(
        connection.scalars(text("SELECT DISTINCT recipe_id FROM recipe_ingredients")).all()
    )
    if not ingredient_recipe_ids <= expected_recipes:
        raise Phase5CQualificationError(
            "qualification_unexplained_current_domain_row"
        )
    amount_revision_ids = set(
        connection.scalars(
            text("SELECT DISTINCT revision_id FROM recipe_publication_amount_definitions")
        ).all()
    )
    nutrient_revision_ids = set(
        connection.scalars(
            text("SELECT DISTINCT revision_id FROM recipe_publication_nutrients")
        ).all()
    )
    if not amount_revision_ids <= expected_revisions or not nutrient_revision_ids <= (
        expected_revisions
    ):
        raise Phase5CQualificationError(
            "qualification_unexplained_current_domain_row"
        )
    plan_ids = {UUID(row["source_recipe_id"]) for row in plan["decisions"]}
    duplicates = connection.execute(
        text("SELECT id FROM recipes GROUP BY id HAVING count(*) <> 1")
    ).all()
    if duplicates or not expected_recipes <= plan_ids:
        raise Phase5CQualificationError(
            "qualification_unexplained_current_domain_row"
        )


def _verify_graph(
    connection: Connection,
    *,
    plan: dict[str, Any],
    outcomes: list[dict[str, Any]],
    source_payload: dict[str, list[dict[str, Any]]],
) -> None:
    decision_by_id = {
        UUID(row["source_recipe_id"]): row for row in plan["decisions"]
    }
    outcome_by_id = {UUID(str(row["source_recipe_id"])): row for row in outcomes}
    projection_subject = {
        row["food_item_id"]: row["id"] for row in source_payload["recipes"]
    }
    current_recipes = {
        row["id"]: row
        for row in connection.execute(text("SELECT id, user_id FROM recipes")).mappings()
    }
    graph: dict[UUID, set[UUID]] = {recipe_id: set() for recipe_id in current_recipes}
    rows = connection.execute(
        text(
            "SELECT ingredient.recipe_id, ingredient.food_item_id, "
            "parent.user_id AS parent_owner, food.user_id AS food_owner, "
            "food.recipe_publication_revision_id "
            "FROM recipe_ingredients ingredient "
            "JOIN recipes parent ON parent.id = ingredient.recipe_id "
            "JOIN food_items food ON food.id = ingredient.food_item_id"
        )
    ).mappings().all()
    for row in rows:
        if row["parent_owner"] != row["food_owner"]:
            raise Phase5CQualificationError("qualification_dependency_invalid")
        child = projection_subject.get(row["food_item_id"])
        if child is None:
            if row["recipe_publication_revision_id"] is not None:
                raise Phase5CQualificationError("qualification_dependency_invalid")
            continue
        child_decision = decision_by_id[child]
        child_outcome = outcome_by_id[child]
        if (
            child_decision["intended_disposition"] != "convert"
            or child_outcome["execution_disposition"] != "converted"
            or child not in current_recipes
        ):
            raise Phase5CQualificationError("qualification_dependency_invalid")
        graph[row["recipe_id"]].add(child)

    remaining = set(graph)
    completed: set[UUID] = set()
    while remaining:
        ready = sorted(
            (node for node in remaining if graph[node] <= completed), key=str
        )
        if not ready:
            raise Phase5CQualificationError("qualification_dependency_cycle")
        for node in ready:
            remaining.remove(node)
            completed.add(node)


def _verify_execution_receipt(
    receipt: dict[str, Any],
    *,
    run: dict[str, Any],
    outcomes: list[dict[str, Any]],
    observed_counts: dict[str, int],
) -> None:
    if (
        UUID(str(receipt["run_id"])) != run["id"]
        or receipt["plan_digest"] != run["plan_digest"]
        or receipt["verification_result"] != run["verification_state"]
        or receipt["counts"] != observed_counts
    ):
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")
    expected_subjects = [_execution_receipt_subject(row) for row in outcomes]
    if receipt["subjects"] != expected_subjects:
        raise Phase5CQualificationError("qualification_execution_receipt_mismatch")


def _execution_receipt_subject(row: dict[str, Any]) -> dict[str, Any]:
    disposition = row["execution_disposition"] or "pending"
    if row["checkpoint_state"] == "failed":
        disposition = "failed"
        reason = row["failure_reason_code"]
    else:
        reason = row["planned_reason_code"]
    subject: dict[str, Any] = {
        "source_recipe_id": str(row["source_recipe_id"]),
        "disposition": disposition,
        "reason_code": reason,
    }
    if row["target_recipe_id"] is not None:
        subject.update(
            {
                "target_recipe_id": str(row["target_recipe_id"]),
                "projection_food_item_id": str(
                    row["reused_projection_food_item_id"]
                ),
                "revision_id": str(row["created_revision_id"]),
                "revision_digest": row["created_revision_digest"],
            }
        )
    return subject


def _qualification_receipt(
    *,
    plan: dict[str, Any],
    execution_attestation: dict[str, Any],
    execution_receipt: dict[str, Any],
    run: dict[str, Any],
    checksums: dict[str, Any],
    observed_counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    daily_digest: str,
    ocr_digest: str,
    ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    planned_reasons = Counter(row["reason_code"] for row in plan["decisions"])
    observed_reasons = Counter(
        row["failure_reason_code"] or row["planned_reason_code"] for row in outcomes
    )
    unsigned = {
        "receipt_version": QUALIFICATION_RECEIPT_VERSION,
        "verifier_version": QUALIFIER_VERSION,
        "plan": {
            "contract_version": plan["manifest_version"],
            "digest": plan["manifest_digest"],
        },
        "execution_attestation": {
            "contract_version": execution_attestation["attestation_version"],
            "digest": execution_attestation["attestation_digest"],
        },
        "conversion_run_id": str(run["id"]),
        "execution_receipt": {
            "contract_version": execution_receipt["receipt_version"],
            "digest": execution_receipt["report_digest"],
        },
        "clone_marker_digest": run["clone_marker_digest"],
        "archive_identity_digest": run["archive_identity"],
        "inventory_digest": run["inventory_digest"],
        "schema_signature_digest": run["schema_signature_digest"],
        "conversion_rules_version": run["conversion_rules_version"],
        "planned_counts": plan["summary"],
        "observed_counts": observed_counts,
        "reason_code_counts": {
            "planned": dict(sorted(planned_reasons.items())),
            "observed": dict(sorted(observed_reasons.items())),
        },
        "source_roots": {
            "archived_recipes": checksums["recipes_checksum"],
            "archived_recipe_ingredients": checksums["ingredients_checksum"],
            "archive": checksums["archive_checksum"],
            "planning_source": checksums["planning_source_checksum"],
        },
        "daily_log_state_digest": daily_digest,
        "ocr_state_digest": ocr_digest,
        "outcome_ledger_digest": canonical_digest(ledger),
        "verification_result": "qualified",
    }
    receipt = {**unsigned, "receipt_digest": canonical_digest(unsigned)}
    return validate_qualification_receipt_contract(receipt)


def _ledger_row(
    decision: dict[str, Any], outcome: dict[str, Any]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_recipe_id": str(outcome["source_recipe_id"]),
        "planned_disposition": decision["intended_disposition"],
        "executed_disposition": outcome["execution_disposition"],
        "reason_code": outcome["failure_reason_code"]
        or outcome["planned_reason_code"],
        "source_checksum": outcome["source_checksum"],
        "verification_state": outcome["verification_state"],
    }
    if outcome["target_recipe_id"] is not None:
        row.update(
            {
                "target_recipe_id": str(outcome["target_recipe_id"]),
                "projection_food_item_id": str(
                    outcome["reused_projection_food_item_id"]
                ),
                "revision_id": str(outcome["created_revision_id"]),
                "revision_digest": outcome["created_revision_digest"],
            }
        )
    return row


def _observed_counts(outcomes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "converted": 0,
        "quarantined": 0,
        "blocked": 0,
        "failed": 0,
        "pending": 0,
    }
    for row in outcomes:
        if row["checkpoint_state"] == "failed":
            counts["failed"] += 1
        else:
            counts[row["execution_disposition"] or "pending"] += 1
    return counts


def _group_by_food(rows: list[dict[str, Any]]) -> dict[UUID, list[dict[str, Any]]]:
    result: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["food_item_id"]].append(row)
    for values in result.values():
        values.sort(key=lambda row: str(row["id"]))
    return result


def _relation_state_digest(
    connection: Connection, tables: tuple[str, ...]
) -> str:
    existing = set(inspect(connection).get_table_names())
    payload: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        if table not in existing:
            payload[table] = []
            continue
        rows = [
            dict(row)
            for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()
        ]
        payload[table] = sorted(rows, key=canonical_json)
    return canonical_digest(payload)


def _database_state_digest(
    connection: Connection,
    *,
    source_schema: str,
    archive_schema: str,
) -> str:
    inspector = inspect(connection)
    payload: dict[str, Any] = {}
    for schema in (source_schema, archive_schema):
        tables: dict[str, Any] = {}
        for table_name in sorted(inspector.get_table_names(schema=schema)):
            qualified = _qualified(connection, schema, table_name)
            rows = [
                dict(row)
                for row in connection.execute(
                    text(f"SELECT * FROM {qualified}")
                ).mappings()
            ]
            tables[table_name] = {
                "count": len(rows),
                "digest": canonical_digest(sorted(rows, key=canonical_json)),
            }
        payload[schema] = tables
    return canonical_digest(payload)


def _authored_content_differs(
    recipe: Recipe, captured_revision: RecipePublicationRevision
) -> bool:
    snapshots: list[NutrientSnapshot] = []
    for ingredient in recipe.ingredients:
        resolved = _resolve_preserved_amount(ingredient)
        for nutrient in resolved.nutrients:
            snapshots.append(
                NutrientSnapshot(
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    data_status=nutrient.data_status,
                )
            )
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


def _resolve_preserved_amount(ingredient: RecipeIngredient) -> ResolvedNutrition:
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
    if serving is None or unit != serving.unit.strip().casefold() or serving.quantity <= 0:
        raise ValueError("unsupported preserved amount")
    return resolve_nutrition(
        ingredient.food_item,
        ingredient.amount_quantity / serving.quantity,
        "serving",
        serving.id,
    )


def _divide_totals(
    totals: list[AggregatedNutrientTotal], divisor: Decimal | None
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


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))
