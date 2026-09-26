# Controller authority and capsule attachment

> **Document role: Engineering Process.** Current ownership and the migration contract.

## Current authority

The owner authorizes product intent, risk and integration. Executable domain contracts
and current accepted repository policy constrain every task. An issue specifies the
outcome; the trusted-author issue comment fixes the controller's exact base, task ID,
revision, nonce, paths and qualification profiles. Candidate history cannot replace it.
A capsule adds the full execution specification only when that lifecycle is explicitly
selected; it cannot override the external authorization or domain contracts.

| Decision or fact | Owning authority | Consumer/check |
| --- | --- | --- |
| Product policy, exceptions and integration permission | Explicit repository-owner decision | Controller records actual authorization |
| Domain behavior and invariants | Current migrations, constraints, tests and accepted requirements | Implementor, verifier and reviewer; conflicts stop |
| Outcome and acceptance | Approved issue and explicit task capsule when selected | Controller bounds scope; reviewer assesses acceptance |
| Allowed edits, base and profiles | Resolved trusted-author authorization comment | Trusted `scripts/task.py` and `scripts/lib/task_authorization.py` |
| Capsule execution specification | Exact qualified capsule/revision and generated handoff | Existing capsule validator; target attachment binding below |
| Runtime/model settings | Actual selected host/transport and observed identity | Controller records requested versus observed; unknown stays unknown |
| Qualification | Candidate-independent trusted planner, selected jobs and finalizer | Dedicated-App exact-SHA Main qualification |
| Verification/review decision | Explicit verifier and independent reviewer evidence | Controller records decisions against one candidate SHA |
| Integration | Owner authorization plus trusted controller checks and live ruleset | Existing `task integrate`; no routine bypass |
| Terminal capsule recovery | Unique HISTORY entry and reachable full-capsule Git bytes | Capsule/history validator and post-closeout observation |

Conflicting authority stops execution. Resolve the conflict explicitly; neither a later
file timestamp nor an agent's preferred guide wins. Conversation can convey owner
instructions, but cannot manufacture a passed gate or silently revise fixed task scope.

## Current interfaces and disposition

| Surface | Current responsibility | Migration disposition |
| --- | --- | --- |
| `scripts/task`, `scripts/task.py` | Prepare/authorize, trusted qualify, explicit verify/review, guarded integrate/reconcile | Retain as the public controller entrypoint; extend in bounded slices |
| `scripts/lib/task_authorization.py` | External authorization v1, exact base/scope/profile and required-native checks | Retain; no schema change in #188 |
| `scripts/lib/trusted_qualification.py` and trusted workflows | Candidate-independent plan/finalization and dedicated-App check | Retain GH-171 credential/cache isolation |
| `scripts/lib/qualification_profiles.py` | Repository/backend/mobile/postgresql/ios-native registry | Retain selected profiles and mandatory-native floor |
| `scripts/capsule`, `scripts/capsule.py` | Legacy capsule state transitions and legacy remote qualification | Retain lifecycle compatibility; legacy qualification cannot satisfy the trusted-App gate by itself |
| `scripts/validate-task-capsules.py` | Capsule schema, READY overlay and HISTORY recovery | Retain; explicitly selected migration capsules use it |
| `scripts/render-task-handoff.py` | Authenticated READY handoff outside candidate source | Reuse for execution attachment; never use as external authorization |
| `scripts/run-review.sh` | Source/log/check evidence bundle | Retain; a bundle is evidence, not an approval |
| Session, documentation and phase-boundary scripts | Repository consistency checks | Retain, including deterministic control-plane inventory |
| `scripts/main-governance.py` and live ruleset | Protected main policy | Preserve dedicated App, loose status requirement and no routine bypass |
| Controller state outside candidate tree | Current authorization and candidate-bound gate records | Retain; extend resumability/portable evidence only with tests |
| Active capsules and HISTORY | Non-terminal contract and terminal Git recovery | Retain; no per-task completed archive |

The current controller stores verification/review assertions with a candidate SHA;
it does not yet mechanically establish reviewer independence or a complete acceptance
matrix. #190 owns that extension. The explicit [bounded execution command](EXECUTION.md) attaches a qualified READY
capsule to external authorization and retains checkpoints for the macOS local-command
transport. Legacy capsule commands do not attach automatically; #191/#192
own RI consumption. #193 owns combined protected closeout. #194 owns promotion and
retirement after pilots. Do not advertise these planned guarantees as current features.

## Capsule attachment design

This is the attachment contract. The [execution command](EXECUTION.md) implements
planning/runtime binding for the initial bounded-command transport; later candidate,
review and terminal integration extensions remain separately owned. It is not an added
v1 capsule metadata key or authorization-v1 extension. Keep the capsule schema and authorization v1
compatible until a separately reviewed implementation defines versioned storage.

The controller records an attachment outside candidate-controlled authority. It contains
repository, issue/task ID, external comment ID/revision/identity digest, exact base B,
planning commit P, capsule path/revision/hash at P, expected execution branch, fixed paths
and profiles. P is a single capsule-only commit directly above B; the capsule contains B,
not its own P, avoiding self-reference. Normal planning transport is a non-main ref;
publication of P to protected main is a separate qualified integration, never a shortcut.

The controller resolves external authority live and validates equality of task, issue,
base, revision and profile selection. Capsule owned/allowed paths must be covered by
external allowed paths, and forbidden restrictions must not be weakened. Qualification
requirements are compared as a normalized set of profile tokens plus explicit specialist
requirements; free text cannot silently add a machine profile. Semantic capsule edits
require a new revision/attachment; lifecycle-only edits retain the frozen execution
contract and have append-only evidence. The planning capsule's hash identifies the frozen
contract; a later reviewed-capsule hash identifies the recoverable lifecycle artifact.

### Worked binding example (illustrative, not executable authority)

For task GH-188, let B be the live main commit at authorization; A the exact trusted
comment identity; P the sole capsule overlay over B; and C the final candidate descended
from P. A authorizes the GH-188 task, revision 1, repository-only qualification and the
specified documentation/capsule paths. The attachment binds A, B, P, the full planning
capsule SHA-256 and `task/GH-188-workflow-authority`. The controller checks that P changes
only the named capsule and that C changes only the authorized paths. It supplies the full
P-to-C implementation diff and the B-to-C authorization scope check to the reviewer.

Qualification Q and review R each bind C and the same A/attachment. A correction produces
C2, which needs new Q2/R2; an approval for C does not approve C2. If authority, profiles,
base, capsule revision or fixed execution contract changes, discard readiness and gate
eligibility, preserve old evidence, and replan. No digest alone proves execution truth.

A terminal commit T containing only HISTORY plus capsule deletion differs from C. It
requires its own bounded authority and exact-SHA repository qualification before protected
integration. Its HISTORY record points to the full capsule at a reachable pre-deletion
commit and binds those bytes by SHA-256. Never call Q(C) qualification of T.

For the bounded-command lane, execution attachment checks are mechanical. Candidate
qualification/review and terminal links still require explicit controller inspection
until their follow-up issues implement those gates. Existing executable gates apply.

## State, concurrency and recovery

Capsule DRAFT through READY are planning, IN_PROGRESS/IMPLEMENTED are implementation,
VERIFIED is explicit verification, and REVIEWED carries the independent disposition.
The trusted task controller separately records PREPARED/AUTHORIZED, qualification,
verification, review and integration. They describe different artifacts: setting a capsule
state does not advance controller authority, and an integrated candidate does not close
an active capsule. Use [States](STATES.md) for legal capsule transitions and [Evidence](EVIDENCE.md)
for terminal facts. No legacy state is silently renamed or discarded.

For this migration, serialize integration and capsule planning against current main;
only one non-administrative active migration capsule is allowed. Independent preparation
may use separate worktrees, but it cannot assume an intermediate unpublished base. Refresh
main before each consequential action. A moved base or incompatible active task requires
replanning with preserved source/evidence, not an automatic rebase and reused approval.

Routine choices inside approved scope need no repeated owner confirmation. A new policy,
trust boundary, destructive action or material exception still needs owner authority.
A bounded correction retains scope/acceptance/qualification and receives fresh proof;
material changes require revision. STOP_REPLAN ends the attempt. Resume only a state whose
identity and prior outcome can be reauthenticated; generic session resume is not proof.
Existing unrelated maintenance follows the accepted task controller and does not have to
adopt experimental capsules merely because this migration is in progress. It must still
respect active work and invalidate stale bases/evidence explicitly.

## Host and transport

The first local controller host is macOS with the repository Python/Node versions.
GitHub source, issue comments, workflows and exact-SHA checks provide remote transport.
Use a clean trusted main checkout and a separate candidate checkout. Keep credentials,
controller state and qualification authority outside candidate execution. Preserve Linux
CI for repository, backend, mobile and PostgreSQL checks; preserve macOS iOS qualification
and separate physical/manual proof. Poker's Rust runtime, host exclusions and DEV-INTEL
ledgers are not Nutrition requirements. RI remains an optional evidence producer until
its consumer and structural-review pilots qualify; it never owns permission or approval.
