from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from app.domain.nutrition import AggregatedNutrientTotal, NutrientBasis, NutrientDataStatus
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationNutrient,
    RecipePublicationRevision,
)
from app.nutrition.resolution import NutritionResolutionError, resolve_nutrition
from app.nutrition.revision_resolution import resolve_revision_nutrition


@dataclass(frozen=True)
class PublishedAmountContent:
    display_order: int
    display_label: str
    semantic_mode: str
    display_quantity: Decimal | None
    display_unit: str
    gram_equivalent: Decimal | None
    is_default: bool
    conversion_metadata: dict | None = None


@dataclass(frozen=True)
class PublishedNutrientContent:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    basis: str
    data_status: str
    diagnostic_provenance: dict | None = None


@dataclass(frozen=True)
class RecipePublicationContent:
    published_name: str
    published_notes: str | None
    amount_definitions: tuple[PublishedAmountContent, ...]
    nutrients: tuple[PublishedNutrientContent, ...]


def content_from_recipe_output(
    *,
    published_name: str,
    published_notes: str | None,
    serving_count_yield: Decimal | None,
    final_cooked_weight_grams: Decimal | None,
    per_serving: list[AggregatedNutrientTotal] | None,
    per_100g: list[AggregatedNutrientTotal] | None,
) -> RecipePublicationContent:
    amounts: list[PublishedAmountContent] = []
    if serving_count_yield is not None:
        amounts.append(
            PublishedAmountContent(
                display_order=len(amounts),
                display_label="1 serving",
                semantic_mode="serving",
                display_quantity=Decimal("1"),
                display_unit="serving",
                gram_equivalent=(
                    final_cooked_weight_grams / serving_count_yield
                    if final_cooked_weight_grams is not None
                    else None
                ),
                is_default=True,
            )
        )
    if final_cooked_weight_grams is not None:
        amounts.append(
            PublishedAmountContent(
                display_order=len(amounts),
                display_label="100 g",
                semantic_mode="serving",
                display_quantity=Decimal("100"),
                display_unit="g",
                gram_equivalent=Decimal("100"),
                is_default=serving_count_yield is None,
            )
        )
        amounts.append(
            PublishedAmountContent(
                display_order=len(amounts),
                display_label="g",
                semantic_mode="g",
                display_quantity=None,
                display_unit="g",
                gram_equivalent=None,
                is_default=False,
            )
        )

    nutrients = [
        _published_nutrient(total, NutrientBasis.PER_SERVING) for total in per_serving or []
    ]
    nutrients.extend(_published_nutrient(total, NutrientBasis.PER_100G) for total in per_100g or [])
    return RecipePublicationContent(
        published_name=published_name,
        published_notes=published_notes,
        amount_definitions=tuple(amounts),
        nutrients=tuple(
            sorted(
                nutrients,
                key=lambda row: (row.nutrient_id, row.basis, row.unit, row.data_status),
            )
        ),
    )


def content_from_projection(projection: FoodItem) -> RecipePublicationContent:
    sorted_servings = sorted(
        projection.serving_definitions,
        key=lambda serving: (
            serving.label.casefold(),
            serving.unit.casefold(),
            decimal_text(serving.quantity),
            decimal_text(serving.gram_weight),
        ),
    )
    amounts = [
        PublishedAmountContent(
            display_order=order,
            display_label=serving.label,
            semantic_mode="serving",
            display_quantity=serving.quantity,
            display_unit=serving.unit,
            gram_equivalent=serving.gram_weight,
            is_default=serving.is_default,
        )
        for order, serving in enumerate(sorted_servings)
    ]
    if projection_supports_gram_resolution(projection):
        amounts.append(
            PublishedAmountContent(
                display_order=len(amounts),
                display_label="g",
                semantic_mode="g",
                display_quantity=None,
                display_unit="g",
                gram_equivalent=None,
                is_default=False,
            )
        )
    nutrients = tuple(
        PublishedNutrientContent(
            nutrient_id=row.nutrient_id,
            amount=row.amount,
            unit=row.unit,
            basis=row.basis,
            data_status=row.data_status,
        )
        for row in sorted(
            projection.nutrients,
            key=lambda value: (
                value.nutrient_id,
                value.basis,
                value.unit,
                value.data_status,
            ),
        )
    )
    return RecipePublicationContent(
        published_name=projection.name,
        published_notes=projection.notes,
        amount_definitions=tuple(amounts),
        nutrients=nutrients,
    )


def build_revision(
    *,
    recipe_id: UUID,
    user_id: UUID,
    revision_number: int,
    creation_origin: str,
    provenance_confidence: str,
    content: RecipePublicationContent,
) -> RecipePublicationRevision:
    revision = RecipePublicationRevision(
        id=uuid4(),
        recipe_id=recipe_id,
        user_id=user_id,
        revision_number=revision_number,
        creation_origin=creation_origin,
        provenance_confidence=provenance_confidence,
        published_name=content.published_name,
        published_notes=content.published_notes,
        content_digest="pending",
    )
    revision.amount_definitions = [
        RecipePublicationAmountDefinition(
            id=uuid4(),
            display_order=amount.display_order,
            display_label=amount.display_label,
            semantic_mode=amount.semantic_mode,
            display_quantity=amount.display_quantity,
            display_unit=amount.display_unit,
            gram_equivalent=amount.gram_equivalent,
            is_default=amount.is_default,
            conversion_metadata=amount.conversion_metadata,
        )
        for amount in content.amount_definitions
    ]
    revision.nutrients = [
        RecipePublicationNutrient(
            id=uuid4(),
            nutrient_id=nutrient.nutrient_id,
            amount=nutrient.amount,
            unit=nutrient.unit,
            basis=nutrient.basis,
            data_status=nutrient.data_status,
            diagnostic_provenance=nutrient.diagnostic_provenance,
        )
        for nutrient in content.nutrients
    ]
    revision.content_digest = revision_content_digest(revision)
    return revision


def validate_revision_resolver_input(revision: RecipePublicationRevision) -> None:
    if not revision.amount_definitions:
        raise ValueError("Publication revision requires at least one amount definition")
    if sum(amount.is_default for amount in revision.amount_definitions) != 1:
        raise ValueError("Publication revision requires exactly one default amount")
    for amount in revision.amount_definitions:
        resolve_revision_nutrition(revision, amount.id, Decimal("1"))


def apply_revision_to_projection(
    projection: FoodItem,
    revision: RecipePublicationRevision,
    *,
    recipe_id: UUID,
    user_id: UUID,
    updated_at: datetime,
) -> None:
    projection.user_id = user_id
    projection.name = revision.published_name
    projection.brand = None
    projection.notes = revision.published_notes
    projection.source_type = "recipe"
    projection.source_id = str(recipe_id)
    projection.is_recipe = True
    projection.deleted_at = None
    projection.updated_at = updated_at
    projection.serving_definitions.clear()
    projection.nutrients.clear()
    projection.sources.clear()
    projection.serving_definitions.extend(
        ServingDefinition(
            id=uuid4(),
            label=amount.display_label,
            quantity=amount.display_quantity,
            unit=amount.display_unit,
            gram_weight=amount.gram_equivalent,
            is_default=amount.is_default,
            source="recipe",
            is_user_confirmed=True,
        )
        for amount in sorted(
            revision.amount_definitions,
            key=lambda value: value.display_order,
        )
        if amount.semantic_mode == "serving" and amount.display_quantity is not None
    )
    projection.nutrients.extend(
        FoodNutrient(
            id=uuid4(),
            nutrient_id=nutrient.nutrient_id,
            amount=nutrient.amount,
            unit=nutrient.unit,
            basis=nutrient.basis,
            data_status=nutrient.data_status,
            source="recipe",
            is_user_confirmed=True,
        )
        for nutrient in revision.nutrients
    )


def projection_matches_revision(
    projection: FoodItem,
    revision: RecipePublicationRevision,
) -> bool:
    comparison = build_revision(
        recipe_id=revision.recipe_id,
        user_id=revision.user_id,
        revision_number=revision.revision_number,
        creation_origin=revision.creation_origin,
        provenance_confidence=revision.provenance_confidence,
        content=content_from_projection(projection),
    )
    return comparison.content_digest == revision.content_digest


def revision_content_digest(revision: RecipePublicationRevision) -> str:
    """Hash immutable content for diagnostics/comparison, never request idempotency."""
    content = {
        "published_name": revision.published_name,
        "published_notes": revision.published_notes,
        "amount_definitions": [
            {
                "display_order": amount.display_order,
                "display_label": amount.display_label,
                "semantic_mode": amount.semantic_mode,
                "display_quantity": decimal_text(amount.display_quantity),
                "display_unit": amount.display_unit,
                "gram_equivalent": decimal_text(amount.gram_equivalent),
                "is_default": amount.is_default,
                "conversion_metadata": amount.conversion_metadata,
            }
            for amount in sorted(
                revision.amount_definitions,
                key=lambda value: value.display_order,
            )
        ],
        "nutrients": [
            {
                "nutrient_id": nutrient.nutrient_id,
                "amount": decimal_text(nutrient.amount),
                "unit": nutrient.unit,
                "basis": nutrient.basis,
                "data_status": nutrient.data_status,
                "diagnostic_provenance": nutrient.diagnostic_provenance,
            }
            for nutrient in sorted(
                revision.nutrients,
                key=lambda value: (
                    value.nutrient_id,
                    value.basis,
                    value.unit,
                    value.data_status,
                ),
            )
        ],
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def projection_supports_gram_resolution(projection: FoodItem) -> bool:
    try:
        resolve_nutrition(projection, Decimal("1"), "g")
    except (NutritionResolutionError, ValueError):
        return False
    return True


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _published_nutrient(
    total: AggregatedNutrientTotal,
    basis: NutrientBasis,
) -> PublishedNutrientContent:
    status = (
        NutrientDataStatus.UNKNOWN if total.has_unknown_contributors else NutrientDataStatus.KNOWN
    )
    amount = (
        None
        if status == NutrientDataStatus.UNKNOWN
        else total.amount_known + total.amount_estimated
    )
    if amount == 0 and status == NutrientDataStatus.KNOWN:
        status = NutrientDataStatus.ZERO
    return PublishedNutrientContent(
        nutrient_id=total.nutrient_id,
        amount=amount,
        unit=total.unit,
        basis=basis.value,
        data_status=status.value,
    )
