from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.operators import phase5c4_control_roles as roles
from app.operators.immutable_provenance_contracts import (
    CURRENT_CONTROL_SCHEMA_REVISION,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    IMMUTABLE_PROVENANCE_CONTROL_ADMISSION_VERSION,
    IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION,
    IMMUTABLE_PROVENANCE_MANIFEST_VERSION,
    IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
    PREVIOUS_CONTROL_SCHEMA_REVISION,
    expected_immutable_provenance_manifest,
    expected_runtime_privilege_manifest,
)
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.resource_membership_contracts import (
    CONSTRAINT_MANIFEST_VERSION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    PREFLIGHT_VERSION,
    expected_constraint_manifest,
)
from tests import test_resource_membership_control_postgres as resource_support


pytestmark = [pytest.mark.phase5c4_control_postgres, pytest.mark.postgres_concurrency]


@dataclass(frozen=True)
class ImmutableControlDatabase:
    database: object
    ops5_manifest_digest: str


def _manifest_digest(database: object) -> str:
    engine = database.database.admin_engine()
    try:
        with engine.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT object_kind, object_signature, definition_digest, "
                        "owning_revision FROM "
                        "phase5c4_control.phase5c4_qualification_v3_catalog_manifest "
                        "ORDER BY object_kind, object_signature"
                    )
                ).mappings()
            ]
        return canonical_digest(rows)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def control_database() -> Generator[ImmutableControlDatabase, None, None]:
    baseline = resource_support.control_database.__wrapped__()
    resource_database = next(baseline)
    ops5_digest = _manifest_digest(resource_database)
    database = resource_database.database
    try:
        upgraded = resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            CURRENT_CONTROL_SCHEMA_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr
        downgraded = resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            PREVIOUS_CONTROL_SCHEMA_REVISION,
        )
        assert downgraded.returncode == 0, downgraded.stderr
        reupgraded = resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            CURRENT_CONTROL_SCHEMA_REVISION,
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        yield ImmutableControlDatabase(resource_database, ops5_digest)
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def _payload() -> dict[str, object]:
    constraints = expected_constraint_manifest()
    immutable_manifest = expected_immutable_provenance_manifest()
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
        "contract_version": IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
        "fence_event_chain_digest": "c" * 64,
        "fence_mode": "closed_prequalification",
        "historical_phase5_schema_revision": HISTORICAL_PHASE5_SCHEMA_REVISION,
        "immutable_provenance_integrity_valid": True,
        "immutable_provenance_manifest": immutable_manifest,
        "immutable_provenance_manifest_digest": canonical_digest(
            immutable_manifest
        ),
        "immutable_provenance_manifest_version": (
            IMMUTABLE_PROVENANCE_MANIFEST_VERSION
        ),
        "local_admission_contract_version": (
            IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION
        ),
        "preflight_contract_version": PREFLIGHT_VERSION,
        "preflight_report_digest": "a" * 64,
        "resource_membership_integrity_valid": True,
        "runtime_privilege_digest": canonical_digest(runtime_privileges),
        "runtime_privileges": runtime_privileges,
        "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
        "target_identity_digest": "b" * 64,
    }
    return {**unsigned, "qualification_digest": canonical_digest(unsigned)}


def _admit(database: object, payload: dict[str, object]) -> dict[str, object]:
    engine = database.database.engine(roles.EXECUTOR_ROLE)
    try:
        with engine.begin() as connection:
            return dict(
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api.admit_immutable_provenance_v1(:artifact)"
                    ),
                    {"artifact": canonical_json(payload).encode("utf-8")},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


def test_ops6_preserves_ops5_manifest_and_qualifies_current_control(
    control_database: ImmutableControlDatabase,
) -> None:
    assert _manifest_digest(control_database.database) == (
        control_database.ops5_manifest_digest
    )
    audit = control_database.database.database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            v4 = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.qualify_control_plane_v4()")
                )
                .mappings()
                .one()
            )
    finally:
        audit.dispose()
    assert v4["control_admission_version"] == (
        IMMUTABLE_PROVENANCE_CONTROL_ADMISSION_VERSION
    )
    assert v4["migration_head"] == CURRENT_CONTROL_SCHEMA_REVISION
    assert v4["qualified"] is True


def test_ops6_admission_is_exact_and_idempotent(
    control_database: ImmutableControlDatabase,
) -> None:
    payload = _payload()
    assert _admit(control_database.database, payload) == {
        "result": "accepted",
        "qualification_digest": payload["qualification_digest"],
    }
    assert _admit(control_database.database, payload) == {
        "result": "idempotent_replay",
        "qualification_digest": payload["qualification_digest"],
    }


@pytest.mark.parametrize(
    "field",
    (
        "constraints",
        "immutable_provenance_manifest",
        "runtime_privileges",
        "resource_membership_integrity_valid",
        "immutable_provenance_integrity_valid",
    ),
)
def test_ops6_rejects_non_authoritative_artifacts(
    control_database: ImmutableControlDatabase,
    field: str,
) -> None:
    payload = json.loads(canonical_json(_payload()))
    payload[field] = False if field.endswith("valid") else []
    unsigned = {
        key: value for key, value in payload.items() if key != "qualification_digest"
    }
    payload["qualification_digest"] = canonical_digest(unsigned)
    with pytest.raises(DBAPIError) as rejected:
        _admit(control_database.database, payload)
    assert getattr(rejected.value.orig, "sqlstate", None) == "22023"


def test_nonempty_ops6_downgrade_fails_forward(
    control_database: ImmutableControlDatabase,
) -> None:
    result = resource_support.historical_support._run_alembic(
        control_database.database.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        PREVIOUS_CONTROL_SCHEMA_REVISION,
    )
    assert result.returncode != 0
