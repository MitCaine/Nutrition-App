from app.domain.food_duplicate_name import allocate_duplicate_food_name


def test_duplicate_name_allocates_the_lowest_available_suffix() -> None:
    assert allocate_duplicate_food_name(
        "Oatmeal",
        ["Oatmeal", "Oatmeal Copy", "Oatmeal Copy 3"],
        source_is_duplicate=False,
    ) == "Oatmeal Copy 2"


def test_duplicate_of_duplicate_advances_without_copy_copy() -> None:
    assert allocate_duplicate_food_name(
        "Oatmeal Copy 2",
        ["Oatmeal", "Oatmeal Copy", "Oatmeal Copy 2", "Oatmeal Copy 3"],
        source_is_duplicate=True,
    ) == "Oatmeal Copy 4"


def test_literal_copy_suffix_is_preserved_for_non_duplicate_source() -> None:
    assert allocate_duplicate_food_name(
        "Recipe Copy",
        ["Recipe Copy"],
        source_is_duplicate=False,
    ) == "Recipe Copy Copy"
