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

See [Production Hardening Phase 1](docs/production-hardening-phase1.md) for the configuration contract
and [Stage 5A Apple Vision OCR](docs/stage5-ocr.md) for native OCR setup and limitations.
