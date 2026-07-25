from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.resource_membership_contracts import (
    CONSTRAINT_MANIFEST_VERSION,
    CONTROL_ADMISSION_VERSION,
    CURRENT_CONTROL_SCHEMA_REVISION,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    LOCAL_ADMISSION_VERSION,
    PREFLIGHT_VERSION,
    QUALIFICATION_VERSION,
    expected_constraint_manifest,
    expected_runtime_privilege_manifest,
)
from tests import test_phase5c4_control_postgres as historical_support


pytestmark = [pytest.mark.phase5c4_control_postgres, pytest.mark.postgres_concurrency]


@dataclass(frozen=True)
class ResourceMembershipControlDatabase:
    database: historical_support.ControlDatabase
    historical_manifest_digest: str


def _historical_manifest_digest(database: historical_support.ControlDatabase) -> str:
    engine = database.admin_engine()
    try:
        with engine.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT object_kind, object_signature, definition_digest, "
                        "owning_revision FROM "
                        "phase5c4_control.phase5c4_qualification_v2_catalog_manifest "
                        "ORDER BY object_kind, object_signature"
                    )
                ).mappings()
            ]
        return canonical_digest(rows)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def control_database() -> Generator[ResourceMembershipControlDatabase, None, None]:
    baseline = historical_support.control_database.__wrapped__()
    database = next(baseline)
    historical_digest = _historical_manifest_digest(database)
    try:
        upgraded = historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            CURRENT_CONTROL_SCHEMA_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr

        # Empty downgrade is the only supported rollback.  Exercise it before
        # this suite records an immutable current admission, then return to head.
        downgraded = historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            historical_support.HISTORICAL_CONTROL_HEAD,
        )
        assert downgraded.returncode == 0, downgraded.stderr
        reupgraded = historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            CURRENT_CONTROL_SCHEMA_REVISION,
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        yield ResourceMembershipControlDatabase(database, historical_digest)
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def _qualification_payload() -> dict[str, object]:
    constraints = expected_constraint_manifest()
    runtime_privileges = expected_runtime_privilege_manifest()
    unsigned: dict[str, object] = {
        "blocking_category_count": 0,
        "blocking_row_count": 0,
        "constraint_manifest_digest": canonical_digest(
            {
                "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
                "constraints": constraints,
            }
        ),
        "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
        "constraints": constraints,
        "contract_version": QUALIFICATION_VERSION,
        "fence_event_chain_digest": "e" * 64,
        "fence_mode": "closed_prequalification",
        "historical_phase5_schema_revision": HISTORICAL_PHASE5_SCHEMA_REVISION,
        "local_admission_contract_version": LOCAL_ADMISSION_VERSION,
        "preflight_contract_version": PREFLIGHT_VERSION,
        "preflight_report_digest": "p" * 64,
        "runtime_privilege_digest": canonical_digest(runtime_privileges),
        "runtime_privileges": runtime_privileges,
        "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
        "target_identity_digest": "t" * 64,
    }
    # Replace the non-hex visual labels before computing the canonical self-digest.
    unsigned["preflight_report_digest"] = "a" * 64
    unsigned["target_identity_digest"] = "b" * 64
    return {**unsigned, "qualification_digest": canonical_digest(unsigned)}


def _admit(
    database: historical_support.ControlDatabase,
    payload: dict[str, object],
) -> dict[str, object]:
    engine = database.engine(roles.EXECUTOR_ROLE)
    try:
        with engine.begin() as connection:
            return dict(
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api.admit_resource_membership_v1(:artifact)"
                    ),
                    {"artifact": canonical_json(payload).encode("utf-8")},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


def test_ops5_versions_control_qualification_without_rewriting_v2_manifest(
    control_database: ResourceMembershipControlDatabase,
) -> None:
    database = control_database.database
    assert _historical_manifest_digest(database) == (
        control_database.historical_manifest_digest
    )
    audit = database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            v2 = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()")
                )
                .mappings()
                .one()
            )
            v3 = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.qualify_control_plane_v3()")
                )
                .mappings()
                .one()
            )
    finally:
        audit.dispose()

    assert v2["qualified"] is False
    assert v3["control_admission_version"] == CONTROL_ADMISSION_VERSION
    assert v3["migration_head"] == CURRENT_CONTROL_SCHEMA_REVISION
    assert v3["qualified"] is True


def test_current_control_admission_is_exact_and_idempotent(
    control_database: ResourceMembershipControlDatabase,
) -> None:
    payload = _qualification_payload()

    first = _admit(control_database.database, payload)
    replay = _admit(control_database.database, payload)

    assert first == {
        "result": "accepted",
        "qualification_digest": payload["qualification_digest"],
    }
    assert replay == {
        "result": "idempotent_replay",
        "qualification_digest": payload["qualification_digest"],
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(blocking_row_count="0"),
        lambda value: value.update(constraints=[]),
        lambda value: value.update(runtime_privileges={}),
        lambda value: value.update(schema_revision=HISTORICAL_PHASE5_SCHEMA_REVISION),
        lambda value: value.update(fence_mode="closed_incident"),
    ),
)
def test_current_control_admission_rejects_non_authoritative_artifacts(
    control_database: ResourceMembershipControlDatabase,
    mutate,
) -> None:
    payload = json.loads(canonical_json(_qualification_payload()))
    mutate(payload)
    unsigned = {key: value for key, value in payload.items() if key != "qualification_digest"}
    payload["qualification_digest"] = canonical_digest(unsigned)

    with pytest.raises(DBAPIError) as rejected:
        _admit(control_database.database, payload)

    assert getattr(rejected.value.orig, "sqlstate", None) == "22023"


def test_nonempty_ops5_downgrade_fails_forward(
    control_database: ResourceMembershipControlDatabase,
) -> None:
    result = historical_support._run_alembic(
        control_database.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        historical_support.HISTORICAL_CONTROL_HEAD,
    )

    assert result.returncode != 0
    engine = control_database.database.admin_engine()
    try:
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT version_num FROM "
                    "phase5c4_control.phase5c4_alembic_version"
                )
            ) == CURRENT_CONTROL_SCHEMA_REVISION
    finally:
        engine.dispose()
