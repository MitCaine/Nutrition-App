# Remaining minimatch 3 findings — resolution assessment

Research snapshot: October 31, 2026, source `1efa58ccbcd4e8c5ef710d82b2072b190c0a7a34`. This is preparation, not remediation, accepted risk, or permission to dismiss an alert. Current tracking remains [GH-455](https://github.com/MitCaine/Nutrition-App/issues/455). Earlier [backport research](dependency-security-repair-research.md) and completed candidates remain historical evidence.

## Recommended decision

Seek an authoritative affected-range clarification for GHSA-g3hv-75wg-m249 first. The described vulnerable optimizer is absent from the installed minimatch 3 implementation. There is no corresponding optimizer fix to backport into 3. Introducing the modern algorithm or forcing minimatch 11 underneath glob 7 would create avoidable compatibility and maintenance risk.

Keep the findings and GH-455 open pending that clarification. A source-based applicability assessment is strong evidence for this specific mechanism; it does not prove that minimatch 3 is generally secure or authorize overriding the published database range. Preserve PostCSS at 8.5.30 and the already qualified modern backports.

## Evidence and its limits

The [maintainer's repository advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249) lists affected version 10.2.6 and patched version 11.0.1. It describes amplification in `firstPhasePreProcess()` at optimization level 2, followed by pairwise processing. The [GitHub Advisory Database entry](https://github.com/advisories/GHSA-g3hv-75wg-m249), last updated October 30, instead declares all versions below 11.0.1 affected. This discrepancy requires clarification; neither page establishes the exact lower bound for every modern version.

The [upstream changelog](https://github.com/isaacs/minimatch/blob/main/changelog.md) places advanced preprocessing in 7.0 and the `optimizationLevel` option in 7.1. The [actual repair](https://github.com/isaacs/minimatch/commit/77a0f5c4b80bdc641c3c930a1d9edf5ad2db57f8) bounds those modern preprocessing functions. In contrast, [versioned 3.1.5 source](https://github.com/isaacs/minimatch/blob/v3.1.5/minimatch.js) and the inspected installed implementation brace-expand, split path portions, and parse directly. The three relevant modern symbols are absent. Other brace-expansion, regular-expression or matching resource risks are separate questions.

The current lock and installed source contain four minimatch 3.1.5 copies:

| Owning installed directory | Observed use |
| --- | --- |
| `@jest/reporters` | glob 7 coverage-threshold path expansion |
| `jest-config` | glob 7 project-pattern expansion |
| `jest-runtime` | glob 7 sibling-file suggestions |
| `test-exclude` | callable minimatch include/exclude matching and glob 7 coverage enumeration |

All four `minimatch.js` files have SHA256 `746849f267c4868a53729225bd85c7dccd387712136fb305fcc0a3eadd4a3d9d`. Their lock integrity is `sha512-VgjWUsnnT6n+NUk6eZq77zeFdpW2LWDzP6zFGrCbHXiYNul5Dzqk2HHQ5uFH2DNW5Xbp8+jVzaeNt94ssEEl4w==`. Installed source exports a callable CommonJS function. Glob 7 also uses matcher constructors and internal pattern sets; replacing this contract with modern named exports requires more than changing a version string.

The retained GH-455 candidate audit names this one advisory for minimatch and propagates it to all copies. That audit is historical, not a newly executed audit or current hosted-alert inventory. Its React Native major-upgrade suggestion does not establish a compatible remediation. This assessment freshly checked the source/lock inventory and live advisory pages, but did not run a hostile pattern, install a candidate, or execute a fresh audit.

## Concrete next step

Prepare an upstream advisory improvement with these facts: inspected version 3.1.5; exact source and affected function names; absence of the modern optimizer; its introduction described in the changelog; and the discrepancy between repository advisory 10.2.6 and database `<11.0.1`. Ask the maintainer/database reviewers to confirm whether 3.x is excluded and determine the correct affected range. Do not guess a replacement lower bound or claim every version before 7 is unaffected without checking them.

GitHub documents an [advisory improvement submission route](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/fix-reported-vulnerabilities/edit-advisory-database). This research sends no upstream message and changes no advisory or alert. Publication is a separate authorized action. Once an authoritative response exists, retain it, refresh audit/dependency-graph observations, and reconcile each remaining finding explicitly. A corrected range may remove the legacy findings while locally maintained modern packages still retain their original affected version identities; those are separate dispositions.

Before submitting, strengthen the evidence with complete 3.1.5 package-to-upstream payload comparison and small bounded mechanism samples under an external deadline. Avoid a resource-exhaustion baseline and do not interpret a finite sample as general denial-of-service immunity. Independent inspection should challenge the proposed applicability conclusion before any local finding disposition.

The subsequent [prepared submission](minimatch3-advisory-submission.md) records that stronger evidence: every installed payload equals the integrity-verified original npm archive, its runtime source equals the versioned upstream source, and three finite small patterns per copy retain identical parsed sets with or without the unsupported optimization option. The sample has an external 10-second deadline and 128 MiB JS heap bound. This preparation does not establish that upstream has accepted or corrected anything. Owner-approved submission and documentation integration are tracked in [GH-460](https://github.com/MitCaine/Nutrition-App/issues/460); later publication and response remain external.

## If removing legacy packages is required

Treat owner migration as a separate coordinated Jest/coverage change. Installed React Native 0.86.3's Jest preset still depends on Jest 29 tooling. Updating only root Jest can leave older transitive tooling in place. Capture every owner edge and prove all four legacy copies disappear in the resulting locked graph.

Upstream development manifests for [Jest config](https://github.com/jestjs/jest/blob/main/packages/jest-config/package.json), [Jest reporters](https://github.com/jestjs/jest/blob/main/packages/jest-reporters/package.json), and [test-exclude](https://github.com/istanbuljs/test-exclude/blob/master/package.json) already use glob 13/minimatch 10 lines. These are development-source observations, not evidence of a published, Expo/React Native-compatible migration or a scanner-clean graph. Those modern version lines also need the existing reviewed backports under the current advisory range.

Prototype only in an isolated workspace with its own lock and cache. Compare project/test discovery, missing-module suggestions, include/exclude/negation/dotfile behavior, coverage file sets and thresholds, and real React Native preset execution. Preserve current TypeScript/Jest behavior, licenses, all backport identities and PostCSS 8.5.30. Require narrow lock review, focused regressions, full mobile tests, Expo compatibility, risk/updater guards, required CI and profile qualification, fresh independent review, protected integration and installed checks. Do not use a global 3-to-11 override, a disguised package version, a postinstall mutation or an unqualified platform downgrade.

## Recovery and validation boundary

The external research inventory retains the exact base, four source hashes, lock integrities, symbol checks and PostCSS selection. Existing GH-454/GH-455 worktrees, original packages, compiler environments, failed attempts, checkpoints and native evidence remain untouched. No package declaration, lock, installed dependency, release, database or application history changes in this assessment. Any future migration must retain the current qualified source/lock and preserve failed candidates; rollback after integration uses a reviewed corrective change, not a protected-main reset.

This research document is ready to guide an advisory clarification or separately bounded migration investigation. It is not a qualified dependency candidate, an independent acceptance review or completed vulnerability resolution.
