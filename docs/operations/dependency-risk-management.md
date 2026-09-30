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

The replacement package is reached through `expo-sharing`, `@expo/config-plugins`,
and `xcode`. The reviewed `xcode` caller uses `uuid.v4()`; the historical UUID 7
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

Installed validation derives the current dependency paths with `npm ls`, checks
ownership with `npm explain`, and inspects the installed xcode package for exactly
one `uuid.v4()` call and no `uuid.v3`, `uuid.v5`, or `uuid.v6` calls. Currently this
validates the UUID replacement path; it does not validate an installed Metro /
image-size asset surface.

This separates package-manager proof from assumptions encoded only in prose.

### Focused security check

After the same locked `npm ci` installation, run from the repository root:

    node apps/mobile/scripts/check-security-dependencies.cjs

The check compares installed and locked brace-expansion/UUID versions and checks
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
