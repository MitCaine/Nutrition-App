from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.database import Base
from app.schemas import food, log, recipe
from app.schemas.common import parse_decimal
from tests.support.foods import create_food, food_payload

CALLER_FIELDS = {
    food.OriginalNutrientValueSchema: ("amount",),
    food.FoodNutrientInput: ("amount",),
    food.ServingDefinitionInput: (
        "quantity", "gram_weight", "reference_quantity", "reference_gram_weight",
    ),
    food.ServingDefinitionCreateRequest: (
        "quantity", "gram_weight", "reference_quantity", "reference_gram_weight",
    ),
    log.DailyLogCreateRequest: ("amount_quantity",),
    log.DailyLogUpdateRequest: ("amount_quantity",),
    recipe.RecipeIngredientInput: ("amount_quantity", "amount_display_quantity"),
    recipe.RecipeCreateRequest: (
        "serving_count_yield", "final_cooked_weight_grams", "final_cooked_weight_display_quantity",
    ),
    recipe.RecipeUpdateRequest: (
        "serving_count_yield", "final_cooked_weight_grams", "final_cooked_weight_display_quantity",
    ),
}
BAD_INPUTS = [
    ("not-a-number", "decimal_invalid"), ("1..2", "decimal_invalid"),
    (" ", "decimal_invalid"), ("1e999999999999999999999", "decimal_invalid"),
    (True, "decimal_type"), (False, "decimal_type"),
    ({}, "decimal_type"), ([], "decimal_type"),
    ("NaN", "decimal_not_finite"), ("sNaN", "decimal_not_finite"),
    ("Infinity", "decimal_not_finite"), ("-Infinity", "decimal_not_finite"),
]


def schema_payload(model):
    if issubclass(model, food.ServingDefinitionInput):
        return {"label": "cup", "quantity": "1", "unit": "cup"}
    if model is food.FoodNutrientInput:
        return food_payload()["nutrients"][0]
    if model is recipe.RecipeIngredientInput:
        return {"food_item_id": uuid4(), "position": 0, "amount_quantity": "1", "amount_unit": "g"}
    if model is log.DailyLogCreateRequest:
        return {"food_item_id": uuid4(), "logged_date": "2026-07-08",
                "amount_quantity": "1", "amount_unit": "g"}
    if model is recipe.RecipeCreateRequest:
        return {"name": "Decimal control"}
    return {}


def test_all_shared_converter_fields_are_covered():
    observed = {}
    for module in (food, log, recipe):
        for value in vars(module).values():
            if not isinstance(value, type) or value.__module__ != module.__name__:
                continue
            names = tuple(name for name, field in getattr(value, "model_fields", {}).items()
                          if any(getattr(item, "func", None) is parse_decimal
                                 for item in field.metadata))
            if names:
                observed[value] = names
    assert observed == CALLER_FIELDS


@pytest.mark.parametrize("model,field", [(model, field) for model, fields in CALLER_FIELDS.items()
                                        for field in fields])
@pytest.mark.parametrize("value,code", BAD_INPUTS)
def test_every_caller_rejects_invalid_decimal_at_field(model, field, value, code):
    payload = schema_payload(model)
    payload[field] = value
    with pytest.raises(ValidationError) as result:
        model.model_validate(payload)
    assert any(error["loc"] == (field,) and error["type"] == code
               for error in result.value.errors())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"),
                                  Decimal("sNaN"), Decimal("-Infinity")])
def test_nonfinite_python_values_are_deliberate_schema_errors(value):
    with pytest.raises(ValidationError) as result:
        food.OriginalNutrientValueSchema(amount=value)
    assert result.value.errors()[0]["type"] == "decimal_not_finite"


@pytest.mark.parametrize("value,expected", [
    ("1e-6", "0.000001"), ("1.25E+2", "125"),
    ("99999999.999999", "99999999.999999"), ("0.0000001", "0.0000001"),
    ("1.2345678901234567890123456789", "1.2345678901234567890123456789"),
    (Decimal("1.230000"), "1.230000"), (2, "2"), (1.25, "1.25"),
])
def test_finite_precision_and_exponents_are_not_rounded_or_broadened(value, expected):
    actual = food.OriginalNutrientValueSchema(amount=value).amount
    assert actual.as_tuple() == Decimal(expected).as_tuple()


@pytest.mark.parametrize("value", [None, ""])
def test_optional_empty_values_keep_existing_semantics(value):
    assert food.OriginalNutrientValueSchema(amount=value).amount is None
    with pytest.raises(ValidationError):
        food.ServingDefinitionInput(label="cup", quantity=value, unit="cup")


@pytest.mark.parametrize("value", ["0", "-1"])
def test_existing_positive_quantity_range_is_preserved(value):
    with pytest.raises(ValidationError, match="greater than zero"):
        food.ServingDefinitionInput(label="cup", quantity=value, unit="cup")


def stored_state(db_session):
    # Include authority/history and mutation receipts, not only row counts.
    return {table.name: sorted(repr(tuple(row)) for row in db_session.execute(select(table)))
            for table in sorted(Base.metadata.tables.values(), key=lambda table: table.name)}


FOOD_PATHS = [
    ("nutrients", 0, "amount"), ("nutrients", 0, "original", "amount"),
    *[("serving_definitions", 0, field) for field in CALLER_FIELDS[food.ServingDefinitionInput]],
]
RECIPE_PATHS = [
    *[(field,) for field in CALLER_FIELDS[recipe.RecipeCreateRequest]],
    *[("ingredients", 0, field) for field in CALLER_FIELDS[recipe.RecipeIngredientInput]],
]
API_CASES = [
    *[(verb, "foods", path) for verb in ("POST", "PATCH") for path in FOOD_PATHS],
    *[("POST", "servings", (field,)) for field in CALLER_FIELDS[food.ServingDefinitionCreateRequest]],
    *[(verb, "recipes", path) for verb in ("POST", "PATCH") for path in RECIPE_PATHS],
    *[(verb, "logs", ("amount_quantity",)) for verb in ("POST", "PATCH")],
]


@pytest.mark.parametrize("verb,kind,path", API_CASES)
def test_invalid_api_decimal_is_structured_and_never_mutates_domain(
    client, db_session, verb, kind, path,
):
    existing_food = create_food(client)
    recipe_payload = {"name": "Decimal recipe", "final_cooked_weight_grams": "1", "ingredients": [{
        "food_item_id": existing_food["id"], "position": 0,
        "amount_quantity": "1", "amount_unit": "g",
    }]}
    recipe_response = client.post("/api/v1/recipes", json=recipe_payload)
    assert recipe_response.status_code == 201, recipe_response.text
    log_payload = {"food_item_id": existing_food["id"], "logged_date": "2026-07-08",
                   "amount_quantity": "1", "amount_unit": "g"}
    log_response = client.post("/api/v1/logs", json=log_payload)
    assert log_response.status_code == 201, log_response.text
    if kind == "foods":
        payload = food_payload()
        payload["nutrients"][0]["original"] = {"amount": "1", "unit": "kcal"}
        url = "/api/v1/foods" + (f"/{existing_food['id']}" if verb == "PATCH" else "")
    elif kind == "servings":
        payload = {"label": "cup", "quantity": "1", "unit": "cup"}
        url = f"/api/v1/foods/{existing_food['id']}/serving-definitions"
    elif kind == "recipes":
        payload = recipe_payload
        url = "/api/v1/recipes" + (f"/{recipe_response.json()['id']}" if verb == "PATCH" else "")
    else:
        payload = log_payload
        url = "/api/v1/logs" + (f"/{log_response.json()['id']}" if verb == "PATCH" else "")
    payload["client_request_id"] = str(uuid4())
    before = stored_state(db_session)
    for value, code in BAD_INPUTS:
        bad_payload = deepcopy(payload)
        target = bad_payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        response = client.request(verb, url, json=bad_payload)
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert any(error["loc"] == ["body", *path] and error["type"] == code
                   for error in detail), detail
        assert stored_state(db_session) == before


def test_valid_api_decimal_exponent_and_storage_scale_are_unchanged(client):
    payload = food_payload()
    payload["nutrients"][0]["amount"] = "1.234567e2"
    payload["serving_definitions"][0]["quantity"] = "1e0"
    response = client.post("/api/v1/foods", json=payload)
    assert response.status_code == 201, response.text
    nutrient = next(item for item in response.json()["nutrients"]
                    if item["nutrient_id"] == "calories")
    assert nutrient["amount"] == "123.456700"
    read = client.get(f"/api/v1/foods/{response.json()['id']}")
    assert read.status_code == 200
    assert read.json()["nutrients"] == response.json()["nutrients"]
