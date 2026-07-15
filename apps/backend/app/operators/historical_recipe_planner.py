from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, inspect, text

from app.operators.historical_database_inventory import REPORT_SCHEMA_VERSION
from app.operators.historical_recipe_bridge import (
    SCHEMA_SIGNATURE_DIGEST,
    _archive_checksums,
    _current_revision,
    load_bridge_metadata,
    phase5c_advisory_lock,
    planning_source_payload,
    require_supported_legacy_schema,
)
from app.operators.phase5c_contracts import (
    CONTROL_REVISION,
    CONVERSION_PLAN_VERSION,
    CONVERSION_RULES_VERSION,
    Phase5CAdmissionError,
    SUPPORTED_SCHEMA_SIGNATURE,
    SUPPORTED_SOURCE_REVISION,
    canonical_digest,
    canonical_json,
    validate_inventory_contract,
)
from app.operators.phase5c_isolation import (
    assert_database_session_isolation,
    phase5c_maintenance_session,
    verify_clone_isolation_evidence,
)


_CONTROL_TABLE = "phase5c_conversion_metadata"
_VALID_BASES = {"per_serving", "per_100g", "per_gram"}
_VALID_STATUSES = {"known", "estimated", "unknown", "zero"}
_SIX_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class ConversionPlan:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        summary = self.payload["summary"]
        lines = [
            "Phase 5C historical Recipe conversion plan",
            f"Manifest: {self.payload['manifest_version']}",
            f"Manifest digest: {self.payload['manifest_digest']}",
            f"Total historical Recipes: {summary['total']}",
            f"Convert: {summary['convert']}",
            f"Quarantine: {summary['quarantine']}",
            f"Block: {summary['block']}",
            "",
            "Decisions",
        ]
        for decision in self.payload["decisions"]:
            lines.append(
                f"  {decision['source_recipe_id']}: "
                f"{decision['intended_disposition']} ({decision['reason_code']}) "
                f"checksum={decision['source_checksum']}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class _Assessment:
    disposition: str
    reason_code: str
    dependencies: frozenset[UUID]


def _by_id(rows: list[dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
    return {row["id"]: row for row in rows}


def _by_food(rows: list[dict[str, Any]]) -> dict[UUID, list[dict[str, Any]]]:
    result: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["food_item_id"]].append(row)
    for values in result.values():
        values.sort(key=lambda row: str(row["id"]))
    return result


def _by_recipe(rows: list[dict[str, Any]]) -> dict[UUID, list[dict[str, Any]]]:
    result: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["recipe_id"]].append(row)
    for values in result.values():
        values.sort(key=lambda row: (row["sort_order"], str(row["id"])))
    return result


def _nutrient_shape_reason(nutrients: list[dict[str, Any]]) -> str | None:
    identities: set[tuple[str, str]] = set()
    for nutrient in nutrients:
        basis = str(nutrient["basis"])
        status = str(nutrient["data_status"])
        if basis not in _VALID_BASES or status not in _VALID_STATUSES:
            return "nutrient_classification_invalid"
        identity = (str(nutrient["nutrient_id"]), basis)
        if identity in identities:
            return "nutrient_identity_ambiguous"
        identities.add(identity)
        amount = nutrient["amount"]
        if status in {"known", "estimated"} and amount is None:
            return "nutrient_status_amount_invalid"
        if status == "unknown" and amount is not None:
            return "nutrient_status_amount_invalid"
        if status == "zero" and amount != 0:
            return "nutrient_status_amount_invalid"
    return None


def _amount_can_resolve(
    nutrients: list[dict[str, Any]],
    *,
    semantic_mode: str,
    serving: dict[str, Any] | None,
    defaults: list[dict[str, Any]],
) -> bool:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for nutrient in nutrients:
        grouped[str(nutrient["nutrient_id"])].append(nutrient)
    if semantic_mode == "g":
        conversion = defaults[0] if len(defaults) == 1 else None
        for rows in grouped.values():
            preferred = [row for row in rows if row["basis"] in {"per_100g", "per_gram"}]
            candidates = preferred or rows
            if len(candidates) != 1:
                return False
            if candidates[0]["basis"] == "per_serving":
                if conversion is None or conversion["gram_weight"] is None:
                    return False
        return True

    if serving is None:
        return False
    for rows in grouped.values():
        preferred = [row for row in rows if row["basis"] == "per_serving"]
        candidates = preferred or rows
        if len(candidates) != 1:
            return False
        if candidates[0]["basis"] in {"per_100g", "per_gram"}:
            if serving["gram_weight"] is None:
                return False
    return True


def _projection_validation(
    projection: dict[str, Any],
    servings: list[dict[str, Any]],
    nutrients: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    if not servings:
        return "projection_servings_invalid", None
    defaults = [serving for serving in servings if serving["is_default"]]
    if len(defaults) != 1:
        return "projection_servings_invalid", None
    labels: set[str] = set()
    for serving in servings:
        label = str(serving["label"])
        label_key = label.strip().casefold()
        if not label_key or label_key in labels:
            return "projection_servings_invalid", None
        labels.add(label_key)
        if serving["quantity"] <= 0:
            return "projection_servings_invalid", None
        if serving["gram_weight"] is not None and serving["gram_weight"] <= 0:
            return "projection_servings_invalid", None
    nutrient_reason = _nutrient_shape_reason(nutrients)
    if nutrient_reason is not None:
        return "projection_nutrition_invalid", None
    if any(
        not _amount_can_resolve(
            nutrients,
            semantic_mode="serving",
            serving=serving,
            defaults=defaults,
        )
        for serving in servings
    ):
        return "projection_nutrition_invalid", None
    provenance_ambiguous = (
        projection["brand"] is not None
        or bool(sources)
        or any(
            serving["source"] != "recipe" or not serving["is_user_confirmed"]
            for serving in servings
        )
        or any(
            nutrient["source"] != "recipe" or not nutrient["is_user_confirmed"]
            for nutrient in nutrients
        )
    )
    return None, "projection_provenance_ambiguous" if provenance_ambiguous else None


def _ingredient_validation(
    ingredient: dict[str, Any],
    *,
    food: dict[str, Any] | None,
    recipe_owner_id: UUID,
    servings: list[dict[str, Any]],
    serving_by_id: dict[UUID, dict[str, Any]],
    nutrients: list[dict[str, Any]],
) -> str | None:
    if food is None:
        return "ingredient_food_missing"
    if food["user_id"] != recipe_owner_id:
        return "ingredient_owner_mismatch"
    if food["deleted_at"] is not None:
        return "ingredient_food_inactive"
    if ingredient["quantity"] <= 0 or ingredient["sort_order"] < 0:
        return "ingredient_amount_invalid"
    if ingredient["gram_amount"] is not None and ingredient["gram_amount"] <= 0:
        return "ingredient_amount_invalid"
    nutrient_reason = _nutrient_shape_reason(nutrients)
    if nutrient_reason is not None:
        return "ingredient_nutrition_invalid"

    defaults = [serving for serving in servings if serving["is_default"]]
    serving_id = ingredient["serving_definition_id"]
    unit = str(ingredient["unit"]).strip().casefold()
    if serving_id is None:
        if unit != "g":
            return "ingredient_serving_identity_missing"
        if (
            ingredient["gram_amount"] is not None
            and ingredient["gram_amount"].quantize(_SIX_PLACES)
            != ingredient["quantity"].quantize(_SIX_PLACES)
        ):
            return "ingredient_gram_amount_inconsistent"
        if not _amount_can_resolve(
            nutrients,
            semantic_mode="g",
            serving=None,
            defaults=defaults,
        ):
            return "ingredient_nutrition_unresolvable"
        return None

    serving = serving_by_id.get(serving_id)
    if serving is None:
        return "ingredient_serving_missing"
    if serving["food_item_id"] != food["id"]:
        return "ingredient_serving_owner_mismatch"
    if serving["quantity"] <= 0:
        return "ingredient_serving_invalid"
    serving_unit = str(serving["unit"]).strip().casefold()
    if unit == "serving":
        serving_count = ingredient["quantity"]
    elif unit == serving_unit:
        serving_count = ingredient["quantity"] / serving["quantity"]
    else:
        return "ingredient_amount_semantics_ambiguous"
    if serving_count <= 0:
        return "ingredient_amount_invalid"
    if ingredient["gram_amount"] is not None:
        if serving["gram_weight"] is None:
            return "ingredient_gram_amount_unverifiable"
        expected_grams = (serving_count * serving["gram_weight"]).quantize(_SIX_PLACES)
        if ingredient["gram_amount"].quantize(_SIX_PLACES) != expected_grams:
            return "ingredient_gram_amount_inconsistent"
    if not _amount_can_resolve(
        nutrients,
        semantic_mode="serving",
        serving=serving,
        defaults=defaults,
    ):
        return "ingredient_nutrition_unresolvable"
    return None


def _initial_assessment(
    recipe: dict[str, Any],
    *,
    users: set[UUID],
    foods: dict[UUID, dict[str, Any]],
    servings_by_food: dict[UUID, list[dict[str, Any]]],
    serving_by_id: dict[UUID, dict[str, Any]],
    nutrients_by_food: dict[UUID, list[dict[str, Any]]],
    sources_by_food: dict[UUID, list[dict[str, Any]]],
    ingredients: list[dict[str, Any]],
    recipe_by_projection: dict[UUID, UUID],
    source_matches: dict[tuple[UUID, str], list[dict[str, Any]]],
) -> _Assessment:
    dependencies: set[UUID] = set()
    owner_id = recipe["user_id"]
    if owner_id not in users:
        return _Assessment("block", "recipe_owner_missing", frozenset())
    projection = foods.get(recipe["food_item_id"])
    if projection is None:
        return _Assessment("block", "projection_missing", frozenset())
    if projection["user_id"] != owner_id:
        return _Assessment("block", "projection_owner_mismatch", frozenset())
    if projection["deleted_at"] is not None:
        return _Assessment("block", "projection_inactive", frozenset())
    if projection["source_type"] != "recipe" or not projection["is_recipe"]:
        return _Assessment("block", "projection_identity_invalid", frozenset())
    if projection["source_id"] not in {None, str(recipe["id"])}:
        return _Assessment("block", "projection_source_identity_mismatch", frozenset())
    active_matches = [
        food
        for food in source_matches.get((owner_id, str(recipe["id"])), [])
        if food["deleted_at"] is None and food["id"] != projection["id"]
    ]
    if active_matches:
        return _Assessment("block", "projection_source_identity_conflict", frozenset())
    positions = [ingredient["sort_order"] for ingredient in ingredients]
    if len(positions) != len(set(positions)):
        return _Assessment("block", "ingredient_positions_ambiguous", frozenset())

    projection_block, projection_quarantine = _projection_validation(
        projection,
        servings_by_food.get(projection["id"], []),
        nutrients_by_food.get(projection["id"], []),
        sources_by_food.get(projection["id"], []),
    )
    if projection_block is not None:
        return _Assessment("block", projection_block, frozenset())

    for ingredient in ingredients:
        food = foods.get(ingredient["ingredient_food_item_id"])
        issue = _ingredient_validation(
            ingredient,
            food=food,
            recipe_owner_id=owner_id,
            servings=servings_by_food.get(ingredient["ingredient_food_item_id"], []),
            serving_by_id=serving_by_id,
            nutrients=nutrients_by_food.get(ingredient["ingredient_food_item_id"], []),
        )
        if issue is not None:
            return _Assessment("block", issue, frozenset())
        if food is not None and (food["is_recipe"] or food["source_type"] == "recipe"):
            nested_recipe_id = recipe_by_projection.get(food["id"])
            if nested_recipe_id is None:
                return _Assessment("block", "nested_recipe_identity_missing", frozenset())
            if food["source_type"] != "recipe" or not food["is_recipe"]:
                return _Assessment("block", "nested_recipe_identity_invalid", frozenset())
            if food["source_id"] not in {None, str(nested_recipe_id)}:
                return _Assessment("block", "nested_recipe_source_mismatch", frozenset())
            dependencies.add(nested_recipe_id)

    if recipe["serving_count"] is not None and recipe["serving_count"] <= 0:
        return _Assessment("block", "serving_count_invalid", frozenset(dependencies))
    quantity = recipe["final_yield_quantity"]
    unit = recipe["final_yield_unit"]
    if (quantity is None) != (unit is None):
        return _Assessment("block", "final_yield_incomplete", frozenset(dependencies))
    if quantity is not None and quantity <= 0:
        return _Assessment("block", "final_yield_invalid", frozenset(dependencies))
    if quantity is not None and str(unit).strip().casefold() != "g":
        return _Assessment(
            "quarantine",
            "final_yield_not_losslessly_representable",
            frozenset(dependencies),
        )
    if recipe["instructions"] not in {None, ""}:
        return _Assessment(
            "quarantine",
            "instructions_not_losslessly_representable",
            frozenset(dependencies),
        )
    if projection_quarantine is not None:
        return _Assessment("quarantine", projection_quarantine, frozenset(dependencies))
    return _Assessment("convert", "eligible_lossless_mapping", frozenset(dependencies))


def _cycle_members(graph: dict[UUID, frozenset[UUID]]) -> set[UUID]:
    visiting: set[UUID] = set()
    visited: set[UUID] = set()
    stack: list[UUID] = []
    members: set[UUID] = set()

    def visit(node: UUID) -> None:
        if node in visited:
            return
        if node in visiting:
            index = stack.index(node)
            members.update(stack[index:])
            return
        visiting.add(node)
        stack.append(node)
        for dependency in sorted(graph.get(node, frozenset()), key=str):
            if dependency in graph:
                visit(dependency)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for recipe_id in sorted(graph, key=str):
        visit(recipe_id)
    return members


def _apply_graph_dispositions(
    assessments: dict[UUID, _Assessment],
) -> dict[UUID, _Assessment]:
    graph = {recipe_id: assessment.dependencies for recipe_id, assessment in assessments.items()}
    for recipe_id in _cycle_members(graph):
        assessments[recipe_id] = _Assessment(
            "block", "nested_recipe_cycle", assessments[recipe_id].dependencies
        )
    changed = True
    while changed:
        changed = False
        for recipe_id in sorted(assessments, key=str):
            assessment = assessments[recipe_id]
            if assessment.disposition == "block":
                continue
            dependency_states = [
                assessments[dependency].disposition
                for dependency in assessment.dependencies
                if dependency in assessments
            ]
            if "block" in dependency_states:
                assessments[recipe_id] = _Assessment(
                    "block", "nested_recipe_dependency_blocked", assessment.dependencies
                )
                changed = True
            elif assessment.disposition == "convert" and "quarantine" in dependency_states:
                assessments[recipe_id] = _Assessment(
                    "quarantine",
                    "nested_recipe_dependency_quarantined",
                    assessment.dependencies,
                )
                changed = True
    return assessments


def _recipe_source_checksum(
    recipe: dict[str, Any],
    *,
    ingredients: list[dict[str, Any]],
    foods: dict[UUID, dict[str, Any]],
    servings_by_food: dict[UUID, list[dict[str, Any]]],
    serving_by_id: dict[UUID, dict[str, Any]],
    nutrients_by_food: dict[UUID, list[dict[str, Any]]],
    sources_by_food: dict[UUID, list[dict[str, Any]]],
) -> str:
    food_ids = {recipe["food_item_id"]}
    food_ids.update(ingredient["ingredient_food_item_id"] for ingredient in ingredients)
    food_ids.update(
        food["id"]
        for food in foods.values()
        if food["user_id"] == recipe["user_id"]
        and food["source_type"] == "recipe"
        and food["source_id"] == str(recipe["id"])
    )
    selected_serving_ids = {
        ingredient["serving_definition_id"]
        for ingredient in ingredients
        if ingredient["serving_definition_id"] is not None
    }
    serving_rows = {
        serving["id"]: serving
        for food_id in food_ids
        for serving in servings_by_food.get(food_id, [])
    }
    serving_rows.update(
        {
            serving_id: serving_by_id[serving_id]
            for serving_id in selected_serving_ids
            if serving_id in serving_by_id
        }
    )
    return canonical_digest(
        {
            "recipe": recipe,
            "ingredients": ingredients,
            "food_items": [foods[food_id] for food_id in sorted(food_ids, key=str) if food_id in foods],
            "serving_definitions": [
                serving_rows[serving_id] for serving_id in sorted(serving_rows, key=str)
            ],
            "food_nutrients": [
                nutrient
                for food_id in sorted(food_ids, key=str)
                for nutrient in nutrients_by_food.get(food_id, [])
            ],
            "food_sources": [
                source
                for food_id in sorted(food_ids, key=str)
                for source in sources_by_food.get(food_id, [])
            ],
        }
    )


def _register_manifest(
    connection: Connection,
    metadata: dict[str, Any],
    manifest_digest: str,
) -> None:
    if _CONTROL_TABLE not in inspect(connection).get_table_names():
        raise Phase5CAdmissionError("Phase 5C control metadata table is absent")
    values = {
        **metadata,
        "manifest_version": CONVERSION_PLAN_VERSION,
        "manifest_digest": manifest_digest,
    }
    control_columns = (
        "archive_identity",
        "source_driver_family",
        "source_host",
        "source_port",
        "source_database",
        "source_schema",
        "archive_schema",
        "conversion_clone_identity_digest",
        "marker_format_version",
        "isolation_evidence_contract_version",
        "clone_marker_identity",
        "clone_marker_digest",
        "clone_database_identity_digest",
        "source_production_identity_digest",
        "operator_attestation_version",
        "operator_attestation_identity",
        "operator_attestation_scope",
        "operator_attestation_digest",
        "source_alembic_revision",
        "inventory_contract_version",
        "inventory_digest",
        "schema_signature",
        "schema_signature_digest",
        "recipe_count",
        "ingredient_count",
        "recipes_checksum",
        "ingredients_checksum",
        "archive_checksum",
        "planning_source_checksum",
        "conversion_rules_version",
        "manifest_version",
        "manifest_digest",
    )
    parameters = {column: values[column] for column in control_columns}
    connection.execute(
        text(
            f"INSERT INTO {_CONTROL_TABLE} ({', '.join(control_columns)}) VALUES "
            f"({', '.join(':' + column for column in control_columns)}) "
            "ON CONFLICT (archive_identity) DO NOTHING"
        ),
        parameters,
    )
    stored = connection.execute(
        text(f"SELECT {', '.join(control_columns)} FROM {_CONTROL_TABLE} "
             "WHERE archive_identity = :archive_identity"),
        {"archive_identity": metadata["archive_identity"]},
    ).mappings().one()
    if any(stored[column] != parameters[column] for column in control_columns):
        raise Phase5CAdmissionError("An immutable manifest with different evidence already exists")


@contextmanager
def _isolated_planning_operation(
    connection: Connection,
    *,
    source_schema: str,
    inventory_digest: str,
    clone_marker_identity: str,
    conversion_clone_id: str,
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
        operation="planning",
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
                operation="planning",
            )
            assert_database_session_isolation(connection, evidence["clone_marker_digest"])
            connection.commit()
            yield evidence


def plan_historical_recipe_conversion(
    engine: Engine,
    *,
    inventory_payload: dict[str, Any],
    archive_schema: str,
    conversion_clone_id: str,
    clone_marker_identity: str,
    attestation_payload: dict[str, Any],
) -> ConversionPlan:
    inventory_payload = validate_inventory_contract(inventory_payload)
    if engine.dialect.name != "postgresql":
        raise Phase5CAdmissionError("The Phase 5C planner supports PostgreSQL only")
    inventory_digest = canonical_digest(inventory_payload)

    with engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection:
        source_schema = str(connection.scalar(text("SELECT current_schema()")))
        with _isolated_planning_operation(
            connection,
            source_schema=source_schema,
            inventory_digest=inventory_digest,
            clone_marker_identity=clone_marker_identity,
            conversion_clone_id=conversion_clone_id,
            attestation_payload=attestation_payload,
        ) as isolation_evidence:
            with connection.begin():
                if _current_revision(connection, source_schema) != CONTROL_REVISION:
                    raise Phase5CAdmissionError(
                        f"Planner target must be at {CONTROL_REVISION}"
                    )
                metadata = load_bridge_metadata(connection, archive_schema)
                required = {
                    "source_alembic_revision": SUPPORTED_SOURCE_REVISION,
                    "inventory_contract_version": REPORT_SCHEMA_VERSION,
                    "inventory_digest": inventory_digest,
                    "schema_signature": SUPPORTED_SCHEMA_SIGNATURE,
                    "schema_signature_digest": SCHEMA_SIGNATURE_DIGEST,
                    "source_schema": source_schema,
                    "archive_schema": archive_schema,
                    "conversion_rules_version": CONVERSION_RULES_VERSION,
                    "marker_format_version": isolation_evidence[
                        "marker_format_version"
                    ],
                    "isolation_evidence_contract_version": isolation_evidence[
                        "isolation_evidence_contract_version"
                    ],
                    "clone_marker_identity": isolation_evidence[
                        "clone_marker_identity"
                    ],
                    "clone_marker_digest": isolation_evidence["clone_marker_digest"],
                    "clone_database_identity_digest": isolation_evidence[
                        "clone_database_identity_digest"
                    ],
                    "source_production_identity_digest": isolation_evidence[
                        "source_production_identity_digest"
                    ],
                    "operator_attestation_version": isolation_evidence[
                        "operator_attestation_version"
                    ],
                    "operator_attestation_identity": isolation_evidence[
                        "operator_attestation_identity"
                    ],
                    "operator_attestation_scope": isolation_evidence[
                        "operator_attestation_scope"
                    ],
                    "operator_attestation_digest": isolation_evidence[
                        "operator_attestation_digest"
                    ],
                }
                if any(metadata.get(key) != value for key, value in required.items()):
                    raise Phase5CAdmissionError(
                        "Bridge metadata does not match the planner prerequisites"
                    )
                if connection.scalar(text("SELECT count(*) FROM recipes")):
                    raise Phase5CAdmissionError("Current Recipe-domain rows are already present")
                if connection.scalar(
                    text("SELECT count(*) FROM recipe_publication_revisions")
                ):
                    raise Phase5CAdmissionError("Immutable Recipe revisions are already present")
                require_supported_legacy_schema(connection, archive_schema)
                payload = planning_source_payload(
                    connection,
                    recipe_schema=archive_schema,
                    supporting_schema=source_schema,
                )
                checksums = _archive_checksums(payload)
                if any(metadata.get(key) != value for key, value in checksums.items()):
                    raise Phase5CAdmissionError(
                        "Archived source checksums cannot be reproduced"
                    )

                recipes = sorted(payload["recipes"], key=lambda row: str(row["id"]))
                ingredients_by_recipe = _by_recipe(payload["recipe_ingredients"])
                users = {row["id"] for row in payload["users"]}
                foods = _by_id(payload["food_items"])
                servings_by_food = _by_food(payload["serving_definitions"])
                serving_by_id = _by_id(payload["serving_definitions"])
                nutrients_by_food = _by_food(payload["food_nutrients"])
                sources_by_food = _by_food(payload["food_sources"])
                recipe_by_projection = {row["food_item_id"]: row["id"] for row in recipes}
                source_matches: dict[tuple[UUID, str], list[dict[str, Any]]] = defaultdict(list)
                for food in foods.values():
                    if food["source_type"] == "recipe" and food["source_id"] is not None:
                        source_matches[(food["user_id"], str(food["source_id"]))].append(food)

                assessments = {
                    recipe["id"]: _initial_assessment(
                        recipe,
                        users=users,
                        foods=foods,
                        servings_by_food=servings_by_food,
                        serving_by_id=serving_by_id,
                        nutrients_by_food=nutrients_by_food,
                        sources_by_food=sources_by_food,
                        ingredients=ingredients_by_recipe.get(recipe["id"], []),
                        recipe_by_projection=recipe_by_projection,
                        source_matches=source_matches,
                    )
                    for recipe in recipes
                }
                assessments = _apply_graph_dispositions(assessments)
                decisions = []
                counts = {"convert": 0, "quarantine": 0, "block": 0}
                for recipe in recipes:
                    assessment = assessments[recipe["id"]]
                    counts[assessment.disposition] += 1
                    decisions.append(
                        {
                            "source_recipe_id": str(recipe["id"]),
                            "source_checksum": _recipe_source_checksum(
                                recipe,
                                ingredients=ingredients_by_recipe.get(recipe["id"], []),
                                foods=foods,
                                servings_by_food=servings_by_food,
                                serving_by_id=serving_by_id,
                                nutrients_by_food=nutrients_by_food,
                                sources_by_food=sources_by_food,
                            ),
                            "intended_disposition": assessment.disposition,
                            "reason_code": assessment.reason_code,
                        }
                    )

                source_identity = {
                    "driver_family": metadata["source_driver_family"],
                    "host": metadata["source_host"],
                    "port": metadata["source_port"],
                    "database": metadata["source_database"],
                    "source_schema": metadata["source_schema"],
                    "archive_schema": metadata["archive_schema"],
                    "conversion_clone_identity_digest": metadata[
                        "conversion_clone_identity_digest"
                    ],
                    "archive_identity": metadata["archive_identity"],
                }
                isolation_manifest = {
                    "contract_version": metadata[
                        "isolation_evidence_contract_version"
                    ],
                    "marker_format_version": metadata["marker_format_version"],
                    "clone_marker_identity": metadata["clone_marker_identity"],
                    "clone_marker_digest": metadata["clone_marker_digest"],
                    "conversion_clone_identity_digest": metadata[
                        "conversion_clone_identity_digest"
                    ],
                    "clone_database_identity_digest": metadata[
                        "clone_database_identity_digest"
                    ],
                    "source_production_identity_digest": metadata[
                        "source_production_identity_digest"
                    ],
                    "operator_attestation_version": metadata[
                        "operator_attestation_version"
                    ],
                    "operator_attestation_identity": metadata[
                        "operator_attestation_identity"
                    ],
                    "operator_attestation_scope": metadata[
                        "operator_attestation_scope"
                    ],
                    "operator_attestation_digest": metadata[
                        "operator_attestation_digest"
                    ],
                }
                manifest = {
                    "manifest_version": CONVERSION_PLAN_VERSION,
                    "inventory_contract_version": REPORT_SCHEMA_VERSION,
                    "supported_schema_signature": {
                        "name": SUPPORTED_SCHEMA_SIGNATURE,
                        "digest": SCHEMA_SIGNATURE_DIGEST,
                    },
                    "inventory_digest": inventory_digest,
                    "conversion_rules_version": CONVERSION_RULES_VERSION,
                    "source_identity": source_identity,
                    "isolation_evidence": isolation_manifest,
                    "ordering": {
                        "recipes": "source_recipe_id_ascending",
                        "ingredients": "sort_order_then_source_ingredient_id",
                    },
                    "source_checksums": {
                        "archived_recipes": checksums["recipes_checksum"],
                        "archived_recipe_ingredients": checksums[
                            "ingredients_checksum"
                        ],
                        "archive": checksums["archive_checksum"],
                        "planning_source": checksums["planning_source_checksum"],
                    },
                    "summary": {"total": len(decisions), **counts},
                    "decisions": decisions,
                }
                manifest_digest = canonical_digest(manifest)
                manifest["manifest_digest"] = manifest_digest
                _register_manifest(connection, metadata, manifest_digest)
                return ConversionPlan(manifest)
