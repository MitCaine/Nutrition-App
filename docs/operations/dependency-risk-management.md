# Dependency risk management

> **Document role: Current Guide.** This guide explains how retained
> dependency-security findings are classified, validated, monitored, and
> remediated.

## Authority

`engineering/security/dependency-risk-register.json` is the canonical
machine-readable source for retained dependency risk.

Dependabot and the GitHub Advisory Database remain the external sources for
repository alerts and advisory facts. The risk register owns the
repository-specific analysis: exact installed package and dependency path,
vulnerable precondition, reachability evidence, supported-remediation state,
disposition, review commit, and reevaluation triggers.

The register does not suppress security findings. A Dependabot alert may remain
open while its repository-specific risk is understood and monitored.

## Dispositions

The repository distinguishes scanner severity from repository-specific
reachability and remediation.

`non-reachable residual dependency risk` means the affected package and version
are installed, but the vulnerable API or input path is not used through the
current dependency owner.

`upstream-blocked accepted risk` means the vulnerable package is relevant to a
bounded installed surface, but there is no currently supported compatible
remediation.

If upstream facts change so that a supported remediation becomes available, the
accepted-risk path stops. The record must be reevaluated and remediation handled
as a bounded implementation task.

## Current findings and retained history

The historical AUDIT-08 / issue #166 review covered three Dependabot alerts.
The two `image-size` records were retired after the package left the mobile
lockfile. Completed [issue #252](https://github.com/MitCaine/Nutrition-App/issues/252)
retired the remaining `uuid` active record into `retired_records`, preserving its
historical UUID 7 assessment and validating the fixed UUID 11.1.1 replacement.
There are no active accepted-risk records. The same task patched brace-expansion
to 5.0.12 and its four nested copies to 1.1.21. Do not reuse historical installed
paths or versions as a current dependency graph.

In the historical replacement graph, the replacement package was reached through
`expo-sharing`, `@expo/config-plugins`, and `xcode`. That reviewed `xcode` caller
used `uuid.v4()`; the historical UUID 7
finding concerned other UUID APIs with caller-supplied buffers. The exact versions, edges,
advisory, reviewed commit, and reevaluation triggers live in the risk register.
After every dependency refresh, run offline validation to detect any changed
package, owner, version, or reachability boundary before relying on the recorded
replacement. A new upstream finding requires its own review rather than an
automatic extension of this record.

## Offline validation

Run:

    python scripts/dependency_risk.py validate-offline

Offline validation does not require mutable upstream state. It fails closed when
the recorded package version, package location, dependency owner, dependency
edge, or reviewed reachability boundary changes.

A vulnerable package disappearing is also treated as drift. Removing the package
may be the correct security outcome, but the stale accepted-risk record must
then be deliberately retired or updated rather than silently passing.

## Installed-graph validation

After installing the exact mobile lockfile, run:

    cd apps/mobile
    npm ci --audit=false
    cd ../..
    python scripts/dependency_risk.py validate-installed

For the current upstream-removal record, installed validation derives the reviewed
sharing → config-plugins → xcode 4 paths with `npm ls`, verifies the installed owner
and dependency metadata, and requires UUID to be absent from the installed tree
and xcode source imports. The offline check also requires UUID absence from the
lockfile and verifies its exact reviewed edges. These are the current graph checks.

For historical records without the removal marker, installed validation retains
the original replacement-path checks: `npm ls`, ownership through `npm explain`,
and exactly one `uuid.v4()` call with no `uuid.v3`, `uuid.v5`, or `uuid.v6` calls.
Neither route validates an installed Metro / image-size asset surface.

This separates package-manager proof from assumptions encoded only in prose.

### Historical replacement-graph security check

Only for a historical locked graph that still contains the reviewed UUID replacement,
run from the repository root after its locked `npm ci` installation:

    node apps/mobile/scripts/check-security-dependencies.cjs

This preserved helper requires UUID to be installed, so it is not a current-graph
check after upstream removal. Use the offline and installed validation commands
above for the current graph. For its historical graph, the helper compares installed
and locked brace-expansion/UUID versions and checks
that the UUID override is scoped to xcode. It exercises ordinary brace expansion
and five hostile inputs against every installed brace-expansion copy, with each
hostile case in a separate process bounded by a 15-second deadline. It checks
UUID v3/v5/v6 invalid output-buffer bounds, unchanged buffers on rejected writes,
and valid writes, then invokes the actual xcode caller to generate 1,000 unique
uppercase 24-character hexadecimal identifiers. This focused check complements
installed-graph validation; it does not replace Jest, repository/mobile/iOS native
qualification, or independent review.

## Remote monitoring

`.github/workflows/dependency-risk-monitor.yml` provides a dedicated bounded
monitoring surface.

For relevant repository changes it runs the deterministic validator and exact
installed-graph validation. On its weekly schedule or manual dispatch it also
checks mutable upstream facts.

The remote check compares the reviewed baseline against current GitHub advisory
metadata and npm registry metadata for the tracked packages and dependency
owners. Material changes include advisory changes, a new image-size release,
Metro changing its image-size dependency, a new xcode release, xcode changing
its UUID dependency, or Expo configuration tooling changing its xcode
dependency.

An unchanged scheduled check succeeds without creating repository state, issue
comments, or alert dismissals. A material change fails the monitoring job and
uploads machine-readable comparison evidence so the accepted-risk record can be
reevaluated.

## Remediation rules

Do not dismiss a Dependabot alert merely to make the security dashboard green.

Do not use package-manager `overrides`, `resolutions`, direct lockfile edits,
vendored forks, or unsupported transitive pinning solely to silence a finding.

The [#454/#455 repair research](../engineering/dependency-security-repair-research.md)
compares bounded security backports and migration options. It is a research
snapshot, not an accepted exception, implemented repair or risk disposition.

When a compatible supported fix becomes available, stop relying on the previous
accepted-risk disposition, create or identify the bounded remediation task,
update through the supported dependency chain, and run the required repository
and mobile qualification. Dependabot should close naturally after the corrected
dependency graph reaches `main`.

## Review triggers

Reevaluate the register when its validator or monitor reports drift, when
Expo/React Native/Metro/Xcode tooling changes, when the OCR input boundary
changes, when an advisory affecting a tracked package changes, or when a tracked
vulnerable package disappears.

Historical security work remains historical. AUDIT-08 does not reopen completed
SEC-01 work.

## Owner-authorized UUID compatibility exception

For issue #252 the repository owner explicitly authorized: “You have permission
to update UUID 7 to the fixed version”. The exception is limited to
`overrides.xcode.uuid = "11.1.1"`. Upstream xcode 3.0.1 still declares
`uuid ^7.0.3`; this is a tested repository compatibility exception, not a claim
that upstream supports UUID 11. The general prohibition on unsupported forcing
solely to silence findings remains in force.

The retired record preserves the previous UUID 7 assessment and owner authority.
Offline validation permits zero active records only with a validated retirement;
it checks the exact replacement path, upstream declaration, and scoped manifest
override. Installed validation still derives the replacement's npm path and owner
and inspects the actual xcode caller. Missing authority, downgrade, owner drift,
or a missing/global override fails closed. Acceptance also requires the focused
hostile UUID bounds and xcode caller checks, existing Node-host Jest fixture,
repository/mobile/iOS native qualification, and fresh independent review.
Upstream advisory and dependency-owner monitoring remains active after retirement.

The top-level `reviewed_at`/`reviewed_commit` fields and preserved historical
assessment identify the original accepted-risk review; they do not attest to
review of the replacement candidate. Replacement acceptance is bound to the
completed issue #252 controller's exact candidate qualification and
independent-review records, indexed in the
[GH-252 capsule history](../../engineering/capsules/HISTORY.md#gh-252---patch-mobile-brace-expansion-and-scoped-xcode-uuid-vulnerabilities).
The accepted candidate passed protected security checks, risk-retirement tests,
offline/installed validation, repository/mobile/iOS native qualification, and
fresh independent review before guarded integration. Separate qualified and
reviewed terminal closeout retained the full reviewed capsule. The register
records authorization and validation requirements; its original review fields
remain historical evidence rather than proof of these replacement gates.

## Current upstream UUID removal

GH-443's reduced Expo patch resolves expo-sharing 57.0.24 → config-plugins 57.0.11
→ npm xcode 4.0.0. Upstream xcode no longer declares UUID. The register appends
`current_upstream_removal`; historical assessments, authority, replacement and the
GH-384 re-evaluation remain unchanged. Their original readers remain selected for
old records without the removal marker.

For the current marker, offline validation requires the exact reviewed versions and
edges, UUID absence throughout the lock, no UUID dependency edge, and no additional
xcode installation. Installed validation checks the actual xcode path/owner, full npm
tree UUID absence and absence of UUID imports in the installed owner. Drift or UUID
reintroduction fails closed. The old scoped manifest override stays unchanged and is
inert with no UUID dependency; this is no new override or advisory dismissal.
Repository/mobile/iOS-native qualification and independent review remain required.

## Zod compatibility exception

Nutrition selects Zod 4.6.7 for the app and uses an `@expo/cli`-only override
referencing that same direct dependency. Expo still declares Zod 3; this is a
repository-qualified compatibility exception, not upstream Expo support. It
removes the separate vulnerable resolution while retaining the native dependency
baseline and PostCSS 8.5.30. Do not replace it with a blanket override or infer
compatibility for new callers from this selection.

The normal `npm test` command runs this compatibility check through `pretest`,
including in mobile CI. After an exact locked installation, it can also run
directly from `apps/mobile`:

    node scripts/check-zod-compatibility.cjs

The check resolves Zod from the actual installed Expo caller, requires a single
patched lock entry, discovers the installed CLI's Zod imports, and exercises its
real plugin/output schemas, plugin constructor and MCP registration boundary.
It verifies required/optional fields, parameter types, strict unknown-key rejection
and the exclusion of CLI-only commands from MCP schemas. New imports or legacy
subpath engines fail closed for review. The ordinary Expo configuration/Doctor,
mobile tests and native qualification remain separate requirements.

The selected graph does not install the optional `expo-mcp` transport. The check
covers schema registration, not a live tunnel or plugin-command execution. Adding
that transport requires separate compatibility qualification; this exception does
not grant it. The bounded collection regressions in `zodMigration.test.ts` verify
that oversized constrained collections reject before element parsing, without an
out-of-memory test. They do not claim that unconstrained collections become bounded.


## Maintained deepmerge security backport

For #454 the owner explicitly authorized the researched backports, required checks,
independent review, publication and protected merge, preserving PostCSS8.5.30 and
recovery. This permits the bounded deepmerge4.3.1 behavior repair; it does not accept
unresolved risk or authorize alert suppression. The upstream proposed fix remains
unmerged. The root direct file dependency and exact-version `$deepmerge` override
select the repository-contained archive before any install hooks, including with
`npm ci --ignore-scripts`. Original package identity/version and MIT notice remain.

`apps/mobile/vendor/security/deepmerge` retains the original integrity-bound archive,
patched archive, readable patch, license and per-member provenance. From the root,
run `python scripts/build-mobile-security-backports.py --check` with the selected
Python3.14 to reproduce/check all bytes offline. The bounded recipe applies the
same two-loop key exclusion to source and published CJS/UMD distributions; it uses
no downloaded compiler or install-time patch. All other payload members are intact.
The pretest `check-security-backports.cjs` verifies every installed member and actual
Expo/Jest owner resolution, plus hostile and ordinary behavior through their callers.
Current risk validation pins the artifact/graph; historical UUID/Zod evidence stays
unchanged. The targeted updater copies and binds these inputs before scratch installs.

This creates maintenance responsibility: dependency-owner changes require rebasing
or replacing the patch and fresh compatibility/security qualification. Original
advisory/version findings may remain visible; disappearance from a local-file
scanner is not proof of repair. No accepted-risk entry or alert dismissal is added.
Glob/minimatch remediation is separate #455 work, with minimatch3 findings open.

## Maintained glob/minimatch backports and legacy findings

The same explicit owner decision authorizes #455's bounded glob13.0.6 cancellation
and minimatch10.2.6 preprocessing repairs, with required qualification/review before
publication/protected integration. Original package names/versions, licenses,
dependency ranges and the previous deepmerge/Zod/UUID selections remain. PostCSS
stays8.5.30. Glob7 and minimatch3 are not upgraded or patched by this work; unresolved
minimatch3 findings remain open, without accepted-risk or alert-dismissal changes.

Glob's original default `index.min.js` entrypoints bundle a private minimatch copy.
Patching only readable walker modules or the standalone dependency would miss it.
The maintained archives preserve the public default/raw paths and exported APIs,
but default CJS/ESM entrypoints forward to their corresponding readable `index.js`.
They now use the declared, locked and patched minimatch instead of hidden bundled
third-party code. This delivery difference requires explicit default/raw CJS/ESM
parity, cancellation, paused-stream and real Expo-caller qualification.

The complete five-edit upstream glob repair includes the four immediate callback
returns and the `onResume` correction. The minimatch repair bounds generated
patterns with `braceExpandMax` (default100,000) and skips pairwise deduplication for
more than1,000 entries. As with the existing brace-expansion limit, expansion above
the cap can be incomplete: do not promise unrestricted matching equivalence after
clipping. Ordinary below/at-cap matches and large-set positive/negative behavior
are tested; the default cap runs only on patched code in a resource-bounded child.
Existing real timeouts, including Expo's five-second search deadline, remain.

`apps/mobile/vendor/security/glob` and `minimatch` contain original/patched archives,
readable source patches, licenses and complete payload provenance. Corrected source,
CJS/ESM modules and JavaScript maps are generated with exact esbuild0.28.2. Unchanged
declaration files retain their bytes; declaration maps rebase only source positions,
with preserved source tokens checked through an independent decoder. The original
bundles remain in the original archives for provenance/recovery.

The build manifest/lock is in `apps/mobile/vendor/security/build`. Copy those two
files to an isolated task-owned directory and install that exact lock with scripts
disabled; never install build tools globally or into the application runtime.
The offline check is then run from the repository root with selected Python3.14:

    python scripts/build-mobile-security-backports.py --package all --check --tools-root /absolute/path/to/locked-build-tools

No automatic compiler installation or runtime build hook is selected. The existing
pretest verifier covers all maintained archives, complete installed inventories,
actual owner resolution, source-map contents, public APIs and bounded security
behavior. Focused negatives exercise actual corruption, stale default bundles,
symlinks, extra copies, selectors and legacy-source preservation. Dependency updater
scratch installs stage these same immutable inputs and fail closed on drift.

Source repair does not change published advisory ranges. Capture actual audit and
hosted scanner outcomes without treating their disappearance as proof; original
versions and legacy minimatch3 may remain flagged. Keep issues tracking unresolved
scanner/applicability/maintenance obligations open after verified behavior repairs.
