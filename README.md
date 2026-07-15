# Nutrition App

iOS-first nutrition tracker with native OCR, a FastAPI calculation backend, and PostgreSQL.

## Production-hardening status

Phase 1 establishes an explicit release configuration and caller-identity boundary. Local
development and controlled private/internal distribution are supported. Public multi-user
production remains blocked because this repository does not contain a production identity
provider; it will fail configuration validation instead of falling back to the development user.

The private mode uses one configured application user and one shared bearer credential. It is
not an account system or scalable multi-user authentication. The credential embedded in a mobile
binary can be extracted, so this mode is only appropriate for a personally controlled backend and
private/internal builds.

## Release matrix

| Deployment | Mobile API URL | Transport | Authentication | Backend exposure |
| --- | --- | --- | --- | --- |
| Local simulator development | Explicit `http://localhost:8000/api/v1` (or another explicit URL) | Local HTTP allowed | Backend `development`; fixed development user | Local machine only |
| Physical local development | Explicit LAN URL such as `http://192.168.1.20:8000/api/v1` | Private-LAN HTTP allowed for development only | Backend `development`; fixed development user | Trusted LAN only; bind Uvicorn deliberately |
| Private internal/TestFlight | Explicit non-local HTTPS URL, normalized to exactly `/api/v1` | HTTPS required | Backend/mobile `private_single_user`; shared bearer secret | Personally controlled backend; restrict access as narrowly as operationally possible |
| Public production | Explicit non-local HTTPS URL | HTTPS required | Real production identity provider required | **Blocked in this build** |

## Backend configuration

Copy the backend example and choose a mode explicitly:

```bash
cp apps/backend/.env.example apps/backend/.env
```

Required in every mode:

- `NUTRITION_DEPLOYMENT_MODE`: `development`, `private_single_user`, `production`, or `test`.
- `NUTRITION_DATABASE_URL`: one SQLAlchemy database URL used by both the app and Alembic.

Development may create the fixed development user. Test mode provides a deterministic test
identity and does not need release credentials. Private mode additionally requires a secret of at
least 32 characters, a configured user ID/email, and optionally the explicit
`NUTRITION_PRIVATE_USER_CREATE_IF_MISSING=true` bootstrap switch. Caller-supplied user IDs are
never accepted.

`production` currently fails startup with an actionable error because no production-capable auth
provider is installed. This is intentional and prevents an anonymous or development-user fallback.

Operational output uses a redacted database identity (driver family, host, port, database). It does
not print usernames, passwords, or URL query values. Configuration validation also hides input
values in errors.

## Local development

Start PostgreSQL and the backend:

```bash
docker compose up -d postgres
cd apps/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Set NUTRITION_DEPLOYMENT_MODE=development explicitly.
alembic upgrade head
uvicorn app.main:app --reload
```

The convenience command is for local development only; it is not a remote deployment platform.
It performs the same configuration check before migrations and never prints the full database URL:

```bash
./scripts/start-backend.sh
```

Alembic does not use an operational URL from `alembic.ini`. Migration and runtime commands both
load `NUTRITION_DATABASE_URL` through the application settings. To select a test database, set that
variable explicitly on the migration command.

Migration `0004_recipe_domain_foundation` intentionally refuses to upgrade a pre-0004 database
when either legacy `recipes` or `recipe_ingredients` table contains rows. Empty databases continue
to upgrade normally. A populated legacy database must use the offline Phase 5C1 bridge and planner,
then the Phase 5C2 checkpointed converter, on an isolated conversion clone.
If a database was already upgraded through the older destructive 0004, discarded rows can be
recovered only from a backup. See
[Production Hardening Phase 5A](docs/production-hardening-phase5a.md).

Before any future historical conversion work, operators can produce an aggregate-only, read-only
inventory of migration, Recipe, publication, projection, log, OCR, idempotency, and retention state:

```bash
cd apps/backend
NUTRITION_DATABASE_URL='<explicit-sqlalchemy-database-url>' \
  .venv/bin/python -m scripts.inventory_historical_database --format human
```

Use `--format json` for the stable machine-readable contract. The command requires the canonical
database variable in its process environment, runs PostgreSQL inspection in a read-only transaction,
does not run migrations or repairs, and emits no row identifiers or user-authored content. See
[Production Hardening Phase 5B](docs/production-hardening-phase5b.md).

For a populated canonical 0003 clone, Phase 5C1 can move the legacy Recipe tables into an immutable
archive, let unchanged Alembic migrations create the current empty Recipe domain, and produce the
canonical `phase5c_conversion_plan_v2` manifest. Destructive bridging requires a separately created
clone marker, distinct source/clone safe identities, versioned operator attestation, and
database-level exclusion of non-Phase-5C client sessions; a boolean confirmation is not accepted.
The operator commands require explicit database configuration and create no Recipe or publication
data. See
[Production Hardening Phase 5C1](docs/production-hardening-phase5c1.md) for the admission rules,
commands, archive contract, deterministic dispositions, and deferred conversion boundary.

Phase 5C2 executes only `convert` decisions from that exact approved plan at migration
`0016_phase5c_execution`. It reuses each compatibility projection, captures one immutable
transition-baseline revision, and records every convert/quarantine/block outcome. Daily Logs and OCR
provenance are unchanged. Execution is restart-safe and produces a privacy-safe receipt, but it does
not accept the Phase 5C1 planning attestation as permission to convert. A separate execution-capable
operator attestation derived from the exact validated plan and bound to the same clone marker is
required. A regenerated plan requires new execution authorization. Phase 5C2 does not authorize
production promotion; rollback remains cutback to the pre-conversion clone. See
[Production Hardening Phase 5C2](docs/production-hardening-phase5c2.md).

Phase 5C3a adds a PostgreSQL-only independent qualification command for completed Phase 5C2 clones.
It re-queries final Recipe, ingredient, revision, projection, graph, archive/source, Daily Log, OCR,
run, outcome, and execution-receipt state inside a read-only repeatable snapshot. Its compact,
deterministic receipt is external evidence only and does not authorize production promotion. See
[Production Hardening Phase 5C3a](docs/production-hardening-phase5c3a.md).

Liveness is public at `/api/v1/health`. Readiness is public at `/api/v1/ready` and performs a small,
bounded database check. Neither endpoint returns configuration, API keys, credentials, user IDs, or
stack traces. Every other `/api/v1` route is authenticated, including nutrients, USDA search/detail,
OCR parsing, and all persisted application resources.

## Mobile configuration

Mobile configuration is validated during Expo config generation and again when the central API
client loads. There is no localhost fallback.

For the iOS simulator:

```bash
cd apps/mobile
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development \
EXPO_PUBLIC_NUTRITION_API_URL=http://localhost:8000/api/v1 \
  npm start
```

For a physical local development build, replace localhost with the development machine's reachable
LAN address. The backend must be deliberately bound and reachable on that trusted network.

For a private internal/TestFlight export, inject all values through the build environment:

```bash
cd apps/mobile
EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=private_single_user \
EXPO_PUBLIC_NUTRITION_API_URL=https://api.example.invalid/api/v1 \
EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN='<build-secret>' \
  npx expo export --platform ios
```

Do not put a real token in source, examples, logs, screenshots, or build transcripts. Expo public
configuration is embedded in the application; the token is therefore extractable. The central API
client adds the bearer header, and feature clients must not duplicate it.

Release/private validation rejects missing URLs, localhost/loopback/emulator aliases, insecure HTTP,
credentials/query strings in the URL, arbitrary paths, duplicate `/api/v1`, and a missing private
credential. Public production configuration is rejected until a real provider is implemented.

## Tests

```bash
cd apps/backend
pytest
ruff check .

cd ../mobile
npm test
npm run typecheck
```

PostgreSQL concurrency tests retain their dedicated URL and do not use release credentials:

```bash
cd apps/backend
NUTRITION_TEST_POSTGRES_URL=postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app \
  pytest -m postgres_concurrency
```

## Architectural invariants

- Daily log history aggregates immutable nutrient snapshots, not mutable current Food nutrients.
- Missing nutrient data is distinct from zero.
- FDA Daily Values are reference rows rather than nutrient columns.
- Parser corrections retain structured provenance without storing raw label images/text.
- Recipe publication revisions are immutable snapshots and ownership remains service-scoped.
- Retryable create operations use owner- and operation-scoped `client_request_id` receipts in the
  same transaction as the created resource. Replays with the same payload return the committed
  resource; reuse with different payload data returns a conflict. Manual Food creation, Food
  duplication, custom serving creation, Recipe creation, Recipe publication, Daily Log creation,
  and OCR confirmation are covered. Favorites and targets remain naturally idempotent `PUT`
  operations, while USDA import retains its owner/source identity deduplication.

Create-operation receipts retain the original response snapshot and are kept indefinitely so an
accepted request ID never expires into permission to create a duplicate. If the exact mutable
result is later archived or its created child is replaced, replay returns the structured
`create_idempotency_result_unavailable` conflict instead of returning stale success or creating a
replacement. Receipt cleanup is intentionally not part of the current retention model.

See [Production Hardening Phase 1](docs/production-hardening-phase1.md) for the configuration contract
and [Stage 5A Apple Vision OCR](docs/stage5-ocr.md) for native OCR setup and limitations.
