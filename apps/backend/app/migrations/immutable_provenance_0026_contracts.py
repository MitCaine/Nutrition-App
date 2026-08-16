"""Revision-scoped immutable-validator evidence for application head 0026."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from app.migrations.immutable_provenance_0025_contracts import (
    EXACT_0025_FUNCTION_DEFINITION_SHA256,
    EXPECTED_0025_ACTIVATION_V4_EXECUTE_ACL,
    EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES,
    EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES,
    immutable_validator_0025_sql,
)


EXPECTED_0026_APPLICATION_HEAD = "0026_food_nutrient_integrity"

EXPECTED_0026_RUNTIME_RELATION_PRIVILEGES = (
    EXPECTED_0025_RUNTIME_RELATION_PRIVILEGES
)
EXPECTED_0026_RUNTIME_EXECUTE_ROUTINES = (
    EXPECTED_0025_RUNTIME_EXECUTE_ROUTINES
)
EXPECTED_0026_ACTIVATION_V4_EXECUTE_ACL = (
    EXPECTED_0025_ACTIVATION_V4_EXECUTE_ACL
)

# Frozen from PostgreSQL 16 pg_get_functiondef after 0026 installation.
# No immutable-provenance routine other than the validator changes in 0026.
EXACT_0026_FUNCTION_DEFINITION_SHA256: Mapping[str, str] = MappingProxyType(
    {
        **EXACT_0025_FUNCTION_DEFINITION_SHA256,
        "phase0020_immutable_provenance_integrity_valid": (
            "46c775ac4a829612ac5870b15939b5ee87354d173a63cc2b0d024864d860ef02"
        ),
    }
)


def immutable_validator_0026_sql(
    *,
    expected_application_head: str = EXPECTED_0026_APPLICATION_HEAD,
    expected_runtime_relation_privileges: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = EXPECTED_0026_RUNTIME_RELATION_PRIVILEGES,
    expected_runtime_execute_routines: tuple[
        str, ...
    ] = EXPECTED_0026_RUNTIME_EXECUTE_ROUTINES,
    function_definition_sha256: Mapping[
        str, str
    ] = EXACT_0026_FUNCTION_DEFINITION_SHA256,
) -> str:
    """Render the current validator from explicit revision-0026 inputs."""

    return immutable_validator_0025_sql(
        expected_application_head=expected_application_head,
        expected_runtime_relation_privileges=(
            expected_runtime_relation_privileges
        ),
        expected_runtime_execute_routines=(
            expected_runtime_execute_routines
        ),
        function_definition_sha256=function_definition_sha256,
    )
