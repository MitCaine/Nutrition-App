from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.models.food import FoodItem, ServingDefinition
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.nutrition import resolution as authoritative_resolution
from app.nutrition.resolution import NutrientResolverInput, UnsupportedNutritionAmountError
from app.nutrition.serving_resolution import AmountDefinitionInput


@dataclass(frozen=True)
class ResolvedRevisionNutrient:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    data_status: NutrientDataStatus
    source_basis: NutrientBasis


@dataclass(frozen=True)
class ResolvedRevisionNutrition:
    amount_definition_id: UUID | None
    semantic_amount_mode: str
    entered_quantity: Decimal
    resolved_grams: Decimal | None
    serving_multiplier: Decimal | None
    nutrients: tuple[ResolvedRevisionNutrient, ...]


@dataclass(frozen=True)
class RevisionLogAmountSelection:
    revision_amount: RecipePublicationAmountDefinition
    compatibility_serving: ServingDefinition | None


def revision_amount_definition_inputs(
    revision: RecipePublicationRevision,
) -> tuple[AmountDefinitionInput, ...]:
    return tuple(
        AmountDefinitionInput(
            id=amount.id,
            semantic_mode=amount.semantic_mode,
            display_label=amount.display_label,
            gram_equivalent=amount.gram_equivalent,
            is_default=amount.is_default,
        )
        for amount in revision.amount_definitions
    )


def revision_nutrient_inputs(
    revision: RecipePublicationRevision,
) -> tuple[NutrientResolverInput, ...]:
    return tuple(
        NutrientResolverInput(
            source_row_id=nutrient.id,
            nutrient_id=nutrient.nutrient_id,
            amount=nutrient.amount,
            unit=nutrient.unit,
            basis=nutrient.basis,
            data_status=nutrient.data_status,
        )
        for nutrient in revision.nutrients
    )


def resolve_revision_nutrition(
    revision: RecipePublicationRevision,
    amount_definition_id: UUID | None,
    entered_quantity: Decimal,
    *,
    semantic_amount_mode: str | None = None,
) -> ResolvedRevisionNutrition:
    """Adapt immutable revision rows into the authoritative resolver input contract."""
    amount_definitions = revision_amount_definition_inputs(revision)
    amount_mode = semantic_amount_mode or _mapped_amount_mode(
        amount_definitions,
        amount_definition_id,
    )
    interpreted = authoritative_resolution.resolve_nutrition_inputs(
        amount_definitions,
        revision_nutrient_inputs(revision),
        entered_quantity,
        amount_mode,
        amount_definition_id,
    )
    return ResolvedRevisionNutrition(
        amount_definition_id=interpreted.amount.amount_definition_id,
        semantic_amount_mode=interpreted.amount.amount_unit,
        entered_quantity=interpreted.amount.amount_quantity,
        resolved_grams=interpreted.amount.gram_amount,
        serving_multiplier=interpreted.amount.serving_multiplier,
        nutrients=tuple(
            ResolvedRevisionNutrient(
                nutrient_id=nutrient.nutrient_id,
                amount=nutrient.amount,
                unit=nutrient.unit,
                data_status=nutrient.data_status,
                source_basis=nutrient.source_basis,
            )
            for nutrient in interpreted.nutrients
        ),
    )


def map_projection_log_amount(
    projection: FoodItem,
    revision: RecipePublicationRevision,
    amount_unit: str,
    serving_definition_id: UUID | None,
) -> RevisionLogAmountSelection:
    """Map a compatibility selection to immutable revision-owned amount input."""
    selected_serving = _projection_serving(projection, serving_definition_id)
    amount_unit = amount_unit.strip().lower()
    if amount_unit == "g":
        if selected_serving is None:
            selected_serving = next(
                (serving for serving in projection.serving_definitions if serving.is_default),
                None,
            )
        canonical = [
            amount for amount in revision.amount_definitions if amount.semantic_mode == "g"
        ]
        if len(canonical) != 1:
            raise UnsupportedNutritionAmountError(
                "Active publication does not support canonical gram logging"
            )
        return RevisionLogAmountSelection(canonical[0], selected_serving)

    if amount_unit != "serving":
        raise UnsupportedNutritionAmountError(f"Unsupported log amount unit: {amount_unit}")
    if selected_serving is None:
        selected_serving = next(
            (serving for serving in projection.serving_definitions if serving.is_default),
            None,
        )
    if selected_serving is None:
        raise UnsupportedNutritionAmountError(
            "Serving-count logging requires a serving definition"
        )
    matches = [
        amount
        for amount in revision.amount_definitions
        if amount.semantic_mode == "serving"
        and amount.display_label == selected_serving.label
        and amount.display_quantity == selected_serving.quantity
        and amount.display_unit == selected_serving.unit
        and amount.gram_equivalent == selected_serving.gram_weight
        and amount.is_default == selected_serving.is_default
    ]
    if len(matches) != 1:
        raise UnsupportedNutritionAmountError(
            "Selected serving does not map to the active publication revision"
        )
    return RevisionLogAmountSelection(matches[0], selected_serving)


def _mapped_amount_mode(
    amount_definitions: tuple[AmountDefinitionInput, ...],
    amount_definition_id: UUID | None,
) -> str:
    for amount in amount_definitions:
        if amount.id == amount_definition_id:
            return amount.semantic_mode
    raise UnsupportedNutritionAmountError("Amount definition does not belong to this revision")


def _projection_serving(
    projection: FoodItem,
    serving_definition_id: UUID | None,
) -> ServingDefinition | None:
    if serving_definition_id is None:
        return None
    for serving in projection.serving_definitions:
        if serving.id == serving_definition_id:
            return serving
    raise UnsupportedNutritionAmountError(
        "Serving definition does not belong to this food"
    )
