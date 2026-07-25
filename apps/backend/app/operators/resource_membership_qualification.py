"""Independent current-schema qualification for resource membership integrity."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.phase5c4_prerequisites import (
    Phase5C4PrerequisiteError,
    validate_prerequisite_observation,
)
from app.operators.resource_membership_contracts import (
    CHECK_CONSTRAINT_CONTRACTS,
    CONSTRAINT_MANIFEST_VERSION,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    LOCAL_ADMISSION_VERSION,
    LOCAL_ADMISSION_V2_DEFINITION_SHA256,
    LOCAL_ADMISSION_V2_RESULT,
    MIGRATION_ADVISORY_LOCK_KEY,
    PREFLIGHT_VERSION,
    PROJECTION_REVISION_UNIQUE_INDEX,
    QUALIFIED_FOREIGN_KEY_CONTRACTS,
    QUALIFICATION_VERSION,
    RETAINED_FOREIGN_KEY_CONTRACTS,
    REQUIRED_PARENT_UNIQUE_CONSTRAINTS,
    SUPPORTING_INDEXES,
    expected_constraint_manifest,
    expected_runtime_privilege_manifest,
)
from app.operators.resource_membership_preflight import (
    ResourceMembershipPreflightError,
    assert_no_blocking_findings,
)


_ACTION_NAMES = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}
_MATCH_NAMES = {"s": "SIMPLE", "f": "FULL", "p": "PARTIAL"}
_DEPLOYABLE_FENCE_MODES = {
    "closed_prequalification",
    "closed_cutover",
}
_TABLE_PRIVILEGES = (
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)


class ResourceMembershipQualificationError(RuntimeError):
    """Stable fail-closed qualification boundary."""


@dataclass(frozen=True)
class ResourceMembershipQualification:
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


def _column_names(connection: Connection, relation_oid: int, keys: list[int]) -> list[str]:
    if not keys:
        return []
    rows = connection.execute(
        text(
            """
            SELECT attribute.attnum, attribute.attname::text AS column_name
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = :relation_oid
              AND attribute.attnum = ANY(CAST(:keys AS smallint[]))
            """
        ),
        {"relation_oid": relation_oid, "keys": keys},
    ).mappings()
    by_number = {int(row["attnum"]): str(row["column_name"]) for row in rows}
    try:
        return [by_number[key] for key in keys]
    except KeyError:
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        ) from None


def _foreign_key_observation(connection: Connection, name: str) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
                SELECT constraint_value.conrelid::bigint AS child_oid,
                       constraint_value.confrelid::bigint AS parent_oid,
                       child.relname::text AS child_table,
                       parent.relname::text AS parent_table,
                       constraint_value.conkey::smallint[] AS child_keys,
                       constraint_value.confkey::smallint[] AS parent_keys,
                       constraint_value.confupdtype::text AS update_action,
                       constraint_value.confdeltype::text AS delete_action,
                       constraint_value.confmatchtype::text AS match_type,
                       constraint_value.condeferrable AS is_deferrable,
                       constraint_value.condeferred AS is_deferred,
                       constraint_value.convalidated AS is_validated,
                       referenced_index.relname::text AS parent_unique
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS child
                  ON child.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_class AS parent
                  ON parent.oid = constraint_value.confrelid
                LEFT JOIN pg_catalog.pg_class AS referenced_index
                  ON referenced_index.oid = constraint_value.conindid
                WHERE constraint_value.connamespace = 'public'::regnamespace
                  AND constraint_value.conname = :name
                  AND constraint_value.contype = 'f'
                """
            ),
            {"name": name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        )
    return {
        "child_table": str(row["child_table"]),
        "parent_table": str(row["parent_table"]),
        "child_columns": _column_names(
            connection,
            int(row["child_oid"]),
            [int(value) for value in row["child_keys"]],
        ),
        "parent_columns": _column_names(
            connection,
            int(row["parent_oid"]),
            [int(value) for value in row["parent_keys"]],
        ),
        "on_update": _ACTION_NAMES.get(str(row["update_action"])),
        "on_delete": _ACTION_NAMES.get(str(row["delete_action"])),
        "match": _MATCH_NAMES.get(str(row["match_type"])),
        "deferrable": bool(row["is_deferrable"]),
        "initially": (
            "DEFERRED"
            if row["is_deferrable"] and row["is_deferred"]
            else "IMMEDIATE" if row["is_deferrable"] else None
        ),
        "validated": bool(row["is_validated"]),
        "parent_unique": (
            None if row["parent_unique"] is None else str(row["parent_unique"])
        ),
    }


def _unique_observation(
    connection: Connection,
    *,
    name: str,
    table_name: str,
) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
                SELECT constraint_value.conrelid::bigint AS relation_oid,
                       constraint_value.conkey::smallint[] AS keys,
                       constraint_value.convalidated AS is_validated
                FROM pg_catalog.pg_constraint AS constraint_value
                WHERE constraint_value.connamespace = 'public'::regnamespace
                  AND constraint_value.conrelid = pg_catalog.to_regclass(
                        'public.' || :table_name
                  )
                  AND constraint_value.conname = :name
                  AND constraint_value.contype = 'u'
                """
            ),
            {"name": name, "table_name": table_name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        )
    return {
        "columns": _column_names(
            connection,
            int(row["relation_oid"]),
            [int(value) for value in row["keys"]],
        ),
        "validated": bool(row["is_validated"]),
    }


def _index_observation(
    connection: Connection,
    *,
    name: str,
    table_name: str,
) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
                SELECT definition.indrelid::bigint AS relation_oid,
                       definition.indkey::smallint[] AS keys,
                       definition.indnkeyatts::integer AS key_count,
                       definition.indnatts::integer AS attribute_count,
                       definition.indisunique AS is_unique,
                       definition.indisvalid AS is_valid,
                       definition.indisready AS is_ready,
                       definition.indislive AS is_live,
                       definition.indexprs IS NULL AS expressions_absent,
                       access_method.amname::text AS access_method,
                       pg_catalog.pg_get_expr(
                           definition.indpred, definition.indrelid, true
                       ) AS predicate
                FROM pg_catalog.pg_class AS index_relation
                JOIN pg_catalog.pg_index AS definition
                  ON definition.indexrelid = index_relation.oid
                JOIN pg_catalog.pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                WHERE index_relation.relnamespace = 'public'::regnamespace
                  AND index_relation.relname = :name
                  AND definition.indrelid = pg_catalog.to_regclass(
                        'public.' || :table_name
                  )
                """
            ),
            {"name": name, "table_name": table_name},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        )
    keys = [int(value) for value in row["keys"]][: int(row["key_count"])]
    return {
        "columns": _column_names(connection, int(row["relation_oid"]), keys),
        "unique": bool(row["is_unique"]),
        "valid": bool(row["is_valid"] and row["is_ready"] and row["is_live"]),
        "plain_columns": bool(row["expressions_absent"]),
        "has_included_columns": int(row["attribute_count"]) != int(row["key_count"]),
        "access_method": str(row["access_method"]),
        "predicate": None if row["predicate"] is None else str(row["predicate"]),
    }


def _normalized_expression(value: str) -> str:
    rendered = "".join(value.lower().split())
    while rendered.startswith("(") and rendered.endswith(")"):
        depth = 0
        encloses_all = True
        for index, character in enumerate(rendered):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(rendered) - 1:
                    encloses_all = False
                    break
        if not encloses_all or depth != 0:
            break
        rendered = rendered[1:-1]
    return rendered


def qualify_local_admission_routine(connection: Connection) -> None:
    row = (
        connection.execute(
            text(
                """
                SELECT owner.rolname::text AS owner_name,
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
                  AND routine.proname = 'phase5c_local_admission_v2'
                  AND pg_catalog.pg_get_function_identity_arguments(
                        routine.oid
                      ) = ''
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ResourceMembershipQualificationError(
            "resource_membership_local_admission_routine_invalid"
        )
    actual = {
        "owner": str(row["owner_name"]),
        "language": str(row["language_name"]),
        "kind": str(row["routine_kind"]),
        "volatility": str(row["volatility"]),
        "security_definer": bool(row["security_definer"]),
        "leakproof": bool(row["leakproof"]),
        "parallel": str(row["parallel_safety"]),
        "strict": bool(row["is_strict"]),
        "returns_set": bool(row["returns_set"]),
        "identity_arguments": str(row["identity_arguments"]),
        "result": str(row["result_type"]),
        "config": list(row["configuration"] or []),
        "definition_sha256": sha256(str(row["definition"]).encode("utf-8")).hexdigest(),
    }
    expected = {
        "owner": "nutrition_owner",
        "language": "plpgsql",
        "kind": "f",
        "volatility": "s",
        "security_definer": True,
        "leakproof": False,
        "parallel": "u",
        "strict": False,
        "returns_set": True,
        "identity_arguments": "",
        "result": LOCAL_ADMISSION_V2_RESULT,
        "config": ["search_path=pg_catalog, public"],
        "definition_sha256": LOCAL_ADMISSION_V2_DEFINITION_SHA256,
    }
    if actual != expected:
        raise ResourceMembershipQualificationError(
            "resource_membership_local_admission_routine_invalid"
        )


def qualify_constraint_manifest(connection: Connection) -> list[dict[str, object]]:
    """Verify the exact current catalog and return its canonical projection."""

    qualify_local_admission_routine(connection)
    owner_column = (
        connection.execute(
            text(
                """
                SELECT attribute.attnotnull AS not_null,
                       attribute.atthasdef AS has_default,
                       attribute.attidentity::text AS identity_kind,
                       attribute.attgenerated::text AS generated_kind,
                       pg_catalog.format_type(
                           attribute.atttypid, attribute.atttypmod
                       )::text AS type_name
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid = 'public.recipe_ingredients'::regclass
                  AND attribute.attname = 'user_id'
                  AND NOT attribute.attisdropped
                """
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        owner_column is None
        or owner_column["not_null"] is not True
        or owner_column["has_default"] is not False
        or str(owner_column["identity_kind"]) != ""
        or str(owner_column["generated_kind"]) != ""
        or str(owner_column["type_name"]) != "uuid"
    ):
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        )

    for contract in QUALIFIED_FOREIGN_KEY_CONTRACTS:
        observed = _foreign_key_observation(connection, contract.name)
        expected = {
            "child_table": contract.child_table,
            "parent_table": contract.parent_table,
            "child_columns": list(contract.child_columns),
            "parent_columns": list(contract.parent_columns),
            "on_update": contract.on_update,
            "on_delete": contract.on_delete,
            "match": contract.match,
            "deferrable": contract.deferrable,
            "initially": contract.initially,
            "validated": True,
            "parent_unique": contract.parent_unique,
        }
        if observed != expected:
            raise ResourceMembershipQualificationError(
                "resource_membership_constraint_manifest_invalid"
            )

    for name, table_name, columns in REQUIRED_PARENT_UNIQUE_CONSTRAINTS:
        if _unique_observation(connection, name=name, table_name=table_name) != {
            "columns": list(columns),
            "validated": True,
        }:
            raise ResourceMembershipQualificationError(
                "resource_membership_constraint_manifest_invalid"
            )

    for name, table_name, columns in SUPPORTING_INDEXES:
        if _index_observation(connection, name=name, table_name=table_name) != {
            "columns": list(columns),
            "unique": False,
            "valid": True,
            "plain_columns": True,
            "has_included_columns": False,
            "access_method": "btree",
            "predicate": None,
        }:
            raise ResourceMembershipQualificationError(
                "resource_membership_constraint_manifest_invalid"
            )

    projection_index = _index_observation(
        connection,
        name=PROJECTION_REVISION_UNIQUE_INDEX,
        table_name="food_items",
    )
    predicate = projection_index.pop("predicate")
    if projection_index != {
        "columns": ["recipe_publication_revision_id"],
        "unique": True,
        "valid": True,
        "plain_columns": True,
        "has_included_columns": False,
        "access_method": "btree",
    } or predicate is None or _normalized_expression(predicate) != (
        "recipe_publication_revision_idisnotnull"
    ):
        raise ResourceMembershipQualificationError(
            "resource_membership_constraint_manifest_invalid"
        )

    for check_contract in CHECK_CONSTRAINT_CONTRACTS:
        check_expression = connection.scalar(
            text(
                """
            SELECT pg_catalog.pg_get_expr(
                       constraint_value.conbin,
                       constraint_value.conrelid,
                       true
                   )::text
            FROM pg_catalog.pg_constraint AS constraint_value
            WHERE constraint_value.connamespace = 'public'::regnamespace
              AND constraint_value.conrelid = pg_catalog.to_regclass(
                    'public.' || :table_name
              )
              AND constraint_value.conname = :name
              AND constraint_value.contype = 'c'
              AND constraint_value.convalidated
                """
            ),
            {"name": check_contract.name, "table_name": check_contract.table},
        )
        if check_expression is None or "".join(str(check_expression).split()) != (
            check_contract.catalog_expression
        ):
            raise ResourceMembershipQualificationError(
                "resource_membership_constraint_manifest_invalid"
            )
    return expected_constraint_manifest()


def qualify_retained_schema_contract(connection: Connection) -> None:
    """Fail before 0019 DDL if a prerequisite retained contract drifted."""

    try:
        for contract in RETAINED_FOREIGN_KEY_CONTRACTS:
            observed = _foreign_key_observation(connection, contract.name)
            expected = {
                "child_table": contract.child_table,
                "parent_table": contract.parent_table,
                "child_columns": list(contract.child_columns),
                "parent_columns": list(contract.parent_columns),
                "on_update": contract.on_update,
                "on_delete": contract.on_delete,
                "match": contract.match,
                "deferrable": contract.deferrable,
                "initially": contract.initially,
                "validated": True,
                "parent_unique": contract.parent_unique,
            }
            if observed != expected:
                raise ResourceMembershipQualificationError(
                    "resource_membership_retained_schema_invalid"
                )
        for check_contract in CHECK_CONSTRAINT_CONTRACTS:
            if check_contract.introduced_by_0019:
                continue
            expression = connection.scalar(
                text(
                    """
                    SELECT pg_catalog.pg_get_expr(
                               constraint_value.conbin,
                               constraint_value.conrelid,
                               true
                           )::text
                    FROM pg_catalog.pg_constraint AS constraint_value
                    WHERE constraint_value.connamespace = 'public'::regnamespace
                      AND constraint_value.conrelid = pg_catalog.to_regclass(
                            'public.' || :table_name
                      )
                      AND constraint_value.conname = :name
                      AND constraint_value.contype = 'c'
                      AND constraint_value.convalidated
                    """
                ),
                {"name": check_contract.name, "table_name": check_contract.table},
            )
            if expression is None or "".join(str(expression).split()) != (
                check_contract.catalog_expression
            ):
                raise ResourceMembershipQualificationError(
                    "resource_membership_retained_schema_invalid"
                )
    except ResourceMembershipQualificationError:
        raise ResourceMembershipQualificationError(
            "resource_membership_retained_schema_invalid"
        ) from None
    except SQLAlchemyError:
        raise ResourceMembershipQualificationError(
            "resource_membership_retained_schema_invalid"
        ) from None


def qualify_runtime_privileges(
    connection: Connection,
    *,
    expected_state: str = "normal",
) -> dict[str, object]:
    if expected_state not in {"normal", "maintenance"}:
        raise ValueError("Runtime privilege state must be normal or maintenance")
    expected = expected_runtime_privilege_manifest()
    if expected_state == "maintenance":
        expected["relation_privileges"] = [
            {
                "relation": item["relation"],
                "privileges": [
                    privilege
                    for privilege in item["privileges"]
                    if privilege == "SELECT"
                ],
            }
            for item in expected["relation_privileges"]
        ]
        expected["recipe_ingredients_user_id_insert"] = False
        expected["recipe_ingredients_user_id_update"] = False
    relation_rows = connection.execute(
        text(
            """
            SELECT relation.relname::text AS relation_name,
                   privilege.name::text AS privilege_name
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN unnest(CAST(:privileges AS text[])) AS privilege(name)
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'S')
              AND pg_catalog.has_table_privilege(
                    'nutrition_runtime', relation.oid, privilege.name
              )
            ORDER BY relation.relname, privilege.name
            """
        ),
        {"privileges": list(_TABLE_PRIVILEGES)},
    ).mappings()
    privilege_map: dict[str, list[str]] = {}
    for row in relation_rows:
        privilege_map.setdefault(str(row["relation_name"]), []).append(
            str(row["privilege_name"])
        )
    relation_privileges = [
        {"relation": f"public.{name}", "privileges": values}
        for name, values in sorted(privilege_map.items())
    ]

    role = (
        connection.execute(
            text(
                """
                SELECT role.rolsuper, role.rolcreatedb, role.rolcreaterole,
                       role.rolreplication, role.rolbypassrls,
                       pg_catalog.has_database_privilege(
                           role.rolname, pg_catalog.current_database(), 'CREATE'
                       ) AS database_create,
                       pg_catalog.has_database_privilege(
                           role.rolname, pg_catalog.current_database(), 'TEMP'
                       ) AS database_temp,
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
    if role is None:
        raise ResourceMembershipQualificationError(
            "resource_membership_runtime_privileges_invalid"
        )
    ownership = connection.execute(
        text(
            """
            SELECT
                (SELECT owner.rolname = 'nutrition_runtime'
                 FROM pg_catalog.pg_database AS database
                 JOIN pg_catalog.pg_roles AS owner ON owner.oid = database.datdba
                 WHERE database.datname = pg_catalog.current_database())
                    AS owns_database,
                (SELECT owner.rolname = 'nutrition_runtime'
                 FROM pg_catalog.pg_namespace AS namespace
                 JOIN pg_catalog.pg_roles AS owner ON owner.oid = namespace.nspowner
                 WHERE namespace.nspname = 'public') AS owns_schema,
                EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_roles AS owner ON owner.oid = relation.relowner
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY(CAST(:relations AS text[]))
                      AND owner.rolname = 'nutrition_runtime'
                ) AS owns_relations
            """
        ),
        {
            "relations": [
                str(item["relation"]).removeprefix("public.")
                for item in expected["relation_privileges"]
            ]
        },
    ).mappings().one()
    execute_roles = [
        role_name
        for role_name in (
            "nutrition_canary",
            "nutrition_migrator",
            "nutrition_ops",
            "nutrition_qualifier",
            "nutrition_runtime",
        )
        if bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_function_privilege("
                    ":role, 'public.phase5c_local_admission_v2()', 'EXECUTE')"
                ),
                {"role": role_name},
            )
        )
    ]
    public_execute = bool(
        connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc AS routine
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            routine.proacl,
                            pg_catalog.acldefault('f', routine.proowner)
                        )
                    ) AS acl
                    WHERE routine.oid =
                        'public.phase5c_local_admission_v2()'::regprocedure
                      AND acl.grantee = 0
                      AND acl.privilege_type = 'EXECUTE'
                )
                """
            )
        )
    )
    runtime_execute_routines = [
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
    local_admission_v2_execute_acl = [
        {
            "role": str(row["grantee_name"]),
            "grantable": bool(row["is_grantable"]),
        }
        for row in connection.execute(
            text(
                """
                SELECT CASE
                           WHEN acl.grantee = 0 THEN 'PUBLIC'
                           ELSE grantee.rolname::text
                       END AS grantee_name,
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
                WHERE routine.oid =
                    'public.phase5c_local_admission_v2()'::regprocedure
                  AND acl.privilege_type = 'EXECUTE'
                ORDER BY grantee_name
                """
            )
        ).mappings()
    ]
    actual: dict[str, object] = {
        "manifest_version": expected["manifest_version"],
        "runtime_role": "nutrition_runtime",
        "relation_privileges": relation_privileges,
        "runtime_execute_routines": runtime_execute_routines,
        "recipe_ingredients_user_id_insert": bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_column_privilege("
                    "'nutrition_runtime', 'public.recipe_ingredients', "
                    "'user_id', 'INSERT')"
                )
            )
        ),
        "recipe_ingredients_user_id_update": bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_column_privilege("
                    "'nutrition_runtime', 'public.recipe_ingredients', "
                    "'user_id', 'UPDATE')"
                )
            )
        ),
        "local_admission_execute_roles": execute_roles,
        "local_admission_v2_execute_acl": local_admission_v2_execute_acl,
        "local_admission_public_execute": public_execute,
        "owns_application_database": bool(ownership["owns_database"]),
        "owns_public_schema": bool(ownership["owns_schema"]),
        "owns_membership_relations": bool(ownership["owns_relations"]),
        "can_assume_owner_or_migrator": bool(role["can_assume_authority"]),
        "can_create_in_database": bool(role["database_create"]),
        "can_create_in_public_schema": bool(role["schema_create"]),
        "can_create_temporary_objects": bool(role["database_temp"]),
        "superuser": bool(role["rolsuper"]),
        "create_database": bool(role["rolcreatedb"]),
        "create_role": bool(role["rolcreaterole"]),
        "replication": bool(role["rolreplication"]),
        "bypass_rls": bool(role["rolbypassrls"]),
    }
    if actual != expected:
        raise ResourceMembershipQualificationError(
            "resource_membership_runtime_privileges_invalid"
        )
    return actual


def _validate_current_prerequisites(raw: Any):
    if not isinstance(raw, Mapping) or raw.get("schema_revision") != (
        CURRENT_RUNTIME_SCHEMA_REVISION
    ):
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_schema_invalid"
        )
    historical = dict(raw)
    historical["schema_revision"] = HISTORICAL_PHASE5_SCHEMA_REVISION
    try:
        prerequisites = validate_prerequisite_observation(historical)
    except Phase5C4PrerequisiteError:
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_prerequisites_invalid"
        ) from None
    if (
        prerequisites.session_role != "nutrition_qualifier"
        or not prerequisites.role_topology_valid
        or not prerequisites.gate_trigger_coverage_valid
        or not prerequisites.immutability_valid
        or prerequisites.state["mode"] not in _DEPLOYABLE_FENCE_MODES
    ):
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_prerequisites_invalid"
        )
    return prerequisites


def collect_resource_membership_qualification(
    database_url: str,
) -> ResourceMembershipQualification:
    """Observe exact 0019 state in one qualifier-owned RO/RR snapshot."""

    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_database_invalid"
        ) from None
    if url.get_backend_name() != "postgresql":
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_requires_postgresql"
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
                    """
                    SELECT session_user::text AS session_user,
                           current_user::text AS current_user,
                           current_setting('transaction_read_only') AS read_only,
                           current_setting('transaction_isolation') AS isolation
                    """
                )
            ).mappings().one()
            if tuple(boundary.values()) != (
                "nutrition_qualifier",
                "nutrition_qualifier",
                "on",
                "repeatable read",
            ):
                raise ResourceMembershipQualificationError(
                    "resource_membership_qualification_role_invalid"
                )
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
            )
            revisions = [
                str(value)
                for value in connection.scalars(
                    text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                )
            ]
            if revisions != [CURRENT_RUNTIME_SCHEMA_REVISION]:
                raise ResourceMembershipQualificationError(
                    "resource_membership_qualification_schema_invalid"
                )
            raw = connection.scalar(
                text("SELECT public.phase5c_read_qualifier_evidence_v2()")
            )
            prerequisites = _validate_current_prerequisites(raw)
            preflight = assert_no_blocking_findings(
                connection,
                observed_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
                read_only=True,
            ).to_dict()
            constraints = qualify_constraint_manifest(connection)
            runtime_privileges = qualify_runtime_privileges(connection)

            manifest_payload = {
                "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
                "constraints": constraints,
            }
            unsigned: dict[str, Any] = {
                "blocking_category_count": int(preflight["blocking_category_count"]),
                "blocking_row_count": int(preflight["blocking_row_count"]),
                "constraint_manifest_digest": canonical_digest(manifest_payload),
                "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
                "constraints": constraints,
                "contract_version": QUALIFICATION_VERSION,
                "fence_event_chain_digest": prerequisites.event_chain_digest,
                "fence_mode": prerequisites.state["mode"],
                "historical_phase5_schema_revision": HISTORICAL_PHASE5_SCHEMA_REVISION,
                "local_admission_contract_version": LOCAL_ADMISSION_VERSION,
                "preflight_contract_version": PREFLIGHT_VERSION,
                "preflight_report_digest": preflight["report_digest"],
                "runtime_privilege_digest": canonical_digest(runtime_privileges),
                "runtime_privileges": runtime_privileges,
                "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
                "target_identity_digest": prerequisites.identity["identity_digest"],
            }
            payload = {
                **unsigned,
                "qualification_digest": canonical_digest(unsigned),
            }
            return ResourceMembershipQualification(payload)
    except ResourceMembershipQualificationError:
        raise
    except ResourceMembershipPreflightError:
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_preflight_invalid"
        ) from None
    except SQLAlchemyError:
        raise ResourceMembershipQualificationError(
            "resource_membership_qualification_database_unavailable"
        ) from None
    finally:
        engine.dispose()


def admit_resource_membership_qualification(
    control_database_url: str,
    qualification: ResourceMembershipQualification,
    *,
    retries: int = 3,
) -> dict[str, str]:
    """Register canonical qualification bytes through the narrow control API."""

    try:
        url = make_url(control_database_url)
    except (ArgumentError, TypeError, ValueError):
        raise ResourceMembershipQualificationError(
            "resource_membership_control_database_invalid"
        ) from None
    if url.get_backend_name() != "postgresql":
        raise ResourceMembershipQualificationError(
            "resource_membership_control_requires_postgresql"
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
                                "phase5c4_api.admit_resource_membership_v1(:artifact)"
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
                        raise ResourceMembershipQualificationError(
                            "resource_membership_control_admission_invalid"
                        )
                    return {"result": result, "qualification_digest": digest}
            except DBAPIError as exc:
                sqlstate = str(getattr(exc.orig, "sqlstate", ""))
                if sqlstate == "40001" and attempt + 1 < retries:
                    continue
                raise ResourceMembershipQualificationError(
                    "resource_membership_control_admission_failed"
                ) from None
    finally:
        engine.dispose()
    raise ResourceMembershipQualificationError(
        "resource_membership_control_admission_failed"
    )
