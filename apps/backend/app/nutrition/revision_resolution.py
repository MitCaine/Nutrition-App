from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.models.recipe_publication import RecipePublicationRevision
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
    nutrients: tuple[ResolvedRevisionNutrient, ...]


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


def _mapped_amount_mode(
    amount_definitions: tuple[AmountDefinitionInput, ...],
    amount_definition_id: UUID | None,
) -> str:
    for amount in amount_definitions:
        if amount.id == amount_definition_id:
            return amount.semantic_mode
    raise UnsupportedNutritionAmountError("Amount definition does not belong to this revision")
