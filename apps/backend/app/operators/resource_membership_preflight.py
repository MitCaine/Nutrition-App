"""Deterministic preflight inventory for the 0019 membership constraints.

The query layer accepts an existing SQLAlchemy ``Connection`` so Alembic can run
the exact same classification inside its migration transaction.  The operator
wrapper is the only layer that opens a connection or establishes a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import Connection, Engine, text

from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.resource_membership_contracts import (
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    PREFLIGHT_CATEGORIES,
    PREFLIGHT_VERSION,
    PreflightCategory,
)


BLOCKING_ERROR_MESSAGE = "Resource membership preflight found blocking rows"
SCHEMA_ERROR_MESSAGE = "Resource membership preflight requires exact schema revision 0018"
POSTGRESQL_ERROR_MESSAGE = "Resource membership operator preflight requires PostgreSQL"


class ResourceMembershipPreflightError(RuntimeError):
    """Stable fail-closed base error for preflight admission failures."""


class ResourceMembershipPreflightBlockedError(ResourceMembershipPreflightError):
    """Raised when any frozen blocking category contains rows."""

    def __init__(self, report: ResourceMembershipPreflightReport):
        super().__init__(BLOCKING_ERROR_MESSAGE)
        self.report = report


@dataclass(frozen=True)
class ResourceMembershipFinding:
    category: str
    classification: str
    blocking: bool
    identifiers: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "classification": self.classification,
            "blocking": self.blocking,
            "identifiers": dict(sorted(self.identifiers.items())),
        }


@dataclass(frozen=True)
class ResourceMembershipPreflightReport:
    payload: Mapping[str, Any]

    @property
    def blocking(self) -> bool:
        return bool(self.payload["blocking"])

    @property
    def finding_count(self) -> int:
        return int(self.payload["finding_count"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def to_json(self) -> str:
        return canonical_json(self.payload)


@dataclass(frozen=True)
class _CategoryQuery:
    category: PreflightCategory
    identifier_columns: tuple[str, ...]
    sql: str


def _query(
    category: PreflightCategory,
    identifier_columns: tuple[str, ...],
    sql: str,
) -> _CategoryQuery:
    return _CategoryQuery(category, identifier_columns, sql)


_CATEGORY_BY_CODE = {category.code: category for category in PREFLIGHT_CATEGORIES}


_CATEGORY_QUERIES = tuple(sorted((
    _query(
        _CATEGORY_BY_CODE["recipe_ingredient_owner_mismatch"],
        ("recipe_ingredient_id", "recipe_id", "food_item_id"),
        """
        SELECT ri.id AS recipe_ingredient_id,
               ri.recipe_id AS recipe_id,
               ri.food_item_id AS food_item_id
        FROM public.recipe_ingredients AS ri
        LEFT JOIN public.recipes AS r ON r.id = ri.recipe_id
        LEFT JOIN public.food_items AS f ON f.id = ri.food_item_id
        WHERE r.id IS NULL OR f.id IS NULL OR r.user_id IS DISTINCT FROM f.user_id
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["recipe_ingredient_serving_food_mismatch"],
        ("recipe_ingredient_id", "food_item_id", "serving_definition_id"),
        """
        SELECT ri.id AS recipe_ingredient_id,
               ri.food_item_id AS food_item_id,
               ri.serving_definition_id AS serving_definition_id
        FROM public.recipe_ingredients AS ri
        LEFT JOIN public.serving_definitions AS sd ON sd.id = ri.serving_definition_id
        WHERE ri.serving_definition_id IS NOT NULL
          AND (sd.id IS NULL OR sd.food_item_id IS DISTINCT FROM ri.food_item_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_food_owner_mismatch"],
        ("daily_log_id", "food_item_id"),
        """
        SELECT dl.id AS daily_log_id, dl.food_item_id AS food_item_id
        FROM public.daily_logs AS dl
        LEFT JOIN public.food_items AS f ON f.id = dl.food_item_id
        WHERE f.id IS NULL OR dl.user_id IS DISTINCT FROM f.user_id
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_serving_food_mismatch"],
        ("daily_log_id", "food_item_id", "serving_definition_id"),
        """
        SELECT dl.id AS daily_log_id,
               dl.food_item_id AS food_item_id,
               dl.serving_definition_id AS serving_definition_id
        FROM public.daily_logs AS dl
        LEFT JOIN public.serving_definitions AS sd ON sd.id = dl.serving_definition_id
        WHERE dl.serving_definition_id IS NOT NULL
          AND (sd.id IS NULL OR sd.food_item_id IS DISTINCT FROM dl.food_item_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_publication_links_unpaired"],
        (
            "daily_log_id",
            "recipe_publication_revision_id",
            "recipe_publication_amount_definition_id",
        ),
        """
        SELECT dl.id AS daily_log_id,
               dl.recipe_publication_revision_id AS recipe_publication_revision_id,
               dl.recipe_publication_amount_definition_id
                   AS recipe_publication_amount_definition_id
        FROM public.daily_logs AS dl
        WHERE (dl.recipe_publication_revision_id IS NULL)
              IS DISTINCT FROM
              (dl.recipe_publication_amount_definition_id IS NULL)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_revision_owner_mismatch"],
        ("daily_log_id", "recipe_publication_revision_id"),
        """
        SELECT dl.id AS daily_log_id,
               dl.recipe_publication_revision_id AS recipe_publication_revision_id
        FROM public.daily_logs AS dl
        LEFT JOIN public.recipe_publication_revisions AS rev
          ON rev.id = dl.recipe_publication_revision_id
        WHERE dl.recipe_publication_revision_id IS NOT NULL
          AND (rev.id IS NULL OR rev.user_id IS DISTINCT FROM dl.user_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_amount_revision_mismatch"],
        (
            "daily_log_id",
            "recipe_publication_revision_id",
            "recipe_publication_amount_definition_id",
        ),
        """
        SELECT dl.id AS daily_log_id,
               dl.recipe_publication_revision_id AS recipe_publication_revision_id,
               dl.recipe_publication_amount_definition_id
                   AS recipe_publication_amount_definition_id
        FROM public.daily_logs AS dl
        LEFT JOIN public.recipe_publication_amount_definitions AS amount
          ON amount.id = dl.recipe_publication_amount_definition_id
        WHERE dl.recipe_publication_amount_definition_id IS NOT NULL
          AND (amount.id IS NULL
               OR amount.revision_id IS DISTINCT FROM dl.recipe_publication_revision_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["daily_log_revision_recipe_projection_mismatch"],
        ("daily_log_id", "food_item_id", "recipe_publication_revision_id", "recipe_id"),
        """
        SELECT dl.id AS daily_log_id,
               dl.food_item_id AS food_item_id,
               dl.recipe_publication_revision_id AS recipe_publication_revision_id,
               rev.recipe_id AS recipe_id
        FROM public.daily_logs AS dl
        LEFT JOIN public.recipe_publication_revisions AS rev
          ON rev.id = dl.recipe_publication_revision_id
        LEFT JOIN public.recipes AS r ON r.id = rev.recipe_id
        WHERE dl.recipe_publication_revision_id IS NOT NULL
          AND (rev.id IS NULL OR r.id IS NULL
               OR r.published_food_item_id IS DISTINCT FROM dl.food_item_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["recipe_projection_owner_mismatch"],
        ("recipe_id", "published_food_item_id"),
        """
        SELECT r.id AS recipe_id, r.published_food_item_id AS published_food_item_id
        FROM public.recipes AS r
        LEFT JOIN public.food_items AS f ON f.id = r.published_food_item_id
        WHERE r.published_food_item_id IS NOT NULL
          AND (f.id IS NULL OR f.user_id IS DISTINCT FROM r.user_id)
        UNION
        SELECT rev.recipe_id AS recipe_id, f.id AS published_food_item_id
        FROM public.food_items AS f
        LEFT JOIN public.recipe_publication_revisions AS rev
          ON rev.id = f.recipe_publication_revision_id
        WHERE f.recipe_publication_revision_id IS NOT NULL
          AND (rev.id IS NULL OR f.user_id IS DISTINCT FROM rev.user_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["recipe_projection_missing_active_revision"],
        ("recipe_id", "published_food_item_id", "active_publication_revision_id"),
        """
        SELECT r.id AS recipe_id,
               r.published_food_item_id AS published_food_item_id,
               r.active_publication_revision_id AS active_publication_revision_id
        FROM public.recipes AS r
        WHERE (r.published_food_item_id IS NULL)
              IS DISTINCT FROM
              (r.active_publication_revision_id IS NULL)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["recipe_projection_active_revision_mismatch"],
        ("recipe_id", "published_food_item_id", "active_publication_revision_id"),
        """
        SELECT r.id AS recipe_id,
               r.published_food_item_id AS published_food_item_id,
               r.active_publication_revision_id AS active_publication_revision_id
        FROM public.recipes AS r
        LEFT JOIN public.food_items AS f ON f.id = r.published_food_item_id
        LEFT JOIN public.recipe_publication_revisions AS rev
          ON rev.id = r.active_publication_revision_id
        WHERE r.active_publication_revision_id IS NOT NULL
          AND (rev.id IS NULL
               OR rev.recipe_id IS DISTINCT FROM r.id
               OR rev.user_id IS DISTINCT FROM r.user_id
               OR (r.published_food_item_id IS NOT NULL
                   AND (f.id IS NULL
                        OR f.recipe_publication_revision_id
                             IS DISTINCT FROM r.active_publication_revision_id)))
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["recipe_projection_source_identity_mismatch"],
        ("recipe_id", "published_food_item_id"),
        """
        SELECT r.id AS recipe_id, r.published_food_item_id AS published_food_item_id
        FROM public.recipes AS r
        LEFT JOIN public.food_items AS f ON f.id = r.published_food_item_id
        WHERE r.published_food_item_id IS NOT NULL
          AND (f.id IS NULL OR f.source_type IS DISTINCT FROM 'recipe'
               OR f.source_id IS DISTINCT FROM CAST(r.id AS VARCHAR)
               OR f.is_recipe IS DISTINCT FROM TRUE)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["projection_revision_duplicate"],
        ("recipe_publication_revision_id",),
        """
        SELECT f.recipe_publication_revision_id AS recipe_publication_revision_id
        FROM public.food_items AS f
        WHERE f.recipe_publication_revision_id IS NOT NULL
        GROUP BY f.recipe_publication_revision_id
        HAVING count(*) > 1
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["projection_revision_without_recipe_backlink"],
        ("food_item_id", "recipe_publication_revision_id", "recipe_id"),
        """
        SELECT f.id AS food_item_id,
               f.recipe_publication_revision_id AS recipe_publication_revision_id,
               rev.recipe_id AS recipe_id
        FROM public.food_items AS f
        LEFT JOIN public.recipe_publication_revisions AS rev
          ON rev.id = f.recipe_publication_revision_id
        LEFT JOIN public.recipes AS r ON r.id = rev.recipe_id
        WHERE f.recipe_publication_revision_id IS NOT NULL
          AND (rev.id IS NULL OR r.id IS NULL
               OR r.published_food_item_id IS DISTINCT FROM f.id
               OR r.active_publication_revision_id
                    IS DISTINCT FROM f.recipe_publication_revision_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["ocr_trace_food_owner_mismatch"],
        ("ocr_trace_id", "food_item_id"),
        """
        SELECT trace.id AS ocr_trace_id, trace.food_item_id AS food_item_id
        FROM public.ocr_nutrition_confirmation_traces AS trace
        LEFT JOIN public.food_items AS f ON f.id = trace.food_item_id
        WHERE f.id IS NULL OR trace.user_id IS DISTINCT FROM f.user_id
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["log_snapshot_source_food_mismatch"],
        ("snapshot_id", "daily_log_id", "source_food_item_id"),
        """
        SELECT snap.id AS snapshot_id,
               snap.daily_log_id AS daily_log_id,
               snap.source_food_item_id AS source_food_item_id
        FROM public.daily_log_nutrient_snapshots AS snap
        LEFT JOIN public.daily_logs AS dl ON dl.id = snap.daily_log_id
        WHERE dl.id IS NULL OR snap.source_food_item_id IS DISTINCT FROM dl.food_item_id
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["log_snapshot_source_nutrient_food_mismatch"],
        ("snapshot_id", "source_food_item_id", "source_food_nutrient_id"),
        """
        SELECT snap.id AS snapshot_id,
               snap.source_food_item_id AS source_food_item_id,
               snap.source_food_nutrient_id AS source_food_nutrient_id
        FROM public.daily_log_nutrient_snapshots AS snap
        LEFT JOIN public.food_nutrients AS nutrient
          ON nutrient.id = snap.source_food_nutrient_id
        WHERE snap.source_food_nutrient_id IS NOT NULL
          AND (nutrient.id IS NULL
               OR nutrient.food_item_id IS DISTINCT FROM snap.source_food_item_id)
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["log_snapshot_source_nutrient_identity_mismatch"],
        ("snapshot_id", "source_food_nutrient_id"),
        """
        SELECT snap.id AS snapshot_id,
               snap.source_food_nutrient_id AS source_food_nutrient_id
        FROM public.daily_log_nutrient_snapshots AS snap
        LEFT JOIN public.food_nutrients AS nutrient
          ON nutrient.id = snap.source_food_nutrient_id
        WHERE snap.source_food_nutrient_id IS NOT NULL
          AND nutrient.id IS NOT NULL
          AND nutrient.nutrient_id IS DISTINCT FROM snap.nutrient_id
        """,
    ),
    _query(
        _CATEGORY_BY_CODE["log_snapshot_serving_food_mismatch"],
        ("snapshot_id", "source_food_item_id", "serving_definition_id"),
        """
        SELECT snap.id AS snapshot_id,
               snap.source_food_item_id AS source_food_item_id,
               snap.serving_definition_id AS serving_definition_id
        FROM public.daily_log_nutrient_snapshots AS snap
        LEFT JOIN public.serving_definitions AS sd ON sd.id = snap.serving_definition_id
        WHERE snap.serving_definition_id IS NOT NULL
          AND (sd.id IS NULL OR sd.food_item_id IS DISTINCT FROM snap.source_food_item_id)
        """,
    ),
), key=lambda query: query.category.code))


# The install preflight runs against 0018, where ``recipe_ingredients.user_id``
# does not exist yet.  Current-schema qualification must additionally verify
# that the denormalized child owner agrees with both parents.  Keep the query
# split explicit so 0018 remains compilable while 0019 cannot hide corruption
# introduced by an owner-level trigger bypass.
_CURRENT_SCHEMA_QUERY_OVERRIDES = {
    "recipe_ingredient_owner_mismatch": """
        SELECT ri.id AS recipe_ingredient_id,
               ri.recipe_id AS recipe_id,
               ri.food_item_id AS food_item_id
        FROM public.recipe_ingredients AS ri
        LEFT JOIN public.recipes AS r ON r.id = ri.recipe_id
        LEFT JOIN public.food_items AS f ON f.id = ri.food_item_id
        WHERE r.id IS NULL
           OR f.id IS NULL
           OR ri.user_id IS DISTINCT FROM r.user_id
           OR ri.user_id IS DISTINCT FROM f.user_id
           OR r.user_id IS DISTINCT FROM f.user_id
    """,
}


if tuple(query.category.code for query in _CATEGORY_QUERIES) != tuple(
    category.code for category in PREFLIGHT_CATEGORIES
):
    raise RuntimeError("Resource membership preflight queries do not match frozen categories")


def _identifier_text(value: Any) -> str:
    if value is None:
        return "missing"
    return str(value)


def classify_resource_membership(
    connection: Connection,
    *,
    observed_schema_revision: str = HISTORICAL_PHASE5_SCHEMA_REVISION,
    required_schema_revision: str = HISTORICAL_PHASE5_SCHEMA_REVISION,
    read_only: bool = True,
) -> ResourceMembershipPreflightReport:
    """Run every frozen classification query on an existing transaction."""
    findings: list[ResourceMembershipFinding] = []
    category_counts: list[dict[str, Any]] = []
    for query in _CATEGORY_QUERIES:
        sql = (
            _CURRENT_SCHEMA_QUERY_OVERRIDES.get(query.category.code, query.sql)
            if observed_schema_revision != HISTORICAL_PHASE5_SCHEMA_REVISION
            else query.sql
        )
        raw_rows = connection.execute(text(sql)).mappings().all()
        category_findings = [
            ResourceMembershipFinding(
                category=query.category.code,
                classification=query.category.classification,
                blocking=query.category.blocking,
                identifiers={
                    column: _identifier_text(row.get(column))
                    for column in query.identifier_columns
                },
            )
            for row in raw_rows
        ]
        category_findings.sort(
            key=lambda finding: tuple(finding.identifiers.items())
        )
        findings.extend(category_findings)
        category_counts.append(
            {
                "category": query.category.code,
                "classification": query.category.classification,
                "blocking": query.category.blocking,
                "count": len(category_findings),
            }
        )

    finding_payloads = [finding.to_dict() for finding in findings]
    blocking_row_count = sum(finding.blocking for finding in findings)
    blocking_category_count = sum(
        row["blocking"] and row["count"] > 0 for row in category_counts
    )
    unsigned: dict[str, Any] = {
        "preflight_version": PREFLIGHT_VERSION,
        "required_schema_revision": required_schema_revision,
        "observed_schema_revision": observed_schema_revision,
        "read_only": read_only,
        "blocking": blocking_row_count > 0,
        "blocking_category_count": blocking_category_count,
        "blocking_row_count": blocking_row_count,
        "finding_count": len(findings),
        "category_counts": category_counts,
        "findings": finding_payloads,
    }
    return ResourceMembershipPreflightReport(
        payload={**unsigned, "report_digest": canonical_digest(unsigned)}
    )


def _require_exact_schema_revision(connection: Connection) -> str:
    revisions = [
        str(value)
        for value in connection.scalars(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        ).all()
    ]
    if revisions != [HISTORICAL_PHASE5_SCHEMA_REVISION]:
        raise ResourceMembershipPreflightError(SCHEMA_ERROR_MESSAGE)
    return revisions[0]


def require_resource_membership_preflight(
    connection: Connection,
) -> ResourceMembershipPreflightReport:
    """Migration-callable admission check; does not own a transaction or process."""
    return assert_no_blocking_findings(connection, require_revision=True)


def assert_no_blocking_findings(
    connection: Connection,
    *,
    require_revision: bool = False,
    observed_schema_revision: str | None = None,
    read_only: bool = False,
) -> ResourceMembershipPreflightReport:
    """Assert zero blocking rows inside the caller's existing transaction.

    Alembic passes ``require_revision=True`` before applying 0019.  The optional
    form remains usable after Alembic has already advanced its in-transaction
    version bookkeeping, while still using the identical classification layer.
    """
    revision = _require_exact_schema_revision(connection) if require_revision else (
        observed_schema_revision or HISTORICAL_PHASE5_SCHEMA_REVISION
    )
    report = classify_resource_membership(
        connection,
        observed_schema_revision=revision,
        required_schema_revision=(
            HISTORICAL_PHASE5_SCHEMA_REVISION
            if require_revision
            else observed_schema_revision or HISTORICAL_PHASE5_SCHEMA_REVISION
        ),
        read_only=read_only,
    )
    if report.blocking:
        raise ResourceMembershipPreflightBlockedError(report)
    return report


def run_resource_membership_operator_preflight(
    engine: Engine,
) -> ResourceMembershipPreflightReport:
    """Run preflight in one PostgreSQL read-only, repeatable-read snapshot."""
    with engine.connect() as raw_connection:
        if raw_connection.dialect.name != "postgresql":
            raise ResourceMembershipPreflightError(POSTGRESQL_ERROR_MESSAGE)
        connection = raw_connection.execution_options(isolation_level="REPEATABLE READ")
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            settings = connection.execute(
                text(
                    """
                    SELECT current_setting('transaction_read_only') AS read_only,
                           current_setting('transaction_isolation') AS isolation
                    """
                )
            ).mappings().one()
            if settings["read_only"] != "on" or settings["isolation"] != "repeatable read":
                raise ResourceMembershipPreflightError(
                    "Resource membership operator transaction boundary is invalid"
                )
            report = assert_no_blocking_findings(
                connection,
                require_revision=True,
                read_only=True,
            )
            return report
        finally:
            transaction.rollback()
