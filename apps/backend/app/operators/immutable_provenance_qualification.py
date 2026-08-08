"""Independent 0020 immutable-provenance qualification and admission."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.immutable_provenance_contracts import (
    APPEND_ONLY_TABLES,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    FUNCTION_DEFINITION_SHA256,
    IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION,
    IMMUTABLE_PROVENANCE_MANIFEST_VERSION,
    IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
    MIGRATION_ADVISORY_LOCK_KEY,
    POSTGRES_TRIGGER_CONTRACTS,
    ROUTINE_CONTRACTS,
    SNAPSHOT_REPLACEMENT_FUNCTION,
    expected_immutable_provenance_manifest,
    expected_runtime_privilege_manifest,
)
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.phase5c4_prerequisites import (
    Phase5C4PrerequisiteError,
    validate_prerequisite_observation,
)
from app.operators.resource_membership_contracts import (
    CONSTRAINT_MANIFEST_VERSION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    PREFLIGHT_VERSION,
    expected_constraint_manifest,
)
from app.operators.resource_membership_preflight import (
    ResourceMembershipPreflightError,
    assert_no_blocking_findings,
)
from app.operators.resource_membership_qualification import (
    ResourceMembershipQualificationError,
    qualify_constraint_manifest,
)


_DEPLOYABLE_FENCE_MODES = {"closed_prequalification", "closed_cutover"}
_TABLE_PRIVILEGES = (
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)
_MANAGED_EXECUTE_ROLES = (
    "nutrition_canary",
    "nutrition_migrator",
    "nutrition_ops",
    "nutrition_qualifier",
    "nutrition_runtime",
)


class ImmutableProvenanceQualificationError(RuntimeError):
    """Stable fail-closed immutable-provenance qualification boundary."""


@dataclass(frozen=True)
class ImmutableProvenanceQualification:
    payload: Mapping[str, Any]

    @property
    def qualification_digest(self) -> str:
        return str(self.payload["qualification_digest"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")


def _routine_acl(connection: Connection, oid: int) -> list[dict[str, object]]:
    return [
        {
            "role": str(row["role_name"]),
            "grantable": bool(row["is_grantable"]),
        }
        for row in connection.execute(
            text(
                """
                SELECT CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                            ELSE grantee.rolname::text END AS role_name,
                       acl.is_grantable
                FROM pg_catalog.pg_proc AS routine
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        routine.proacl,
                        pg_catalog.acldefault('f', routine.proowner)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = acl.grantee
                WHERE routine.oid = :oid
                  AND acl.privilege_type = 'EXECUTE'
                ORDER BY role_name
                """
            ),
            {"oid": oid},
        ).mappings()
    ]


def _qualify_trigger_manifest(connection: Connection) -> list[dict[str, object]]:
    observed: list[dict[str, object]] = []
    event_bits = {"DELETE": 8, "INSERT": 4, "UPDATE": 16, "TRUNCATE": 32}
    for contract in POSTGRES_TRIGGER_CONTRACTS:
        row = (
            connection.execute(
                text(
                    """
                    SELECT trigger.tgtype::integer AS trigger_type,
                           trigger.tgenabled::text AS enabled,
                           trigger.tgisinternal AS internal,
                           trigger.tgconstraint <> 0 AS is_constraint,
                           COALESCE(constraint_value.condeferrable, false)
                               AS is_deferrable,
                           COALESCE(constraint_value.condeferred, false)
                               AS is_initially_deferred,
                           relation.relname::text AS table_name,
                           routine.proname::text AS function_name
                    FROM pg_catalog.pg_trigger AS trigger
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.oid = trigger.tgrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_proc AS routine
                      ON routine.oid = trigger.tgfoid
                    LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                      ON constraint_value.oid = trigger.tgconstraint
                    WHERE namespace.nspname = 'public'
                      AND trigger.tgname = :name
                    """
                ),
                {"name": contract.name},
            )
            .mappings()
            .one_or_none()
        )
        expected_type = (
            sum(event_bits[event] for event in contract.events)
            + (2 if contract.timing == "BEFORE" else 0)
            + (1 if contract.orientation == "ROW" else 0)
        )
        if (
            row is None
            or int(row["trigger_type"]) != expected_type
            or str(row["enabled"]) != "O"
            or bool(row["internal"])
            or str(row["table_name"]) != contract.table
            or str(row["function_name"]) != contract.function
            or bool(row["is_constraint"]) != contract.constraint
            or bool(row["is_deferrable"]) != contract.deferrable
            or bool(row["is_initially_deferred"]) != contract.initially_deferred
        ):
            raise ImmutableProvenanceQualificationError(
                "immutable_provenance_trigger_manifest_invalid"
            )
        observed.append(
            {
                "name": contract.name,
                "table": contract.table,
                "function": contract.function,
                "events": list(contract.events),
                "timing": contract.timing,
                "orientation": contract.orientation,
                "constraint": contract.constraint,
                "deferrable": contract.deferrable,
                "initially_deferred": contract.initially_deferred,
                "enabled": "origin",
            }
        )
    installed_names = tuple(
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT trigger.tgname::text
                FROM pg_catalog.pg_trigger AS trigger
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = trigger.tgrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND NOT trigger.tgisinternal
                  AND trigger.tgname LIKE 'phase0020_%'
                ORDER BY trigger.tgname
                """
            )
        )
    )
    if installed_names != tuple(sorted(item.name for item in POSTGRES_TRIGGER_CONTRACTS)):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_trigger_manifest_invalid"
        )
    return observed


def _qualify_routine_manifest(connection: Connection) -> list[dict[str, object]]:
    observed: list[dict[str, object]] = []
    volatility_names = {"v": "volatile", "s": "stable", "i": "immutable"}
    for contract in ROUTINE_CONTRACTS:
        row = (
            connection.execute(
                text(
                    """
                    SELECT routine.oid::bigint AS oid,
                           owner.rolname::text AS owner_name,
                           language.lanname::text AS language_name,
                           routine.prokind::text AS routine_kind,
                           routine.provolatile::text AS volatility,
                           routine.prosecdef AS security_definer,
                           routine.proleakproof AS leakproof,
                           routine.proparallel::text AS parallel_safety,
                           routine.proisstrict AS is_strict,
                           routine.proretset AS returns_set,
                           pg_catalog.pg_get_function_identity_arguments(
                               routine.oid
                           )::text AS identity_arguments,
                           pg_catalog.pg_get_function_result(routine.oid)::text
                               AS result_type,
                           routine.proconfig::text[] AS configuration,
                           pg_catalog.pg_get_functiondef(routine.oid)::text
                               AS definition
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = routine.proowner
                    JOIN pg_catalog.pg_language AS language
                      ON language.oid = routine.prolang
                    WHERE namespace.nspname = 'public'
                      AND routine.proname = :name
                      AND pg_catalog.pg_get_function_identity_arguments(
                            routine.oid
                          ) = :arguments
                    """
                ),
                {"name": contract.name, "arguments": contract.identity_arguments},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ImmutableProvenanceQualificationError(
                "immutable_provenance_routine_manifest_invalid"
            )
        observed.append(
            {
                "name": contract.name,
                "schema": "public",
                "identity_arguments": str(row["identity_arguments"]),
                "result": str(row["result_type"]),
                "owner": str(row["owner_name"]),
                "language": str(row["language_name"]),
                "kind": "function" if str(row["routine_kind"]) == "f" else "invalid",
                "volatility": volatility_names.get(str(row["volatility"]), "invalid"),
                "security_definer": bool(row["security_definer"]),
                "leakproof": bool(row["leakproof"]),
                "parallel": (
                    "unsafe" if str(row["parallel_safety"]) == "u" else "invalid"
                ),
                "strict": bool(row["is_strict"]),
                "returns_set": bool(row["returns_set"]),
                "config": list(row["configuration"] or []),
                "definition_sha256": sha256(
                    str(row["definition"]).encode("utf-8")
                ).hexdigest(),
                "execute_acl": _routine_acl(connection, int(row["oid"])),
            }
        )
    installed = tuple(
        (str(row["routine_name"]), str(row["identity_arguments"]))
        for row in connection.execute(
            text(
                """
                SELECT routine.proname::text AS routine_name,
                       pg_catalog.pg_get_function_identity_arguments(
                            routine.oid
                       )::text AS identity_arguments
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = routine.pronamespace
                WHERE namespace.nspname = 'public'
                  AND (
                    routine.proname LIKE 'phase0020_%'
                    OR routine.proname = 'phase5c_local_admission_v3'
                  )
                ORDER BY routine.proname, identity_arguments
                """
            )
        ).mappings()
    )
    expected_installed = tuple(
        sorted((item.name, item.identity_arguments) for item in ROUTINE_CONTRACTS)
    )
    if installed != expected_installed:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_routine_manifest_invalid"
        )
    return observed


def qualify_immutable_provenance_manifest(
    connection: Connection,
    *,
    function_definition_sha256: Mapping[str, str] = FUNCTION_DEFINITION_SHA256,
) -> dict[str, object]:
    expected = expected_immutable_provenance_manifest(
        function_definition_sha256=function_definition_sha256,
    )
    table_names = [
        str(item["table"])
        for item in expected["protected_tables"]  # type: ignore[index]
    ]
    wrong_owner_count = int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_roles AS owner
                  ON owner.oid = relation.relowner
                WHERE namespace.nspname = 'public'
                  AND relation.relname = ANY(CAST(:tables AS text[]))
                  AND owner.rolname <> 'nutrition_owner'
                """
            ),
            {"tables": table_names},
        )
        or 0
    )
    if wrong_owner_count:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_table_owner_invalid"
        )
    actual = {
        "manifest_version": IMMUTABLE_PROVENANCE_MANIFEST_VERSION,
        "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
        "protected_tables": expected["protected_tables"],
        "postgresql_triggers": _qualify_trigger_manifest(connection),
        "routines": _qualify_routine_manifest(connection),
        "snapshot_delete_contract": expected["snapshot_delete_contract"],
        "sqlite_triggers": expected["sqlite_triggers"],
    }
    if actual != expected:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_manifest_invalid"
        )
    return actual


def qualify_runtime_privileges(connection: Connection) -> dict[str, object]:
    expected = expected_runtime_privilege_manifest()
    rows = connection.execute(
        text(
            """
            SELECT relation.relname::text AS relation_name,
                   privilege.name::text AS privilege_name
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN pg_catalog.unnest(CAST(:privileges AS text[]))
                AS privilege(name)
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r','p','S')
              AND pg_catalog.has_table_privilege(
                    'nutrition_runtime', relation.oid, privilege.name
                  )
            ORDER BY relation.relname, privilege.name
            """
        ),
        {"privileges": list(_TABLE_PRIVILEGES)},
    ).mappings()
    relation_map: dict[str, list[str]] = {}
    for row in rows:
        relation_map.setdefault(str(row["relation_name"]), []).append(
            str(row["privilege_name"])
        )
    runtime_routines = [
        f"{row['schema_name']}.{row['routine_name']}({row['arguments']})"
        for row in connection.execute(
            text(
                """
                SELECT namespace.nspname::text AS schema_name,
                       routine.proname::text AS routine_name,
                       pg_catalog.pg_get_function_identity_arguments(
                            routine.oid
                       )::text AS arguments
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = routine.pronamespace
                WHERE namespace.nspname = 'public'
                  AND pg_catalog.has_function_privilege(
                        'nutrition_runtime', routine.oid, 'EXECUTE'
                      )
                ORDER BY namespace.nspname, routine.proname, arguments
                """
            )
        ).mappings()
    ]
    execute_roles = [
        role
        for role in _MANAGED_EXECUTE_ROLES
        if bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_function_privilege("
                    ":role, 'public.phase5c_local_admission_v3()', 'EXECUTE')"
                ),
                {"role": role},
            )
        )
    ]
    authority = (
        connection.execute(
            text(
                """
                SELECT role.rolsuper, role.rolcreatedb, role.rolcreaterole,
                       role.rolreplication, role.rolbypassrls,
                       pg_catalog.has_database_privilege(
                            role.rolname, pg_catalog.current_database(), 'CREATE'
                       ) AS database_create,
                       pg_catalog.has_schema_privilege(
                            role.rolname, 'public', 'CREATE'
                       ) AS schema_create,
                       pg_catalog.pg_has_role(
                            role.rolname, 'nutrition_owner', 'USAGE'
                       ) OR pg_catalog.pg_has_role(
                            role.rolname, 'nutrition_migrator', 'USAGE'
                       ) AS can_assume_authority
                FROM pg_catalog.pg_roles AS role
                WHERE role.rolname = 'nutrition_runtime'
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if authority is None:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_runtime_privileges_invalid"
        )
    protected_tables = [item.table for item in APPEND_ONLY_TABLES] + [
        "daily_logs",
        "daily_log_nutrient_snapshots",
    ]
    owns_relations = bool(
        connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = relation.relowner
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY(CAST(:tables AS text[]))
                      AND owner.rolname = 'nutrition_runtime'
                )
                """
            ),
            {"tables": protected_tables},
        )
    )
    owns_routines = bool(
        connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = routine.proowner
                    WHERE namespace.nspname = 'public'
                      AND routine.proname = ANY(CAST(:routines AS text[]))
                      AND owner.rolname = 'nutrition_runtime'
                )
                """
            ),
            {"routines": [item.name for item in ROUTINE_CONTRACTS]},
        )
    )
    actual: dict[str, object] = {
        "manifest_version": expected["manifest_version"],
        "runtime_role": "nutrition_runtime",
        "relation_privileges": [
            {"relation": f"public.{name}", "privileges": privileges}
            for name, privileges in sorted(relation_map.items())
        ],
        "runtime_execute_routines": runtime_routines,
        "append_only_tables": [item.table for item in APPEND_ONLY_TABLES],
        "snapshot_direct_delete": bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_table_privilege("
                    "'nutrition_runtime', "
                    "'public.daily_log_nutrient_snapshots', 'DELETE')"
                )
            )
        ),
        "snapshot_replacement_routine": (
            f"public.{SNAPSHOT_REPLACEMENT_FUNCTION}(uuid, uuid)"
        ),
        "local_admission_execute_roles": execute_roles,
        "owns_immutable_relations": owns_relations,
        "owns_protection_routines": owns_routines,
        "can_assume_owner_or_migrator": bool(authority["can_assume_authority"]),
        "can_alter_protection_objects": owns_relations or owns_routines,
        "can_disable_triggers": owns_relations,
        "can_set_replication_role": bool(authority["rolsuper"]),
        "superuser": bool(authority["rolsuper"]),
        "create_database": bool(authority["rolcreatedb"]),
        "create_role": bool(authority["rolcreaterole"]),
        "replication": bool(authority["rolreplication"]),
        "bypass_rls": bool(authority["rolbypassrls"]),
    }
    if actual != expected:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_runtime_privileges_invalid"
        )
    return actual


def _validate_prerequisites(raw: Any):
    if not isinstance(raw, Mapping) or raw.get("schema_revision") != (
        CURRENT_RUNTIME_SCHEMA_REVISION
    ):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_schema_invalid"
        )
    historical = dict(raw)
    historical["schema_revision"] = HISTORICAL_PHASE5_SCHEMA_REVISION
    try:
        prerequisites = validate_prerequisite_observation(historical)
    except Phase5C4PrerequisiteError:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_prerequisites_invalid"
        ) from None
    if (
        prerequisites.session_role != "nutrition_qualifier"
        or not prerequisites.role_topology_valid
        or not prerequisites.gate_trigger_coverage_valid
        or not prerequisites.immutability_valid
        or prerequisites.state["mode"] not in _DEPLOYABLE_FENCE_MODES
    ):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_prerequisites_invalid"
        )
    return prerequisites


def qualify_immutable_provenance_connection(
    connection: Connection,
    *,
    function_definition_sha256: Mapping[str, str] = FUNCTION_DEFINITION_SHA256,
) -> ImmutableProvenanceQualification:
    """Qualify an already protected qualifier-owned transaction."""

    revisions = list(
        connection.scalars(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        )
    )
    if revisions != [CURRENT_RUNTIME_SCHEMA_REVISION]:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_schema_invalid"
        )
    prerequisites = _validate_prerequisites(
        connection.scalar(text("SELECT public.phase5c_read_qualifier_evidence_v2()"))
    )
    preflight = assert_no_blocking_findings(
        connection,
        observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
        read_only=True,
    ).to_dict()
    constraints = qualify_constraint_manifest(connection)
    if constraints != expected_constraint_manifest():
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_resource_membership_invalid"
        )
    immutable_manifest = qualify_immutable_provenance_manifest(
        connection,
        function_definition_sha256=function_definition_sha256,
    )
    runtime_privileges = qualify_runtime_privileges(connection)
    constraint_payload = {
        "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
        "constraints": constraints,
    }
    unsigned: dict[str, Any] = {
        "blocking_category_count": int(preflight["blocking_category_count"]),
        "blocking_row_count": int(preflight["blocking_row_count"]),
        "constraint_manifest_digest": canonical_digest(constraint_payload),
        "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
        "constraints": constraints,
        "contract_version": IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
        "fence_event_chain_digest": prerequisites.event_chain_digest,
        "fence_mode": prerequisites.state["mode"],
        "historical_phase5_schema_revision": HISTORICAL_PHASE5_SCHEMA_REVISION,
        "immutable_provenance_integrity_valid": True,
        "immutable_provenance_manifest": immutable_manifest,
        "immutable_provenance_manifest_digest": canonical_digest(immutable_manifest),
        "immutable_provenance_manifest_version": (
            IMMUTABLE_PROVENANCE_MANIFEST_VERSION
        ),
        "local_admission_contract_version": (
            IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION
        ),
        "preflight_contract_version": PREFLIGHT_VERSION,
        "preflight_report_digest": str(preflight["report_digest"]),
        "resource_membership_integrity_valid": True,
        "runtime_privilege_digest": canonical_digest(runtime_privileges),
        "runtime_privileges": runtime_privileges,
        "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
        "target_identity_digest": prerequisites.identity["identity_digest"],
    }
    return ImmutableProvenanceQualification(
        {**unsigned, "qualification_digest": canonical_digest(unsigned)}
    )


def collect_immutable_provenance_qualification(
    database_url: str,
) -> ImmutableProvenanceQualification:
    """Observe exact 0020 state in one qualifier-owned RO/RR snapshot."""

    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_database_invalid"
        ) from None
    if url.get_backend_name() != "postgresql":
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_requires_postgresql"
        )
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="REPEATABLE READ",
        connect_args=database_connect_args(database_url),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            boundary = connection.execute(
                text(
                    "SELECT session_user::text, current_user::text, "
                    "current_setting('transaction_read_only'), "
                    "current_setting('transaction_isolation')"
                )
            ).one()
            if tuple(boundary) != (
                "nutrition_qualifier",
                "nutrition_qualifier",
                "on",
                "repeatable read",
            ):
                raise ImmutableProvenanceQualificationError(
                    "immutable_provenance_qualification_role_invalid"
                )
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
            )
            return qualify_immutable_provenance_connection(connection)
    except ImmutableProvenanceQualificationError:
        raise
    except (ResourceMembershipPreflightError, ResourceMembershipQualificationError):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_resource_membership_invalid"
        ) from None
    except SQLAlchemyError:
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_qualification_database_unavailable"
        ) from None
    finally:
        engine.dispose()


def admit_immutable_provenance_qualification(
    control_database_url: str,
    qualification: ImmutableProvenanceQualification,
    *,
    retries: int = 3,
) -> dict[str, str]:
    """Register canonical qualification bytes through the narrow control API."""

    try:
        url = make_url(control_database_url)
    except (ArgumentError, TypeError, ValueError):
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_control_database_invalid"
        ) from None
    if url.get_backend_name() != "postgresql":
        raise ImmutableProvenanceQualificationError(
            "immutable_provenance_control_requires_postgresql"
        )
    engine = create_engine(
        control_database_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="SERIALIZABLE",
        connect_args={"connect_timeout": 5},
    )
    try:
        for attempt in range(retries):
            try:
                with engine.begin() as connection:
                    row = (
                        connection.execute(
                            text(
                                "SELECT * FROM "
                                "phase5c4_api.admit_immutable_provenance_v1(:artifact)"
                            ),
                            {"artifact": qualification.to_bytes()},
                        )
                        .mappings()
                        .one()
                    )
                    result = str(row["result"])
                    digest = str(row["qualification_digest"])
                    if result not in {"accepted", "idempotent_replay"} or digest != (
                        qualification.qualification_digest
                    ):
                        raise ImmutableProvenanceQualificationError(
                            "immutable_provenance_control_admission_invalid"
                        )
                    return {"result": result, "qualification_digest": digest}
            except DBAPIError as exc:
                sqlstate = str(getattr(exc.orig, "sqlstate", ""))
                if sqlstate == "40001" and attempt + 1 < retries:
                    continue
                raise ImmutableProvenanceQualificationError(
                    "immutable_provenance_control_admission_failed"
                ) from None
    finally:
        engine.dispose()
    raise ImmutableProvenanceQualificationError(
        "immutable_provenance_control_admission_failed"
    )
