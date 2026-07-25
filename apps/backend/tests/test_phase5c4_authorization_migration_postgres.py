from __future__ import annotations

import secrets

import pytest
from psycopg import sql
from sqlalchemy import make_url, text

from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c4_authorization import AUTHORIZATION_CONTROL_REVISION
from tests import test_phase5c4_authorization_control_postgres as authorization_support
from tests import test_phase5c4_recovery_control_postgres as recovery_support


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


def test_ops8_aborts_without_mutating_nonempty_legacy_placeholders() -> None:
    baseline = recovery_support.control_database.__wrapped__()
    recovery_database = next(baseline)
    database = recovery_database.database
    try:
        admin = database.admin_engine()
        try:
            roles.provision_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
            password = secrets.token_urlsafe(24)
            with admin.begin() as connection:
                raw = connection.connection.driver_connection
                with raw.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(
                                roles.AUTHORIZATION_VERIFIER_ROLE
                            ),
                            sql.Literal(password),
                        )
                    )
                connection.execute(
                    text(
                        """
                        INSERT INTO
                            phase5c4_control.
                                phase5c4_authorization_envelope_bindings(
                            artifact_id, authorization_type,
                            authorization_id, nonce, environment_key,
                            attempt_id, environment_generation,
                            artifact_set_digest, source_incarnation_digest,
                            target_incarnation_digest, deployment_digest,
                            not_before, expires_at
                        ) VALUES (
                            CAST(:artifact_id AS uuid), 'legacy_test',
                            CAST(:authorization_id AS uuid),
                            CAST(:nonce AS uuid), :environment_key,
                            CAST(:attempt_id AS uuid), 1,
                            :artifact_set_digest, :source_digest,
                            :target_digest, :deployment_digest,
                            '2026-07-25T12:00:00Z',
                            '2026-07-25T12:10:00Z'
                        )
                        """
                    ),
                    {
                        "artifact_id": recovery_database.expectation.backup_artifact_id,
                        "authorization_id": authorization_support._uuid(40_001),
                        "nonce": authorization_support._uuid(40_002),
                        "environment_key": recovery_database.expectation.environment_key,
                        "attempt_id": recovery_database.expectation.attempt_id,
                        "artifact_set_digest": authorization_support._digest(40_003),
                        "source_digest": authorization_support._digest(40_004),
                        "target_digest": authorization_support._digest(40_005),
                        "deployment_digest": authorization_support._digest(40_006),
                    },
                )
        finally:
            admin.dispose()
        verifier_url = (
            make_url(database.admin_url)
            .set(
                username=roles.AUTHORIZATION_VERIFIER_ROLE,
                password=password,
            )
            .render_as_string(hide_password=False)
        )
        assert verifier_url
        upgraded = authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            AUTHORIZATION_CONTROL_REVISION,
        )
        assert upgraded.returncode != 0
        assert "authorization_placeholder_rows_present" in upgraded.stderr
        admin = database.admin_engine()
        try:
            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT version_num FROM "
                        "phase5c4_control.phase5c4_alembic_version"
                    )
                ) == recovery_support.RECOVERY_CONTROL_REVISION
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM "
                        "phase5c4_control."
                        "phase5c4_authorization_envelope_bindings"
                    )
                ) == 1
                assert connection.scalar(
                    text(
                        "SELECT to_regclass("
                        "'phase5c4_control.phase5c4_authorization_keys')"
                    )
                ) is None
        finally:
            admin.dispose()
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass
        authorization_support._drop_verifier_after_database_cleanup()
