from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_roles as roles


def test_privilege_manifest_is_exact_versioned_and_canonical() -> None:
    manifest = roles.build_privilege_manifest()

    assert roles.validate_privilege_manifest(manifest) == manifest
    assert roles.serialize_privilege_manifest(manifest) == canonical.canonical_json(manifest)
    assert manifest["manifest_version"] == "phase5c4_postgresql_privilege_manifest_v1"
    assert manifest["role_policy_version"] == "phase5c4_postgresql_role_policy_v1"
    assert manifest["deployment_scope"] == "phase5c4_controlled_portfolio_demo_v1"
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    assert manifest["manifest_digest"] == canonical.canonical_digest(unsigned)


def test_every_contract_serialization_uses_shared_canonical_authority(monkeypatch) -> None:
    calls = []
    original = canonical.canonical_json

    def observed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(canonical, "canonical_json", observed)
    roles.serialize_privilege_manifest()

    # Validation recomputes both candidate and authority digests before the final
    # serialization; every pass still crosses the one shared implementation.
    assert len(calls) == 3
    assert calls[-1] == roles.PRIVILEGE_MANIFEST


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("deployment_scope",), "different_scope"),
        (("database", "public_privileges"), ["CONNECT"]),
        (("relations", 0, "grants", 0, "privileges"), ["SELECT", "UPDATE"]),
        (("prohibited", "grant_all"), False),
        (("manifest_digest",), "0" * 64),
    ],
)
def test_privilege_manifest_tampering_fails_closed(path, replacement) -> None:
    payload = deepcopy(roles.PRIVILEGE_MANIFEST)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(roles.Phase5C4RoleError):
        roles.validate_privilege_manifest(payload)


def test_runtime_write_manifest_preserves_immutable_surfaces() -> None:
    assert roles.RUNTIME_WRITE_PRIVILEGES == {
        "create_operation_idempotency": ("INSERT", "UPDATE"),
        "daily_log_nutrient_snapshots": ("DELETE", "INSERT"),
        "daily_logs": ("DELETE", "INSERT", "UPDATE"),
        "food_favorites": ("DELETE", "INSERT"),
        "food_items": ("INSERT", "UPDATE"),
        "food_nutrients": ("DELETE", "INSERT", "UPDATE"),
        "food_sources": ("DELETE", "INSERT", "UPDATE"),
        "nutrition_targets": ("DELETE", "INSERT", "UPDATE"),
        "ocr_nutrition_confirmation_traces": ("INSERT",),
        "recipe_ingredients": ("DELETE", "INSERT", "UPDATE"),
        "recipe_publication_amount_definitions": ("INSERT",),
        "recipe_publication_nutrients": ("INSERT",),
        "recipe_publication_revisions": ("INSERT",),
        "recipes": ("INSERT", "UPDATE"),
        "serving_definitions": ("DELETE", "INSERT", "UPDATE"),
        "user_profiles": ("DELETE", "INSERT", "UPDATE"),
        "users": ("INSERT",),
    }
    assert roles.RUNTIME_WRITE_PRIVILEGES["recipe_publication_revisions"] == ("INSERT",)
    assert roles.RUNTIME_WRITE_PRIVILEGES["recipe_publication_amount_definitions"] == (
        "INSERT",
    )
    assert roles.RUNTIME_WRITE_PRIVILEGES["recipe_publication_nutrients"] == ("INSERT",)
    assert roles.RUNTIME_WRITE_PRIVILEGES["daily_log_nutrient_snapshots"] == (
        "DELETE",
        "INSERT",
    )
    assert "nutrients" not in roles.RUNTIME_WRITE_PRIVILEGES
    assert not set(roles.RETAINED_RELATIONS) & set(roles.RUNTIME_RELATIONS)
    assert "create_operation_idempotency" not in roles.CANARY_RELATIONS
    assert "food_favorites" not in roles.CANARY_RELATIONS


def test_role_attribute_and_membership_contract_is_exact() -> None:
    assert roles.ROLE_ATTRIBUTES[roles.OWNER_ROLE] == {"login": False, "inherit": False}
    assert roles.ROLE_ATTRIBUTES[roles.MIGRATOR_ROLE] == {"login": True, "inherit": False}
    assert roles.ROLE_ATTRIBUTES[roles.RUNTIME_ROLE] == {"login": True, "inherit": True}
    assert roles.ROLE_SETTINGS[roles.CANARY_ROLE] == (
        "default_transaction_read_only=on",
    )
    assert roles.ROLE_SETTINGS[roles.QUALIFIER_ROLE] == (
        "default_transaction_read_only=on",
    )
    assert roles.EXPECTED_MEMBERSHIPS == {
        roles.Membership("nutrition_owner", "nutrition_migrator", False, False, True),
        roles.Membership("nutrition_runtime_read", "nutrition_runtime", False, True, False),
        roles.Membership("nutrition_runtime_write", "nutrition_runtime", False, True, False),
        roles.Membership("nutrition_canary_read", "nutrition_canary", False, True, False),
        roles.Membership("pg_signal_backend", "nutrition_ops", False, True, False),
    }


def _eligibility_fixture() -> dict:
    unsigned = {
        "contract_version": roles.SOURCE_ELIGIBILITY_VERSION,
        "deployment_scope": roles.DEPLOYMENT_SCOPE,
        "role_policy_version": roles.ROLE_POLICY_VERSION,
        "privilege_manifest_version": roles.PRIVILEGE_MANIFEST_VERSION,
        "privilege_manifest_digest": roles.PRIVILEGE_MANIFEST_DIGEST,
        "database_identity_digest": canonical.canonical_digest({"database": "fixture"}),
        "expected_state": "normal",
        "archive_schema_digests": [],
        "checks": [
            {
                "check_code": check_code,
                "passed": True,
                "observation_digest": canonical.canonical_digest(
                    {"check_code": check_code, "passed": True}
                ),
            }
            for check_code in sorted(roles.ELIGIBILITY_CHECK_CODES)
        ],
        "reason_codes": [],
        "qualified": True,
    }
    return {
        **unsigned,
        "qualification_digest": canonical.canonical_digest(unsigned),
    }


def test_source_eligibility_contract_is_strict_and_tamper_evident() -> None:
    evidence = _eligibility_fixture()
    assert roles.validate_source_eligibility(evidence) == evidence
    assert roles.serialize_source_eligibility(evidence) == canonical.canonical_json(evidence)

    for mutation in ("reason", "observation", "decision", "self_digest"):
        tampered = deepcopy(evidence)
        if mutation == "reason":
            tampered["reason_codes"] = ["role_attribute_mismatch"]
        elif mutation == "observation":
            tampered["checks"][0]["observation_digest"] = "0" * 64
        elif mutation == "decision":
            tampered["qualified"] = False
        else:
            tampered["qualification_digest"] = "f" * 64
        with pytest.raises(roles.Phase5C4RoleError):
            roles.validate_source_eligibility(tampered)

    incomplete = deepcopy(evidence)
    incomplete["checks"].pop()
    incomplete_unsigned = {
        key: value for key, value in incomplete.items() if key != "qualification_digest"
    }
    incomplete["qualification_digest"] = canonical.canonical_digest(incomplete_unsigned)
    with pytest.raises(roles.Phase5C4RoleError, match="check set is incomplete"):
        roles.validate_source_eligibility(incomplete)

    duplicate_archive = deepcopy(evidence)
    archive_digest = canonical.canonical_digest({"archive": "fixture"})
    duplicate_archive["archive_schema_digests"] = [archive_digest, archive_digest]
    duplicate_unsigned = {
        key: value
        for key, value in duplicate_archive.items()
        if key != "qualification_digest"
    }
    duplicate_archive["qualification_digest"] = canonical.canonical_digest(
        duplicate_unsigned
    )
    with pytest.raises(roles.Phase5C4RoleError, match="archive digests are invalid"):
        roles.validate_source_eligibility(duplicate_archive)

    multiple_archives = deepcopy(evidence)
    multiple_archives["archive_schema_digests"] = sorted(
        [
            canonical.canonical_digest({"archive": "first"}),
            canonical.canonical_digest({"archive": "second"}),
        ]
    )
    multiple_unsigned = {
        key: value
        for key, value in multiple_archives.items()
        if key != "qualification_digest"
    }
    multiple_archives["qualification_digest"] = canonical.canonical_digest(
        multiple_unsigned
    )
    assert roles.validate_source_eligibility(multiple_archives) == multiple_archives


class _FakeConnection:
    def __init__(self, session_user: str, database_owner: str = roles.OWNER_ROLE):
        self.dialect = SimpleNamespace(name="postgresql")
        self.session_user = session_user
        self.current_user = session_user
        self.database_owner = database_owner
        self.statements: list[str] = []

    def scalar(self, statement):
        sql = str(statement)
        if "session_user" in sql:
            return self.session_user
        if "current_user" in sql:
            return self.current_user
        if "FROM pg_catalog.pg_database" in sql:
            return self.database_owner
        raise AssertionError(sql)

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql == "SET ROLE nutrition_owner":
            self.current_user = "nutrition_owner"


def test_migrator_explicitly_assumes_owner_but_runtime_is_rejected() -> None:
    migrator = _FakeConnection(roles.MIGRATOR_ROLE)
    roles.assume_migration_owner(migrator)
    assert migrator.statements == ["SET ROLE nutrition_owner"]

    with pytest.raises(roles.Phase5C4RoleError, match="Only nutrition_migrator"):
        roles.assume_migration_owner(_FakeConnection(roles.RUNTIME_ROLE))
    with pytest.raises(roles.Phase5C4RoleError, match="Only nutrition_migrator"):
        roles.assume_migration_owner(_FakeConnection("bootstrap_admin"))


def test_manifest_contains_no_implicit_sequence_or_future_object_grants() -> None:
    defaults = roles.PRIVILEGE_MANIFEST["default_privileges"]
    assert roles.PRIVILEGE_MANIFEST["sequences"] == []
    assert defaults["tables"] == []
    assert defaults["sequences"] == []
    assert defaults["routines"] == []
    assert defaults["types"] == []
    assert defaults["rule"] == "fail_closed_until_manifest_and_explicit_grants_are_updated"


@pytest.mark.parametrize(
    ("quiet", "timeout", "poll"),
    [
        (-1.0, 30.0, 0.1),
        (31.0, 30.0, 0.1),
        (0.0, 0.0, 0.1),
        (0.0, 30.0, -1.0),
        (float("nan"), 30.0, 0.1),
        (0.0, float("inf"), 0.1),
    ],
)
def test_session_drain_timing_is_finite_and_bounded(quiet, timeout, poll) -> None:
    with pytest.raises(roles.Phase5C4RoleError, match="timing values"):
        roles._validate_drain_timing(
            quiet_period_seconds=quiet,
            drain_timeout_seconds=timeout,
            poll_interval_seconds=poll,
        )

    roles._validate_drain_timing(
        quiet_period_seconds=2.0,
        drain_timeout_seconds=30.0,
        poll_interval_seconds=0.1,
    )
