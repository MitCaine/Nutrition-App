# Production Hardening Phase 5C2.2: optimized T0 requalification

Phase 5C2.2 requalified the unchanged optimized historical Recipe conversion path. It did not
change conversion, checksum, plan-v2, execution-authorization, qualification-receipt, checkpoint,
restart, archive-reconciliation, or public-API behavior.

## Evidence identity

The operator-gated T0 path ran against a newly created disposable PostgreSQL database with the
existing fixture generator, tier, seed, and warm-cache declaration:

- fixture generator: `phase5c_performance_fixture_generator_v1`;
- tier and seed: `T0`, `20260714`;
- blueprint digest: `9ed9edb7024aad5ec13860030edbfc0ba1b8287e1a78edc46d96dc3857c4f06e`;
- logical-data digest: `93c9035037c39b62714972626e5b9fad73cbead40bbf671b5a45e13f630d6a97`;
- dimensions: 50 Recipes, 274 ingredients, 250 Foods, 5,000 Daily Logs, and 1,000 OCR records; and
- manifest digest: `b9e28da1443f5861e942ae49d76063efa9a32c32f1db07cd05a6ba5d4eece070`.

The [requalification manifest](../apps/backend/phase5c-performance-t0-requalified.json) is the
canonical evidence. Database-bound receipt and manifest digests are expected to differ between
disposable runs; the fixture blueprint, logical-data digest, dimensions, rules, and decision
distribution are the reproducible workload identity.

Independent qualification and restart verification both passed. The manifest remains
`performance_failed` only because four aggregate scan ceilings are below the measured full-path
proof obligations.

## Before and after

| Metric | Initial T0 | Phase 5C2.1 T0 | Phase 5C2.2 requalification |
| --- | ---: | ---: | ---: |
| Global source passes | 213 | 25 | 25 |
| Archive/support relation scans | 632 | 68 | 68 |
| Daily Log relation scans | 196 | 20 | 20 |
| OCR relation scans | 389 | 37 | 37 |
| Per-subject source / Daily / OCR scans | 140 / 90 / 180 | 0 / 0 / 0 | 0 / 0 / 0 |
| Total queries | 6,081 | 5,517 | 5,532 |
| Conversion wall time | 20.849 s | 2.176 s | 2.269 s |
| Restart-verification wall time | 15.452 s | 1.288 s | 1.352 s |
| Independent-qualification wall time | 1.520 s | 1.484 s | 1.577 s |
| Subject p95 time / queries | 0.475 s / 72 | 0.046 s / 65 | 0.049 s / 65 |
| Peak Python RSS | 442,433,536 B | 171,556,864 B | 171,589,632 B |

The 15-query increase from the prior optimized run is isolated to bridge and migration metadata:
bridge increased from 124 to 135 queries and migration to execution head from 23 to 27. This is the
expected cost of transactional dynamic-archive index provisioning and verification. Conversion,
restart, qualification, per-subject query distribution, and every scan count are structurally
unchanged. Small wall-time differences are ordinary run-to-run variation on the same environment,
not evidence of a converter regression.

## Exhaustive remaining-scan ledger

The full-path stage totals account for every remaining classified scan:

| Proof obligation | Global | Archive/support | Daily Log | OCR |
| --- | ---: | ---: | ---: | ---: |
| Authorization and admission | 13 | 35 | 10 | 17 |
| Restart guarantees | 3 | 7 | 4 | 8 |
| Independent qualification | 9 | 26 | 6 | 12 |
| Operational bookkeeping | 0 | 0 | 0 | 0 |
| **Total** | **25** | **68** | **20** | **37** |

Authorization and admission comprise inventory, marker creation, bridge verification, planning,
and conversion admission/finalization. These reads bind the clone, archive, plan, immutable run,
and preservation roots at the transaction boundaries where each operation acts. Restart executes
the same admission and final verification against the persisted checkpoint/run evidence. Independent
qualification deliberately re-reads source, archive, converted domain, Daily Log, and OCR state in
its own read-only repeatable snapshot. Fixture creation, migrations, attestation creation, and
receipt serialization issue bookkeeping queries but contribute no classified source scans.

All three per-subject full-scan categories remain zero. No unidentified or accidentally repeated
per-subject scan source remains.

## Remaining optimization candidates

| Candidate | Expected gain at T0 | Complexity | Correctness risk | Maintenance cost | Decision |
| --- | --- | --- | --- | --- | --- |
| Reuse inventory roots across inventory, marker, and bridge operations | Less than the combined 0.27 s stage time; at most 8/24/6/9 classified scans | Medium | High: evidence would cross operation and transaction boundaries | High | Reject |
| Remove or replace conversion final-root verification with generation state or long-held locks | Upper bound is the 2.27 s conversion stage; realistic gain is materially lower | High | Very high: weakens detection of source or preservation changes across subject commits | High | Reject |
| Treat a completed receipt as sufficient for restart without re-verification | At most 1.35 s and 3/7/4/8 scans | Medium | High: changes the documented restart guarantee | Medium | Reject |
| Consolidate independent-qualification queries | At most its 1.58 s stage time; scan elimination is not expected because independence still requires reads | Medium–high | Medium–high: increases coupling to converter assumptions | High | Reject at T0 |
| Add further bounded indexes or SQL tuning | Negligible demonstrated T0 gain | Low–medium | Low if strictly non-semantic | Low–medium | Reconsider only if T1/T2 evidence identifies a query bottleneck |

The scan ceilings of 6/54/8/16 cannot be reached from the measured full workflow while retaining
the current 25/68/20/37 proof ledger. Further converter optimization should not be used to make the
manifest green by removing, reusing, or relabeling required evidence. Any future budget calibration
must be a separate performance-contract decision based on the complete proof floor.

## Architecture recommendation

Stop verifier optimization and proceed to Phase 5C4. T0 conversion and qualification times are
orders of magnitude below their ceilings, total and per-subject query budgets pass, memory passes,
correctness passes, restart passes, and no per-subject full scans remain. The remaining scans are
fully attributed to authorization, restart, and independent qualification.

Phase 5C4 should address promotion, cutover, and recovery qualification: artifact admission,
maintenance-mode cutover, pre-cutover backup and restore evidence, quarantine acceptance, bounded
post-cutover verification, and cutback expectations. It should consume the existing immutable
inventory, plan, execution receipt, qualification receipt, and performance evidence without
changing conversion semantics or authorizing archive cleanup.
