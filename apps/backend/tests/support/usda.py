from __future__ import annotations


class FakeUsdaClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.detail_calls = 0

    def search_foods(self, query: str, *, page_size: int = 25, page_number: int = 1) -> dict:
        return {
            "totalHits": 1,
            "foods": [
                {
                    "fdcId": self.payload["fdcId"],
                    "description": self.payload["description"],
                    "dataType": self.payload["dataType"],
                }
            ],
        }

    def get_food(self, fdc_id: int) -> dict:
        self.detail_calls += 1
        assert fdc_id == self.payload["fdcId"]
        return self.payload


def usda_banana_payload() -> dict:
    return {
        "fdcId": 1105314,
        "description": "Bananas, raw",
        "dataType": "Foundation",
        "publicationDate": "10/30/2020",
        "foodCategory": {"description": "Fruits and Fruit Juices"},
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 89},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 1.09},
            {
                "nutrient": {
                    "id": 1005,
                    "number": "205",
                    "name": "Carbohydrate, by difference",
                    "unitName": "G",
                },
                "amount": 22.8,
            },
            {"nutrient": {"id": 1004, "number": "204", "name": "Total lipid (fat)", "unitName": "G"}, "amount": 0.33},
            {"nutrient": {"id": 1093, "number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 1},
            {"nutrient": {"id": 1253, "number": "601", "name": "Cholesterol", "unitName": "MG"}, "amount": 0},
            {"nutrient": {"id": 1092, "number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 358},
            {"nutrient": {"id": 1090, "number": "304", "name": "Magnesium, Mg", "unitName": "MG"}, "amount": 27},
            {"nutrient": {"id": 9999, "number": "999", "name": "Unsupported", "unitName": "IU"}, "amount": 1},
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "MG"}, "amount": 1},
        ],
        "foodPortions": [
            {
                "amount": 1,
                "gramWeight": 118,
                "modifier": "medium",
                "measureUnit": {"name": "banana", "abbreviation": "banana"},
            }
        ],
    }


def usda_branded_bar_payload() -> dict:
    return {
        "fdcId": 555000,
        "description": "Example Protein Bar",
        "dataType": "Branded",
        "brandOwner": "Example Foods",
        "servingSize": 40,
        "servingSizeUnit": "g",
        "householdServingFullText": "1 bar",
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 250},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 20},
        ],
        "foodPortions": [
            {
                "id": 12345,
                "amount": 1,
                "gramWeight": 40,
                "modifier": "bar",
                "measureUnit": {"name": "bar", "abbreviation": "bar"},
            }
        ],
    }


def usda_branded_full_macro_payload() -> dict:
    return {
        "fdcId": 555001,
        "description": "Complete Protein Bar",
        "dataType": "Branded",
        "brandOwner": "Example Foods",
        "servingSize": 50,
        "servingSizeUnit": "g",
        "householdServingFullText": "1 bar",
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 300},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 18},
            {"nutrient": {"id": 1005, "number": "205", "name": "Carbohydrate, by difference", "unitName": "G"}, "amount": 40},
            {"nutrient": {"id": 1004, "number": "204", "name": "Total lipid (fat)", "unitName": "G"}, "amount": 10},
            {"nutrient": {"id": 1079, "number": "291", "name": "Fiber, total dietary", "unitName": "G"}, "amount": 7},
            {"nutrient": {"id": 2000, "number": "269", "name": "Total Sugars", "unitName": "G"}, "amount": 12},
            {"nutrient": {"id": 1258, "number": "606", "name": "Fatty acids, total saturated", "unitName": "G"}, "amount": 2},
            {"nutrient": {"id": 1093, "number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 250},
            {"nutrient": {"id": 1253, "number": "601", "name": "Cholesterol", "unitName": "MG"}, "amount": 5},
            {"nutrient": {"id": 1114, "number": "328", "name": "Vitamin D (D2 + D3)", "unitName": "UG"}, "amount": 1.5},
            {"nutrient": {"id": 1087, "number": "301", "name": "Calcium, Ca", "unitName": "G"}, "amount": 0.2},
            {"nutrient": {"id": 1089, "number": "303", "name": "Iron, Fe", "unitName": "MG"}, "amount": 4},
            {"nutrient": {"id": 1092, "number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 300},
            {"nutrient": {"id": 1090, "number": "304", "name": "Magnesium, Mg", "unitName": "MG"}, "amount": 60},
        ],
    }
