from __future__ import annotations

import pytest

from app import models  # noqa: F401
from app.core.database import Base
from app.migrations import runtime_authority_0033_contracts as contract
from app.operators import phase5c4_roles as roles
from app.operators.current_runtime_authority import (
    CurrentRuntimeAuthorityError,
    assert_current_runtime_model_surface,
)


HISTORICAL_MANIFEST_DIGESTS = {
    "0017_phase5c_indexes": (
        "ca31552e9683b39d0b837bbb0eb3a85ad711e5141df87683c48d3bdd40726abd"
    ),
    "0018_phase5c_promotion_prerequisites": (
        "7b2172fa091d5c596b2c6aae529047cc4de8208a0160712558a41b4439da6be0"
    ),
    "0019_resource_membership_integrity": (
        "466ca2099e04ad69d52f8c842b466227130d0fcd435d9046622e35abb90aee33"
    ),
    "0020_immutable_provenance_enforcement": (
        "5a5bbfa64d94b0c0179f9561ae98c3af44d40f753ef7f3414cedabc72d61335f"
    ),
    "0021_target_activation_execution": (
        "6bb62851d9bb8b858703675909c236fcce66ebb6e06fc4f0029e17c1adf44df9"
    ),
}


def test_every_current_orm_relation_has_an_explicit_authority_classification() -> None:
    assert_current_runtime_model_surface(Base.metadata)
    assert set(Base.metadata.tables) == set(contract.CURRENT_RUNTIME_RELATIONS)


def test_unclassified_orm_relation_fails_the_current_surface_guardrail() -> None:
    copy = Base.metadata.__class__()
    from sqlalchemy import Column, Integer, Table

    Table("future_unclassified_relation", copy, Column("id", Integer, primary_key=True))

    with pytest.raises(
        CurrentRuntimeAuthorityError,
        match="current_runtime_relation_classification_mismatch",
    ):
        assert_current_runtime_model_surface(copy)


def test_current_complete_privileges_and_canary_decision_are_explicit() -> None:
    assert contract.CURRENT_RUNTIME_WRITE_PRIVILEGES[
        contract.COMPLETE_RELATION
    ] == ("DELETE", "INSERT")
    assert contract.COMPLETE_RELATION in contract.CURRENT_RUNTIME_RELATIONS
    assert contract.COMPLETE_RELATION in contract.CURRENT_CANARY_RELATIONS

    profile = roles._revision_role_policy(contract.CURRENT_RUNTIME_AUTHORITY_REVISION)
    assert profile.runtime_writes[contract.COMPLETE_RELATION] == ("DELETE", "INSERT")
    assert contract.COMPLETE_RELATION in profile.runtime_relations
    assert contract.COMPLETE_RELATION in profile.canary_relations
    assert profile.restore_allowed is False

    relation = next(
        item
        for item in roles.build_revision_privilege_manifest(profile.revision)["relations"]
        if item["name"] == contract.COMPLETE_RELATION
    )
    assert relation["grants"] == [
        {"role": roles.CANARY_READ_ROLE, "privileges": ["SELECT"]},
        {"role": roles.QUALIFIER_ROLE, "privileges": ["SELECT"]},
        {"role": roles.RUNTIME_READ_ROLE, "privileges": ["SELECT"]},
        {"role": roles.RUNTIME_WRITE_ROLE, "privileges": ["DELETE", "INSERT"]},
    ]


def test_current_sql_contract_is_exact_and_negative() -> None:
    admission = contract.current_runtime_admission_sql()
    sync = contract.current_write_state_sync_sql()

    for privilege in ("SELECT", "INSERT", "DELETE"):
        assert (
            "'nutrition_runtime', 'public.daily_log_day_completions', "
            f"'{privilege}') IS true"
        ) in admission
    for privilege in ("UPDATE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert (
            "'nutrition_runtime', 'public.daily_log_day_completions', "
            f"'{privilege}') IS false"
        ) in admission

    assert "GRANT DELETE, INSERT ON TABLE public.daily_log_day_completions" in sync
    assert "REVOKE DELETE, INSERT ON TABLE public.daily_log_day_completions" in sync
    assert "CREATE TRIGGER phase5c_write_fence_gate" in sync
    assert "ALTER DEFAULT PRIVILEGES" not in sync
    assert "GRANT ALL" not in sync


@pytest.mark.parametrize(
    ("revision", "digest"),
    HISTORICAL_MANIFEST_DIGESTS.items(),
)
def test_frozen_historical_role_policy_manifests_are_unchanged(
    revision: str,
    digest: str,
) -> None:
    assert roles.revision_privilege_manifest_digest(revision) == digest
