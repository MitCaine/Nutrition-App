#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "$0")/lib/common.sh"

banner "E4-16 History Parity Qualification"
repo_cd

require_command node
require_command npm

E4_16_BACKEND_PYTHON="$REPO_ROOT/apps/backend/.venv/bin/python"
E4_16_POSTGRES_URL="${NUTRITION_TEST_POSTGRES_URL:-postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app}"
E4_16_ORDINARY_MARKERS="not postgres_concurrency and not phase5c_performance_t0 and not phase5c4_control_postgres and not phase5c4_minio and not phase5c4_docker_integration"

[[ -x "$E4_16_BACKEND_PYTHON" ]] || \
    die "Repository Python environment is missing at apps/backend/.venv."

section "Repository toolchains"
"$E4_16_BACKEND_PYTHON" --version
node --version
"$E4_16_BACKEND_PYTHON" scripts/toolchain-report.py --check node

section "Ordinary backend History, mutation, and transfer contracts"
(
    cd apps/backend
    "$E4_16_BACKEND_PYTHON" -m pytest -q --strict-markers \
        -m "$E4_16_ORDINARY_MARKERS" \
        tests/test_e4_16_history_parity.py \
        tests/test_e4_03_complete_invalidation.py \
        tests/test_e4_04_history_range.py \
        tests/test_stage2_logs.py::test_food_edits_do_not_change_historical_totals_and_log_update_rebuilds_snapshots \
        tests/test_stage4_recipes.py::test_historical_recipe_logs_remain_immutable_after_edit_and_republish \
        tests/test_e2_15_transfer_package.py \
        tests/test_e2_15_exporter.py \
        tests/test_e2_15_source_schema_contract.py \
        tests/test_e2_15_current_source_projection.py
)

section "Mobile shared projection, failure, calendar, UI, and durability contracts"
(
    cd apps/mobile
    npm test -- --runInBand --runTestsByPath \
        __tests__/e4_16HistoryParity.test.ts \
        __tests__/e4_03CompleteInvalidation.test.ts \
        __tests__/e4_04HistoryRange.test.ts \
        __tests__/e4_05HistoryProjection.test.ts \
        __tests__/e4_06HistoryQuery.test.ts \
        __tests__/e4_09HistoryShell.test.ts \
        __tests__/e4_10HistoryOverview.test.ts \
        __tests__/e4_11HistoryNutritionDetails.test.ts \
        __tests__/e4_12FocusedNutrientHistory.test.ts \
        __tests__/e4_15CompleteDurability.test.ts \
        __tests__/localBackupValidation.test.ts \
        __tests__/localBackupActivation.test.ts \
        __tests__/e2_15TransferPackage.test.ts \
        __tests__/e2_15TransferPackageValidator.test.ts \
        __tests__/e2_15TransferImporter.test.ts
)

section "PostgreSQL 16 server contract"
NUTRITION_TEST_POSTGRES_URL="$E4_16_POSTGRES_URL" \
    "$E4_16_BACKEND_PYTHON" -c \
    "from sqlalchemy import create_engine, text; import os; engine = create_engine(os.environ['NUTRITION_TEST_POSTGRES_URL']); connection = engine.connect(); version = connection.execute(text('SHOW server_version')).scalar_one(); connection.close(); engine.dispose(); print(f'PostgreSQL server version: {version}'); assert version.split('.')[0] == '16', f'expected PostgreSQL 16, found {version}'"

section "Explicit E4 PostgreSQL product and parity contracts"
(
    cd apps/backend
    REQUIRE_POSTGRES_TESTS=1 \
    NUTRITION_TEST_POSTGRES_URL="$E4_16_POSTGRES_URL" \
        "$E4_16_BACKEND_PYTHON" -m pytest -q --strict-markers \
        tests/test_e4_01_complete_persistence_postgres.py \
        tests/test_e4_02_complete_mutation_postgres.py \
        tests/test_e4_03_complete_invalidation_postgres.py \
        tests/test_e4_04_history_range_postgres.py \
        tests/test_e4_16_history_parity_postgres.py \
        tests/test_e2_15_exporter_postgres.py
)

section "Residual PostgreSQL schema and database cleanup"
NUTRITION_TEST_POSTGRES_URL="$E4_16_POSTGRES_URL" \
    "$E4_16_BACKEND_PYTHON" -c \
    "from sqlalchemy import create_engine, text; import os; engine = create_engine(os.environ['NUTRITION_TEST_POSTGRES_URL']); connection = engine.connect(); residual_schemas = connection.execute(text(\"SELECT schema_name FROM information_schema.schemata WHERE starts_with(schema_name, 'e4_02_complete_') OR starts_with(schema_name, 'e4_03_') OR starts_with(schema_name, 'e4_04_history_range_') OR starts_with(schema_name, 'e4_16_history_parity_') ORDER BY schema_name\")).scalars().all(); residual_databases = connection.execute(text(\"SELECT datname FROM pg_catalog.pg_database WHERE starts_with(datname, 'test_e4_01_complete_persistence_') OR starts_with(datname, 'test_phase5c4_target_') ORDER BY datname\")).scalars().all(); connection.close(); engine.dispose(); print(f'residual_schemas={residual_schemas}'); print(f'residual_databases={residual_databases}'); assert not residual_schemas, f'residual PostgreSQL test schemas: {residual_schemas}'; assert not residual_databases, f'residual PostgreSQL test databases: {residual_databases}'"

success "E4-16 automated qualification passed. Physical target-iPhone P-1 through P-12 remains a separate post-commit gate."
