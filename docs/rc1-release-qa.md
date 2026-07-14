# Release Candidate 1 QA report

Date: 2026-07-14 (America/Los_Angeles)

## 1. Environment matrix

| Component | Release-QA environment |
| --- | --- |
| Host | macOS 26.5.2 (25F84), Apple silicon |
| Xcode | 26.6 (17F113) |
| iOS runtime | iOS 26.5 (23F77) |
| Large simulator | iPhone 17 Pro Max, iOS 26.5, `07726290-AA0C-45C9-92D2-FE64AA514824` |
| Small simulator | iPhone 17e, iOS 26.5, `91EF0D93-F66C-4D58-82D0-A907D4B0E8B7` |
| Physical iPhone | “MiPhone”, iOS 26.5.2, registered but offline; model and camera session unavailable |
| Node / npm | Node 26.3.1 / npm 11.16.0 |
| Expo | Expo CLI 0.24.24, Expo SDK/package 53.0.27, React Native 0.79.6 |
| Python | CPython 3.12.13 in isolated RC venv |
| PostgreSQL | 16.14 (Debian 16.14-1.pgdg13+1), aarch64 |
| Alembic | `0012_food_favorites` (head) |
| Backend configuration | Local FastAPI/Uvicorn process, local PostgreSQL, environment USDA key present but not reported |
| App build | Release, iOS Simulator, Hermes; production Expo export also generated |
| Simulator API URL | `http://localhost:8000/api/v1` |

Mobile dependencies were installed with `npm ci`. Backend dependencies were installed from `.[dev]` into a new Python 3.12 venv. Expo prebuild used `--clean`; Pods and autolinking were regenerated. Live QA used clearly prefixed `RC1` records in the existing local development account rather than deleting pre-existing user data.

The local development database intentionally retains the QA evidence: 13 `RC1` manual Foods (12 logged), 12 Daily Logs, six favorites, and one `RC1 Scanned Label Food` with one service-immutable / append-only OCR trace. No pre-existing rows were removed.

## 2. Automated release gate

| Gate | Result |
| --- | --- |
| Backend full suite | PASS — 394 passed, 12 PostgreSQL-gated skipped |
| PostgreSQL concurrency suite | PASS — 12 passed against PostgreSQL, 394 deselected |
| Baseline-to-head migration | PASS in an isolated temporary PostgreSQL schema |
| Latest downgrade/re-upgrade | PASS: `0012_food_favorites` → `0011_nutrition_target_foundation` → head |
| Ruff | PASS |
| Backend import/startup | PASS — import reported API title and 12 routes; live Uvicorn OpenAPI request returned 200 |
| Mobile Jest | PASS — 58 suites, 421 tests |
| TypeScript | PASS |
| Expo prebuild | PASS — clean prebuild |
| CocoaPods/autolinking | PASS — 84 pods; `NutritionOcr` linked |
| iOS Release simulator build | PASS after the bounded Hermes fix below |
| Production JavaScript export | PASS — 804 modules, Hermes bundle, 19 assets |
| Dependency consistency | PASS — `pip check` reported no broken requirements |
| `git diff --check` | PASS |

The 12 skips in the ordinary backend run are all `postgres_concurrency` tests and were separately executed against PostgreSQL:

1. concurrent Daily Log create idempotency;
2. concurrent OCR confirmation idempotency;
3. concurrent favorite identity-race recovery;
4. target override uniqueness;
5. idempotency migration upgrade/downgrade;
6. serialized quantity patching;
7. metadata patching against committed nutrition;
8. rollback waiter recovery;
9. unrelated-log non-blocking behavior;
10. coherent amount-definition changes;
11. serialized manual Food updates;
12. serialized deleted-projection revision log updates.

No PostgreSQL test is being counted as passed from a skip.

`npm audit` reports 11 moderate, zero high, and zero critical transitive findings in Expo 53 tooling (including PostCSS and `xcode`/`uuid`). npm proposes an Expo 57 semver-major update. That upgrade is not a bounded RC correction and remains an accepted dependency-upgrade item. Clean install also emits transitive package deprecation notices.

## 3. Warning investigation

### React `act(...)`

Source: two synchronous renderer unmounts in `foodLogHandoff.integration.test.ts`. They scheduled mounted-component state work outside `act`, so the warning could hide incomplete asynchronous assertions. Both unmounts now await `act`. The focused integration test and the final full Jest run are warning-free.

### Starlette/httpx

Source: Starlette 1.3.1's test client prefers the separately distributed `httpx2` package and warns when it falls back to legacy `httpx`. `httpx2>=2.5,<3` is now a development dependency; production `httpx` remains because the USDA client uses it. Focused and full backend runs are warning-free. This is a test-transport compatibility correction, not a production behavior change.

### Accepted toolchain warnings

The Release build still emits warnings owned by React Native 0.79.6 / Expo 53 / CocoaPods-generated code: deprecated React methods, missing third-party nullability annotations, empty archive objects, Hermes/Codegen build phases without output declarations, and duplicate `-lc++`. The build completes and the warnings do not point into application-owned native code. CocoaPods also reports third-party codegen/direct-pod-install deprecations. Expo export reports that `NO_COLOR` is ignored because its own worker environment sets `FORCE_COLOR`. These are non-blocking upgrade backlog; none were globally suppressed.

## 4. OCR physical-device results

Not executed. The only registered physical iPhone was offline. Therefore camera and photo-library permissions, real image orientation, recognized dimensions, overlay alignment, reading order, temporary-file cleanup, OCR duration, glare/skew/small-text behavior, and stale-result behavior on physical hardware are unverified in RC1.

The simulator Release build includes and autolinks the Apple Vision `NutritionOcr` module, but Simulator evidence is not a substitute for camera geometry. No parser or geometry behavior was changed from simulator-only evidence.

## 5. OCR confirmation results

A representative confirmation was exercised through the live Uvicorn/PostgreSQL stack. It created a manual Food labeled `Scanned label`, persisted an `ocr_confirmed` source kind, retained explicit sodium zero as `0.000000`, and returned one trace ID. An unchanged retry returned the identical 201 response; an edited payload with the same request ID returned 409 with `ocr_confirmation_idempotency_conflict`.

The automated suite covers clean/old-style labels, fractions, servings per container, household and gram servings, explicit zero, less-than values, missing and unknown nutrients, conflicts, confidence/review states, malformed input, confirmation guards, idempotency recovery, editing/duplication/logging/deletion, and trace privacy. These cases were not all repeated with physical labels during this pass.

## 6. Food discovery results

The live stack was populated with 12 recent manual Foods and six favorites, including a long Food name and brand. The APIs returned exactly six favorites and 12 recents in log-creation order; a past-date log was still recent. Large and small simulator screenshots showed five-row Favorites and Recent previews, the `preview` terminology, source labels, empty states, populated states, and long-name wrapping. The existing automated suite remains the authority for repeated favorite idempotency, delete filtering, historical-log edits, prior-usage reveal, Recipe projection inclusion/exclusion, provenance redaction, nested Recipe selection, and cycle prevention.

## 7. Daily Log and target results

The live daily summary for 2026-07-14 returned snapshot-derived totals of 1,740 kcal and 2,975 mg sodium. The comparison endpoint used FDA catalog `fda_daily_values_2016_v1`; sodium returned 129.3478% against 2,300 mg, direction `limit`, with no percentage cap. Calories correctly returned `target_unavailable` when no personal profile was configured. Automated regressions cover no-log dates, Recipe revision history, deleted source Recipes, unknown contributors, explicit zero, target changes, date-scoped refresh, target/minimum/limit/reference directions, and 80% styling terminology.

The progress-bar accessibility node duplicated the complete nutrient-row announcement. The visual bar is now excluded from the accessibility tree; the separately accessible row label retains nutrient, amounts, percentage, authority, direction, overflow, and incomplete-data semantics.

## 8. Recipe results

The full automated Recipe suite passed. The read-only retention audit inspected five Recipes, four projections, and one publication revision. It found zero inconsistent rows, zero orphan revision children, and zero purge candidates. Active and compatibility-retained projections/revisions were all protected. Interactive publish/republish/dependency dialogs were not manually tapped in Simulator during this pass.

## 9. Accessibility results

Mounted-component tests cover headings, labels, roles, selection, busy/disabled states, OCR review decisions, unknown-row dismissals, target semantics, source/favorite state, and independent controls. The target-row redundancy correction is described above.

At `accessibility-extra-extra-large` on iPhone 17e, fixed Saved Foods chrome initially clipped the settings control and made action/tab labels unusable. Root titles, tab labels, fixed scan/custom actions, and the fixed search input now cap visual scaling at 1.5 while preserving full accessibility labels and touch targets. Scrollable content continues to honor the device's full text size. The rebuilt Release app was visually rechecked at the same setting: root settings, scan, custom Food, search, and all three tabs remained reachable and legible.

Actual VoiceOver speech, focus order, urgency, rotor behavior, and control activation were not executed because no physical device was available and the CLI harness does not expose the spoken accessibility tree. TalkBack remains a separate Android release requirement.

## 10. Visual and keyboard results

Release screenshots were inspected on iPhone 17 Pro Max and iPhone 17e in light and dark appearance, with empty, populated, backend-unavailable, long-name, and large-Dynamic-Type states. The bounded large-type defect above was corrected. No unreadable contrast or non-scrollable populated state was confirmed. Keyboard presentation/dismissal and every form's keyboard-safe scrolling were not manually exercised; their component contracts remain covered by Jest.

## 11. Network and lifecycle results

Stopping the backend while launching the mounted Release app produced bounded Favorites, Recents, and Saved Foods unavailable messages, with explicit retry controls and the rest of navigation/actions intact. Restarting the backend and backgrounding/foregrounding the same process did not automatically refetch; the visible Retry action is the supported recovery boundary. Its activation is covered by mounted tests but was not physically tapped in this pass. Uvicorn recovered and served 200 responses without rebuilding the app.

Automated flow-specific tests cover 400/409/500/network error mapping, unchanged versus edited retries, response-loss idempotency, synchronous rapid-tap guards, and unmount safety for Daily Logs, OCR confirmation, favorites, Recipe publication, and targets. Process-death recovery is not claimed for mounted-screen request identities.

## 12. Database integrity results

Read-only post-workflow queries returned zero duplicate favorites, zero Foods with multiple OCR traces, zero duplicate confirmation request IDs, zero duplicate Daily Log request IDs, zero duplicate nutrient rows per snapshot set, zero orphan traces, and zero cross-user trace relationships. The single live OCR trace contained no forbidden path/URI material and no raw/full OCR text or image URI/path key. Alembic remained at `0012_food_favorites`.

The Recipe retention audit returned zero inconsistent rows and zero purge candidates.

## 13. Findings by severity

### Release blocker — resolved: Release build failed in a checkout path containing spaces

- Reproduction: clean prebuild/Pods followed by a Release simulator `xcodebuild` from `Nutrition App`.
- Platform: iOS Release build.
- Evidence: React Native 0.79.6's Hermes replacement interpolated `PODS_ROOT` into an unquoted `tar` shell command and truncated the path at the space.
- Consequence: no installable iOS Release artifact.
- Root cause: upstream Hermes build script shell interpolation.
- Correction: the existing iOS build-workaround plugin now rewrites only the Hermes replacement phase to use a no-space temporary symlink.
- Regression requirement: clean prebuild, Pods install, and Release build from the current path; all pass.

### High — resolved: fixed app chrome unusable at accessibility text size

- Reproduction: iPhone 17e, `accessibility-extra-extra-large`, open Saved Foods.
- Platform: shared iOS screen chrome.
- Evidence: clipped settings icon, oversized floating actions, truncated tab labels, and overlap in the pre-fix screenshot.
- Consequence: core navigation and Food creation controls were difficult or impossible to use.
- Root cause: fixed-height/absolute chrome allowed unbounded visual font scaling.
- Correction: cap only fixed chrome at 1.5; preserve full scaling in scrollable content and preserve complete accessible labels.
- Regression requirement: new fixed-chrome test, updated Saved Foods test, focused suite, full Jest, and rebuilt Release screenshot all pass.

### Low — resolved: duplicated target progress VoiceOver semantics

- Reproduction: inspect the mounted accessibility tree for a target row.
- Platform: shared accessibility semantics.
- Evidence: the complete row label and an adjacent progressbar repeated percentage/direction.
- Consequence: redundant announcements and slower navigation.
- Root cause: a decorative visual bar was also exposed as a semantic progress node.
- Correction: hide the visual bar while retaining the complete row text equivalent.
- Regression requirement: target progress test asserts no progressbar node and a retained complete row label.

### Low — resolved: React asynchronous test warning

Reproduction, cause, correction, and regression evidence are in section 3.

### Low — resolved: Starlette test transport deprecation

Reproduction, cause, correction, and regression evidence are in section 3.

### Accepted limitation — physical and spoken accessibility QA incomplete

The registered iPhone was offline. This is a release-evidence gap, not a confirmed production defect. It blocks calling the build production-ready, but it does not block a limited internal/TestFlight build whose purpose includes completing physical OCR and VoiceOver validation.

### Accepted limitation — Expo 53 dependency warnings/audit findings

Eleven moderate transitive audit findings and the native build warnings described above require a coordinated Expo/React Native upgrade, not an RC patch. There are no high or critical npm findings.

## 14. Corrections implemented

1. Correctly await React renderer unmounts in `act`.
2. Install Starlette's preferred `httpx2` test transport in backend development environments.
3. Make the Hermes Release replacement phase safe for workspace paths containing spaces.
4. Remove redundant target progressbar accessibility semantics.
5. Keep fixed root chrome usable at accessibility text sizes while retaining fully scalable content.

## 15. Tests added

- New `fixedChromeDynamicType.test.ts` verifies the root header and all three tabs cap fixed visual labels.
- `foodDiscovery.test.ts` now verifies fixed Saved Foods action/search scaling.
- `targetProgressSection.test.ts` now verifies the visual bar is excluded without removing the row text equivalent.
- `foodLogHandoff.integration.test.ts` now awaits both unmount updates.

## 16. Unexecuted QA and reasons

- All physical-camera, photo-library permission, orientation/overlay, temporary-file, glare/skew, and performance cases: physical iPhone offline.
- Physical representative-label confirmation matrix: physical iPhone offline.
- Actual VoiceOver speech/focus/rotor/urgency checks: no available physical session or CLI accessibility inspector.
- TalkBack: Android remains a separate shared-screen release requirement; Android OCR is out of scope.
- Full touch-driven Recipe and form walkthrough, keyboard dismissal, Cancel-while-pending, and retry activation: Simulator CLI could build, launch, configure, and capture, but did not provide reliable touch/assistive interaction automation.
- Controlled packet latency, response loss after commit, and app backgrounding mid-write on the live stack: automated idempotency/lifecycle contracts passed; no network conditioner was available in this session.

## 17. Release recommendation

**A. Ready for a limited internal/TestFlight release.**

- Automated-contract confidence: high; all clean suites and release build/export gates pass.
- Simulator confidence: moderate-high; large/small, light/dark, populated/empty/offline, and large-type Saved Foods states were exercised.
- Physical-device confidence: low; no physical OCR session was possible.
- Accessibility confidence: moderate; mounted semantics and large-type layout pass, but spoken VoiceOver remains unverified.
- Backend/database confidence: high; real PostgreSQL concurrency, migrations, live API workflows, invariant queries, and retention audit pass.

This recommendation is deliberately limited to internal/TestFlight distribution. The app is **not assessed as production-ready** until the physical OCR matrix, real VoiceOver walkthrough, and remaining touch/keyboard/network-conditioner cases are completed.

## 18. Final release-QA checklist

- [x] Clean mobile and backend dependency installs
- [x] Full backend suite
- [x] Real PostgreSQL concurrency suite
- [x] Baseline upgrade and latest downgrade/re-upgrade
- [x] Ruff, TypeScript, import/startup, production export
- [x] Clean prebuild, Pods/autolinking, iOS Release build
- [x] Known React and Starlette warnings resolved without suppression
- [x] Populated Favorites/Recents live-stack smoke
- [x] Daily summary and uncapped target comparison live-stack smoke
- [x] OCR confirmation replay/conflict live-stack smoke
- [x] Backend-unavailable presentation
- [x] Large/small, light/dark, long-name, and large-type screenshot review
- [x] Database invariant and Recipe retention audits
- [x] `git diff --check`
- [ ] Physical-device OCR camera/geometry/cleanup matrix
- [ ] Real-label physical confirmation matrix
- [ ] VoiceOver spoken focus and interaction matrix
- [ ] Touch-driven keyboard and pending/cancel/retry matrix
- [ ] Controlled live latency/response-loss/backgrounding matrix
