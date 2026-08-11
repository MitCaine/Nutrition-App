"""Revision-scoped immutable-validator evidence for application head 0025."""

from __future__ import annotations

from importlib import import_module
from types import MappingProxyType
from typing import Mapping

from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
)
from app.operators.resource_membership_contracts import (
    FROZEN_RUNTIME_EXECUTE_ROUTINES as FROZEN_0019_RUNTIME_EXECUTE_ROUTINES,
    FROZEN_RUNTIME_RELATION_PRIVILEGES as FROZEN_0019_RUNTIME_RELATION_PRIVILEGES,
)


EXPECTED_0025_APPLICATION_HEAD = "0025_immutable_validator_head"
_SNAPSHOT_REPLACEMENT_ROUTINE = (
    "public.phase0020_delete_log_snapshots_for_replacement(uuid, uuid)"
)
_LOCAL_ADMISSION_V3_ROUTINE = "public.phase5c_local_admission_v3()"
EXPECTED_0025_ACTIVATION_V4_ROUTINE = "public.phase5c_local_admission_v4()"
_HISTORICAL_0020_RUNTIME_RELATION_PRIVILEGES = tuple(
    (
        relation,
        tuple(
            privilege
            for privilege in privileges
            if not (
                relation == "daily_log_nutrient_snapshots"
                and privilege == "DELETE"
            )
        ),
    )
    for relation, privileges in FROZEN_0019_RUNTIME_RELATION_PRIVILEGES
)
_HISTORICAL_0020_RUNTIME_EXECUTE_ROUTINES = tuple(
    sorted(
        (
            *FROZEN_0019_RUNTIME_EXECUTE_ROUTINES,
            _SNAPSHOT_REPLACEMENT_ROUTINE,
            _LOCAL_ADMISSION_V3_ROUTINE,
        )
    )
)
EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES = tuple(
    (relation, tuple(privileges))
    for relation, privileges in _HISTORICAL_0020_RUNTIME_RELATION_PRIVILEGES
)
EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES = tuple(
    sorted(
        (
            *_HISTORICAL_0020_RUNTIME_EXECUTE_ROUTINES,
            EXPECTED_0025_ACTIVATION_V4_ROUTINE,
        )
    )
)
EXPECTED_0025_ACTIVATION_V4_EXECUTE_ACL = (
    ("nutrition_canary", False),
    ("nutrition_owner", False),
    ("nutrition_runtime", False),
)

# The validator hash is frozen from PostgreSQL 16 pg_get_functiondef after the
# migration is installed. No other immutable-provenance routine changes in 0025.
EXACT_0025_FUNCTION_DEFINITION_SHA256: Mapping[str, str] = MappingProxyType(
    {
        **EXACT_0024_FUNCTION_DEFINITION_SHA256,
        "phase0020_immutable_provenance_integrity_valid": (
            "59a0bc3d25b6bb99f01bd3629edac86a50c7ec0c216337ea02ea5622be2746bb"
        ),
    }
)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _relation_values(values: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    return ",\n".join(
        f"({_literal(relation)},{_literal(privilege)})"
        for relation, privileges in values
        for privilege in privileges
    )


def immutable_validator_0025_sql(
    *,
    expected_application_head: str = EXPECTED_0025_APPLICATION_HEAD,
    expected_runtime_relation_privileges: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES,
    expected_runtime_execute_routines: tuple[
        str, ...
    ] = EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES,
    function_definition_sha256: Mapping[
        str, str
    ] = EXACT_0025_FUNCTION_DEFINITION_SHA256,
) -> str:
    """Render the current validator from explicit revision-0025 inputs."""

    historical = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    rendered = historical._immutable_validator_sql(  # noqa: SLF001
        function_definition_sha256=function_definition_sha256,
    )
    old_head = "version_num = '0020_immutable_provenance_enforcement'"
    new_head = f"version_num = '{expected_application_head}'"
    if rendered.count(old_head) != 1:
        raise RuntimeError("immutable_validator_0025_head_replacement_invalid")
    rendered = rendered.replace(old_head, new_head, 1)
    historical_relations = _relation_values(
        tuple(
            (relation, tuple(privileges))
            for relation, privileges in _HISTORICAL_0020_RUNTIME_RELATION_PRIVILEGES
        )
    )
    current_relations = _relation_values(expected_runtime_relation_privileges)
    if rendered.count(historical_relations) != 1:
        raise RuntimeError("immutable_validator_0025_relation_replacement_invalid")
    rendered = rendered.replace(historical_relations, current_relations, 1)
    historical_execute = _array(_HISTORICAL_0020_RUNTIME_EXECUTE_ROUTINES)
    current_execute = _array(expected_runtime_execute_routines)
    if rendered.count(historical_execute) != 1:
        raise RuntimeError("immutable_validator_0025_execute_replacement_invalid")
    rendered = rendered.replace(historical_execute, current_execute, 1)
    create = (
        "CREATE FUNCTION public."
        "phase0020_immutable_provenance_integrity_valid()"
    )
    replace = (
        "CREATE OR REPLACE FUNCTION public."
        "phase0020_immutable_provenance_integrity_valid()"
    )
    if rendered.count(create) != 1:
        raise RuntimeError("immutable_validator_0025_create_replacement_invalid")
    return rendered.replace(create, replace, 1)
