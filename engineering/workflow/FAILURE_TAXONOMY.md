# Failure taxonomy

> **Document role: Engineering Process.** Classify failures so authority gaps, environment
> issues, implementation defects, and evidence defects are not handled as the same problem.

| Code | Meaning | Response |
| --- | --- | --- |
| `AUTHORITY_GAP` | Required product/architecture/operations authority is absent. | Stop and obtain approved authority. |
| `AUTHORITY_CONFLICT` | Higher-authority artifacts disagree. | Stop and escalate. |
| `SPECIFICATION_AMBIGUITY` | Acceptance requires invention. | Return to grilling/specification. |
| `ARCHITECTURE_CONFLICT` | Work violates an invariant or boundary. | Stop and replan. |
| `SCOPE_BREACH` | Required edits exceed owned/allowed surface. | Revise capsule or create dependency. |
| `MODEL_OR_TOOL_MISMATCH` | Actual identity/capability differs from qualified route. | Record and reroute or approve explicitly. |
| `BASE_STATE_MISMATCH` | Commit, branch, dependency, or repo state differs. | Stop and requalify. |
| `ENVIRONMENT_FAILURE` | Toolchain, service, credential, or environment blocks work. | Preserve logs; repair separately. |
| `IMPLEMENTATION_DEFECT` | Code violates acceptance or repository contract. | Bounded correction or replan. |
| `TEST_OR_EVIDENCE_DEFECT` | Test, fixture, or evidence is invalid/incomplete. | Repair evidence and rerun. |
| `REPOSITORY_DRIFT` | Source changes during verification/packaging. | Critical: discard package and rerun. |
| `QUALIFICATION_UNAVAILABLE` | Required specialized check cannot run. | Block completion unless human accepts risk. |
| `EXTERNAL_DEPENDENCY` | External service, approval, or artifact blocks progress. | Use blocking overlay and recheck condition. |
| `IRREVERSIBLE_RISK` | Next action can destroy data/change trust beyond policy. | Stop for explicit human authority/runbook. |

Authority conflict, architecture conflict, base mismatch, repository drift, unapproved scope,
identity mismatch on a model-dependent route, and irreversible risk are immediate stop
conditions.

A correction is bounded only while goal, authority, acceptance, risk, surface, and qualification
remain unchanged. Record failure code, evidence, impact, owner, next action, and partial-work
safety.
