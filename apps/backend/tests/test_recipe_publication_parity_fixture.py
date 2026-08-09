from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from uuid import uuid4

from app.publication.recipe_revision import (
    build_revision,
    content_from_recipe_output,
    decimal_text,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared-contracts"
    / "e2-08"
    / "recipe-publication-parity-fixtures.json"
)


def test_publication_amount_division_fixture_matches_backend_digest_authority() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in fixture["amount_division_cases"]:
        content = content_from_recipe_output(
            published_name="Publication amount parity",
            published_notes=None,
            serving_count_yield=Decimal(case["serving_count_yield"]),
            final_cooked_weight_grams=Decimal(case["final_cooked_weight_grams"]),
            per_serving=[],
            per_100g=[],
        )
        serving = content.amount_definitions[0]
        revision = build_revision(
            recipe_id=uuid4(),
            user_id=uuid4(),
            revision_number=1,
            creation_origin="normal_publication",
            provenance_confidence="complete",
            content=content,
        )

        assert decimal_text(serving.gram_equivalent) == case["raw_digest_gram_equivalent"]
        assert revision.content_digest == case["backend_content_digest"]
        assert format(
            serving.gram_equivalent.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            "f",
        ) == case["persisted_gram_equivalent"]
