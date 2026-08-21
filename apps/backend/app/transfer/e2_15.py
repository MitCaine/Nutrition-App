"""E2-15 canonical transfer package boundary.

This module owns only the one approved PostgreSQL-to-SQLite handoff format.
It is deliberately not a generic migration, archive, or synchronization API.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping, Sequence
from uuid import NAMESPACE_DNS, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, ValidationError

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.ocr.confirmation_schemas import validate_persisted_trace_snapshot
from app.schemas.food import FoodResponse
from app.schemas.recipe import RecipePublishResponse, RecipeResponse

_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = (
    _ROOT / "packages" / "shared-contracts" / "e2-15" / "transfer-contract.json"
)
SOURCE_SCHEMA_PATH = (
    _ROOT / "packages" / "shared-contracts" / "e2-15" / "source-schema.json"
)


class TransferPackageError(RuntimeError):
    """Fail closed when transfer bytes or package values violate E2-15."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _DuplicateKey(ValueError):
    pass


def _load_contract() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:  # pragma: no cover - install defect
        raise RuntimeError("The frozen E2-15 transfer contract is unavailable.") from error
    if not isinstance(value, dict):  # pragma: no cover - install defect
        raise RuntimeError("The frozen E2-15 transfer contract is invalid.")
    return value


def _load_source_schema() -> dict[str, Any]:
    try:
        value = json.loads(SOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:  # pragma: no cover - install defect
        raise RuntimeError("The frozen E2-15 source schema is unavailable.") from error
    if not isinstance(value, dict):  # pragma: no cover - install defect
        raise RuntimeError("The frozen E2-15 source schema is invalid.")
    return value


CONTRACT = _load_contract()
SOURCE_SCHEMA = _load_source_schema()
MAXIMUM_TRANSFER_BYTES = int(CONTRACT["maximum_bytes"])
SECTION_NAMES = tuple(str(section["name"]) for section in CONTRACT["sections"])
SECTION_CONTRACTS = {
    str(section["name"]): section for section in CONTRACT["sections"]
}
NUTRIENT_IDS = frozenset(item.id for item in NUTRIENT_CATALOG)
_MAXIMUM_SAFE_INTEGER = 9_007_199_254_740_991
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$")
_RESPONSE_DECIMAL = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")
_DECIMAL_SPECS = {
    "numeric_14_6": (14, 6),
    "numeric_8_3": (8, 3),
    "numeric_5_4": (5, 4),
}
_TOP_LEVEL_KEYS = {
    "codec_version",
    "exported_at",
    "format",
    "format_version",
    "idempotency_policy",
    "nutrient_catalog_digest",
    "overall_digest",
    "owner_id",
    "qualification",
    "sections",
    "source",
    "target",
}
_E2_13_MAX_TRACE_BYTES = 48_000


def _json_number(value: int | float) -> str:
    if isinstance(value, bool):  # bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, int):
        if abs(value) > _MAXIMUM_SAFE_INTEGER:
            raise ValueError("JSON integer exceeds the cross-runtime safe range")
        return str(value)
    if not math.isfinite(value):
        raise ValueError("Non-finite JSON numbers are unsupported")
    if value == 0:
        return "0"
    absolute = abs(value)
    spelling = repr(value).lower()
    if 1e-6 <= absolute < 1e21:
        if "e" in spelling:
            rendered = format(Decimal(spelling), "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
        else:
            rendered = spelling[:-2] if spelling.endswith(".0") else spelling
        return rendered
    if "e" not in spelling:
        spelling = format(value, ".15e")
    mantissa, exponent = spelling.split("e", 1)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    exponent_value = int(exponent)
    sign = "+" if exponent_value >= 0 else ""
    return f"{mantissa}e{sign}{exponent_value}"


def _render_canonical_json(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _json_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_render_canonical_json(item) for item in value) + "]"
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Canonical JSON object keys must be strings")
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{_render_canonical_json(value[key])}"
            for key in sorted(value)
        ) + "}"
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


SCHEMA_CONTRACT_DIGEST = hashlib.sha256(
    _render_canonical_json(SOURCE_SCHEMA).encode("utf-8")
).hexdigest()
if SCHEMA_CONTRACT_DIGEST != CONTRACT["source"]["schema_descriptor_digest"]:  # pragma: no cover - install defect
    raise RuntimeError("The frozen E2-15 source schema digest does not match its contract.")


def canonical_transfer_json(value: Any) -> str:
    """Render the exact compact, sorted-key JSON spelling used by E2-02."""

    try:
        return _render_canonical_json(value)
    except (TypeError, ValueError) as error:
        raise TransferPackageError(
            "invalid_canonical_value",
            "Transfer value cannot be represented as canonical JSON.",
        ) from error


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_transfer_json(value).encode("utf-8")).hexdigest()


def canonicalize_transfer_scalar(kind: str, value: Any) -> Any:
    """Convert one source scalar to the fixed E2-15 package representation."""

    if kind.startswith("nullable_"):
        if value is None:
            return None
        kind = kind.removeprefix("nullable_")
    if kind == "uuid":
        try:
            return str(value if isinstance(value, UUID) else UUID(str(value)))
        except (TypeError, ValueError, AttributeError) as error:
            raise TransferPackageError("invalid_record_value", "Source UUID is invalid.") from error
    if kind == "instant":
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise ValueError("instant is not UTC")
            parsed = parsed.astimezone(timezone.utc)
            timespec = "seconds" if parsed.microsecond == 0 else "microseconds"
            return parsed.isoformat(timespec=timespec).replace("+00:00", "Z")
        except (TypeError, ValueError, AttributeError) as error:
            raise TransferPackageError("invalid_record_value", "Source instant is invalid.") from error
    if kind == "date":
        try:
            parsed_date = value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))
            return parsed_date.isoformat()
        except (TypeError, ValueError) as error:
            raise TransferPackageError("invalid_record_value", "Source date is invalid.") from error
    if kind in _DECIMAL_SPECS:
        precision, scale = _DECIMAL_SPECS[kind]
        try:
            with localcontext() as context:
                context.prec = max(precision + scale + 2, 28)
                decimal_value = Decimal(str(value)).quantize(
                    Decimal(1).scaleb(-scale),
                    rounding=ROUND_HALF_UP,
                )
            rendered = format(decimal_value, f".{scale}f")
            _validate_decimal(rendered, kind)
            return rendered
        except (ArithmeticError, ValueError) as error:
            raise TransferPackageError("invalid_record_value", "Source decimal is invalid.") from error
    if kind == "response_decimal":
        if not isinstance(value, (str, Decimal)):
            raise TransferPackageError("invalid_record_value", "Source response decimal is invalid.")
        rendered = format(value, "f") if isinstance(value, Decimal) else value
        if _RESPONSE_DECIMAL.fullmatch(rendered) is None:
            raise TransferPackageError("invalid_record_value", "Source response decimal is invalid.")
        whole, separator, fraction = rendered.partition(".")
        whole = whole.lstrip("0") or "0"
        return whole + (separator + fraction if separator else "")
    if kind == "json_document":
        if value is None:
            raise TransferPackageError(
                "invalid_record_value",
                "Source non-null JSON is SQL NULL.",
            )
        if isinstance(value, str):
            try:
                value = json.loads(value, object_pairs_hook=_object_without_duplicate_keys)
            except (json.JSONDecodeError, _DuplicateKey) as error:
                raise TransferPackageError("invalid_record_value", "Source JSON is invalid.") from error
        return canonical_transfer_json(value)
    if kind in {"nonnegative_integer", "positive_integer"}:
        _validate_value(value, kind)
        return value
    if kind == "boolean":
        _validate_value(value, kind)
        return value
    if kind in {"text", "time_zone", "sha256", "nutrient_id"} or kind in CONTRACT["enums"]:
        _validate_value(value, kind)
        return value
    raise TransferPackageError("invalid_record_value", "Source scalar kind is unsupported.")


def sort_transfer_records(
    records: Sequence[Mapping[str, Any]],
    primary_key: Sequence[str],
) -> list[dict[str, Any]]:
    """Sort independently of database collation by canonical PK tuple."""

    copied = [dict(record) for record in records]
    try:
        return sorted(copied, key=lambda record: tuple(str(record[column]) for column in primary_key))
    except KeyError as error:
        raise TransferPackageError("invalid_record_shape", "Transfer primary key is missing.") from error


def build_section(name: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if name not in SECTION_CONTRACTS:
        raise TransferPackageError("unsupported_section", "Transfer section is unsupported.")
    copied = [dict(record) for record in records]
    preimage = {"count": len(copied), "name": name, "records": copied}
    return {**preimage, "digest": canonical_digest(preimage)}


def build_daily_totals_section(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    copied = [dict(record) for record in records]
    preimage = {"count": len(copied), "name": "daily_totals", "records": copied}
    return {**preimage, "digest": canonical_digest(preimage)}


def with_overall_digest(document: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(document))
    result.pop("overall_digest", None)
    result["overall_digest"] = canonical_digest(result)
    return result


def serialize_transfer_document(document: Mapping[str, Any]) -> bytes:
    completed = with_overall_digest(document)
    rendered = canonical_transfer_json(completed).encode("utf-8")
    if len(rendered) > MAXIMUM_TRANSFER_BYTES:
        raise TransferPackageError(
            "package_too_large",
            "Transfer package exceeds the 64 MiB maximum.",
        )
    return rendered


def _object_without_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def parse_transfer_document(document: bytes) -> dict[str, Any]:
    """Parse only exact E2-02 canonical bytes under the fixed size bound."""

    if not isinstance(document, bytes):
        raise TypeError("Transfer document must be bytes.")
    if len(document) > MAXIMUM_TRANSFER_BYTES:
        raise TransferPackageError(
            "package_too_large",
            "Transfer package exceeds the 64 MiB maximum.",
        )
    if not document or document.startswith(b"\xef\xbb\xbf"):
        raise TransferPackageError(
            "noncanonical_package",
            "Transfer package is not canonical UTF-8 JSON.",
        )
    try:
        text_value = document.decode("utf-8")
        value = json.loads(
            text_value,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey, ValueError):
        raise TransferPackageError(
            "noncanonical_package",
            "Transfer package is not canonical UTF-8 JSON.",
        ) from None
    if not isinstance(value, dict):
        raise TransferPackageError(
            "invalid_package_shape",
            "Transfer package must be a JSON object.",
        )
    if canonical_transfer_json(value).encode("utf-8") != document:
        raise TransferPackageError(
            "noncanonical_package",
            "Transfer package is not in canonical byte form.",
        )
    return value


def _invalid(code: str, message: str) -> TransferPackageError:
    return TransferPackageError(code, message)


def _require_exact_keys(value: Any, keys: set[str], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _invalid(code, "Transfer object has an unsupported key set.")
    return value


def _validate_uuid(value: Any) -> None:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ValueError("invalid UUID")
    if str(UUID(value)) != value:
        raise ValueError("noncanonical UUID")


def _validate_instant(value: Any) -> None:
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        raise ValueError("invalid instant")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("instant is not UTC")
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") == value:
        return
    if parsed.microsecond == 0 and parsed.isoformat(timespec="seconds").replace("+00:00", "Z") == value:
        return
    raise ValueError("noncanonical instant")


def _validate_date(value: Any) -> None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError("invalid date")
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("noncanonical date")


def _validate_time_zone(value: Any) -> None:
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > 255:
        raise ValueError("invalid time zone")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        raise ValueError("invalid time zone") from None


def _validate_decimal(value: Any, spec_name: str) -> None:
    precision, scale = _DECIMAL_SPECS[spec_name]
    if not isinstance(value, str):
        raise ValueError("decimal is not text")
    match = re.fullmatch(rf"(0|[1-9]\d*)\.(\d{{{scale}}})", value)
    if match is None or len(match.group(1)) > precision - scale:
        raise ValueError("decimal is not fixed scale")


def _parse_json_document(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        raise ValueError("JSON document is not text")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (json.JSONDecodeError, _DuplicateKey, ValueError):
        raise ValueError("JSON document is malformed") from None
    if canonical_transfer_json(parsed) != value:
        raise ValueError("JSON document is not canonical")
    return parsed


def _validate_value(value: Any, kind: str) -> None:
    if kind.startswith("nullable_"):
        if value is None:
            return
        kind = kind.removeprefix("nullable_")
    if kind == "uuid":
        _validate_uuid(value)
    elif kind == "instant":
        _validate_instant(value)
    elif kind == "date":
        _validate_date(value)
    elif kind == "time_zone":
        _validate_time_zone(value)
    elif kind in _DECIMAL_SPECS:
        _validate_decimal(value, kind)
    elif kind == "response_decimal":
        if not isinstance(value, str) or _RESPONSE_DECIMAL.fullmatch(value) is None:
            raise ValueError("invalid response decimal")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("invalid boolean")
    elif kind in {"nonnegative_integer", "positive_integer"}:
        minimum = 0 if kind == "nonnegative_integer" else 1
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
            or value > _MAXIMUM_SAFE_INTEGER
        ):
            raise ValueError("invalid integer")
    elif kind == "sha256":
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError("invalid digest")
    elif kind == "json_document":
        _parse_json_document(value)
    elif kind == "nutrient_id":
        if value not in NUTRIENT_IDS:
            raise ValueError("invalid nutrient")
    elif kind in CONTRACT["enums"]:
        if value not in CONTRACT["enums"][kind]:
            raise ValueError("invalid enum")
    elif kind == "text":
        if not isinstance(value, str):
            raise ValueError("invalid text")
    else:  # pragma: no cover - frozen-contract installation defect
        raise RuntimeError(f"Unsupported transfer value kind: {kind}")


def _primary_key(record: Mapping[str, Any], columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(record[column]) for column in columns)


def _validate_records(
    records: Any,
    *,
    columns: Sequence[Sequence[str]],
    primary_key: Sequence[str],
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise _invalid("invalid_section_shape", "Transfer section records must be an array.")
    expected_keys = {column[0] for column in columns}
    previous: tuple[str, ...] | None = None
    seen: set[tuple[str, ...]] = set()
    validated: list[dict[str, Any]] = []
    for raw_record in records:
        record = _require_exact_keys(raw_record, expected_keys, code="invalid_record_shape")
        try:
            for column_name, kind in columns:
                _validate_value(record[column_name], kind)
        except (TypeError, ValueError, TransferPackageError):
            raise _invalid("invalid_record_value", "Transfer record contains an invalid value.") from None
        key = _primary_key(record, primary_key)
        if key in seen:
            raise _invalid("duplicate_primary_key", "Transfer section contains a duplicate primary key.")
        if previous is not None and key <= previous:
            raise _invalid("record_order_invalid", "Transfer section records are not canonically ordered.")
        previous = key
        seen.add(key)
        validated.append(record)
    return validated


def _validate_section(section: Any, contract: Mapping[str, Any]) -> dict[str, Any]:
    value = _require_exact_keys(
        section,
        {"count", "digest", "name", "records"},
        code="invalid_section_shape",
    )
    if value["name"] != contract["name"]:
        raise _invalid("section_order_invalid", "Transfer section order is invalid.")
    if (
        isinstance(value["count"], bool)
        or not isinstance(value["count"], int)
        or value["count"] < 0
        or value["count"] > _MAXIMUM_SAFE_INTEGER
        or not isinstance(value["records"], list)
        or value["count"] != len(value["records"])
    ):
        raise _invalid("section_count_invalid", "Transfer section count is invalid.")
    _validate_records(
        value["records"],
        columns=contract["columns"],
        primary_key=contract["primary_key"],
    )
    expected = canonical_digest(
        {"count": value["count"], "name": value["name"], "records": value["records"]}
    )
    if value["digest"] != expected:
        raise _invalid("section_digest_invalid", "Transfer section digest is invalid.")
    return value


def _validate_daily_totals(value: Any) -> dict[str, Any]:
    contract = CONTRACT["qualification"]
    section = _require_exact_keys(
        value,
        {"count", "digest", "name", "records"},
        code="invalid_qualification_shape",
    )
    if section["name"] != "daily_totals":
        raise _invalid("invalid_qualification_shape", "Daily totals qualification name is invalid.")
    if (
        isinstance(section["count"], bool)
        or not isinstance(section["count"], int)
        or section["count"] != len(section["records"])
    ):
        raise _invalid("qualification_count_invalid", "Daily totals count is invalid.")
    _validate_records(
        section["records"],
        columns=contract["daily_totals_columns"],
        primary_key=contract["daily_totals_primary_key"],
    )
    if section["digest"] != canonical_digest(
        {"count": section["count"], "name": section["name"], "records": section["records"]}
    ):
        raise _invalid("qualification_digest_invalid", "Daily totals digest is invalid.")
    return section


def _section_records(package: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {section["name"]: section["records"] for section in package["sections"]}


def _validate_owner_graph(package: Mapping[str, Any]) -> None:
    owner_id = package["owner_id"]
    records = _section_records(package)
    if len(records["users"]) != 1 or records["users"][0]["id"] != owner_id:
        raise _invalid("owner_graph_invalid", "Transfer package must contain exactly one selected owner.")
    if len(records["user_profiles"]) != 1 or records["user_profiles"][0]["user_id"] != owner_id:
        raise _invalid("owner_graph_invalid", "Transfer package must contain the selected owner's profile.")

    owner_sections = {
        "food_favorites",
        "recipes",
        "recipe_ingredients",
        "recipe_publication_revisions",
        "daily_logs",
        "daily_log_day_completions",
        "ocr_nutrition_confirmation_traces",
        "nutrition_targets",
        "create_operation_idempotency",
    }
    for name in owner_sections:
        if any(row["user_id"] != owner_id for row in records[name]):
            raise _invalid("owner_graph_invalid", "Transfer package contains a cross-owner row.")
    if any(row["user_id"] != owner_id for row in records["food_items"]):
        raise _invalid("owner_graph_invalid", "Transfer package contains a cross-owner Food.")

    foods = {row["id"]: row for row in records["food_items"]}
    servings = {row["id"]: row for row in records["serving_definitions"]}
    for serving in servings.values():
        if "reference_quantity" not in serving:
            continue  # frozen v1 rows predate the explicit reference measurement
        parts = (
            serving["reference_quantity"],
            serving["reference_unit"],
            serving["reference_gram_weight"],
        )
        if any(value is not None for value in parts):
            if any(value is None for value in parts):
                raise _invalid(
                    "owner_graph_invalid",
                    "Serving reference measurement is incomplete.",
                )
            if (
                Decimal(str(serving["reference_quantity"])) <= 0
                or not str(serving["reference_unit"]).strip()
                or Decimal(str(serving["reference_gram_weight"])) <= 0
            ):
                raise _invalid(
                    "owner_graph_invalid",
                    "Serving reference measurement is invalid.",
                )
    food_nutrients = {row["id"]: row for row in records["food_nutrients"]}
    recipes = {row["id"]: row for row in records["recipes"]}
    revisions = {row["id"]: row for row in records["recipe_publication_revisions"]}
    amounts = {row["id"]: row for row in records["recipe_publication_amount_definitions"]}
    logs = {row["id"]: row for row in records["daily_logs"]}
    logged_dates = {
        row["logged_date"] for row in logs.values()
    }
    completion_dates = {
        row["logged_date"]
        for row in records["daily_log_day_completions"]
    }
    if not completion_dates.issubset(logged_dates):
        raise _invalid(
            "owner_graph_invalid",
            "Complete assertion references a date without a transferred Daily Log.",
        )

    linked_recipes = {
        row["published_food_item_id"]: row
        for row in recipes.values()
        if row["published_food_item_id"] is not None
    }
    for food in foods.values():
        if food["source_type"] == "manual" and food["source_id"] is not None:
            try:
                source_id = str(UUID(food["source_id"]))
            except (TypeError, ValueError, AttributeError):
                raise _invalid("owner_graph_invalid", "Manual duplicate provenance is malformed.") from None
            if source_id != food["source_id"] or source_id == food["id"] or source_id not in foods:
                raise _invalid("owner_graph_invalid", "Manual duplicate provenance is not owner-local.")
        linked = linked_recipes.get(food["id"])
        has_projection_marker = (
            food["is_recipe"]
            or food["source_type"] == "recipe"
            or food["recipe_publication_revision_id"] is not None
            or linked is not None
        )
        if has_projection_marker and (
            linked is None
            or food["is_recipe"] is not True
            or food["source_type"] != "recipe"
            or food["source_id"] != linked["id"]
            or linked["active_publication_revision_id"] is None
            or food["recipe_publication_revision_id"] != linked["active_publication_revision_id"]
        ):
            raise _invalid("owner_graph_invalid", "Recipe projection links are incoherent.")
    for recipe in recipes.values():
        projection_id = recipe["published_food_item_id"]
        revision_id = recipe["active_publication_revision_id"]
        if (projection_id is None) != (revision_id is None):
            raise _invalid("owner_graph_invalid", "Recipe publication links are not paired.")
        if projection_id is not None and (
            projection_id not in foods
            or revision_id not in revisions
            or revisions[revision_id]["recipe_id"] != recipe["id"]
            or revisions[revision_id]["user_id"] != owner_id
        ):
            raise _invalid("owner_graph_invalid", "Recipe publication links are incoherent.")

    for name in ("food_sources", "food_nutrients", "serving_definitions"):
        if any(row["food_item_id"] not in foods for row in records[name]):
            raise _invalid("owner_graph_invalid", "Food child references an excluded Food.")
    for favorite in records["food_favorites"]:
        if favorite["food_item_id"] not in foods:
            raise _invalid("owner_graph_invalid", "Favorite references an excluded Food.")
    for trace in records["ocr_nutrition_confirmation_traces"]:
        if trace["food_item_id"] not in foods:
            raise _invalid("owner_graph_invalid", "OCR trace references an excluded Food.")
        _validate_ocr_trace(trace)
    for revision in revisions.values():
        if revision["recipe_id"] not in recipes or revision["user_id"] != owner_id:
            raise _invalid("owner_graph_invalid", "Publication revision references an excluded Recipe.")
    for row in records["recipe_publication_amount_definitions"] + records["recipe_publication_nutrients"]:
        if row["revision_id"] not in revisions:
            raise _invalid("owner_graph_invalid", "Publication child references an excluded revision.")
    for ingredient in records["recipe_ingredients"]:
        if ingredient["recipe_id"] not in recipes or ingredient["food_item_id"] not in foods:
            raise _invalid("owner_graph_invalid", "Recipe ingredient references an excluded owner resource.")
        serving_id = ingredient["serving_definition_id"]
        if serving_id is not None and (
            serving_id not in servings or servings[serving_id]["food_item_id"] != ingredient["food_item_id"]
        ):
            raise _invalid("owner_graph_invalid", "Recipe ingredient serving does not belong to its Food.")
    for log in logs.values():
        if log["food_item_id"] not in foods:
            raise _invalid("owner_graph_invalid", "Daily Log references an excluded Food.")
        serving_id = log["serving_definition_id"]
        if serving_id is not None and (
            serving_id not in servings or servings[serving_id]["food_item_id"] != log["food_item_id"]
        ):
            raise _invalid("owner_graph_invalid", "Daily Log serving does not belong to its Food.")
        revision_id = log["recipe_publication_revision_id"]
        amount_id = log["recipe_publication_amount_definition_id"]
        if (revision_id is None) != (amount_id is None):
            raise _invalid("owner_graph_invalid", "Daily Log publication links are not paired.")
        if revision_id is not None and (
            revision_id not in revisions
            or amount_id not in amounts
            or amounts[amount_id]["revision_id"] != revision_id
            or revisions[revision_id]["user_id"] != owner_id
        ):
            raise _invalid("owner_graph_invalid", "Daily Log publication links are incoherent.")
    for snapshot in records["daily_log_nutrient_snapshots"]:
        log = logs.get(snapshot["daily_log_id"])
        if log is None or snapshot["source_food_item_id"] != log["food_item_id"]:
            raise _invalid("owner_graph_invalid", "Daily Log snapshot does not belong to its Log Food.")
        nutrient_id = snapshot["source_food_nutrient_id"]
        if nutrient_id is not None:
            nutrient = food_nutrients.get(nutrient_id)
            if nutrient is None or (
                nutrient["food_item_id"] != snapshot["source_food_item_id"]
                or nutrient["nutrient_id"] != snapshot["nutrient_id"]
            ):
                raise _invalid("owner_graph_invalid", "Snapshot nutrient provenance is incoherent.")
        serving_id = snapshot["serving_definition_id"]
        if serving_id is not None and (
            serving_id not in servings
            or servings[serving_id]["food_item_id"] != snapshot["source_food_item_id"]
        ):
            raise _invalid("owner_graph_invalid", "Snapshot serving provenance is incoherent.")
    for food in foods.values():
        if food["source_type"] == "manual" and food["source_id"] is not None:
            try:
                source_uuid = str(UUID(food["source_id"]))
            except ValueError:
                continue
            if source_uuid == food["source_id"] and source_uuid not in foods:
                raise _invalid("owner_graph_invalid", "Duplicate Food source is not owner-reachable.")
    _validate_idempotency_policy(package, records)


_FORBIDDEN_TRACE_REFERENCE = re.compile(
    r"(?:file|content|ph|assets-library)://|/(?:private|var|users)/",
    re.IGNORECASE,
)


def _walk_json(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from _walk_json(item)


def _validate_ocr_trace(row: Mapping[str, Any]) -> None:
    trace = _parse_json_document(row["trace_snapshot"])
    if not isinstance(trace, dict) or set(trace) != {
        "schema_version",
        "field_decisions",
        "unknown_nutrients",
        "parser_warning_codes",
    }:
        raise _invalid("ocr_trace_invalid", "OCR trace has an unsupported bounded shape.")
    if trace["schema_version"] != row["schema_version"]:
        raise _invalid("ocr_trace_invalid", "OCR trace schema is inconsistent.")
    forbidden = set(CONTRACT["privacy"]["forbidden_ocr_trace_keys"])
    for key, item in _walk_json(trace):
        if key is not None and key.casefold() in forbidden:
            raise _invalid("privacy_violation", "OCR trace contains forbidden source data.")
        if isinstance(item, str) and _FORBIDDEN_TRACE_REFERENCE.search(item):
            raise _invalid("privacy_violation", "OCR trace contains a forbidden local reference.")
    # Preserve E2-13's established authority exactly: compact Python JSON with
    # the default ensure_ascii=True behavior, including Unicode escape bytes.
    trace_bytes = len(json.dumps(trace, separators=(",", ":")).encode())
    if trace_bytes > _E2_13_MAX_TRACE_BYTES:
        raise _invalid("ocr_trace_invalid", "OCR trace exceeds the established bound.")
    try:
        validate_persisted_trace_snapshot(trace)
    except (TypeError, ValueError):
        raise _invalid("ocr_trace_invalid", "OCR trace violates the persisted E2-13 contract.") from None


def _validate_idempotency_policy(
    package: Mapping[str, Any],
    records: Mapping[str, list[dict[str, Any]]],
) -> None:
    receipts = records["create_operation_idempotency"]
    copied = set(CONTRACT["idempotency"]["copied_operations"])
    copied_count = sum(row["operation"] in copied for row in receipts)
    translated_count = sum(row["operation"] == "log.update" for row in receipts)
    reconstructed_count = sum(row["operation"] == "log.create" for row in receipts)
    expected_reconstructed = sum(row["client_request_id"] is not None for row in records["daily_logs"])
    policy = package["idempotency_policy"]
    if (
        policy["copied_portable_count"] != copied_count
        or policy["translated_log_update_count"] != translated_count
        or policy["reconstructed_log_create_count"] != reconstructed_count
        or reconstructed_count != expected_reconstructed
    ):
        raise _invalid("idempotency_policy_invalid", "Transfer receipt policy counts are invalid.")
    if any(row["operation"] == "log.delete" for row in receipts):
        raise _invalid("idempotency_policy_invalid", "Delete receipts cannot be imported.")
    by_log_request = {
        row["client_request_id"]: row
        for row in records["daily_logs"]
        if row["client_request_id"] is not None
    }
    for receipt in receipts:
        operation = receipt["operation"]
        try:
            snapshot = _parse_json_document(receipt["response_snapshot"])
        except ValueError:
            raise _invalid("idempotency_policy_invalid", "Receipt snapshot is malformed.") from None
        if operation == "log.create":
            log = by_log_request.get(receipt["client_request_id"])
            expected_id = str(uuid5(
                NAMESPACE_DNS,
                f"nutrition-app:e2-15:log.create:{package['owner_id']}:{receipt['client_request_id']}",
            ))
            if (
                log is None
                or receipt["id"] != expected_id
                or receipt["resource_id"] != log["id"]
                or receipt["request_fingerprint"] != log["client_request_fingerprint"]
                or receipt["created_at"] != log["created_at"]
                or receipt["completed_at"] != log["created_at"]
                or not isinstance(snapshot, dict)
                or snapshot.get("id") != log["id"]
            ):
                raise _invalid("idempotency_policy_invalid", "Reconstructed create receipt is invalid.")
        elif operation == "log.update":
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != {"kind", "source_logged_date", "destination_logged_date", "result"}
                or snapshot["kind"] != "log.update"
            ):
                raise _invalid("idempotency_policy_invalid", "Translated update receipt is invalid.")
            result = _exact_response_snapshot(snapshot["result"], _LocalDailyLogResponse)
            if result["id"] != receipt["resource_id"]:
                raise _invalid("idempotency_policy_invalid", "Translated update receipt is invalid.")
            try:
                _validate_date(snapshot["source_logged_date"])
                _validate_date(snapshot["destination_logged_date"])
            except ValueError:
                raise _invalid("idempotency_policy_invalid", "Translated update dates are invalid.") from None
        elif operation in copied:
            validate_portable_receipt(
                receipt,
                snapshot,
                records,
                package["owner_id"],
            )


def _exact_response_snapshot(
    snapshot: Any,
    model: type[BaseModel],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
    try:
        validated = model.model_validate(snapshot).model_dump(mode="json")
    except ValidationError:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.") from None
    if validated != snapshot:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot has an unsupported shape.")
    return validated




def _validate_food_response_reference_measurements(response: Mapping[str, Any]) -> None:
    for serving in response.get("serving_definitions", []):
        if not isinstance(serving, Mapping):
            raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
        reference_keys = ("reference_quantity", "reference_unit", "reference_gram_weight")
        present = [key in serving for key in reference_keys]
        if not any(present):
            continue  # Historical pre-0027 receipt snapshot.
        if not all(present):
            raise _invalid("idempotency_policy_invalid", "Receipt serving reference measurement is incomplete.")
        parts = tuple(serving[key] for key in reference_keys)
        if all(value is None for value in parts):
            continue
        if any(value is None for value in parts):
            raise _invalid("idempotency_policy_invalid", "Receipt serving reference measurement is incomplete.")
        try:
            if (
                Decimal(str(serving["reference_quantity"])) <= 0
                or not str(serving["reference_unit"]).strip()
                or Decimal(str(serving["reference_gram_weight"])) <= 0
            ):
                raise ValueError
        except (ArithmeticError, TypeError, ValueError):
            raise _invalid("idempotency_policy_invalid", "Receipt serving reference measurement is invalid.") from None


def _expand_legacy_food_reference_fields(food: Any) -> dict[str, Any]:
    if not isinstance(food, dict) or not isinstance(food.get("serving_definitions"), list):
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
    expanded = deepcopy(food)
    for serving in expanded["serving_definitions"]:
        if not isinstance(serving, dict):
            raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
        reference_keys = ("reference_quantity", "reference_unit", "reference_gram_weight")
        if any(key in serving for key in reference_keys):
            raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
        for key in reference_keys:
            serving[key] = None
    return expanded


def _exact_food_response_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
    try:
        validated = FoodResponse.model_validate(snapshot).model_dump(mode="json")
    except ValidationError:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.") from None
    if validated == snapshot:
        _validate_food_response_reference_measurements(snapshot)
        return validated

    # Receipts written before 0027 legitimately lack all three reference keys. Preserve their
    # exact replay snapshot while validating every other field through the current response model.
    expanded = _expand_legacy_food_reference_fields(snapshot)
    try:
        validated_expanded = FoodResponse.model_validate(expanded).model_dump(mode="json")
    except ValidationError:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.") from None
    if validated_expanded != expanded:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot has an unsupported shape.")
    _validate_food_response_reference_measurements(snapshot)
    return deepcopy(snapshot)


def _exact_recipe_publish_response_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.")
    try:
        validated = RecipePublishResponse.model_validate(snapshot).model_dump(mode="json")
    except ValidationError:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.") from None
    if validated == snapshot:
        _validate_food_response_reference_measurements(snapshot.get("food", {}))
        return validated

    expanded = deepcopy(snapshot)
    expanded["food"] = _expand_legacy_food_reference_fields(expanded.get("food"))
    try:
        validated_expanded = RecipePublishResponse.model_validate(expanded).model_dump(mode="json")
    except ValidationError:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot is malformed.") from None
    if validated_expanded != expanded:
        raise _invalid("idempotency_policy_invalid", "Portable receipt snapshot has an unsupported shape.")
    _validate_food_response_reference_measurements(snapshot.get("food", {}))
    return deepcopy(snapshot)


class _LocalDailyLogResponse(BaseModel):
    id: UUID
    food_item_id: UUID
    food_name_snapshot: str | None
    is_editable: bool
    source_food_available: bool
    edit_block_reason: Literal["source_food_deleted"] | None
    logged_date: date
    meal_type: str | None
    amount_quantity: Decimal
    amount_unit: Literal["serving", "g"]
    serving_definition_id: UUID | None
    gram_amount: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


def validate_portable_receipt(
    receipt: Mapping[str, Any],
    snapshot: Any,
    records: Mapping[str, Sequence[Mapping[str, Any]]],
    owner_id: str,
) -> None:
    """Validate copied receipt replay state without reconstructing mutable output."""

    operation = receipt["operation"]
    foods = {row["id"]: row for row in records["food_items"]}
    servings = {row["id"]: row for row in records["serving_definitions"]}
    recipes = {row["id"]: row for row in records["recipes"]}
    revisions = {row["id"]: row for row in records["recipe_publication_revisions"]}

    if receipt["user_id"] != owner_id:
        raise _invalid("idempotency_policy_invalid", "Portable receipt owner is invalid.")

    if operation in {"food.create_manual", "food.duplicate", "food.add_serving"}:
        response = _exact_food_response_snapshot(snapshot)
        response_food = foods.get(response["id"])
        if response_food is None:
            raise _invalid("idempotency_policy_invalid", "Portable Food receipt is not owner-reachable.")
        if (
            response_food["source_type"] != response["source_type"]
            or response_food["source_id"] != response["source_id"]
            or response_food["is_recipe"] != response["is_recipe"]
            or response_food["created_at"] != response["created_at"]
        ):
            raise _invalid("idempotency_policy_invalid", "Portable Food provenance is inconsistent.")
        if operation == "food.add_serving":
            response_servings = {
                serving["id"]: serving for serving in response["serving_definitions"]
            }
            if receipt["resource_id"] not in response_servings:
                raise _invalid("idempotency_policy_invalid", "Serving receipt resource is invalid.")
            current_serving = servings.get(receipt["resource_id"])
            if current_serving is not None and current_serving["food_item_id"] != response["id"]:
                raise _invalid("idempotency_policy_invalid", "Serving receipt owner graph is invalid.")
            return
        if receipt["resource_id"] != response["id"]:
            raise _invalid("idempotency_policy_invalid", "Food receipt resource is invalid.")
        if operation == "food.create_manual":
            if (
                response["source_type"] != "manual"
                or response["source_id"] is not None
                or response["source_kind"] != "manual"
                or response["is_recipe"] is not False
            ):
                raise _invalid("idempotency_policy_invalid", "Manual Food receipt provenance is invalid.")
            return
        source_id = response["source_id"]
        if (
            response["source_type"] != "manual"
            or response["source_kind"] != "duplicate"
            or response["is_recipe"] is not False
            or source_id == response["id"]
            or source_id not in foods
        ):
            raise _invalid("idempotency_policy_invalid", "Duplicate Food provenance is invalid.")
        return

    if operation in {"recipe.create", "recipe.duplicate"}:
        response = _exact_response_snapshot(snapshot, RecipeResponse)
        recipe = recipes.get(response["id"])
        if (
            receipt["resource_id"] != response["id"]
            or response["user_id"] != owner_id
            or recipe is None
            or recipe["created_at"] != response["created_at"]
        ):
            raise _invalid(
                "idempotency_policy_invalid",
                "Recipe result receipt resource is invalid.",
            )
        return

    if operation == "recipe.publish":
        response = _exact_recipe_publish_response_snapshot(snapshot)
        recipe_snapshot = response["recipe"]
        food_snapshot = response["food"]
        revision = revisions.get(receipt["resource_id"])
        recipe = recipes.get(recipe_snapshot["id"])
        food = foods.get(food_snapshot["id"])
        if (
            revision is None
            or revision["user_id"] != owner_id
            or revision["recipe_id"] != recipe_snapshot["id"]
            or revision["published_name"] != recipe_snapshot["name"]
            or revision["published_notes"] != recipe_snapshot["notes"]
            or recipe_snapshot["user_id"] != owner_id
            or recipe_snapshot["published_food_item_id"] != food_snapshot["id"]
            or recipe is None
            or food is None
            or food_snapshot["source_type"] != "recipe"
            or food_snapshot["source_kind"] != "recipe"
            or food_snapshot["source_id"] != recipe_snapshot["id"]
            or food_snapshot["is_recipe"] is not True
        ):
            raise _invalid("idempotency_policy_invalid", "Recipe publication receipt resource is invalid.")
        return

    raise _invalid("idempotency_policy_invalid", "Portable receipt operation is unsupported.")


def validate_transfer_package(document: bytes) -> dict[str, Any]:
    """Validate all package-local contracts before a SQLite write is acquired."""

    package = parse_transfer_document(document)
    _require_exact_keys(package, _TOP_LEVEL_KEYS, code="invalid_package_shape")
    if (
        package["format"] != CONTRACT["format"]
        or package["format_version"] != CONTRACT["format_version"]
        or package["codec_version"] != CONTRACT["codec_version"]
    ):
        raise _invalid("unsupported_package", "Transfer package version is unsupported.")
    source = _require_exact_keys(
        package["source"],
        {"postgres_major", "alembic_revision", "schema_contract", "schema_contract_digest"},
        code="invalid_package_shape",
    )
    if source != {
        "postgres_major": CONTRACT["source"]["postgres_major"],
        "alembic_revision": CONTRACT["source"]["alembic_revision"],
        "schema_contract": CONTRACT["source"]["schema_contract"],
        "schema_contract_digest": SCHEMA_CONTRACT_DIGEST,
    }:
        raise _invalid("unsupported_source", "Transfer source contract is unsupported.")
    target = _require_exact_keys(
        package["target"],
        {"sqlite_schema_version", "migration_ids"},
        code="invalid_package_shape",
    )
    if target != CONTRACT["target"]:
        raise _invalid("unsupported_target", "Transfer target contract is unsupported.")
    try:
        _validate_instant(package["exported_at"])
        _validate_uuid(package["owner_id"])
        _validate_value(package["nutrient_catalog_digest"], "sha256")
    except (TypeError, ValueError):
        raise _invalid("invalid_package_value", "Transfer package metadata is invalid.") from None
    if package["nutrient_catalog_digest"] != CONTRACT["nutrient_catalog_digest"]:
        raise _invalid("nutrient_catalog_invalid", "Transfer nutrient catalog is unsupported.")
    policy = _require_exact_keys(
        package["idempotency_policy"],
        {
            "version",
            "copied_portable_count",
            "translated_log_update_count",
            "reconstructed_log_create_count",
            "excluded_log_delete_count",
        },
        code="invalid_package_shape",
    )
    if policy["version"] != CONTRACT["idempotency"]["policy_version"]:
        raise _invalid("idempotency_policy_invalid", "Transfer receipt policy is unsupported.")
    for key in policy.keys() - {"version"}:
        try:
            _validate_value(policy[key], "nonnegative_integer")
        except ValueError:
            raise _invalid("idempotency_policy_invalid", "Transfer receipt count is invalid.") from None

    sections = package["sections"]
    if not isinstance(sections, list) or len(sections) != len(SECTION_NAMES):
        raise _invalid("section_order_invalid", "Transfer section catalog is invalid.")
    if [section.get("name") if isinstance(section, dict) else None for section in sections] != list(SECTION_NAMES):
        raise _invalid("section_order_invalid", "Transfer section order is invalid.")
    for section, section_contract in zip(sections, CONTRACT["sections"], strict=True):
        _validate_section(section, section_contract)

    qualification = _require_exact_keys(
        package["qualification"],
        {"daily_totals"},
        code="invalid_qualification_shape",
    )
    _validate_daily_totals(qualification["daily_totals"])
    _validate_owner_graph(package)
    if not isinstance(package["overall_digest"], str) or _SHA256.fullmatch(package["overall_digest"]) is None:
        raise _invalid("overall_digest_invalid", "Transfer package digest is invalid.")
    unsigned = dict(package)
    unsigned.pop("overall_digest")
    if package["overall_digest"] != canonical_digest(unsigned):
        raise _invalid("overall_digest_invalid", "Transfer package digest is invalid.")
    return deepcopy(package)
