# Maintenance guide

Nutrition App is a personal app running on one iPhone (iPhone 17 Pro Max). Day-to-day work is
mostly keeping dependencies patched when Dependabot reports vulnerabilities. This guide is the
whole process.

## Handling a Dependabot alert or PR

1. Read the alert: which package, which manifest (`apps/mobile/package-lock.json` or
   `apps/backend/requirements-dev.lock`), and the first patched version.
2. Prefer the Dependabot PR if it exists. If not, update the package yourself:
   - Mobile: `cd apps/mobile && npm install <package>@<patched-version>` for a direct dependency,
     or `npm update <package>` for a transitive one. If the patched version is outside the
     parent's semver range, add an entry under `overrides` in `apps/mobile/package.json`.
   - Backend (parked): update the pin in `apps/backend/requirements-dev.lock`.
3. Let CI run. Merge when it is green. Close duplicate PRs.
4. If the change touches Expo, React Native or a native module, also run the
   **iOS native build** workflow from the Actions tab, then reinstall on the phone (below).

Major-version upgrades (Expo SDK, React Native, TypeScript, Jest, Zod) are not routine. Do them on
purpose, one at a time, and test them on the phone.

## Existing security patches

- `deepmerge` is installed from `apps/mobile/vendor/security/deepmerge/patched.tgz`, a
  prototype-pollution fix applied to the upstream 4.3.1 release (`security.patch` and
  `provenance.json` alongside it). Drop it once an upstream release includes the fix.
- `minimatch` 11.0.1 is pinned at the root, and the `minimatch@10.2.6` override moves Expo
  fingerprint's `^10.2.6` request onto it. Remove the override once that caller asks for a patched
  version itself.
- `glob` 14.0.3 is pinned at the root; Expo's callers now request `^14.0.3` themselves.
- Three overrides no longer match anything and can be deleted in a future dependency PR:
  `glob@^13.0.0`, `@expo/cli` → `zod` (Expo CLI no longer depends on Zod), and `xcode` → `uuid`
  (xcode 4 dropped its uuid dependency).
- Jest 29 still installs its own `glob` 7 / `minimatch` 3 copies; that only goes away with a Jest
  major upgrade.

## CI

`.github/workflows/ci.yml` runs on every PR and push to `main`:

- **Mobile**: `npm ci`, Expo config validation, `tsc`, and Jest. `expo install --check` runs too, but
  failures only warn, because Expo ships patch releases independently.
- **Backend (parked)**: Ruff and the ordinary pytest suite (no PostgreSQL), so the parked backend does
  not rot.

`.github/workflows/ios-native.yml` is manual (**Actions → iOS native build → Run workflow**) and
builds the app for the iOS simulator on macOS.

## Running checks locally

```bash
cd apps/mobile
npm ci
npm run typecheck
npm test
```

```bash
./scripts/run-backend-baseline.sh
```

## Installing on the iPhone

Building needs a Mac with Xcode. From `apps/mobile`:

```bash
export EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=local
export EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE=development
npx expo prebuild --clean --platform ios
npx expo run:ios --configuration Release --device
```

A Release build bundles the JavaScript, so it needs no Metro server after installing. To iterate on
JS/TS against an installed development build, run `npx expo start --dev-client --host lan` instead.
Reinstalling over the existing app keeps its on-device SQLite data. Uninstalling the app deletes it.

## Parked components

These are kept in the repo for possible future use but are not part of the current app:

- `apps/backend`: FastAPI/PostgreSQL remote runtime (see [docs/backend](backend/)).
- `docker/`, `docker-compose*.yml`: backend and control-plane infrastructure.
- Android and app-store publishing were never used.

The app runs entirely on-device (`EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY=local`) and never talks to the
backend.
