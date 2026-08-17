#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from pprint import pformat
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

SOURCE = (
    ROOT
    / "engineering"
    / "reference-data"
    / "dri_adults_2026_v1.json"
)

BACKEND_OUTPUT = (
    ROOT
    / "apps"
    / "backend"
    / "app"
    / "targets"
    / "dri_data.py"
)

MOBILE_OUTPUT = (
    ROOT
    / "apps"
    / "mobile"
    / "src"
    / "shared"
    / "nutrition"
    / "driData.ts"
)

REFERENCE_TYPES = {"RDA", "AI"}
SEXES = {"any", "female", "male"}
LIFE_STAGES = {
    "general_adult",
    "pregnant",
    "lactating",
}
CALCULATION_KINDS = {
    "fixed",
    "per_kg",
}


def source_bytes() -> bytes:
    if not SOURCE.is_file():
        raise RuntimeError(
            f"Canonical DRI source is missing: {SOURCE}"
        )

    return SOURCE.read_bytes()


def load_source() -> dict[str, Any]:
    data = json.loads(
        source_bytes().decode("utf-8")
    )

    required_top_level = {
        "dataset_version",
        "population_scope",
        "source_documents",
        "recommendations",
        "upper_limits",
        "no_goal",
    }

    if set(data) != required_top_level:
        raise RuntimeError(
            "Canonical DRI source has unexpected "
            "top-level fields"
        )

    if (
        not isinstance(data["dataset_version"], str)
        or not data["dataset_version"]
    ):
        raise RuntimeError(
            "DRI dataset version is required"
        )

    if (
        not isinstance(data["population_scope"], str)
        or not data["population_scope"]
    ):
        raise RuntimeError(
            "DRI population scope is required"
        )

    source_documents = data["source_documents"]

    if not isinstance(source_documents, list):
        raise RuntimeError(
            "source_documents must be a list"
        )

    source_ids: set[str] = set()

    for source in source_documents:
        if not isinstance(source, dict):
            raise RuntimeError(
                "Every source document must be an object"
            )

        if set(source) != {
            "id",
            "title",
            "publisher",
            "year",
        }:
            raise RuntimeError(
                "A source document has unexpected fields"
            )

        source_id = source["id"]

        if (
            not isinstance(source_id, str)
            or not source_id
        ):
            raise RuntimeError(
                "Source document IDs must be nonempty strings"
            )

        if source_id in source_ids:
            raise RuntimeError(
                f"Duplicate source document ID: {source_id}"
            )

        source_ids.add(source_id)

        if (
            not isinstance(source["title"], str)
            or not source["title"]
        ):
            raise RuntimeError(
                f"Source {source_id} has no title"
            )

        if (
            not isinstance(source["publisher"], str)
            or not source["publisher"]
        ):
            raise RuntimeError(
                f"Source {source_id} has no publisher"
            )

        if (
            not isinstance(source["year"], int)
            or source["year"] < 1900
            or source["year"] > 2100
        ):
            raise RuntimeError(
                f"Source {source_id} has an invalid year"
            )

    validate_recommendations(
        data["recommendations"],
        source_ids,
    )

    validate_upper_limits(
        data["upper_limits"],
        source_ids,
    )

    validate_no_goal(
        data["no_goal"],
        source_ids,
        data["recommendations"],
    )

    validate_selector_uniqueness(
        data["recommendations"],
        "recommendations",
    )

    validate_selector_uniqueness(
        data["upper_limits"],
        "upper_limits",
    )

    validate_selector_coverage(
        data["recommendations"],
        "recommendations",
    )

    validate_selector_coverage(
        data["upper_limits"],
        "upper_limits",
    )

    return data


def validate_selector_fields(
    row: dict[str, Any],
    *,
    collection_name: str,
) -> None:
    nutrient_id = row["nutrient_id"]

    if (
        not isinstance(nutrient_id, str)
        or not nutrient_id
    ):
        raise RuntimeError(
            f"{collection_name}: nutrient_id "
            "must be a nonempty string"
        )

    age_min = row["age_min"]
    age_max = row["age_max"]

    if (
        not isinstance(age_min, int)
        or age_min < 19
    ):
        raise RuntimeError(
            f"{collection_name}: {nutrient_id} "
            "starts below adult age 19"
        )

    if (
        age_max is not None
        and (
            not isinstance(age_max, int)
            or age_max < age_min
        )
    ):
        raise RuntimeError(
            f"{collection_name}: {nutrient_id} "
            "has an invalid age range"
        )

    sex = row["sex"]

    if sex not in SEXES:
        raise RuntimeError(
            f"{collection_name}: {nutrient_id} "
            f"has invalid sex selector {sex!r}"
        )

    life_stage = row["life_stage"]

    if life_stage not in LIFE_STAGES:
        raise RuntimeError(
            f"{collection_name}: {nutrient_id} "
            f"has invalid life stage {life_stage!r}"
        )

    if life_stage in {
        "pregnant",
        "lactating",
    }:
        if sex != "female":
            raise RuntimeError(
                f"{collection_name}: {nutrient_id} "
                "pregnancy/lactation row must use "
                "female reference sex"
            )

        if age_max is None or age_max > 50:
            raise RuntimeError(
                f"{collection_name}: {nutrient_id} "
                "pregnancy/lactation row exceeds "
                "supported adult age 50"
            )


def validate_decimal_string(
    value: Any,
    *,
    field: str,
) -> None:
    if (
        not isinstance(value, str)
        or not value
    ):
        raise RuntimeError(
            f"{field} must be a nonempty decimal string"
        )

    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(
            f"{field} is not a valid decimal string"
        ) from exc

    if parsed < 0:
        raise RuntimeError(
            f"{field} cannot be negative"
        )


def validate_recommendations(
    rows: Any,
    source_ids: set[str],
) -> None:
    if not isinstance(rows, list):
        raise RuntimeError(
            "recommendations must be a list"
        )

    required = {
        "nutrient_id",
        "reference_type",
        "unit",
        "age_min",
        "age_max",
        "sex",
        "life_stage",
        "calculation",
        "source_id",
    }

    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != required
        ):
            raise RuntimeError(
                "A recommendation row has "
                "unexpected fields"
            )

        validate_selector_fields(
            row,
            collection_name="recommendations",
        )

        nutrient_id = row["nutrient_id"]

        if row["reference_type"] not in REFERENCE_TYPES:
            raise RuntimeError(
                f"recommendations: {nutrient_id} "
                "must use RDA or AI"
            )

        if (
            not isinstance(row["unit"], str)
            or not row["unit"]
        ):
            raise RuntimeError(
                f"recommendations: {nutrient_id} "
                "has no unit"
            )

        if row["source_id"] not in source_ids:
            raise RuntimeError(
                f"recommendations: {nutrient_id} "
                f"references unknown source "
                f"{row['source_id']}"
            )

        calculation = row["calculation"]

        if not isinstance(calculation, dict):
            raise RuntimeError(
                f"recommendations: {nutrient_id} "
                "has invalid calculation metadata"
            )

        kind = calculation.get("kind")

        if kind not in CALCULATION_KINDS:
            raise RuntimeError(
                f"recommendations: {nutrient_id} "
                f"has invalid calculation kind {kind!r}"
            )

        if kind == "fixed":
            if set(calculation) != {
                "kind",
                "amount",
            }:
                raise RuntimeError(
                    f"recommendations: {nutrient_id} "
                    "fixed calculation has unexpected fields"
                )

            validate_decimal_string(
                calculation["amount"],
                field=(
                    f"recommendations."
                    f"{nutrient_id}.amount"
                ),
            )

        else:
            if set(calculation) != {
                "kind",
                "factor",
            }:
                raise RuntimeError(
                    f"recommendations: {nutrient_id} "
                    "per_kg calculation has unexpected fields"
                )

            validate_decimal_string(
                calculation["factor"],
                field=(
                    f"recommendations."
                    f"{nutrient_id}.factor"
                ),
            )


def validate_upper_limits(
    rows: Any,
    source_ids: set[str],
) -> None:
    if not isinstance(rows, list):
        raise RuntimeError(
            "upper_limits must be a list"
        )

    required = {
        "nutrient_id",
        "unit",
        "amount",
        "age_min",
        "age_max",
        "sex",
        "life_stage",
        "source_id",
        "scope",
        "comparable_to_recommendation",
    }

    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != required
        ):
            raise RuntimeError(
                "An upper-limit row has "
                "unexpected fields"
            )

        validate_selector_fields(
            row,
            collection_name="upper_limits",
        )

        nutrient_id = row["nutrient_id"]

        if (
            not isinstance(row["unit"], str)
            or not row["unit"]
        ):
            raise RuntimeError(
                f"upper_limits: {nutrient_id} "
                "has no unit"
            )

        validate_decimal_string(
            row["amount"],
            field=(
                f"upper_limits."
                f"{nutrient_id}.amount"
            ),
        )

        if row["source_id"] not in source_ids:
            raise RuntimeError(
                f"upper_limits: {nutrient_id} "
                f"references unknown source "
                f"{row['source_id']}"
            )

        if (
            not isinstance(row["scope"], str)
            or not row["scope"]
        ):
            raise RuntimeError(
                f"upper_limits: {nutrient_id} "
                "has no scope"
            )

        if not isinstance(
            row["comparable_to_recommendation"],
            bool,
        ):
            raise RuntimeError(
                f"upper_limits: {nutrient_id} "
                "has invalid comparable flag"
            )


def validate_no_goal(
    no_goal: Any,
    source_ids: set[str],
    recommendations: list[dict[str, Any]],
) -> None:
    if not isinstance(no_goal, dict):
        raise RuntimeError(
            "no_goal must be an object"
        )

    recommendation_ids = {
        row["nutrient_id"]
        for row in recommendations
    }

    overlap = (
        recommendation_ids
        .intersection(no_goal)
    )

    if overlap:
        raise RuntimeError(
            "Nutrients cannot have both DRI "
            "recommendations and no-goal declarations: "
            + ", ".join(sorted(overlap))
        )

    for nutrient_id, metadata in no_goal.items():
        if (
            not isinstance(metadata, dict)
            or set(metadata)
            != {
                "reason_code",
                "source_id",
            }
        ):
            raise RuntimeError(
                f"no_goal: {nutrient_id} "
                "has unexpected metadata"
            )

        if (
            not isinstance(
                metadata["reason_code"],
                str,
            )
            or not metadata["reason_code"]
        ):
            raise RuntimeError(
                f"no_goal: {nutrient_id} "
                "has no reason code"
            )

        if metadata["source_id"] not in source_ids:
            raise RuntimeError(
                f"no_goal: {nutrient_id} "
                f"references unknown source "
                f"{metadata['source_id']}"
            )


def selector_identity(
    row: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        row["nutrient_id"],
        row["age_min"],
        row["age_max"],
        row["sex"],
        row["life_stage"],
    )


def validate_selector_uniqueness(
    rows: list[dict[str, Any]],
    collection_name: str,
) -> None:
    identities: set[tuple[Any, ...]] = set()

    for row in rows:
        identity = selector_identity(row)

        if identity in identities:
            raise RuntimeError(
                f"{collection_name}: duplicate selector "
                f"{identity}"
            )

        identities.add(identity)


def matches(
    row: dict[str, Any],
    *,
    age: int,
    sex: str,
    life_stage: str,
) -> bool:
    return (
        row["life_stage"] == life_stage
        and row["age_min"] <= age
        and (
            row["age_max"] is None
            or age <= row["age_max"]
        )
        and (
            row["sex"] == "any"
            or row["sex"] == sex
        )
    )


def validate_selector_coverage(
    rows: list[dict[str, Any]],
    collection_name: str,
) -> None:
    # Exercise every boundary that currently exists in
    # the adult table. This catches accidental overlap
    # without imposing a false requirement that every
    # nutrient have a DRI/UL for every profile.
    ages = {
        19,
        30,
        31,
        50,
        51,
        70,
        71,
        90,
    }

    for row in rows:
        ages.add(row["age_min"])

        if row["age_max"] is not None:
            ages.add(row["age_max"])

            if row["age_max"] + 1 <= 120:
                ages.add(row["age_max"] + 1)

    for age in sorted(ages):
        for sex in ("male", "female"):
            life_stages = ["general_adult"]

            if sex == "female" and age <= 50:
                life_stages.extend(
                    ("pregnant", "lactating")
                )

            for life_stage in life_stages:
                by_nutrient: dict[
                    str,
                    list[dict[str, Any]],
                ] = {}

                for row in rows:
                    if matches(
                        row,
                        age=age,
                        sex=sex,
                        life_stage=life_stage,
                    ):
                        by_nutrient.setdefault(
                            row["nutrient_id"],
                            [],
                        ).append(row)

                ambiguous = {
                    nutrient_id: selected
                    for nutrient_id, selected
                    in by_nutrient.items()
                    if len(selected) > 1
                }

                if ambiguous:
                    raise RuntimeError(
                        f"{collection_name}: ambiguous "
                        "selector resolution for "
                        f"age={age}, sex={sex}, "
                        f"life_stage={life_stage}: "
                        + ", ".join(
                            sorted(ambiguous)
                        )
                    )


def source_digest() -> str:
    return hashlib.sha256(
        source_bytes()
    ).hexdigest()


def python_output(
    data: dict[str, Any],
) -> str:
    digest = source_digest()

    documents = pformat(
        tuple(data["source_documents"]),
        width=88,
        sort_dicts=False,
    )

    recommendations = pformat(
        tuple(data["recommendations"]),
        width=88,
        sort_dicts=False,
    )

    upper_limits = pformat(
        tuple(data["upper_limits"]),
        width=88,
        sort_dicts=False,
    )

    no_goal = pformat(
        data["no_goal"],
        width=88,
        sort_dicts=False,
    )

    return (
        '"""Generated DRI reference data.\n\n'
        "Do not edit by hand. Regenerate with:\n"
        "    python3 engineering/"
        "generate_dri_reference.py\n\n"
        "Canonical source:\n"
        "    engineering/reference-data/"
        "dri_adults_2026_v1.json\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        f"DRI_DATASET_VERSION = "
        f"{data['dataset_version']!r}\n"
        f"DRI_POPULATION_SCOPE = "
        f"{data['population_scope']!r}\n"
        f"DRI_SOURCE_SHA256 = {digest!r}\n\n"
        f"DRI_SOURCE_DOCUMENTS = "
        f"{documents}\n\n"
        f"DRI_RECOMMENDATIONS = "
        f"{recommendations}\n\n"
        f"DRI_UPPER_LIMITS = "
        f"{upper_limits}\n\n"
        f"DRI_NO_GOAL = "
        f"{no_goal}\n"
    )


def typescript_output(
    data: dict[str, Any],
) -> str:
    digest = source_digest()

    documents = json.dumps(
        data["source_documents"],
        indent=2,
        ensure_ascii=False,
    )

    recommendations = json.dumps(
        data["recommendations"],
        indent=2,
        ensure_ascii=False,
    )

    upper_limits = json.dumps(
        data["upper_limits"],
        indent=2,
        ensure_ascii=False,
    )

    no_goal = json.dumps(
        data["no_goal"],
        indent=2,
        ensure_ascii=False,
    )

    version = json.dumps(
        data["dataset_version"]
    )

    scope = json.dumps(
        data["population_scope"]
    )

    digest_literal = json.dumps(digest)

    return f'''// Generated DRI reference data.
//
// Do not edit by hand. Regenerate with:
//   python3 engineering/generate_dri_reference.py
//
// Canonical source:
//   engineering/reference-data/dri_adults_2026_v1.json

export type DriReferenceType =
  | "RDA"
  | "AI";

export type DriReferenceSex =
  | "any"
  | "female"
  | "male";

export type DriLifeStage =
  | "general_adult"
  | "pregnant"
  | "lactating";

export type DriCalculation =
  | Readonly<{{
      kind: "fixed";
      amount: string;
    }}>
  | Readonly<{{
      kind: "per_kg";
      factor: string;
    }}>;

export type DriSourceDocument =
  Readonly<{{
    id: string;
    title: string;
    publisher: string;
    year: number;
  }}>;

export type DriRecommendationDataRow =
  Readonly<{{
    nutrient_id: string;
    reference_type: DriReferenceType;
    unit: string;
    age_min: number;
    age_max: number | null;
    sex: DriReferenceSex;
    life_stage: DriLifeStage;
    calculation: DriCalculation;
    source_id: string;
  }}>;

export type DriUpperLimitDataRow =
  Readonly<{{
    nutrient_id: string;
    unit: string;
    amount: string;
    age_min: number;
    age_max: number | null;
    sex: DriReferenceSex;
    life_stage: DriLifeStage;
    source_id: string;
    scope: string;
    comparable_to_recommendation: boolean;
  }}>;

export type DriNoGoalData =
  Readonly<{{
    reason_code: string;
    source_id: string;
  }}>;

export const DRI_DATASET_VERSION =
  {version};

export const DRI_POPULATION_SCOPE =
  {scope};

export const DRI_SOURCE_SHA256 =
  {digest_literal};

export const DRI_SOURCE_DOCUMENTS =
{documents} as const satisfies
  readonly DriSourceDocument[];

export const DRI_RECOMMENDATIONS =
{recommendations} as const satisfies
  readonly DriRecommendationDataRow[];

export const DRI_UPPER_LIMITS =
{upper_limits} as const satisfies
  readonly DriUpperLimitDataRow[];

export const DRI_NO_GOAL =
{no_goal} as const satisfies
  Readonly<Record<string, DriNoGoalData>>;
'''


def expected_outputs(
    data: dict[str, Any],
) -> dict[Path, str]:
    return {
        BACKEND_OUTPUT: python_output(data),
        MOBILE_OUTPUT: typescript_output(data),
    }


def check_outputs(
    expected: dict[Path, str],
) -> None:
    stale: list[Path] = []

    for path, content in expected.items():
        if not path.is_file():
            stale.append(path)
            continue

        if (
            path.read_text(encoding="utf-8")
            != content
        ):
            stale.append(path)

    if stale:
        rendered = "\n".join(
            "  "
            + str(path.relative_to(ROOT))
            for path in stale
        )

        raise SystemExit(
            "Generated DRI artifacts are stale:\n"
            + rendered
        )

    print(
        "DRI generated artifacts are current."
    )


def write_outputs(
    expected: dict[Path, str],
) -> None:
    for path, content in expected.items():
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            content,
            encoding="utf-8",
        )

    print("Generated DRI artifacts:")

    for path in expected:
        print(
            "  "
            + str(path.relative_to(ROOT))
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate backend/mobile DRI data "
            "from the canonical reference source."
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Fail if generated artifacts differ "
            "from the canonical source."
        ),
    )

    args = parser.parse_args()

    data = load_source()
    expected = expected_outputs(data)

    if args.check:
        check_outputs(expected)
        return

    write_outputs(expected)


if __name__ == "__main__":
    main()
