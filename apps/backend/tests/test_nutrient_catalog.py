from dataclasses import asdict

from app.catalog.nutrients import NUTRIENT_CATALOG, nutrient_seed_rows


def test_seed_rows_derive_from_canonical_nutrient_catalog() -> None:
    assert nutrient_seed_rows() == [asdict(nutrient) for nutrient in NUTRIENT_CATALOG]


def test_nutrient_catalog_has_stable_hierarchy_for_label_display() -> None:
    parents_by_id = {nutrient.id: nutrient.parent_nutrient_id for nutrient in NUTRIENT_CATALOG}

    assert parents_by_id["saturated_fat"] == "total_fat"
    assert parents_by_id["trans_fat"] == "total_fat"
    assert parents_by_id["dietary_fiber"] == "total_carbohydrate"
    assert parents_by_id["total_sugars"] == "total_carbohydrate"
    assert parents_by_id["added_sugars"] == "total_sugars"
