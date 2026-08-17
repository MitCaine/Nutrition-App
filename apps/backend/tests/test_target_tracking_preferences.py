from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from tests.test_targets import configuration_payload


def tracking_payload():
    payload = configuration_payload()
    payload["tracking_preferences"] = {}
    return payload


def effective_by_id(body: dict) -> dict[str, dict]:
    return {
        item["nutrient_id"]: item
        for item in body["effective_targets"]
    }


def test_tracking_modes_recommended_custom_amount_only_ignored_and_restored(
    client: TestClient,
):
    recommended = client.put(
        "/api/v1/targets",
        json=tracking_payload(),
    )
    assert recommended.status_code == 200, recommended.text

    protein = effective_by_id(recommended.json())["protein"]

    assert protein["tracking_mode"] == "recommended"
    assert protein["authority"] == "dri"
    assert protein["reference_type"] == "RDA"
    assert protein["amount"] == "56.000000"

    custom_payload = tracking_payload()
    custom_payload["manual_overrides"]["protein"] = "90"

    custom = client.put(
        "/api/v1/targets",
        json=custom_payload,
    )
    assert custom.status_code == 200, custom.text

    protein = effective_by_id(custom.json())["protein"]

    assert protein["tracking_mode"] == "custom"
    assert protein["authority"] == "manual_override"
    assert protein["amount"] == "90.000000"

    amount_only_payload = tracking_payload()
    amount_only_payload["tracking_preferences"]["protein"] = "amount_only"

    amount_only = client.put(
        "/api/v1/targets",
        json=amount_only_payload,
    )
    assert amount_only.status_code == 200, amount_only.text

    protein = effective_by_id(amount_only.json())["protein"]

    assert protein["tracking_mode"] == "amount_only"
    assert protein["amount"] is None
    assert protein["reason_code"] == "target_amount_only_preference"
    assert amount_only.json()["tracking_preferences"] == {
        "protein": "amount_only",
    }

    ignored_payload = tracking_payload()
    ignored_payload["tracking_preferences"]["protein"] = "ignored"

    ignored = client.put(
        "/api/v1/targets",
        json=ignored_payload,
    )
    assert ignored.status_code == 200, ignored.text

    protein = effective_by_id(ignored.json())["protein"]

    assert protein["tracking_mode"] == "ignored"
    assert protein["amount"] is None
    assert protein["reason_code"] == "target_ignored_preference"

    comparison = client.get(
        "/api/v1/targets/daily-comparison",
        params={"date": "2026-07-14"},
    )
    assert comparison.status_code == 200, comparison.text

    assert "protein" not in {
        item["nutrient_id"]
        for item in comparison.json()["comparisons"]
    }

    restored = client.put(
        "/api/v1/targets",
        json=tracking_payload(),
    )
    assert restored.status_code == 200, restored.text

    protein = effective_by_id(restored.json())["protein"]

    assert protein["tracking_mode"] == "recommended"
    assert protein["authority"] == "dri"
    assert protein["amount"] == "56.000000"
    assert restored.json()["tracking_preferences"] == {}


def test_custom_target_supports_any_canonical_nutrient(
    client: TestClient,
):
    payload = tracking_payload()

    payload["manual_overrides"]["vitamin_c"] = "123.456789"

    response = client.put(
        "/api/v1/targets",
        json=payload,
    )
    assert response.status_code == 200, response.text

    vitamin_c = effective_by_id(response.json())["vitamin_c"]

    assert vitamin_c == {
        **vitamin_c,
        "amount": "123.456789",
        "unit": "mg",
        "authority": "manual_override",
        "direction": "target",
        "tracking_mode": "custom",
    }


def test_no_reference_nutrients_default_to_amount_only_without_fabricated_target(
    client: TestClient,
):
    response = client.put(
        "/api/v1/targets",
        json=tracking_payload(),
    )
    assert response.status_code == 200, response.text

    effective = effective_by_id(response.json())

    for nutrient_id in ("epa", "dha"):
        nutrient = effective[nutrient_id]

        assert nutrient["tracking_mode"] == "amount_only"
        assert nutrient["amount"] is None
        assert nutrient["authority"] == "unavailable"
        assert nutrient["reason_code"] == "target_reference_not_established"


def test_explicit_tracking_preference_survives_profile_recalculation(
    client: TestClient,
):
    payload = tracking_payload()

    payload["tracking_preferences"]["protein"] = "ignored"

    initial = client.put(
        "/api/v1/targets",
        json=payload,
    )
    assert initial.status_code == 200, initial.text

    changed = deepcopy(payload)
    changed["profile"]["weight_kg"] = "80"

    recalculated = client.put(
        "/api/v1/targets",
        json=changed,
    )
    assert recalculated.status_code == 200, recalculated.text

    protein = effective_by_id(recalculated.json())["protein"]

    assert protein["tracking_mode"] == "ignored"
    assert protein["amount"] is None
    assert recalculated.json()["tracking_preferences"] == {
        "protein": "ignored",
    }
