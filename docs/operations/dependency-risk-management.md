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

## Retained findings

The historical AUDIT-08 / issue #166 review covered three Dependabot alerts.
The two `image-size` records were retired after the package left the mobile
lockfile. The canonical register currently retains one `uuid` record. Do not
reuse the historical installed paths or versions as a current dependency graph.

The retained package is reached through `expo-sharing`, `@expo/config-plugins`,
and `xcode`. The reviewed `xcode` caller uses `uuid.v4()`; the advisory concerns
other UUID APIs with caller-supplied buffers. The exact versions, edges,
advisory, reviewed commit, and reevaluation triggers live in the risk register.
After every dependency refresh, run offline validation to detect any changed
package, owner, version, or reachability boundary before relying on this
disposition. A new upstream finding requires its own review rather than an
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
ownership with `npm explain`, verifies Metro's installed image-size asset
surface, and inspects the installed xcode package for UUID API usage.

This separates package-manager proof from assumptions encoded only in prose.

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
