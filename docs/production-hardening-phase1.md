# Production Hardening Phase 1

## Configuration and identity contract

The backend has four explicit modes. Absence or misspelling is a startup error.

- `development`: fixed local development identity; no bearer credential required.
- `test`: deterministic test identity; no production credential dependency.
- `private_single_user`: one configured identity and a constant-time-checked bearer credential.
- `production`: requires an installed production authentication provider. No provider exists in this
  phase, so startup fails closed.

The shared `get_current_user` dependency is the sole API caller-identity boundary. Development and
test creation behavior is deterministic. Private user creation occurs only for the configured ID and
only when `NUTRITION_PRIVATE_USER_CREATE_IF_MISSING=true`; arbitrary caller-supplied identities are
not created. Missing, malformed, and invalid private credentials all return the same 401 contract.

The private credential is intentionally narrow. It grants access to the one configured user's data,
does not identify different people, has no refresh/revocation protocol, and can be extracted from the
mobile app. Use it only for a controlled private/internal deployment over HTTPS. It is not suitable
for public or multi-user production.

## Route policy

Public:

- `GET /api/v1/health`: process liveness only.
- `GET /api/v1/ready`: required configuration was already validated at startup and the database
  responds to a bounded `SELECT 1`.

Authenticated application routers:

- nutrients;
- Foods, favorites, and recents;
- Daily Logs and summaries;
- Recipes, publication, and nutrition;
- target configuration/comparison;
- OCR parsing and confirmation;
- USDA search, detail/preview, and import.

The route-coverage test inspects every included application router and fails if the shared dependency
is absent. USDA quota-consuming methods are also tested not to run for unauthorized requests.

## Database configuration

`NUTRITION_DATABASE_URL` is canonical. Runtime engine creation and Alembic `env.py` load the same
validated settings value; `alembic.ini` contains no operational URL. Tests can explicitly override
the canonical variable, while `NUTRITION_TEST_POSTGRES_URL` remains dedicated to isolated PostgreSQL
concurrency tests.

Startup diagnostics render only driver family, host, port, and database name. Usernames, passwords,
and query parameters are removed. Pydantic input values are hidden from validation errors.

## Mobile build contract

`EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE` and `EXPO_PUBLIC_NUTRITION_API_URL` are mandatory. Expo's
dynamic app config runs the same validator used by the API client, so invalid configuration stops
config generation/export before an artifact is created. The URL is normalized to one `/api/v1`.

Private builds also require `EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN`. The central client attaches
it as `Authorization: Bearer ...`. Because Expo public values are compiled into the app, the value is
extractable and must be treated as a limited internal credential, not a user secret.

## Readiness decision

- Local development: supported.
- Private internal/TestFlight: supported when the backend is personally controlled, HTTPS is used,
  and both sides receive matching credentials through their deployment environments.
- Public/multi-user production: blocked until a real production identity provider and resolver are
  implemented and installed.

No schema migration is introduced by this phase.
