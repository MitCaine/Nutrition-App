# Bounded capsule execution

> **Document role: Engineering Process.** The initial controller-owned execution transport.

`./scripts/task execution` adds authenticated execution checkpoints to the existing
trusted task controller. It does not qualify, review, publish or integrate a candidate.
The accepted operator still performs those gates through [Start here](START_HERE.md).

## Supported transport

The first transport is an explicit offline **macos-bounded-command**: one pinned local
executable plus its argument vector, under native macOS isolation. It supports a bounded
single-process patch/tool operation. It is not an automatic Codex/model launcher, shell
or test-process supervisor. Child process creation and network access are denied. A
future model or multiprocess transport requires its own implementation and qualification;
never claim this lane supplies those capabilities or silently run outside isolation.

Executable bytes and arguments are bound. System libraries and the installed executable's
runtime prefix are host dependencies, not a cryptographically attested complete toolchain.
Read access covers that prefix, platform libraries, the candidate and attempt scratch;
write access covers candidate source and scratch, with capsule/Git authority protected.
Home credentials and controller state are outside the read/write envelope. Model and
reasoning effort are explicitly null because this command transport does not observe them.

The controller chooses the executable and supplies this JSON outside candidate source:

```json
{
  "transport": "macos-bounded-command",
  "executable": "/absolute/path/to/installed/python3.12",
  "sha256": "<SHA-256 of the executable bytes>",
  "argv": ["-c", "<bounded operation that writes a structured outcome>"]
}
```

Resolve the real executable and compute its digest from installed bytes; do not infer
identity from PATH or reuse a stale manifest. The executable's installation prefix is
its real path's parent-parent, so choose a dedicated installed runtime, not an executable
placed in a broad home directory. That prefix is read-only; no package installation or
credential provisioning occurs during a run.

## Prepare and run

Use trusted main code, a separate clean task checkout and state outside that checkout.
Existing `task prepare` / `task authorize` must already bind the same issue/task,
revision, base and machine qualification profiles. The READY capsule must be the sole
planning commit above that base. Its owned/allowed patterns must be covered by external
authorization; arbitrary glob containment is rejected instead of guessed.

```bash
./scripts/task --state-dir /absolute/controller-state execution ISSUE prepare \
  --candidate-root /absolute/task-checkout --planning FULL_PLANNING_SHA \
  --branch task/EXACT_BRANCH --runtime /absolute/runtime.json --corrections 0
./scripts/task --state-dir /absolute/controller-state execution ISSUE run \
  --candidate-root /absolute/task-checkout --timeout 900
```

Preparation repeats the existing strict READY renderer and writes its full capsule/handoff
outside the candidate. It also checks actual tracked planning bytes and modes, including
changes hidden by index flags. Ignored/untracked material, symlinks, multiply linked files and non-regular source
are not accepted as clean input. A checkpoint may not be overwritten by another preparation.
Keep the planning capsule byte-identical while the executable runs; lifecycle updates and
candidate commits remain controller actions after a completed handoff.

The process receives `NUTRITION_CAPSULE`, pointing to an attempt copy of the full capsule,
`NUTRITION_HANDOFF`, containing the complete rendered executor packet, and
`NUTRITION_OUTCOME`, the only result path the controller reads. The environment is
minimal and carries no inherited credentials. On successful process exit, write exactly:

```json
{"outcome": "completed", "summary": "What was changed and which checks actually ran"}
```

Other allowed outcomes are `blocked` and `stop_replan`. A zero exit without a valid result
is not completion. The supervisor checks source bytes, branch, HEAD, index, capsule and
allowed/forbidden paths after termination. An out-of-scope edit is retained for diagnosis
and reported as STOP_REPLAN even when the command claims completed. Scope enforcement is
an after-execution gate; the capsule/Git/controller write restrictions are native isolation.

## Checkpoints and recovery

An exclusive per-issue lock prevents simultaneous dispatch. PREPARED becomes RUNNING
before launch, then COMPLETED, BLOCKED or STOP_REPLAN. Each attempt preserves stdout,
stderr, sandbox policy, command identity, source observations and outcome outside candidate
source. Successfully inspected post-failure source is retained, including scope violations and
invalid results. If source acquisition itself fails, accounting remains null, never a
fabricated empty diff.
A process exception or supervisor death can leave RUNNING; this state cannot resume.

Only an explicitly returned BLOCKED outcome with unchanged authority, runtime and exact
last-observed source is resumable. Preparation allows zero corrections by default or one
explicit correction; there is no unlimited retry setting. Use:

```bash
./scripts/task --state-dir /absolute/controller-state execution ISSUE resume \
  --candidate-root /absolute/task-checkout --timeout 900
```

Changed source between attempts, timeout, ambiguous interruption, exhausted budget,
changed authorization, changed capsule or moved planning require replan. Preserve the
checkpoint and source; do not delete the record to pretend this is the first attempt.
`status` authenticates the live execution envelope and reports its phase; after the
controller advances to candidate qualification/integration, consult retained evidence and
normal `task status` instead of using execution status as a new grant.

## Qualification boundary

Execution COMPLETED is source-handoff evidence only. The controller must inspect it,
make any authorized lifecycle update/candidate commit, then obtain fresh qualification and
independent review for that committed SHA. #190 supplies richer candidate evidence binding;
#192 adds RI structural review. No existing gate is waived by this execution command.

Native isolation qualification runs the focused execution tests on macOS with
`NUTRITION_REQUIRE_EXECUTION_SANDBOX=1`; a missing sandbox is a failure in that run.
Linux CI can run deterministic binding tests, but skipped native tests are not macOS proof.
The tests include protected files, forbidden forks, scope breach, hidden index changes,
finite blocked resume and timeout. Product iOS/native qualification remains separate.
