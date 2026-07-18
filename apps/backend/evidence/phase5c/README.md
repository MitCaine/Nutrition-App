# Phase 5C performance evidence

These files are captured qualification manifests, not runtime configuration or mutable benchmark
output:

- `phase5c-performance-t0.json` is the initial T0 measurement;
- `phase5c-performance-t0-optimized.json` is the bounded Phase 5C2.1 optimization measurement; and
- `phase5c-performance-t0-requalified.json` is the Phase 5C2.2 requalification measurement.

The historical `overall_result: performance_failed` value is correct under the original v1
aggregate scan ceilings. It must be interpreted through the governing
[Phase 5C3b](../../../../docs/production-hardening-phase5c3b.md) and
[Phase 5C2.2](../../../../docs/production-hardening-phase5c2.2.md) records, which preserve the
correctness results and the later budget-ratification decision.

Contract and admission tests load these exact files as immutable evidence examples. Do not edit or
reformat them; generate new qualification output separately and admit it only through the
governing evidence process.

