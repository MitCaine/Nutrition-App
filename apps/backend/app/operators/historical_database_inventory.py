from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy import Connection, Engine, inspect, text


REPORT_SCHEMA_VERSION = "historical_database_inventory_v1"
CURRENT_HEAD = "0015_phase5c_conversion_control"
REVISIONS = (
    "0001_initial_schema",
    "0002_snapshot_fk",
    "0003_usda_source_identity",
    "0004_recipe_domain_foundation",
    "0005_recipe_display_units",
    "0006_recipe_needs_republish",
    "0007_log_food_name_snapshot",
    "0008_recipe_pub_revisions",
    "0009_log_creation_idempotency",
    "0010_ocr_confirmation_trace",
    "0011_nutrition_target_foundation",
    "0012_food_favorites",
    "0013_food_recipe_integrity",
    "0014_create_idempotency",
    CURRENT_HEAD,
)


@dataclass(frozen=True)
class HistoricalDatabaseInventoryReport:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload

    def to_json(self) -> str:
        return json.dumps(self.payload, indent=2, sort_keys=True)

    def to_human(self) -> str:
        sections = [
            ("Migration", self.payload["migration"]),
            ("Legacy Recipe state", self.payload["legacy_recipes"]),
            ("Current Recipe system", self.payload["current_recipes"]),
            ("Revision state", self.payload["revisions"]),
            ("Daily Logs", self.payload["daily_logs"]),
            ("OCR", self.payload["ocr"]),
            ("Idempotency", self.payload["idempotency"]),
            ("Retention", self.payload["retention"]),
            ("Consistency", self.payload["consistency"]),
        ]
        classification = self.payload["classification"]
        lines = [
            "Historical Database Inventory",
            f"Report schema: {self.payload['schema_version']}",
            f"Classification: {classification['value']}",
            f"Reason: {classification['reason']}",
            "Read only: yes",
        ]
        for title, values in sections:
            lines.append("")
            lines.append(title)
            lines.extend(_human_lines(values, prefix="  "))
        if self.payload["limitations"]:
            lines.append("")
            lines.append("Limitations")
            lines.extend(f"  {value}" for value in self.payload["limitations"])
        return "\n".join(lines)


def _human_lines(values: dict[str, Any], *, prefix: str) -> list[str]:
    lines: list[str] = []
    for key in sorted(values):
        value = values[key]
        label = key.replace("_", " ")
        if isinstance(value, dict):
            lines.append(f"{prefix}{label}:")
            lines.extend(_human_lines(value, prefix=f"{prefix}  "))
        elif value is None:
            lines.append(f"{prefix}{label}: not applicable")
        elif isinstance(value, bool):
            lines.append(f"{prefix}{label}: {'yes' if value else 'no'}")
        else:
            lines.append(f"{prefix}{label}: {value}")
    return lines


def inventory_database(engine: Engine) -> HistoricalDatabaseInventoryReport:
    """Inspect one coherent database snapshot and always roll the transaction back."""
    with engine.connect() as raw_connection:
        connection = raw_connection
        if connection.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        transaction = connection.begin()
        try:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            return HistoricalDatabaseInventory(connection).inspect()
        finally:
            transaction.rollback()


class HistoricalDatabaseInventory:
    """Schema-adaptive, aggregate-only historical database inspection."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.inspector = inspect(connection)
        self.tables = set(self.inspector.get_table_names())
        self._columns: dict[str, set[str]] = {}
        self.limitations: set[str] = set()

    def inspect(self) -> HistoricalDatabaseInventoryReport:
        migration = self._migration()
        legacy = self._legacy_recipes()
        current = self._current_recipes()
        revisions = self._revisions()
        logs = self._daily_logs()
        ocr = self._ocr()
        idempotency = self._idempotency()
        retention = self._retention(current)
        consistency = self._consistency(current, revisions, logs)
        classification = self._classification(
            migration=migration,
            legacy=legacy,
            current=current,
            revisions=revisions,
            logs=logs,
            ocr=ocr,
            idempotency=idempotency,
            retention=retention,
            consistency=consistency,
        )
        return HistoricalDatabaseInventoryReport(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "read_only": True,
                "classification": classification,
                "migration": migration,
                "legacy_recipes": legacy,
                "current_recipes": current,
                "revisions": revisions,
                "daily_logs": logs,
                "ocr": ocr,
                "idempotency": idempotency,
                "retention": retention,
                "consistency": consistency,
                "limitations": sorted(self.limitations),
            }
        )

    def _columns_for(self, table: str) -> set[str]:
        if table not in self.tables:
            return set()
        if table not in self._columns:
            self._columns[table] = {
                str(column["name"]) for column in self.inspector.get_columns(table)
            }
        return self._columns[table]

    def _count(self, statement: str) -> int:
        return int(self.connection.scalar(text(statement)) or 0)

    def _table_count(self, table: str, where: str | None = None) -> int:
        if table not in self.tables:
            return 0
        statement = f'SELECT count(*) FROM "{table}"'
        if where:
            statement += f" WHERE {where}"
        return self._count(statement)

    def _migration(self) -> dict[str, Any]:
        revision_rows: list[str] = []
        if "alembic_version" in self.tables:
            revision_rows = [
                str(row)
                for row in self.connection.scalars(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                ).all()
            ]
        current_revision = revision_rows[0] if len(revision_rows) == 1 else None
        if len(revision_rows) > 1:
            self.limitations.add("multiple_alembic_revision_rows")

        pending: bool | None
        beyond: bool | None
        status: str
        if current_revision is None and not self.tables:
            pending, beyond, status = True, False, "unversioned_empty"
        elif current_revision in REVISIONS:
            index = REVISIONS.index(current_revision)
            migration_index = REVISIONS.index("0004_recipe_domain_foundation")
            pending = index < migration_index
            beyond = index > migration_index
            status = "pending" if pending else ("already_beyond" if beyond else "applied")
        else:
            pending, beyond, status = None, None, "unknown"
            self.limitations.add("unknown_or_missing_alembic_revision")

        legacy_table_names = self._legacy_recipe_table_names()
        legacy_count = sum(self._table_count(table) for table in legacy_table_names)
        can_proceed: bool | None = None
        if pending is True:
            if status == "unversioned_empty":
                can_proceed = True
            else:
                canonical_legacy_schema = (
                    "food_item_id" in self._columns_for("recipes")
                    and "published_food_item_id" not in self._columns_for("recipes")
                    and "ingredient_food_item_id"
                    in self._columns_for("recipe_ingredients")
                    and "food_item_id" not in self._columns_for("recipe_ingredients")
                )
                can_proceed = canonical_legacy_schema and legacy_count == 0
                if not canonical_legacy_schema:
                    self.limitations.add("migration_0004_legacy_schema_incomplete")
        elif pending is False:
            can_proceed = None

        return {
            "current_alembic_revision": current_revision,
            "alembic_revision_row_count": len(revision_rows),
            "migration_0004_status": status,
            "migration_0004_pending": pending,
            "migration_0004_can_safely_proceed": can_proceed,
            "already_beyond_migration_0004": beyond,
            "expected_head": CURRENT_HEAD,
            "at_expected_head": current_revision == CURRENT_HEAD,
        }

    def _legacy_recipe_table_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if "recipes_legacy" in self.tables:
            names.append("recipes_legacy")
        recipe_columns = self._columns_for("recipes")
        if "food_item_id" in recipe_columns and "published_food_item_id" not in recipe_columns:
            names.append("recipes")
        if "recipe_ingredients_legacy" in self.tables:
            names.append("recipe_ingredients_legacy")
        ingredient_columns = self._columns_for("recipe_ingredients")
        if "ingredient_food_item_id" in ingredient_columns and "food_item_id" not in ingredient_columns:
            names.append("recipe_ingredients")
        return tuple(names)

    def _legacy_recipes(self) -> dict[str, Any]:
        recipe_tables = []
        ingredient_tables = []
        if "recipes_legacy" in self.tables:
            recipe_tables.append("recipes_legacy")
        if "food_item_id" in self._columns_for("recipes") and "published_food_item_id" not in self._columns_for("recipes"):
            recipe_tables.append("recipes")
        if "recipe_ingredients_legacy" in self.tables:
            ingredient_tables.append("recipe_ingredients_legacy")
        if "ingredient_food_item_id" in self._columns_for("recipe_ingredients") and "food_item_id" not in self._columns_for("recipe_ingredients"):
            ingredient_tables.append("recipe_ingredients")
        return {
            "recipes_table_present": bool(recipe_tables),
            "recipe_ingredients_table_present": bool(ingredient_tables),
            "recipe_count": sum(self._table_count(table) for table in recipe_tables),
            "recipe_ingredient_count": sum(
                self._table_count(table) for table in ingredient_tables
            ),
        }

    def _has_current_recipe_schema(self) -> bool:
        return {"id", "user_id", "name", "published_food_item_id", "deleted_at"} <= self._columns_for("recipes")

    def _projection_candidate_condition(self, alias: str = "f") -> str:
        conditions = [f"{alias}.is_recipe = true", f"{alias}.source_type = 'recipe'"]
        if "recipe_publication_revision_id" in self._columns_for("food_items"):
            conditions.append(f"{alias}.recipe_publication_revision_id IS NOT NULL")
        if self._has_current_recipe_schema():
            conditions.append(
                f"EXISTS (SELECT 1 FROM recipes r WHERE r.published_food_item_id = {alias}.id)"
            )
        return "(" + " OR ".join(conditions) + ")"

    def _current_recipes(self) -> dict[str, Any]:
        if not self._has_current_recipe_schema():
            return {
                "schema_present": False,
                "recipe_count": 0,
                "active_recipe_count": 0,
                "deleted_recipe_count": 0,
                "published_recipe_count": 0,
                "draft_recipe_count": 0,
                "authored_recipe_ingredient_count": 0,
                "recipes_lacking_immutable_revisions": 0,
                "recipes_lacking_compatibility_projections": 0,
                "projection_count": 0,
                "projections_without_source_recipes": 0,
                "projection_owner_inconsistencies": 0,
                "projections_referencing_inactive_objects": 0,
            }

        recipe_columns = self._columns_for("recipes")
        has_active_revision = "active_publication_revision_id" in recipe_columns
        active_revision = "r.active_publication_revision_id" if has_active_revision else "NULL"
        publication_signal = (
            f"(r.published_food_item_id IS NOT NULL OR {active_revision} IS NOT NULL)"
        )
        draft_signal = (
            f"(r.published_food_item_id IS NULL AND {active_revision} IS NULL)"
        )
        published_count = self._count(
            f"SELECT count(*) FROM recipes r WHERE r.deleted_at IS NULL AND {publication_signal}"
        )
        draft_count = self._count(
            f"SELECT count(*) FROM recipes r WHERE r.deleted_at IS NULL AND {draft_signal}"
        )

        if "recipe_publication_revisions" in self.tables and has_active_revision:
            lacking_revisions = self._count(
                "SELECT count(*) FROM recipes r "
                "WHERE r.deleted_at IS NULL AND r.published_food_item_id IS NOT NULL "
                "AND (r.active_publication_revision_id IS NULL OR NOT EXISTS ("
                "SELECT 1 FROM recipe_publication_revisions rev "
                "WHERE rev.id = r.active_publication_revision_id "
                "AND rev.recipe_id = r.id AND rev.user_id = r.user_id))"
            )
        else:
            lacking_revisions = published_count

        lacking_projections = 0
        if has_active_revision and "food_items" in self.tables:
            lacking_projections = self._count(
                "SELECT count(*) FROM recipes r "
                "WHERE r.deleted_at IS NULL AND r.active_publication_revision_id IS NOT NULL "
                "AND (r.published_food_item_id IS NULL OR NOT EXISTS ("
                "SELECT 1 FROM food_items f WHERE f.id = r.published_food_item_id))"
            )

        projection_condition = self._projection_candidate_condition()
        projection_count = self._count(
            f"SELECT count(*) FROM food_items f WHERE {projection_condition}"
        ) if "food_items" in self.tables else 0
        projections_without_recipe = self._count(
            f"SELECT count(*) FROM food_items f WHERE {projection_condition} "
            "AND NOT EXISTS (SELECT 1 FROM recipes r WHERE r.published_food_item_id = f.id)"
        ) if "food_items" in self.tables else 0
        owner_mismatch = self._count(
            "SELECT count(*) FROM recipes r JOIN food_items f ON f.id = r.published_food_item_id "
            "WHERE r.user_id IS DISTINCT FROM f.user_id"
        ) if "food_items" in self.tables else 0
        inactive_projection = self._count(
            "SELECT count(*) FROM recipes r JOIN food_items f ON f.id = r.published_food_item_id "
            "WHERE (r.deleted_at IS NULL AND f.deleted_at IS NOT NULL) "
            "OR (r.deleted_at IS NOT NULL AND f.deleted_at IS NULL)"
        ) if "food_items" in self.tables else 0

        return {
            "schema_present": True,
            "recipe_count": self._table_count("recipes"),
            "active_recipe_count": self._table_count("recipes", "deleted_at IS NULL"),
            "deleted_recipe_count": self._table_count("recipes", "deleted_at IS NOT NULL"),
            "published_recipe_count": published_count,
            "draft_recipe_count": draft_count,
            "authored_recipe_ingredient_count": (
                self._table_count("recipe_ingredients")
                if "food_item_id" in self._columns_for("recipe_ingredients")
                else 0
            ),
            "recipes_lacking_immutable_revisions": lacking_revisions,
            "recipes_lacking_compatibility_projections": lacking_projections,
            "projection_count": projection_count,
            "projections_without_source_recipes": projections_without_recipe,
            "projection_owner_inconsistencies": owner_mismatch,
            "projections_referencing_inactive_objects": inactive_projection,
        }

    def _revision_ingredient_table(self) -> str | None:
        for table in ("recipe_publication_ingredients", "recipe_revision_ingredients"):
            if table in self.tables:
                return table
        return None

    def _revisions(self) -> dict[str, Any]:
        table = "recipe_publication_revisions"
        ingredient_table = self._revision_ingredient_table()
        if table not in self.tables:
            return {
                "table_present": False,
                "total_revision_count": 0,
                "active_revision_count": 0,
                "orphan_revision_count": 0,
                "amount_definition_snapshot_count": 0,
                "nutrient_snapshot_count": 0,
                "ingredient_snapshot_table_present": ingredient_table is not None,
                "ingredient_snapshot_count": (
                    self._table_count(ingredient_table) if ingredient_table else None
                ),
                "orphan_revision_ingredient_count": None,
            }
        active_count = 0
        if "active_publication_revision_id" in self._columns_for("recipes"):
            active_count = self._count(
                "SELECT count(DISTINCT rev.id) FROM recipe_publication_revisions rev "
                "JOIN recipes r ON r.active_publication_revision_id = rev.id "
                "AND r.id = rev.recipe_id AND r.user_id = rev.user_id"
            )
        orphan_count = self._count(
            "SELECT count(*) FROM recipe_publication_revisions rev "
            "WHERE NOT EXISTS (SELECT 1 FROM recipes r "
            "WHERE r.id = rev.recipe_id AND r.user_id = rev.user_id)"
        )
        orphan_ingredients: int | None = None
        if ingredient_table:
            ingredient_columns = self._columns_for(ingredient_table)
            if "revision_id" in ingredient_columns:
                orphan_ingredients = self._count(
                    f'SELECT count(*) FROM "{ingredient_table}" child '
                    "WHERE NOT EXISTS (SELECT 1 FROM recipe_publication_revisions rev "
                    "WHERE rev.id = child.revision_id)"
                )
            else:
                self.limitations.add("unknown_revision_ingredient_schema")
        return {
            "table_present": True,
            "total_revision_count": self._table_count(table),
            "active_revision_count": active_count,
            "orphan_revision_count": orphan_count,
            "amount_definition_snapshot_count": self._table_count(
                "recipe_publication_amount_definitions"
            ),
            "nutrient_snapshot_count": self._table_count("recipe_publication_nutrients"),
            "ingredient_snapshot_table_present": ingredient_table is not None,
            "ingredient_snapshot_count": (
                self._table_count(ingredient_table) if ingredient_table else None
            ),
            "orphan_revision_ingredient_count": orphan_ingredients,
        }

    def _daily_logs(self) -> dict[str, Any]:
        if "daily_logs" not in self.tables:
            return {
                "total_log_count": 0,
                "mutable_food_log_count": 0,
                "immutable_recipe_revision_log_count": 0,
                "unknown_authority_count": 0,
                "nutrient_snapshot_count": 0,
                "orphan_nutrient_snapshot_count": 0,
            }
        columns = self._columns_for("daily_logs")
        has_revision_links = {
            "recipe_publication_revision_id",
            "recipe_publication_amount_definition_id",
        } <= columns
        if has_revision_links:
            immutable = self._table_count(
                "daily_logs",
                "recipe_publication_revision_id IS NOT NULL "
                "AND recipe_publication_amount_definition_id IS NOT NULL",
            )
            mutable = self._count(
                "SELECT count(*) FROM daily_logs log "
                "JOIN food_items f ON f.id = log.food_item_id "
                "WHERE log.recipe_publication_revision_id IS NULL "
                "AND log.recipe_publication_amount_definition_id IS NULL "
                "AND f.is_recipe = false"
            )
        else:
            immutable = 0
            mutable = self._count(
                "SELECT count(*) FROM daily_logs log "
                "JOIN food_items f ON f.id = log.food_item_id WHERE f.is_recipe = false"
            )
        total = self._table_count("daily_logs")
        snapshot_count = self._table_count("daily_log_nutrient_snapshots")
        orphan_snapshots = 0
        if "daily_log_nutrient_snapshots" in self.tables:
            orphan_snapshots = self._count(
                "SELECT count(*) FROM daily_log_nutrient_snapshots snapshot "
                "WHERE NOT EXISTS (SELECT 1 FROM daily_logs log "
                "WHERE log.id = snapshot.daily_log_id)"
            )
        return {
            "total_log_count": total,
            "mutable_food_log_count": mutable,
            "immutable_recipe_revision_log_count": immutable,
            "unknown_authority_count": total - mutable - immutable,
            "nutrient_snapshot_count": snapshot_count,
            "orphan_nutrient_snapshot_count": orphan_snapshots,
        }

    def _ocr(self) -> dict[str, Any]:
        legacy_tables: dict[str, dict[str, Any]] = {}
        for table in ("ocr_scans", "parse_results", "parser_corrections"):
            legacy_tables[table] = {
                "present": table in self.tables,
                "row_count": self._table_count(table),
            }
        raw_payload_count = 0
        if "raw_ocr_payload" in self._columns_for("ocr_scans"):
            raw_payload_count = self._table_count("ocr_scans", "raw_ocr_payload IS NOT NULL")
        return {
            "confirmation_trace_count": self._table_count(
                "ocr_nutrition_confirmation_traces"
            ),
            "legacy_tables_present": any(
                details["present"] for details in legacy_tables.values()
            ),
            "legacy_tables": legacy_tables,
            "raw_ocr_payload_row_count": raw_payload_count,
            "raw_ocr_payload_contains_data": raw_payload_count > 0,
        }

    def _idempotency(self) -> dict[str, Any]:
        daily_request_count = 0
        if "client_request_id" in self._columns_for("daily_logs"):
            daily_request_count = self._table_count(
                "daily_logs", "client_request_id IS NOT NULL"
            )
        return {
            "create_operation_receipt_count": self._table_count(
                "create_operation_idempotency"
            ),
            "daily_log_request_identity_count": daily_request_count,
        }

    def _retention(
        self,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        projection_count = current["projection_count"]
        deleted_projections = 0
        if "food_items" in self.tables:
            deleted_projections = self._count(
                "SELECT count(*) FROM food_items f WHERE f.deleted_at IS NOT NULL AND "
                + self._projection_candidate_condition()
            )
        return {
            "user_count": self._table_count("users"),
            "food_count": self._table_count("food_items"),
            "deleted_food_count": (
                self._table_count("food_items", "deleted_at IS NOT NULL")
                if "deleted_at" in self._columns_for("food_items")
                else 0
            ),
            "deleted_recipe_count": current["deleted_recipe_count"],
            "projection_count": projection_count,
            "deleted_projection_count": deleted_projections,
            "superseded_revision_count": (
                self._count(
                    "SELECT count(*) FROM recipe_publication_revisions rev "
                    "WHERE EXISTS (SELECT 1 FROM recipes owner "
                    "WHERE owner.id = rev.recipe_id AND owner.user_id = rev.user_id) "
                    "AND NOT EXISTS (SELECT 1 FROM recipes active "
                    "WHERE active.active_publication_revision_id = rev.id "
                    "AND active.id = rev.recipe_id AND active.user_id = rev.user_id)"
                )
                if "recipe_publication_revisions" in self.tables
                and "active_publication_revision_id" in self._columns_for("recipes")
                else 0
            ),
            "revision_referenced_by_log_count": (
                self._count(
                    "SELECT count(DISTINCT recipe_publication_revision_id) FROM daily_logs "
                    "WHERE recipe_publication_revision_id IS NOT NULL"
                )
                if "recipe_publication_revision_id" in self._columns_for("daily_logs")
                else 0
            ),
        }

    def _consistency(
        self,
        current: dict[str, Any],
        revisions: dict[str, Any],
        logs: dict[str, Any],
    ) -> dict[str, Any]:
        source_mismatch = 0
        revision_mismatch: int | None = None
        inactive_ingredient_references = 0
        unexpected_ownership = current["projection_owner_inconsistencies"]
        if self._has_current_recipe_schema() and "food_items" in self.tables:
            source_mismatch = self._count(
                "SELECT count(*) FROM recipes r "
                "JOIN food_items f ON f.id = r.published_food_item_id "
                "WHERE f.source_type IS DISTINCT FROM 'recipe' "
                "OR f.is_recipe IS DISTINCT FROM true "
                "OR f.source_id IS DISTINCT FROM CAST(r.id AS TEXT)"
            )
            if {
                "active_publication_revision_id",
            } <= self._columns_for("recipes") and {
                "recipe_publication_revision_id",
            } <= self._columns_for("food_items"):
                revision_mismatch = self._count(
                    "SELECT count(*) FROM recipes r "
                    "JOIN food_items f ON f.id = r.published_food_item_id "
                    "WHERE f.recipe_publication_revision_id "
                    "IS DISTINCT FROM r.active_publication_revision_id"
                )
        if "food_item_id" in self._columns_for("recipe_ingredients"):
            inactive_ingredient_references = self._count(
                "SELECT count(*) FROM recipe_ingredients ingredient "
                "JOIN recipes r ON r.id = ingredient.recipe_id "
                "JOIN food_items f ON f.id = ingredient.food_item_id "
                "WHERE r.deleted_at IS NULL AND f.deleted_at IS NOT NULL"
            )
            unexpected_ownership += self._count(
                "SELECT count(*) FROM recipe_ingredients ingredient "
                "JOIN recipes r ON r.id = ingredient.recipe_id "
                "JOIN food_items f ON f.id = ingredient.food_item_id "
                "WHERE r.user_id IS DISTINCT FROM f.user_id"
            )
        if "recipe_publication_revisions" in self.tables:
            unexpected_ownership += self._count(
                "SELECT count(*) FROM recipe_publication_revisions rev "
                "JOIN recipes r ON r.id = rev.recipe_id "
                "WHERE r.user_id IS DISTINCT FROM rev.user_id"
            )
        if "daily_logs" in self.tables and "food_items" in self.tables:
            unexpected_ownership += self._count(
                "SELECT count(*) FROM daily_logs log "
                "JOIN food_items f ON f.id = log.food_item_id "
                "WHERE log.user_id IS DISTINCT FROM f.user_id"
            )
        if "ocr_nutrition_confirmation_traces" in self.tables:
            unexpected_ownership += self._count(
                "SELECT count(*) FROM ocr_nutrition_confirmation_traces trace "
                "JOIN food_items f ON f.id = trace.food_item_id "
                "WHERE trace.user_id IS DISTINCT FROM f.user_id"
            )

        orphan_amounts = 0
        if "recipe_publication_amount_definitions" in self.tables:
            orphan_amounts = self._count(
                "SELECT count(*) FROM recipe_publication_amount_definitions snapshot "
                "WHERE NOT EXISTS (SELECT 1 FROM recipe_publication_revisions rev "
                "WHERE rev.id = snapshot.revision_id)"
            )
        orphan_nutrients = 0
        if "recipe_publication_nutrients" in self.tables:
            orphan_nutrients = self._count(
                "SELECT count(*) FROM recipe_publication_nutrients snapshot "
                "WHERE NOT EXISTS (SELECT 1 FROM recipe_publication_revisions rev "
                "WHERE rev.id = snapshot.revision_id)"
            )
        inactive_references = (
            current["projections_referencing_inactive_objects"]
            + inactive_ingredient_references
        )
        return {
            "missing_recipe_projections": current[
                "recipes_lacking_compatibility_projections"
            ],
            "projection_owner_mismatches": current["projection_owner_inconsistencies"],
            "projection_source_mismatches": source_mismatch,
            "projection_revision_mismatches": revision_mismatch,
            "projections_without_source_recipes": current[
                "projections_without_source_recipes"
            ],
            "orphan_revisions": revisions["orphan_revision_count"],
            "orphan_revision_amount_snapshots": orphan_amounts,
            "orphan_revision_nutrient_snapshots": orphan_nutrients,
            "orphan_revision_ingredients": revisions[
                "orphan_revision_ingredient_count"
            ],
            "orphan_daily_log_snapshots": logs["orphan_nutrient_snapshot_count"],
            "inactive_references": inactive_references,
            "unexpected_ownership_relationships": unexpected_ownership,
        }

    def _classification(
        self,
        *,
        migration: dict[str, Any],
        legacy: dict[str, Any],
        current: dict[str, Any],
        revisions: dict[str, Any],
        logs: dict[str, Any],
        ocr: dict[str, Any],
        idempotency: dict[str, Any],
        retention: dict[str, Any],
        consistency: dict[str, Any],
    ) -> dict[str, str]:
        legacy_present = (
            legacy["recipes_table_present"]
            or legacy["recipe_ingredients_table_present"]
        )
        legacy_rows = legacy["recipe_count"] + legacy["recipe_ingredient_count"]
        if legacy_present and current["schema_present"]:
            return {
                "value": "mixed_legacy_current_state",
                "reason": "legacy_and_current_recipe_schemas_coexist",
            }
        if migration["migration_0004_pending"] is True and legacy_rows > 0:
            return {
                "value": "legacy_conversion_required",
                "reason": "populated_legacy_recipe_tables_block_migration_0004",
            }

        domain_count = sum(
            (
                retention["user_count"],
                retention["food_count"],
                legacy_rows,
                current["recipe_count"],
                revisions["total_revision_count"],
                logs["total_log_count"],
                ocr["confirmation_trace_count"],
                sum(
                    details["row_count"]
                    for details in ocr["legacy_tables"].values()
                ),
                idempotency["create_operation_receipt_count"],
            )
        )
        if domain_count == 0 and not self.limitations:
            return {
                "value": "empty_database",
                "reason": "no_application_or_historical_rows_detected",
            }

        if self.limitations or not migration["at_expected_head"]:
            return {
                "value": "inventory_inconclusive",
                "reason": "database_state_cannot_be_classified_with_current_schema_contract",
            }
        anomaly_counts = [
            current["recipes_lacking_immutable_revisions"],
            logs["unknown_authority_count"],
            *(
                value
                for value in consistency.values()
                if isinstance(value, int) and not isinstance(value, bool)
            ),
        ]
        if any(value > 0 for value in anomaly_counts):
            return {
                "value": "historical_repair_required",
                "reason": "historical_consistency_anomalies_detected",
            }
        return {
            "value": "clean_current_database",
            "reason": "current_schema_has_no_detected_historical_consistency_anomalies",
        }
