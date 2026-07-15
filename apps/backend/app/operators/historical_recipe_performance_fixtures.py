from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from math import ceil
import re
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, text

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.phase5c_performance_contracts import FIXTURE_GENERATOR_VERSION


FIXTURE_LOGICAL_DIGEST_VERSION = "phase5c_performance_fixture_logical_digest_v1"
INTERNAL_REDUCED_TIER = "TEST_REDUCED"

_SUPPORTED_SOURCE_REVISION = "0003_usda_source_identity"
_POSTGRES_IDENTIFIER_MAX_BYTES = 63
_DISPOSABLE_DATABASE = re.compile(
    r"^nutrition_phase5c_(?:benchmark|bench)_[a-z0-9_]{3,48}$"
)
_FIXTURE_NAMESPACE = UUID("f95f26f6-4fd0-5992-985d-f6f6b356e45f")
_FIXED_TIMESTAMP = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
_FIXED_LOG_DATE = date(2024, 1, 1)
_TABLE_ORDER = (
    "users",
    "food_items",
    "food_sources",
    "serving_definitions",
    "food_nutrients",
    "recipes",
    "recipe_ingredients",
    "daily_logs",
    "daily_log_nutrient_snapshots",
    "ocr_scans",
    "parse_results",
    "parser_corrections",
)
_SEEDED_TABLES = (
    "nutrition_targets",
    "parser_corrections",
    "parse_results",
    "ocr_scans",
    "daily_log_nutrient_snapshots",
    "daily_logs",
    "recipe_ingredients",
    "recipes",
    "food_nutrients",
    "serving_definitions",
    "food_sources",
    "food_items",
    "nutrient_reference_values",
    "user_profiles",
    "users",
)
_EXPECTED_SOURCE_TABLES = frozenset(
    (*_SEEDED_TABLES, "nutrients", "alembic_version")
)


class PerformanceFixtureError(RuntimeError):
    """Fail safely when deterministic fixture prerequisites are not satisfied."""


@dataclass(frozen=True)
class PerformanceFixtureProfile:
    tier_id: str
    recipe_count: int
    food_count: int
    daily_log_count: int
    ocr_record_count: int
    convert_count: int
    quarantine_count: int
    block_count: int
    ingredient_p50: int
    ingredient_p95: int
    graph_depth: int
    graph_breadth: int
    servings_per_food: int
    nutrients_per_food: int
    internal_only: bool = False

    def __post_init__(self) -> None:
        if not self.tier_id or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (
                self.recipe_count,
                self.food_count,
                self.daily_log_count,
                self.ocr_record_count,
                self.convert_count,
                self.quarantine_count,
                self.block_count,
                self.ingredient_p50,
                self.ingredient_p95,
                self.graph_depth,
                self.graph_breadth,
                self.servings_per_food,
                self.nutrients_per_food,
            )
        ):
            raise ValueError("Performance fixture profile values must be nonnegative integers")
        if self.recipe_count <= 0:
            raise ValueError("Performance fixture profile must contain Recipes")
        if self.food_count < self.recipe_count + 2:
            raise ValueError(
                "Performance fixture profile requires projection, owner, and foreign Foods"
            )
        if self.convert_count + self.quarantine_count + self.block_count != (self.recipe_count):
            raise ValueError("Performance fixture dispositions must cover every Recipe")
        if self.block_count <= 0 or self.quarantine_count <= 0:
            raise ValueError("Performance fixture must exercise quarantine and block cases")
        if not 0 < self.ingredient_p50 <= self.ingredient_p95:
            raise ValueError("Ingredient percentile targets are invalid")
        if not 0 < self.servings_per_food:
            raise ValueError("Performance fixture Foods require serving definitions")
        if not 0 < self.nutrients_per_food <= len(NUTRIENT_CATALOG):
            raise ValueError(
                "Performance fixture nutrients must use only catalog nutrient identities"
            )
        required_convert_recipes = self.graph_depth + self.graph_breadth
        if self.convert_count < required_convert_recipes:
            raise ValueError("Convert population is too small for the declared nested graph")
        if self.graph_breadth > self.ingredient_p50:
            raise ValueError("Root ingredient count is too small for declared graph breadth")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "tier_id": self.tier_id,
            "recipe_count": self.recipe_count,
            "food_count": self.food_count,
            "daily_log_count": self.daily_log_count,
            "ocr_record_count": self.ocr_record_count,
            "dispositions": {
                "convert": self.convert_count,
                "quarantine": self.quarantine_count,
                "block": self.block_count,
            },
            "ingredient_p50": self.ingredient_p50,
            "ingredient_p95": self.ingredient_p95,
            "graph_depth": self.graph_depth,
            "graph_breadth": self.graph_breadth,
            "servings_per_food": self.servings_per_food,
            "nutrients_per_food": self.nutrients_per_food,
            "internal_only": self.internal_only,
        }


_PROFILE_VALUES = {
    "T0": PerformanceFixtureProfile(
        tier_id="T0",
        recipe_count=50,
        food_count=250,
        daily_log_count=5_000,
        ocr_record_count=1_000,
        convert_count=45,
        quarantine_count=4,
        block_count=1,
        ingredient_p50=4,
        ingredient_p95=10,
        graph_depth=3,
        graph_breadth=2,
        servings_per_food=4,
        nutrients_per_food=len(NUTRIENT_CATALOG),
    ),
    "T1": PerformanceFixtureProfile(
        tier_id="T1",
        recipe_count=1_000,
        food_count=3_000,
        daily_log_count=100_000,
        ocr_record_count=25_000,
        convert_count=900,
        quarantine_count=80,
        block_count=20,
        ingredient_p50=8,
        ingredient_p95=25,
        graph_depth=5,
        graph_breadth=3,
        servings_per_food=6,
        nutrients_per_food=len(NUTRIENT_CATALOG),
    ),
    "T2": PerformanceFixtureProfile(
        tier_id="T2",
        recipe_count=10_000,
        food_count=25_000,
        daily_log_count=1_000_000,
        ocr_record_count=250_000,
        convert_count=9_000,
        quarantine_count=800,
        block_count=200,
        ingredient_p50=10,
        ingredient_p95=50,
        graph_depth=8,
        graph_breadth=5,
        servings_per_food=8,
        nutrients_per_food=len(NUTRIENT_CATALOG),
    ),
    "T3": PerformanceFixtureProfile(
        tier_id="T3",
        recipe_count=50_000,
        food_count=100_000,
        daily_log_count=5_000_000,
        ocr_record_count=1_000_000,
        convert_count=45_000,
        quarantine_count=4_000,
        block_count=1_000,
        ingredient_p50=10,
        ingredient_p95=50,
        graph_depth=8,
        graph_breadth=5,
        servings_per_food=8,
        nutrients_per_food=len(NUTRIENT_CATALOG),
    ),
    INTERNAL_REDUCED_TIER: PerformanceFixtureProfile(
        tier_id=INTERNAL_REDUCED_TIER,
        recipe_count=4,
        food_count=12,
        daily_log_count=12,
        ocr_record_count=6,
        convert_count=2,
        quarantine_count=1,
        block_count=1,
        ingredient_p50=2,
        ingredient_p95=3,
        graph_depth=1,
        graph_breadth=1,
        servings_per_food=2,
        nutrients_per_food=4,
        internal_only=True,
    ),
}
PERFORMANCE_FIXTURE_PROFILES: Mapping[str, PerformanceFixtureProfile] = MappingProxyType(
    _PROFILE_VALUES
)


def performance_fixture_profile(
    tier_id: str, *, allow_internal: bool = False
) -> PerformanceFixtureProfile:
    try:
        profile = PERFORMANCE_FIXTURE_PROFILES[tier_id]
    except KeyError:
        raise PerformanceFixtureError("Unsupported performance fixture tier") from None
    if profile.internal_only and not allow_internal:
        raise PerformanceFixtureError("Internal performance fixture tier is test-only")
    return profile


@dataclass(frozen=True)
class PerformanceFixtureBlueprint:
    profile: PerformanceFixtureProfile
    seed: int
    ingredient_counts: tuple[int, ...]
    blueprint_digest: str

    def disposition_for(self, recipe_index: int) -> str:
        self._require_recipe_index(recipe_index)
        if recipe_index < self.profile.convert_count:
            return "convert"
        if recipe_index < self.profile.convert_count + self.profile.quarantine_count:
            return "quarantine"
        return "block"

    def dependencies_for(self, recipe_index: int) -> tuple[int, ...]:
        """Return convert-only child indices for a small deterministic acyclic graph."""
        self._require_recipe_index(recipe_index)
        if recipe_index >= self.profile.convert_count:
            return ()
        if recipe_index == 0:
            extras_start = self.profile.graph_depth + 1
            extras_end = extras_start + self.profile.graph_breadth - 1
            return (1, *range(extras_start, extras_end))
        if recipe_index < self.profile.graph_depth:
            return (recipe_index + 1,)
        return ()

    @property
    def dimensions(self) -> dict[str, Any]:
        sorted_counts = self.ingredient_counts
        return {
            "recipes": self.profile.recipe_count,
            "ingredients": sum(sorted_counts),
            "foods": self.profile.food_count,
            "servings": self.profile.food_count * self.profile.servings_per_food,
            "nutrients": self.profile.food_count * self.profile.nutrients_per_food,
            "daily_logs": self.profile.daily_log_count,
            "ocr_records": self.profile.ocr_record_count,
            "max_servings_per_food": self.profile.servings_per_food,
            "max_nutrients_per_food": self.profile.nutrients_per_food,
            "ingredients_per_recipe": {
                "count": self.profile.recipe_count,
                "p50": _nearest_rank(sorted_counts, 50),
                "p95": _nearest_rank(sorted_counts, 95),
                "p99": _nearest_rank(sorted_counts, 99),
                "maximum": sorted_counts[-1],
            },
            "nested_graph": {
                "depth": self.profile.graph_depth,
                "breadth": self.profile.graph_breadth,
            },
            "dispositions": {
                "convert": self.profile.convert_count,
                "quarantine": self.profile.quarantine_count,
                "block": self.profile.block_count,
            },
        }

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "generator_version": FIXTURE_GENERATOR_VERSION,
            "tier_id": self.profile.tier_id,
            "seed": self.seed,
            "dimensions": self.dimensions,
            "ingredient_vector_digest": canonical_digest(self.ingredient_counts),
            "blueprint_digest": self.blueprint_digest,
        }

    def _require_recipe_index(self, recipe_index: int) -> None:
        if not 0 <= recipe_index < self.profile.recipe_count:
            raise IndexError("Recipe fixture index is outside the blueprint")


def build_performance_fixture_blueprint(
    tier_id: str,
    seed: int,
    *,
    allow_internal: bool = False,
) -> PerformanceFixtureBlueprint:
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**63:
        raise PerformanceFixtureError("Fixture seed must be an integer from 0 through 2^63-1")
    profile = performance_fixture_profile(tier_id, allow_internal=allow_internal)
    ingredient_counts = _ingredient_count_vector(profile)
    unsigned = {
        "generator_version": FIXTURE_GENERATOR_VERSION,
        "tier_id": profile.tier_id,
        "seed": seed,
        "profile": profile.to_safe_dict(),
        "ingredient_counts": ingredient_counts,
        "nested_dependencies": [
            [index, list(_dependencies_for_profile(profile, index))]
            for index in range(profile.recipe_count)
            if _dependencies_for_profile(profile, index)
        ],
    }
    return PerformanceFixtureBlueprint(
        profile=profile,
        seed=seed,
        ingredient_counts=ingredient_counts,
        blueprint_digest=canonical_digest(unsigned),
    )


@dataclass(frozen=True)
class PerformanceFixtureSeedResult:
    generator_version: str
    tier_id: str
    seed: int
    blueprint_digest: str
    logical_digest: str
    dimensions: dict[str, Any]
    table_counts: dict[str, int]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "generator_version": self.generator_version,
            "tier_id": self.tier_id,
            "seed": self.seed,
            "blueprint_digest": self.blueprint_digest,
            "logical_digest": self.logical_digest,
            "dimensions": self.dimensions,
            "table_counts": self.table_counts,
        }


def seed_performance_fixture(
    engine: Engine,
    blueprint: PerformanceFixtureBlueprint,
    *,
    confirmed_database_name: str,
    batch_size: int = 2_000,
) -> PerformanceFixtureSeedResult:
    """Seed one clean PostgreSQL database at revision 0003 in bounded batches."""
    if engine.dialect.name != "postgresql":
        raise PerformanceFixtureError("Performance fixtures support PostgreSQL only")
    database_name = str(engine.url.database or "")
    if (
            confirmed_database_name != database_name
            or not _DISPOSABLE_DATABASE.fullmatch(database_name)
            or len(database_name.encode("ascii")) > _POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise PerformanceFixtureError(
            "Performance fixture target is not an explicitly confirmed disposable database"
        )
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= 50_000
    ):
        raise PerformanceFixtureError("Fixture batch size must be from 1 through 50000")

    accumulator = _LogicalDigestAccumulator(blueprint)
    with engine.connect() as connection:
        _require_clean_legacy_source(connection)
        connection.commit()
        for table_name, statement, rows, transform in _fixture_table_streams(blueprint):
            accumulator.start_table(table_name)
            _insert_rows(
                connection,
                statement=statement,
                rows=rows,
                transform=transform,
                batch_size=batch_size,
                accumulator=accumulator,
            )

    expected_counts = _expected_table_counts(blueprint)
    if accumulator.table_counts != expected_counts:
        raise PerformanceFixtureError("Generated fixture row counts differ from blueprint")
    return PerformanceFixtureSeedResult(
        generator_version=FIXTURE_GENERATOR_VERSION,
        tier_id=blueprint.profile.tier_id,
        seed=blueprint.seed,
        blueprint_digest=blueprint.blueprint_digest,
        logical_digest=accumulator.hexdigest(),
        dimensions=blueprint.dimensions,
        table_counts=dict(accumulator.table_counts),
    )


def calculate_performance_fixture_logical_digest(
    blueprint: PerformanceFixtureBlueprint,
) -> str:
    """Reproduce the logical digest without retaining or writing generated rows."""
    accumulator = _LogicalDigestAccumulator(blueprint)
    for table_name, _statement, rows, _transform in _fixture_table_streams(blueprint):
        accumulator.start_table(table_name)
        for row in rows:
            accumulator.add_row(row)
    if accumulator.table_counts != _expected_table_counts(blueprint):
        raise PerformanceFixtureError("Generated fixture row counts differ from blueprint")
    return accumulator.hexdigest()


def _ingredient_count_vector(profile: PerformanceFixtureProfile) -> tuple[int, ...]:
    median_rank = ceil(profile.recipe_count * Decimal("0.50"))
    p95_index = ceil(profile.recipe_count * Decimal("0.95")) - 1
    middle_count = max(0, p95_index - median_rank)
    middle_span = max(0, profile.ingredient_p95 - profile.ingredient_p50 - 1)
    values: list[int] = []
    for index in range(profile.recipe_count):
        if index < median_rank:
            value = profile.ingredient_p50
        elif index >= p95_index:
            value = profile.ingredient_p95
        elif middle_span == 0:
            value = profile.ingredient_p50
        else:
            offset = index - median_rank
            denominator = max(1, middle_count - 1)
            value = profile.ingredient_p50 + 1 + (offset * (middle_span - 1) // denominator)
        values.append(value)
    result = tuple(values)
    if (
        _nearest_rank(result, 50) != profile.ingredient_p50
        or _nearest_rank(result, 95) != profile.ingredient_p95
    ):
        raise ValueError("Ingredient vector does not meet declared nearest-rank percentiles")
    return result


def _nearest_rank(sorted_values: tuple[int, ...], percentile: int) -> int:
    if not sorted_values or not 1 <= percentile <= 100:
        raise ValueError("Nearest-rank percentile input is invalid")
    index = ceil(len(sorted_values) * Decimal(percentile) / Decimal(100)) - 1
    return sorted_values[index]


def _dependencies_for_profile(
    profile: PerformanceFixtureProfile, recipe_index: int
) -> tuple[int, ...]:
    if recipe_index >= profile.convert_count:
        return ()
    if recipe_index == 0:
        extras_start = profile.graph_depth + 1
        extras_end = extras_start + profile.graph_breadth - 1
        return (1, *range(extras_start, extras_end))
    if recipe_index < profile.graph_depth:
        return (recipe_index + 1,)
    return ()


class _LogicalDigestAccumulator:
    def __init__(self, blueprint: PerformanceFixtureBlueprint):
        self._digest = hashlib.sha256()
        self.table_counts: dict[str, int] = {}
        self._current_table: str | None = None
        self._update(
            canonical_json(
                {
                    "digest_version": FIXTURE_LOGICAL_DIGEST_VERSION,
                    "generator_version": FIXTURE_GENERATOR_VERSION,
                    "tier_id": blueprint.profile.tier_id,
                    "seed": blueprint.seed,
                    "blueprint_digest": blueprint.blueprint_digest,
                }
            ).encode("utf-8")
        )

    def start_table(self, table_name: str) -> None:
        if table_name not in _TABLE_ORDER or table_name in self.table_counts:
            raise PerformanceFixtureError("Fixture table stream order is invalid")
        expected = _TABLE_ORDER[len(self.table_counts)]
        if table_name != expected:
            raise PerformanceFixtureError("Fixture table stream order is invalid")
        self._current_table = table_name
        self.table_counts[table_name] = 0
        self._update(b"table")
        self._update(table_name.encode("ascii"))

    def add_row(self, row: dict[str, Any]) -> None:
        if self._current_table is None:
            raise PerformanceFixtureError("Fixture logical row has no table scope")
        encoded = canonical_json(row).encode("utf-8")
        self._update(b"row")
        self._update(encoded)
        self.table_counts[self._current_table] += 1

    def hexdigest(self) -> str:
        if tuple(self.table_counts) != _TABLE_ORDER:
            raise PerformanceFixtureError("Fixture logical digest is incomplete")
        return self._digest.hexdigest()

    def _update(self, value: bytes) -> None:
        self._digest.update(len(value).to_bytes(8, "big"))
        self._digest.update(value)


def _insert_rows(
    connection: Connection,
    *,
    statement: str,
    rows: Iterator[dict[str, Any]],
    transform: Callable[[dict[str, Any]], dict[str, Any]],
    batch_size: int,
    accumulator: _LogicalDigestAccumulator,
) -> None:
    query = text(statement)
    batch: list[dict[str, Any]] = []
    for row in rows:
        accumulator.add_row(row)
        batch.append(transform(row))
        if len(batch) == batch_size:
            connection.execute(query, batch)
            connection.commit()
            batch.clear()
    if batch:
        connection.execute(query, batch)
        connection.commit()


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    return row


def _json_parameters(*fields: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def transform(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field in fields:
            if result[field] is not None:
                result[field] = canonical_json(result[field])
        return result

    return transform


def _fixture_table_streams(
    blueprint: PerformanceFixtureBlueprint,
) -> Iterator[
    tuple[
        str,
        str,
        Iterator[dict[str, Any]],
        Callable[[dict[str, Any]], dict[str, Any]],
    ]
]:
    yield (
        "users",
        "INSERT INTO users (id, email, display_name, created_at) "
        "VALUES (:id, :email, :display_name, :created_at)",
        _user_rows(blueprint),
        _identity,
    )
    yield (
        "food_items",
        "INSERT INTO food_items "
        "(id, user_id, name, brand, source_type, source_id, is_recipe, notes, "
        "created_at, updated_at, deleted_at) VALUES "
        "(:id, :user_id, :name, :brand, :source_type, :source_id, :is_recipe, "
        ":notes, :created_at, :updated_at, :deleted_at)",
        _food_rows(blueprint),
        _identity,
    )
    yield (
        "food_sources",
        "INSERT INTO food_sources "
        "(id, food_item_id, source_type, external_id, raw_payload, metadata, created_at) "
        "VALUES (:id, :food_item_id, :source_type, :external_id, "
        "CAST(:raw_payload AS jsonb), CAST(:metadata AS jsonb), :created_at)",
        _empty_rows(),
        _json_parameters("raw_payload", "metadata"),
    )
    yield (
        "serving_definitions",
        "INSERT INTO serving_definitions "
        "(id, food_item_id, label, quantity, unit, gram_weight, is_default, source, "
        "confidence, is_user_confirmed) VALUES "
        "(:id, :food_item_id, :label, :quantity, :unit, :gram_weight, :is_default, "
        ":source, :confidence, :is_user_confirmed)",
        _serving_rows(blueprint),
        _identity,
    )
    yield (
        "food_nutrients",
        "INSERT INTO food_nutrients "
        "(id, food_item_id, nutrient_id, amount, unit, basis, data_status, "
        "confidence, source, is_user_confirmed, original_amount, original_unit, "
        "original_text, created_at, updated_at) VALUES "
        "(:id, :food_item_id, :nutrient_id, :amount, :unit, :basis, :data_status, "
        ":confidence, :source, :is_user_confirmed, :original_amount, :original_unit, "
        ":original_text, :created_at, :updated_at)",
        _nutrient_rows(blueprint),
        _identity,
    )
    yield (
        "recipes",
        "INSERT INTO recipes "
        "(id, food_item_id, user_id, serving_count, final_yield_quantity, "
        "final_yield_unit, instructions, created_at, updated_at) VALUES "
        "(:id, :food_item_id, :user_id, :serving_count, :final_yield_quantity, "
        ":final_yield_unit, :instructions, :created_at, :updated_at)",
        _recipe_rows(blueprint),
        _identity,
    )
    yield (
        "recipe_ingredients",
        "INSERT INTO recipe_ingredients "
        "(id, recipe_id, ingredient_food_item_id, quantity, unit, "
        "serving_definition_id, gram_amount, preparation_note, sort_order) VALUES "
        "(:id, :recipe_id, :ingredient_food_item_id, :quantity, :unit, "
        ":serving_definition_id, :gram_amount, :preparation_note, :sort_order)",
        _ingredient_rows(blueprint),
        _identity,
    )
    yield (
        "daily_logs",
        "INSERT INTO daily_logs "
        "(id, user_id, food_item_id, logged_date, meal_type, amount_quantity, "
        "amount_unit, serving_definition_id, gram_amount, package_fraction, notes, "
        "created_at, updated_at) VALUES "
        "(:id, :user_id, :food_item_id, :logged_date, :meal_type, :amount_quantity, "
        ":amount_unit, :serving_definition_id, :gram_amount, :package_fraction, "
        ":notes, :created_at, :updated_at)",
        _daily_log_rows(blueprint),
        _identity,
    )
    yield (
        "daily_log_nutrient_snapshots",
        "INSERT INTO daily_log_nutrient_snapshots "
        "(id, daily_log_id, source_food_item_id, source_food_nutrient_id, "
        "serving_definition_id, nutrient_id, amount, unit, data_status, "
        "consumed_amount_quantity, consumed_amount_unit, consumed_gram_amount, "
        "consumed_package_fraction, calculation_metadata) VALUES "
        "(:id, :daily_log_id, :source_food_item_id, :source_food_nutrient_id, "
        ":serving_definition_id, :nutrient_id, :amount, :unit, :data_status, "
        ":consumed_amount_quantity, :consumed_amount_unit, :consumed_gram_amount, "
        ":consumed_package_fraction, CAST(:calculation_metadata AS jsonb))",
        _daily_snapshot_rows(blueprint),
        _json_parameters("calculation_metadata"),
    )
    yield (
        "ocr_scans",
        "INSERT INTO ocr_scans "
        "(id, user_id, image_metadata, ocr_engine, raw_ocr_payload, full_text, "
        "created_at) VALUES "
        "(:id, :user_id, CAST(:image_metadata AS jsonb), :ocr_engine, "
        "CAST(:raw_ocr_payload AS jsonb), :full_text, :created_at)",
        _ocr_rows(blueprint),
        _json_parameters("image_metadata", "raw_ocr_payload"),
    )
    yield (
        "parse_results",
        "INSERT INTO parse_results "
        "(id, ocr_scan_id, parser_version, status, diagnostics, parsed_payload, "
        "created_food_item_id, created_at) VALUES "
        "(:id, :ocr_scan_id, :parser_version, :status, CAST(:diagnostics AS jsonb), "
        "CAST(:parsed_payload AS jsonb), :created_food_item_id, :created_at)",
        _parse_result_rows(blueprint),
        _json_parameters("diagnostics", "parsed_payload"),
    )
    yield (
        "parser_corrections",
        "INSERT INTO parser_corrections "
        "(id, user_id, ocr_scan_id, parse_result_id, parser_version, field_name, "
        "nutrient_id, parsed_value, confirmed_value, confirmation_action, created_at) "
        "VALUES (:id, :user_id, :ocr_scan_id, :parse_result_id, :parser_version, "
        ":field_name, :nutrient_id, CAST(:parsed_value AS jsonb), "
        "CAST(:confirmed_value AS jsonb), :confirmation_action, :created_at)",
        _empty_rows(),
        _json_parameters("parsed_value", "confirmed_value"),
    )


def _fixture_uuid(blueprint: PerformanceFixtureBlueprint, entity: str, *indices: int) -> UUID:
    suffix = ":".join(str(value) for value in indices)
    return uuid5(
        _FIXTURE_NAMESPACE,
        f"{FIXTURE_GENERATOR_VERSION}:{blueprint.profile.tier_id}:"
        f"{blueprint.seed}:{entity}:{suffix}",
    )


def _empty_rows() -> Iterator[dict[str, Any]]:
    yield from ()


def _owner_id(blueprint: PerformanceFixtureBlueprint) -> UUID:
    return _fixture_uuid(blueprint, "user", 0)


def _foreign_owner_id(blueprint: PerformanceFixtureBlueprint) -> UUID:
    return _fixture_uuid(blueprint, "user", 1)


def _food_id(blueprint: PerformanceFixtureBlueprint, food_index: int) -> UUID:
    return _fixture_uuid(blueprint, "food", food_index)


def _serving_id(
    blueprint: PerformanceFixtureBlueprint, food_index: int, serving_index: int
) -> UUID:
    return _fixture_uuid(blueprint, "serving", food_index, serving_index)


def _nutrient_row_id(
    blueprint: PerformanceFixtureBlueprint, food_index: int, nutrient_index: int
) -> UUID:
    return _fixture_uuid(blueprint, "nutrient", food_index, nutrient_index)


def _recipe_id(blueprint: PerformanceFixtureBlueprint, recipe_index: int) -> UUID:
    return _fixture_uuid(blueprint, "recipe", recipe_index)


def _user_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    for index, label in enumerate(("owner", "foreign")):
        user_id = _fixture_uuid(blueprint, "user", index)
        yield {
            "id": user_id,
            "email": f"phase5c-fixture-{user_id.hex}@example.invalid",
            "display_name": f"phase5c-fixture-{label}",
            "created_at": _FIXED_TIMESTAMP,
        }


def _food_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    owner_id = _owner_id(blueprint)
    foreign_owner_id = _foreign_owner_id(blueprint)
    for food_index in range(blueprint.profile.food_count):
        is_recipe = food_index < blueprint.profile.recipe_count
        is_foreign = food_index == blueprint.profile.recipe_count
        yield {
            "id": _food_id(blueprint, food_index),
            "user_id": foreign_owner_id if is_foreign else owner_id,
            "name": f"phase5c-fixture-food-{food_index:08d}",
            "brand": None,
            "source_type": "recipe" if is_recipe else "manual",
            "source_id": str(_recipe_id(blueprint, food_index)) if is_recipe else None,
            "is_recipe": is_recipe,
            "notes": None,
            "created_at": _FIXED_TIMESTAMP,
            "updated_at": _FIXED_TIMESTAMP,
            "deleted_at": None,
        }


def _serving_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    for food_index in range(blueprint.profile.food_count):
        is_recipe = food_index < blueprint.profile.recipe_count
        for serving_index in range(blueprint.profile.servings_per_food):
            yield {
                "id": _serving_id(blueprint, food_index, serving_index),
                "food_item_id": _food_id(blueprint, food_index),
                "label": f"fixture-serving-{serving_index + 1}",
                "quantity": Decimal(serving_index + 1),
                "unit": f"fixture-unit-{serving_index + 1}",
                "gram_weight": Decimal(100 * (serving_index + 1)),
                "is_default": serving_index == 0,
                "source": "recipe" if is_recipe else "manual",
                "confidence": Decimal("1.0000"),
                "is_user_confirmed": True,
            }


def _nutrient_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    definitions = NUTRIENT_CATALOG[: blueprint.profile.nutrients_per_food]
    for food_index in range(blueprint.profile.food_count):
        is_recipe = food_index < blueprint.profile.recipe_count
        for nutrient_index, definition in enumerate(definitions):
            yield {
                "id": _nutrient_row_id(blueprint, food_index, nutrient_index),
                "food_item_id": _food_id(blueprint, food_index),
                "nutrient_id": definition.id,
                "amount": Decimal(nutrient_index + 1),
                "unit": definition.default_unit,
                "basis": "per_serving",
                "data_status": "known",
                "confidence": Decimal("1.0000"),
                "source": "recipe" if is_recipe else "manual",
                "is_user_confirmed": True,
                "original_amount": None,
                "original_unit": None,
                "original_text": None,
                "created_at": _FIXED_TIMESTAMP,
                "updated_at": _FIXED_TIMESTAMP,
            }


def _recipe_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    owner_id = _owner_id(blueprint)
    for recipe_index in range(blueprint.profile.recipe_count):
        disposition = blueprint.disposition_for(recipe_index)
        yield {
            "id": _recipe_id(blueprint, recipe_index),
            "food_item_id": _food_id(blueprint, recipe_index),
            "user_id": owner_id,
            "serving_count": Decimal(4),
            "final_yield_quantity": Decimal(400),
            "final_yield_unit": "g",
            "instructions": (
                "phase5c-fixture-unrepresentable-instructions"
                if disposition == "quarantine"
                else None
            ),
            "created_at": _FIXED_TIMESTAMP,
            "updated_at": _FIXED_TIMESTAMP,
        }


def _ingredient_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    owner_manual_count = blueprint.profile.food_count - blueprint.profile.recipe_count - 1
    for recipe_index, ingredient_count in enumerate(blueprint.ingredient_counts):
        disposition = blueprint.disposition_for(recipe_index)
        dependencies = blueprint.dependencies_for(recipe_index)
        for position in range(ingredient_count):
            if position < len(dependencies):
                food_index = dependencies[position]
            elif disposition == "block" and position == 0:
                food_index = blueprint.profile.recipe_count
            else:
                owner_offset = (
                    blueprint.seed + recipe_index * 1_315_423_911 + position * 2_654_435_761
                ) % owner_manual_count
                food_index = blueprint.profile.recipe_count + 1 + owner_offset
            amount = Decimal(1 + ((recipe_index + position) % 3))
            yield {
                "id": _fixture_uuid(blueprint, "ingredient", recipe_index, position),
                "recipe_id": _recipe_id(blueprint, recipe_index),
                "ingredient_food_item_id": _food_id(blueprint, food_index),
                "quantity": amount,
                "unit": "serving",
                "serving_definition_id": _serving_id(blueprint, food_index, 0),
                "gram_amount": amount * Decimal(100),
                "preparation_note": None,
                "sort_order": position,
            }


def _owner_manual_food_index(blueprint: PerformanceFixtureBlueprint, record_index: int) -> int:
    owner_manual_count = blueprint.profile.food_count - blueprint.profile.recipe_count - 1
    offset = (blueprint.seed + record_index * 2_654_435_761) % owner_manual_count
    return blueprint.profile.recipe_count + 1 + offset


def _daily_log_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    owner_id = _owner_id(blueprint)
    for record_index in range(blueprint.profile.daily_log_count):
        food_index = _owner_manual_food_index(blueprint, record_index)
        yield {
            "id": _fixture_uuid(blueprint, "daily-log", record_index),
            "user_id": owner_id,
            "food_item_id": _food_id(blueprint, food_index),
            "logged_date": _FIXED_LOG_DATE + timedelta(days=record_index % 366),
            "meal_type": "fixture",
            "amount_quantity": Decimal(1),
            "amount_unit": "serving",
            "serving_definition_id": _serving_id(blueprint, food_index, 0),
            "gram_amount": Decimal(100),
            "package_fraction": None,
            "notes": None,
            "created_at": _FIXED_TIMESTAMP,
            "updated_at": _FIXED_TIMESTAMP,
        }


def _daily_snapshot_rows(
    blueprint: PerformanceFixtureBlueprint,
) -> Iterator[dict[str, Any]]:
    calories = NUTRIENT_CATALOG[0]
    for record_index in range(blueprint.profile.daily_log_count):
        food_index = _owner_manual_food_index(blueprint, record_index)
        yield {
            "id": _fixture_uuid(blueprint, "daily-snapshot", record_index),
            "daily_log_id": _fixture_uuid(blueprint, "daily-log", record_index),
            "source_food_item_id": _food_id(blueprint, food_index),
            "source_food_nutrient_id": _nutrient_row_id(blueprint, food_index, 0),
            "serving_definition_id": _serving_id(blueprint, food_index, 0),
            "nutrient_id": calories.id,
            "amount": Decimal(1),
            "unit": calories.default_unit,
            "data_status": "known",
            "consumed_amount_quantity": Decimal(1),
            "consumed_amount_unit": "serving",
            "consumed_gram_amount": Decimal(100),
            "consumed_package_fraction": None,
            "calculation_metadata": {"fixture_generator_version": FIXTURE_GENERATOR_VERSION},
        }


def _ocr_rows(blueprint: PerformanceFixtureBlueprint) -> Iterator[dict[str, Any]]:
    owner_id = _owner_id(blueprint)
    for record_index in range(blueprint.profile.ocr_record_count):
        yield {
            "id": _fixture_uuid(blueprint, "ocr-scan", record_index),
            "user_id": owner_id,
            "image_metadata": {"fixture": True},
            "ocr_engine": "phase5c-fixture-engine-v1",
            "raw_ocr_payload": {"fixture_generator_version": FIXTURE_GENERATOR_VERSION},
            "full_text": "phase5c deterministic fixture text",
            "created_at": _FIXED_TIMESTAMP,
        }


def _parse_result_rows(
    blueprint: PerformanceFixtureBlueprint,
) -> Iterator[dict[str, Any]]:
    for record_index in range(blueprint.profile.ocr_record_count):
        food_index = _owner_manual_food_index(blueprint, record_index)
        yield {
            "id": _fixture_uuid(blueprint, "parse-result", record_index),
            "ocr_scan_id": _fixture_uuid(blueprint, "ocr-scan", record_index),
            "parser_version": "phase5c-fixture-parser-v1",
            "status": "confirmed",
            "diagnostics": None,
            "parsed_payload": {"fixture_generator_version": FIXTURE_GENERATOR_VERSION},
            "created_food_item_id": _food_id(blueprint, food_index),
            "created_at": _FIXED_TIMESTAMP,
        }


def _expected_table_counts(
    blueprint: PerformanceFixtureBlueprint,
) -> dict[str, int]:
    return {
        "users": 2,
        "food_items": blueprint.profile.food_count,
        "food_sources": 0,
        "serving_definitions": (blueprint.profile.food_count * blueprint.profile.servings_per_food),
        "food_nutrients": (blueprint.profile.food_count * blueprint.profile.nutrients_per_food),
        "recipes": blueprint.profile.recipe_count,
        "recipe_ingredients": sum(blueprint.ingredient_counts),
        "daily_logs": blueprint.profile.daily_log_count,
        "daily_log_nutrient_snapshots": blueprint.profile.daily_log_count,
        "ocr_scans": blueprint.profile.ocr_record_count,
        "parse_results": blueprint.profile.ocr_record_count,
        "parser_corrections": 0,
    }


def _require_clean_legacy_source(connection: Connection) -> None:
    if connection.scalar(text("SELECT current_schema()")) != "public":
        raise PerformanceFixtureError(
            "Performance fixture target must use the public source schema"
        )
    actual_tables = frozenset(
        connection.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            )
        ).all()
    )
    if actual_tables != _EXPECTED_SOURCE_TABLES:
        raise PerformanceFixtureError(
            "Performance fixture target has an unsupported source schema"
        )
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != _SUPPORTED_SOURCE_REVISION:
        raise PerformanceFixtureError(
            "Performance fixture target must be at 0003_usda_source_identity"
        )
    catalog_ids = tuple(
        connection.scalars(text("SELECT id FROM nutrients ORDER BY display_order, id")).all()
    )
    expected_catalog_ids = tuple(
        row.id for row in sorted(NUTRIENT_CATALOG, key=lambda item: (item.display_order, item.id))
    )
    if catalog_ids != expected_catalog_ids:
        raise PerformanceFixtureError("Performance fixture nutrient catalog is unsupported")
    populated = [
        table_name
        for table_name in _SEEDED_TABLES
        if connection.scalar(text(f'SELECT EXISTS (SELECT 1 FROM "{table_name}" LIMIT 1)'))
    ]
    if populated:
        raise PerformanceFixtureError("Performance fixture target contains application rows")
