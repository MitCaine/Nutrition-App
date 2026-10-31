# Prepared advisory clarification submission

Preparation snapshot for [GH-460](https://github.com/MitCaine/Nutrition-App/issues/460). Owner authorization covers submission after review and documentation integration; live issue and external execution evidence own later publication and response. This document alone does not establish that a submission was sent or accepted.

Destination: `github/advisory-database`, an existing-advisory clarification request for GHSA-g3hv-75wg-m249. Request curator/maintainer determination rather than proposing an unverified replacement range. No new vulnerability or exploit is being disclosed. The [assessment](minimatch3-resolution-assessment.md) records the local decision and fallback.

## Submission title

GHSA-g3hv-75wg-m249: clarify minimatch 3.1.5 applicability and affected range

## Submission body

Could the advisory reviewers and original publisher clarify whether **minimatch 3.1.5** is affected by **GHSA-g3hv-75wg-m249 / CVE-2026-118764**, and correct the published affected range if this version is excluded?

The [maintainer's advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249) lists affected version **10.2.6**. The [GitHub Advisory Database record](https://github.com/advisories/GHSA-g3hv-75wg-m249) lists **<11.0.1**. Both describe input amplification in `firstPhasePreProcess()` with `optimizationLevel >= 2`, followed by quadratic `secondPhasePreProcess()` work. Why does the database include all earlier versions, including 3.1.5, when the described optimizer is absent from that source?

Our Nutrition App mobile lock at source `1efa58ccbcd4e8c5ef710d82b2072b190c0a7a34` installs four copies of **minimatch 3.1.5** under these dependency paths (relative to `apps/mobile`):

| Installed package path | Owning dependency path |
| --- | --- |
| `node_modules/@jest/reporters/node_modules/minimatch` | `@jest/reporters` → `glob@7.2.3` → `minimatch@3.1.5` |
| `node_modules/jest-config/node_modules/minimatch` | `jest-config` → `glob@7.2.3` → `minimatch@3.1.5` |
| `node_modules/jest-runtime/node_modules/minimatch` | `jest-runtime` → `glob@7.2.3` → `minimatch@3.1.5` |
| `node_modules/test-exclude/node_modules/minimatch` | `test-exclude` → `minimatch@3.1.5`, also used by its `glob@7.2.3` |

All four complete installed package payloads match the original [npm 3.1.5 archive](https://registry.npmjs.org/minimatch/-/minimatch-3.1.5.tgz). The archive SHA256 is `d81817ecf72de3c8c5d3724407752d943c9e1a42af5c437d9cb923be8a72c648`; its SHA512 lock integrity is `sha512-VgjWUsnnT6n+NUk6eZq77zeFdpW2LWDzP6zFGrCbHXiYNul5Dzqk2HHQ5uFH2DNW5Xbp8+jVzaeNt94ssEEl4w==`. Each installed `minimatch.js` has SHA256 `746849f267c4868a53729225bd85c7dccd387712136fb305fcc0a3eadd4a3d9d` and is byte-identical to the [versioned upstream source](https://github.com/isaacs/minimatch/blob/v3.1.5/minimatch.js).

In that 3.1.5 source, `Minimatch.prototype.make` / `make()` (approximately lines 161–206) performs brace expansion, splits entries on slashes, then maps `parse()` over the portions. The full source contains neither `firstPhasePreProcess`, `secondPhasePreProcess`, nor `optimizationLevel`. The [upstream changelog](https://github.com/isaacs/minimatch/blob/main/changelog.md) associates advanced preprocessing with 7.0 and the `optimizationLevel` option with 7.1. The [referenced fix](https://github.com/isaacs/minimatch/commit/77a0f5c4b80bdc641c3c930a1d9edf5ad2db57f8) changes those modern preprocessing functions.

As a small corroborating observation, each installed 3.1.5 copy constructs `**/../x`, `**/../**/../x`, and `**/../**/../**/../x` with one `globSet` entry and identical parsed sets with and without `{ optimizationLevel: 2 }`. This finite sample was run under a 10-second external deadline and 128 MiB JS heap limit; it is not an exhaustive denial-of-service test or the basis for a claim about all pattern behavior.

Our assessment is narrowly that the **specific optimizer mechanism described by this advisory appears absent from the inspected 3.1.5 implementation**. We are not asserting that minimatch 3 is generally safe, that all versions before 7 are unaffected, or that other brace-expansion/regular-expression/matching risks are absent. We have not dismissed the findings and are keeping them open pending authoritative clarification.

Please confirm whether 3.1.5 should be excluded, explain any different mechanism that makes it affected by this advisory, and determine the correct affected range from the relevant version history. We deliberately have not guessed a new lower bound or changed dependency versions merely to make scanner output disappear.
