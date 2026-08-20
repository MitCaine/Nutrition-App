"""Current PostgreSQL runtime-authority projection and ORM guardrail."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import Connection, MetaData

from app.migrations.runtime_authority_0033_contracts import (
    CURRENT_CANARY_RELATIONS,
    CURRENT_PUBLIC_RELATIONS,
    CURRENT_RUNTIME_AUTHORITY_REVISION,
    CURRENT_RUNTIME_RELATIONS,
    CURRENT_RUNTIME_WRITE_PRIVILEGES,
)


class CurrentRuntimeAuthorityError(RuntimeError):
    """The current runtime model or physical authority differs from policy."""


def assert_current_runtime_model_surface(metadata: MetaData) -> None:
    """Require every current ORM table to have an explicit authority decision."""

    models = set(metadata.tables)
    declared = set(CURRENT_RUNTIME_RELATIONS)
    if models != declared:
        missing = sorted(models - declared)
        stale = sorted(declared - models)
        raise CurrentRuntimeAuthorityError(
            f"current_runtime_relation_classification_mismatch:missing={missing}:stale={stale}"
        )
    if not set(CURRENT_RUNTIME_WRITE_PRIVILEGES) <= declared:
        raise CurrentRuntimeAuthorityError("current_runtime_write_relation_unclassified")
    if not set(CURRENT_CANARY_RELATIONS) <= declared:
        raise CurrentRuntimeAuthorityError("current_canary_relation_unclassified")
    if not declared <= set(CURRENT_PUBLIC_RELATIONS):
        raise CurrentRuntimeAuthorityError("current_public_relation_classification_incomplete")


def qualify_current_runtime_authority(
    connection: Connection,
    *,
    expected_state: Literal["normal", "maintenance"],
) -> dict[str, object]:
    """Return exact Phase 5C role-policy evidence for the current revision."""

    # Lazy import keeps the immutable current declaration independent from the
    # role-policy integration module that consumes it.
    from app.operators.phase5c4_roles import qualify_source_role_policy

    evidence = qualify_source_role_policy(
        connection,
        expected_state=expected_state,
        policy_revision=CURRENT_RUNTIME_AUTHORITY_REVISION,
    )
    if evidence.get("qualified") is not True:
        raise CurrentRuntimeAuthorityError("current_runtime_authority_not_exact")
    return evidence
