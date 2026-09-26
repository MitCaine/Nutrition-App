# Candidate evidence and independent review

> **Document role: Engineering Process.** Optional attached lane implemented by GH-190.

Use the accepted controller from clean synchronized main, a separate committed candidate,
and controller state outside that candidate. This lane preserves external authorization,
trusted qualification and protected integration. It does not promote capsule/RI policy.
Unattached compatibility tasks keep their existing explicit verifier/reviewer interface.

## Frozen evidence requirements

The READY capsule at planning commit P must contain exactly one fenced
`nutrition-evidence-v1` JSON array in its body. No capsule metadata schema changes.
For example:

````markdown
```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_candidate_evidence.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/run-review.sh","--profile","repository","--no-package"]}
]
```
````

Required focused and baseline entries are mandatory. Kinds are `focused`, `baseline`,
`sqlite`, `postgresql`, `infrastructure`, `native`, and `manual`. A manual entry has null
argv and cannot be executed or marked passed by the command transport. Use `evidence ISSUE
manual --candidate-root PATH --check ID --comment-id ID` to retrieve an actual trusted-owner
issue comment containing exactly one `nutrition-manual-v1` fenced JSON object with keys
`candidate`, `binding_sha256`, `check`, `status`, and a nonempty `evidence` account. The first
three must match this attachment; status is passed/failed/skipped/unavailable. The comment
must be authored by the authorized human account, not an App, on this task issue. Its bytes
are retained and revalidated before review/integration. The owner supplies physical/device
observations; the controller never invents them. Missing mandatory attestation blocks.
Remote selected-profile qualification remains separate in the dedicated-App record;
it cannot silently substitute for a declared local command. Optional entries may be absent.

Each command is a fixed argument array, not shell text. Entire arguments `{python}`,
`{repository}`, and `{evidence}` resolve to the observed controller interpreter,
disposable committed-source clone and scratch output directory. Repository-relative
executables resolve inside that clone. Requirement IDs are stable lowercase identifiers.
`specialized_qualification` retains `profile:NAME`; additional local requirements can use
`evidence:ID`, referring to a required entry. Unknown specialist declarations stop attachment.

Attachment checks P is the sole capsule overlay directly over authorized base B, C descends
from P, branch/scope/profiles match, and the actual clean source matches committed C.
Lifecycle fields, acceptance checkboxes, State history and Completion record may change;
all other capsule semantics are frozen. A changed contract requires new authority, not a
correction. The issue body/title snapshot is recorded with its digest as review context;
external authorization and the frozen capsule remain the execution contract.

## Operator sequence

All examples run from trusted main. `STATE` and `CANDIDATE` below mean absolute paths;
`P` and `C` are exact 40-character commits. Obtain normal external authorization first.

```bash
./scripts/task --state-dir "$STATE" evidence ISSUE attach --candidate-root "$CANDIDATE" --planning "$P" --corrections 1
./scripts/task --state-dir "$STATE" evidence ISSUE check --candidate-root "$CANDIDATE" --check focused
./scripts/task --state-dir "$STATE" evidence ISSUE check --candidate-root "$CANDIDATE" --check baseline
./scripts/task --state-dir "$STATE" qualify ISSUE --candidate-root "$CANDIDATE"
./scripts/task --state-dir "$STATE" evidence ISSUE seal --candidate-root "$CANDIDATE"
./scripts/task --state-dir "$STATE" verify ISSUE --candidate-sha "$C" --actor 'controller' --decision pass --evidence 'Exact observed records'
./scripts/task --state-dir "$STATE" evidence ISSUE review --candidate-root "$CANDIDATE" --runtime /absolute/codex --runtime-sha256 EXACT_BINARY_SHA256
./scripts/task --state-dir "$STATE" evidence ISSUE publish --candidate-root "$CANDIDATE"
./scripts/task --state-dir "$STATE" integrate ISSUE --candidate-root "$CANDIDATE" --human-owner-authorized
```

Use the configured dedicated qualification App setting required by the normal controller.
`seal` queries the actual check, requiring exact App, candidate, external authorization ID,
completed success and removed temporary candidate ref. Existing profile planning, native
triggers, trusted dispatch/execution separation and cache/credential isolation are unchanged.
A mere GitHub Actions success is not this dedicated-App qualification.

`check` captures frozen argv, executable digest, elapsed time, exit code, stdout/stderr,
sandbox policy, canonical review output artifacts when produced, and before/after source
identity. The initial local transport is macOS-only and offline. It runs a full disposable
clone without hardlinks inside writable scratch, with no write grant to the real candidate,
Git metadata or controller evidence. Commands see system/runtime reads and scratch, no
inherited credentials. Required network/infrastructure work unavailable in this transport
blocks instead of being waived. The accepted remote qualification transport is unchanged.
The canonical runner's real results and fingerprint files remain individual hashed artifacts.

All required entries must pass; failed, skipped, unavailable and absent are distinct. Artifact
bytes are rechecked before review/integration. A zero command exit is execution evidence,
not proof of acceptance; the independent reviewer evaluates its adequacy against the capsule.
The controller state directory is trusted, private operator state. Do not edit it to manufacture
observations. Preserve interrupted attempts and their raw files.

## Observed independent review

The qualified runtime is `codex-cli 0.153.4` with an explicitly supplied binary SHA-256.
A different version or binary requires a new runtime qualification, not silent fallback.
Default model/effort are inherited and observed; optional `--model`/`--effort` requests must
match the actual session. The controller records provider, fresh thread/turn IDs, nonce,
completion, runtime digest and transcript digest. No implementation thread is resumed.

The ephemeral reviewer has explicitly empty environments, no imported repository instructions,
no workspace roots, read-only sandbox policy, approval never and no provider-model fallback.
Inherited MCP servers are enumerated and explicitly disabled, then their empty disabled
inventory is verified before and after the turn. Shell, browser, agent, memory, hook and
plugin features are disabled. The code-mode dispatch host remains available for the three
controller-supplied bounded callbacks; it is not a grant to repository shell or MCP tools.
The full event stream, including handshake waits and terminal drain, is validated before
signing. Unexpected capabilities, approvals, session events, late requests, timeouts or source changes
stop the attempt. The controller owns all command execution evidence.

The reviewer receives the entire frozen capsule, issue snapshot, authorization, full P-to-C
diff, scope paths, exact qualification and command records. It can read committed regular
files at B/P/C, list bounded committed paths and read declared hashed evidence artifacts.
Callbacks never accept arbitrary filesystem paths or run commands. Missing context fails the
relevant AC. Review must return every AC exactly once with PASS/FAIL and evidence, findings
with source locations, and one disposition. Approval requires all PASS and no findings.

Only an observed completed session produces a controller-authenticated receipt. The key is
private outside the candidate, with restricted permissions. Imported approval JSON and supplied
actor names cannot advance attached review. The receipt binds both candidate and evidence
packet, so later command/qualification changes invalidate it. Source observations cover raw
committed bytes, executable modes, branch, HEAD, index and refs, including hidden index changes,
symlinks and hardlinks. These are observed checks, not reviewer assertions.

## Corrections, failure and portability

Approved maps to REVIEWED_APPROVED; bounded-correction maps to REVIEWED_CHANGES_REQUESTED;
stop-replan and failed runtime observation map to STOP_REPLAN. There is at most one correction
(default one, optionally zero). `evidence ISSUE correct --candidate-root PATH` requires the
observed bounded-correction receipt, archives prior evidence and clears qualification,
verification, review and integration. Then attach a newly committed C2 with the same P;
run all required commands, Q2, verification and a fresh independent review. C1's gates cannot
approve C2. A timeout/ambiguous attempt is not resumable and cannot become an unlimited retry.

`publish` creates an issue comment containing exact identities, qualification links, observed
runtime/session, complete decision/matrix and raw artifact digests. Public summaries omit local
paths, keys and raw log contents. Local raw artifacts use `controller-local:SHA256` locators;
that explicitly does not claim remote raw-log availability. GitHub qualification and the full
review decision remain remotely retrievable. Preserve the controller archive for raw inspection.
Publication never grants authority or substitutes for live integration checks.

GH-190 itself bootstraps through the previously accepted controller plus independent external
reviews; its new receipt generator does not approve its own introduction. Later terminal
HISTORY/deletion still requires separate exact-SHA qualification under the existing closeout
process until GH-193 supplies its unified transaction.

## Qualification of this transport

Run focused candidate-evidence, independent-review and controller tests. On the capable host,
set `NUTRITION_REQUIRE_EVIDENCE_SANDBOX=1` for actual offline/write-denial command tests.
For the real reviewer roundtrip, set `NUTRITION_REQUIRE_REVIEW_RUNTIME=1`,
`NUTRITION_REVIEW_RUNTIME` and `NUTRITION_REVIEW_RUNTIME_SHA256` to the observed runtime.
`NUTRITION_REVIEW_ORACLE_RECORD` optionally retains the signed fixture observation externally.
The fixture proves source access, freshness and non-mutation; it explicitly lacks production
qualification and must not approve the fixture as a production candidate. Skipped host tests
are not transport qualification. Product native/device and PostgreSQL tests remain distinct.
