# AGENTS.md

Nutrition App is a personal, on-device iPhone app (Expo / React Native / TypeScript, SQLite).
Maintenance is mostly applying Dependabot security fixes. Follow
[docs/maintenance.md](docs/maintenance.md) for that workflow.

## Working rules

- Keep changes small and focused, and don't rewrite subsystems unless asked.
- Look at the actual code and tests before changing behavior.
- Don't weaken tests or suppress warnings to get CI green. Fix the cause.
- Don't commit, push, merge, or change repository settings unless the owner asks.
- Never commit credentials, tokens, private keys, or real personal data.

## Data-integrity invariants

These hold regardless of how small the change is (details in [docs/invariants.md](docs/invariants.md)):

- Daily Log nutrition history is immutable. Later edits to Foods, servings or Recipes never
  rewrite it.
- Recipe publication revisions are immutable, and logging resolves through them.
- OCR corrections keep their provenance.
- Mutations stay atomic and idempotent, and failures roll back completely.
- New SQLite/Alembic migrations are added, never edited after the fact.

## Checks

```bash
cd apps/mobile && npm ci && npm run typecheck && npm test
./scripts/run-backend-baseline.sh   # parked backend, only if touched
```

Run the manual **iOS native build** workflow after changes to native modules, Expo/React Native
versions, permissions, camera or OCR.

## Parked

`apps/backend` (FastAPI/PostgreSQL), `docker/` and the control-plane docs in `docs/backend/` are kept
for possible future use. The app does not depend on them.
