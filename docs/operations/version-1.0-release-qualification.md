# Version 1.0 PostgreSQL release qualification

> **Document role: Operational Reference.** This is the canonical Version 1.0 PostgreSQL
> backend/control qualification manifest.

## Release boundary

The current active development head is `0025_immutable_validator_head`; the Version 1.0
release boundary below remains pinned to its historical application head.

The application migration head is `0021_target_activation_execution`; the control migration head
is `ops_0011_phase5c4_recovery_audit`. Release qualification uses PostgreSQL 16 and a disposable
bootstrap database. It covers current-head application and control migration replay, the frozen
`0001_initial_schema` replay-equivalence check, application/control role validation, target
activation and emergency close, recovery, purpose-specific preactivation cutback, and cumulative
control qualification.

The database URL below must identify a disposable PostgreSQL 16 cluster whose current login may
create databases and roles. The suites create and remove databases, schemas, and managed roles.
Never point this command at production, shared, or valuable development data.

## Canonical fail-closed PostgreSQL command

Run from the repository root after installing the locked backend development environment. The
command fails if the repository heads drift, PostgreSQL is unavailable or not major version 16,
the login lacks bootstrap authority, any selected test fails, or any selected test is skipped.

```bash
(
  set -euo pipefail
  test -z "$(git status --porcelain)"
  ./scripts/project-audit.sh boundaries
  export REQUIRE_POSTGRES_TESTS=1
  : "${NUTRITION_TEST_POSTGRES_URL:?set a disposable PostgreSQL 16 bootstrap URL}"
  cd apps/backend
  report="$(mktemp -t nutrition-v1-postgres.XXXXXX)"
  trap 'rm -f "$report"' EXIT

  python - <<'PY'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["NUTRITION_TEST_POSTGRES_URL"])
with engine.connect() as connection:
    version = int(connection.scalar(text("SHOW server_version_num")) or 0)
    bootstrap = connection.execute(
        text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole "
            "FROM pg_catalog.pg_roles WHERE rolname = current_user"
        )
    ).one()
engine.dispose()
assert 160000 <= version < 170000, f"expected PostgreSQL 16, found {version}"
assert all(bool(value) for value in bootstrap), "bootstrap role requires superuser, createdb, and createrole"
PY

  pytest -q --strict-markers --junitxml="$report" \
    tests/test_postgres_test_support.py \
    tests/test_legacy_recipe_migration_safety_postgres.py \
    tests/test_initial_migration_replay_postgres.py \
    tests/test_phase5c4_roles_postgres.py \
    tests/test_phase5c4_prerequisites_postgres.py \
    tests/test_resource_membership_migration_postgres.py \
    tests/test_immutable_provenance_migration_postgres.py \
    tests/test_phase5c4_target_activation_postgres.py \
    tests/test_phase5c4_control_postgres.py \
    tests/test_resource_membership_control_postgres.py \
    tests/test_immutable_provenance_control_postgres.py \
    tests/test_phase5c4_recovery_postgres.py \
    tests/test_phase5c4_recovery_control_postgres.py \
    tests/test_phase5c4_authorization_control_postgres.py \
    tests/test_phase5c4_authorization_migration_postgres.py \
    tests/test_phase5c4_promotion_authorization_control_postgres.py \
    tests/test_phase5c4_target_activation_control_postgres.py \
    tests/test_phase5c4_cutback_control_postgres.py \
    tests/test_phase5c4_recovery_qualification_control_postgres.py

  python - "$report" <<'PY'
import sys
from xml.etree import ElementTree

root = ElementTree.parse(sys.argv[1]).getroot()
skipped = sum(int(suite.get("skipped", "0")) for suite in root.iter("testsuite"))
if skipped:
    raise SystemExit(f"release qualification is fail-closed: {skipped} selected test(s) skipped")
PY
)
```

## Required retained infrastructure evidence

After the exact release source is committed and the tree is clean, the release gate also requires
fresh evidence from the implemented disposable infrastructure qualifier:

```bash
NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM=phase5c4_infrastructure_destroy_disposable \
NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE=1 \
  ./scripts/qualify-phase5c4-infrastructure.sh
```

The retained summary must report `dirty_tree: false`, the exact release commit, a successful
overall result, and the documented scenario/configuration/inventory digests. Its explicit
`application_schema_and_domain_restore` and `control_provider_end_to_end_binding` limitations
remain limitations; the local provider stand-in is not production-vendor certification.

## Developer convenience commands

Focused commands in the [Testing Guide](testing.md) are appropriate while developing. Unless they
use the full command above, they may skip when optional PostgreSQL, Docker, MinIO, provider,
performance, or Apple infrastructure is absent. A focused pass or skip is not Version 1.0 release
qualification and must not be reported as one.
