# Bounded workflow tools

These local helpers reduce repeated reading and copy maintenance. They do not
choose task scope, authorize reads or writes, establish test adequacy, approve a
candidate, or connect chats. Select their installed location/version through the
project map or assigned handoff; an unavailable helper does not authorize a
different instruction revision or additional reading. Ordinary file tools remain
supported. No service or persistent index is required.

## Consumer check runner

Command execution and source projection belong to the consumer. Its map should
identify the selected runner, usable invocation/help, authored checks and evidence
location. RI supplies no duplicate executor or mandatory historical capsule packet.
Poker's ordinary runner is developed under
[Poker #472](https://github.com/MitCaine/poker-app/issues/472); installation and
consumer proof remain separate from this contract.

The minimum request identifies a unique attempt, exact source, repository,
authored argument vectors, working directories, selected child environment,
prerequisites and relevant input coverage. The consumer authenticates its actual
source and execution context. Source-sensitive checks retain independent HEAD,
index and worktree observations, including staged, unstaged and hidden-index
changes; a clean status alone is insufficient. Source-independent commands may
use explicit relevant-input coverage instead of repeated full-tree scans. Such
coverage must not be reported as full-source stability. Relevant transitive inputs
and configuration remain part of the project's evidence eligibility policy.

Use an exclusive attempt location and preserve each attempt's command outcomes,
log references, failures, skips, missing/incomplete results and before/after source
and relevant-input observations. Record selected configuration separately from
effective child configuration; avoid storing credential values. A later successful
command must not mask an earlier failure. An interrupted attempt is incomplete,
not a pass. Successful exits establish neither semantic acceptance nor evidence
equivalence. Apply the selected [evidence rules](start-an-issue.md#evidence-eligibility-and-corrections).

## Section reader

The optional `repository_intelligence.section_reader` module reads explicitly
selected Markdown headings from an exact local Git commit. It uses RI's existing
Markdown grammar, without changing navigation mappings. It emits complete raw
section text and source identity/coverage; overlapping selections are emitted once.
Only explicitly selected documents/headings are read. Links are not followed.
The caller still owns role read boundaries and required reading coverage.

```sh
PYTHONPATH=src .venv/bin/python -m repository_intelligence.section_reader --request request.json
```

For example, use this request against a checkout containing the named commit:

```json
{
  "repository": "/absolute/path/to/Repository Intelligence",
  "revision": "5d5be9ecdf103494ed0c44bd58f4e6e9e6fb8d0e",
  "selections": [
    {"path": "docs/worker-instructions.md", "headings": ["Shared worker rules", "Implementor"]}
  ],
  "max_output_bytes": 256000
}
```

Each selection may also supply `expected_sha256`. Exact visible document-level
heading text is required; duplicate headings are ambiguous. Setext headings are
supported; fenced examples, list and quote headings are not selection targets.
Sections include subsections through the next same/higher-level heading. The text
budget excludes JSON metadata overhead; truncated ranges and selection coverage
remain `incomplete` and exit 1. Complete requests exit 0. Schema version 1 records
document hashes, commit blob identities and half-open raw byte ranges.

No newest-head selection or network fetch occurs. A successful section read does
not prove the worktree equals the selected commit or that every required reference
was read. Output describes committed objects only. Missing/ambiguous headings,
identity conflicts and output limits remain explicit incomplete results.

## Declared-resource adoption

The optional `repository_intelligence.adoption` module takes an explicit local
source commit, destination repository and declared resource inventory. Literal
link relocations have expected replacement counts. Preview and verification are
read-only; application is an explicitly selected action under existing project
authority. It never selects latest main, changes refs, publishes, integrates or
decides to repin an active task. Runtime/dependency pin changes must not be
inferred from an instruction inventory.

```sh
PYTHONPATH=src .venv/bin/python -m repository_intelligence.adoption --request adoption.json --mode preview
PYTHONPATH=src .venv/bin/python -m repository_intelligence.adoption --request adoption.json --mode verify
# Only with the existing task's application authority:
PYTHONPATH=src .venv/bin/python -m repository_intelligence.adoption --request adoption.json --mode apply
```

Supply expected destination identities before application, inspect preview
conflicts and retain prior evidence. Dirty or drifting destinations are not
silently overwritten. Repeat application of already matching resources is a
no-op. Consumers may select a generated identity sidecar below; consumer-owned
selection prose, runtime pins and authority still require separate reconciliation. The consumer
checks local validators and links, reviews the full candidate and verifies
installed closeout. Resource equality alone does not prove usable skills, host
availability or adoption correctness.

Optional `metadata_output` has exactly `destination` and
`expected_destination_sha256` (null for an absent sidecar). When selected, every
resource must also supply `expected_source_sha256` and `expected_output_sha256`.
These bind the controlled inventory to pinned upstream bytes and exact transformed
bytes; missing or mismatched identities refuse the entire plan before writes.
The standalone UTF-8 JSON sidecar contains `metadata_schema_version: 1`, the exact
`revision`, and destination-sorted resource entries with source/destination paths,
Git blob, raw/output SHA-256 and byte counts, and declared replacements. It is
canonical sorted-key, two-space-indented JSON with a trailing newline; excludes
machine paths, modes, transient destination status, runtime pins and local prose.
Preview/verify calculate the same bytes; apply includes the explicitly named
sidecar in existing destination safety, identity conflict and rollback handling.
Do not target an existing historical SOURCE prose record: use a dedicated sidecar
and preserve other consumer-local declarations. This is an additive request/report
option; the existing adoption report schema remains 1. Metadata format has its
own version; it does not change source/navigation/runtime compatibility versions.
Resource inventory completeness remains caller-controlled, not inferred from a
repository crawl or a consumer's historical record.

The request shape is:

```json
{
  "source_repository": "/absolute/canonical/source/repository",
  "revision": "5d5be9ecdf103494ed0c44bd58f4e6e9e6fb8d0e",
  "destination_repository": "/absolute/canonical/consumer/repository",
  "resources": [{
    "source": "docs/start-an-issue.md",
    "destination": "docs/ri_start_an_issue.md",
    "expected_destination_sha256": null,
    "replacements": [{"old": "worker-instructions.md", "new": "ri_worker_instructions.md", "expected_count": 1}]
  }]
}
```

This is a shape example, not a ready-to-apply inventory: inspect and supply the
actual relocation count and destination hash (`null` means absent). Replacements
are literal UTF-8 strings applied in order. Full lowercase commit IDs are required.
Canonical repository roots cannot contain symlink components; on macOS use the
resolved `/private/tmp` location rather than its `/tmp` alias. Application refuses
staged changes, hidden index flags and unrelated/drifting worktree files; use a
clean owned worktree. Already matching declared resources permit repeat no-op
application despite their first application's unstaged output.

The whole destination inventory is checked before application writes, including
filesystem aliases and file/ancestor overlaps with already matching resources.
Existing identities use native filesystem identity. Missing ASCII case-equivalent
names use Darwin's read-only filesystem case-sensitivity query; on other hosts
that ambiguous missing-name comparison is explicitly unsupported. Comparisons involving differing missing Unicode
components are unsupported rather than approximating native Unicode mappings.
Distinct existing paths on case-sensitive filesystems remain valid. No universal
lowercase destination policy or filesystem probe writes are used.

Destinations inside nested repositories or submodules are unsupported, including
Git metadata aliases. Apply them separately through a request naming that nested
worktree's own root, subject to the ordinary root metadata protections. A refusal
preserves all declared destination bytes, including earlier ordinary resources.

Preview exits 0 for a valid plan, including reported differences/conflicts; inspect
the result rather than treating its exit as verification. Verification exits 0
only for matching resources. Application reports `applied` or `unchanged`; errors
and rollback outcomes exit 1. Per-file writes are atomic, with rollback reporting
on failure. Path/byte rechecks are best effort, not a global filesystem transaction;
exclude concurrent writers. Request/resource byte and count limits are explicit in
module help/source. Prior attempt records belong in the consumer's existing durable
evidence location; the helper does not create a state store.

## Existing optional evidence helpers

The [evidence preflight helper](https://github.com/MitCaine/repository-intelligence/blob/5319549b0c1d5da91d4f8e7be3eac64e622f2075/docs/skill-templates/capsule-preflight/scripts/evidence%5Fpreflight.py)
contains pure input-equivalence predicates; unknown relevant inputs are not
cacheable. Its extended packet validation remains optional and is not required
by these tools. [Documentation/link checks](https://github.com/MitCaine/repository-intelligence/blob/5319549b0c1d5da91d4f8e7be3eac64e622f2075/scripts/check%5Fdocs%5Fand%5Fskills.py),
the [bounded source locator](https://github.com/MitCaine/repository-intelligence/blob/5319549b0c1d5da91d4f8e7be3eac64e622f2075/docs/consumer-guide.md) and
[review bundles](https://github.com/MitCaine/repository-intelligence/blob/5319549b0c1d5da91d4f8e7be3eac64e622f2075/docs/review-evidence.md) retain their existing separate scopes.
None authenticates task authority or proves runtime availability.

## Prepared worker execution linkage

The optional `repository_intelligence.worker_execution` helper links an explicitly
prepared disposable workspace to consumer-authorized edit/capture commands, a
consumer check runner and mechanically validated terminal facts. The consumer
still owns commands, permissions, request/result formats and substantive review.
It does not publish refs, connect chats or replace the check executor. Select it
only under existing task authority; no remote-free capture policy is imposed.

```sh
PYTHONPATH=src .venv/bin/python -m repository_intelligence.worker_execution --request execution.json --evidence /absolute/private/evidence --mode prepare
PYTHONPATH=src .venv/bin/python -m repository_intelligence.worker_execution --request execution.json --evidence /absolute/private/evidence --mode run
```

Version 1 request fields are `assignment`, unique `attempt`, absolute `workspace`
and separate `protected_repository`, full `base`, `inputs` (absolute regular-file
`path`/`sha256` bindings for the handoff, instructions and relevant consumer tools),
exact relative `allowed_changes`, optional `route` (`subprocess`, the compatible
default, or explicitly selected `interactive`), `capture_authority` (consumer grant reference),
selected child `environment`, optional `edit`, required `capture` and `runner`,
`require_new_candidate` (explicit boolean), `check_request`, `runner_result` and
`result_bindings`. Optional `timeout_seconds` is 1–3600 per operation. Each operation
contains only `argv` and the selected executable's `executable_sha256`; use its
absolute resolved non-symlink path. Bind interpreted scripts and relevant toolchain
inputs in `inputs`, not merely the interpreter. Authority references record a
consumer selection, not independent authentication of a human grant.

`--mode generate` derives a request without creating an attempt or running operations.
Supply all existing task/authority/check selections, but omit `inputs` and executable
hashes. Each operation supplies `argv` only. Supply `input_inventory` with absolute
`path`, expected `sha256`, and `keys` (an object-key path, or `[]` for the root).
The authenticated JSON projection at that location is a nonempty list of required
`path`/expected `sha256` entries, exported automatically from the runner's authoritative dependency definition, which
the selected consumer validator also uses. An agent-written inventory merely moves
the manual omission risk and does not satisfy this contract.
Generation authenticates every entry, adds the inventory itself to `inputs`, and hashes
selected executable identities; it never imports the inventory or discovers dependencies.
Prepare/run recheck the SAME inventory binding and exact ordered input set, catching
manual omissions as well as drift. Consumers must expose their authoritative inventory
projection; a separately hand-written list is not coverage proof. No consumer inventory
integration follows automatically. A consumer regression must prove its normal route
obtains this projection automatically from that same definition; shared fixtures alone
do not establish that wiring or resolve its end-to-end manual-setup problem.

Use the existing [pinned resource operation](#declared-resource-adoption) to provision
an explicitly selected helper snapshot when authorized, retaining its revision and
source/output hashes in the owning inventory. Bind that stable provisioned location,
not a moving shared checkout. This reuses adoption's exact-commit reads and destination
conflict checks; generation does not install tools, change Git configuration or select a
revision. Missing capture authority or mismatched selected source refuses before static
error collection. Independent safely inspectable environment/operation errors are
collected read-only; no mismatched code is imported or executed. Git/source readiness
checks remain read-only and fail closed; required Git setup belongs to authorized
consumer setup. Existing returned candidate/request/reference facts remain generated
from actual capture/runner records rather than manually restated by later roles.

Preparation verifies a clean base and stores workspace/Git directory filesystem
identities, shared Git configuration identity and selected input/operation/request/environment hashes in exclusive
`PREPARED.json`. Run requires that identical preparation, then creates an exclusive
`LAUNCHED` marker: retries cannot repeat capture/execution after failure or lost
reply. Reconcile retained partial evidence under the existing consumer recovery
route; this helper does not resume interrupted operations. Edits occur only through
the optional selected edit invocation, which may itself be a consumer launcher;
manual source changes are refused on that compatible subprocess route. On the
explicit interactive route, prepare authenticates the clean original base before
worker edits; run reauthenticates the original assignment, selected inputs and
workspace/Git configuration, checks all committed and working changes against
original allowed paths, and invokes the unchanged selected capture/runner.
Authorized local descendant commits are supported without silently repreparing
or changing the original base. Interactive requests cannot also select an edit
launcher. A blocked or interrupted run still requires a new explicitly reconciled
attempt, not rerunning its launch marker. This is an optional selected operation
path, not filesystem isolation or an agent-launch service.

Exact argv tokens `{workspace}`, `{attempt}` (private attempt directory),
`{candidate}` and `{check_request}` resolve per invocation. Capture must leave a
clean descendant Git commit in the same workspace, limited to declared changed
paths; a consumer can explicitly permit a no-change capture. After capture, exact
string tokens in the JSON `check_request` template bind `{workspace}`, `{candidate}`
and `{attempt}` (attempt ID). The helper saves `CHECK_REQUEST.json` and passes its
path to the runner when selected in argv. A consumer adapter invokes its actual
runner and projects its actual results into the selected binding shape; it must
not synthesize passing evidence from plain logs.

`runner_result` names a new direct attempt JSON filename. `result_bindings` maps
`candidate`, `workspace`, `attempt`, `request_sha256`, `ready` and `references` to
nonempty lists of object keys in that consumer result. Readiness must be exact
boolean true, candidate/workspace/attempt/request hash must agree, and references
must be a nonempty bounded list of regular absolute `path`/`sha256` files. The
consumer's result bindings must cover its required gate outcomes and coverage;
RI does not infer that those were adequate from a readiness boolean. Keep private
request/environment values out of public summaries; do not put credential values
in selected input files or request templates. The return contains identities,
operation exits, selected source/base/changed paths and references, not raw child
configuration. Consumer runners retain their own exclusive per-gate outputs; only
edit/capture/runner invocation stdout/stderr are retained by this linkage helper.

`RETURN.json` is persisted before operations and after each observed transition;
failed/blocked/incomplete returns never acquire `review_ready: true`. A completed
return is mechanical source/reference consistency, not independent review,
semantic acceptance, delivery consumption or permission to integrate. Existing
result-report schema versions remain unchanged; this helper's packets use
`schema_version: 1`. Before/after identity checks and cwd selection are not
filesystem isolation, continuous observation, or protection against arbitrary
outside writes. Consumer capture permissions and active instruction pins remain
unchanged until separately adopted.

Structured request/result parsing remains bounded to 1,000,000 bytes. Regular
executable/input/output/evidence identity hashing streams 64 KiB chunks up to
1,000,000,000 bytes, rejects nonregular/symlink endpoints and checks file identity,
size and modification observations before/after reading. It does not omit large
interpreters or logs merely because they exceed the JSON parsing limit. Every
known result-binding key path is validated during preparation, before operations.
These additive options retain helper schema version 1; existing subprocess
bindings retain their selected behavior. Consumer adapters and actual host return
consumption need their own bounded proof when selected, not routine live exercises.

### Operation finality and adapter conformance

Local operation launch supports owned POSIX process groups. A timeout or interruption handled by the helper
terminates the selected group and waits for completion before hashing final output;
descendants that outlive their immediate parent make the operation incomplete.
Unknown remaining activity retains output paths as not-final, never final hashes
or review-ready status. Escaped process groups and external host jobs are outside
this local ownership contract and must use a selected consumer completion route;
immediate-child success alone cannot qualify them. Unsupported platforms refuse
local operation ownership. Helper termination by an unhandled signal or host crash does not establish cleanup.
This is not universal process supervision.

Return writes use exclusive unpredictable temporary files and replacement; residue
from an older write cannot block a normal new write. Uncertain launch markers and
partial evidence still require reconciliation, not blind retry. Final capture scope
always considers rename source deletion and destination addition independently of
Git rename configuration. Known output filenames, argv and environment forms are
validated during preparation; runtime capability failures remain honest failures.

The optional `adapter_conformance.assess` accepts a consumer projection, not a
replacement native result format: `source_stable`, `terminal_complete`, explicit
`outcomes` with boolean `mandatory` and `status`, and named `request_digests`.
Statuses are passed/failed/blocked/unlaunched/incomplete/pending. Due required outcomes must
pass independently of source stability, command exit or an intermediate finalize;
advisory failures remain observations. Empty/malformed or unknown observations
cannot qualify. A selected `conformance` object-key path in the execution request
applies this check to the actual mapped consumer result before review-ready status.
Consumer adapters own authentic projection and required-outcome coverage; the helper
cannot certify a deliberately false adapter.

`raw_file_sha256` hashes actual CHECK_REQUEST bytes; `canonical_json_sha256` hashes
parsed JSON serialized with sorted keys, compact separators and ASCII escaping.
Verify each selected representation under its own name. Other native formats need
an explicit supported mapping; never relabel canonical hashes as raw file hashes.
Existing raw request/source/reference validation remains required. Consumers own
actual adapter and selected-worker integration tests, including interrupted and
failed native results; shared fixtures supply small reusable conformance controls.

Optional `integration_base` is a full ancestor commit of the original recovery
`base`. Return `integration_changed_paths` describes B→C2; `changed_paths` describes
C1→C2 and `recovery_base` retains C1. This uses existing Git projection, not a new
ledger or acceptance narrowing. Existing requests default integration base to base;
all additions retain packet schema1. No consumer adoption or active pin changes
follow automatically. See the [selected role entrypoint](worker-instructions.md#implementor)
when an available binding is explicitly assigned; other project routes remain valid.

### Consequential dispositions

Keep distinct meanings in existing handoffs and records; consumers may retain native
statuses with explicit translation. **Execution outcome** describes what actually ran
and its tool-reported exits/results, including partial work before a block.
**Evidence eligibility** describes whether source, inputs and provenance permit using
those results: successful execution can still supply ineligible evidence.
**Review** judges the candidate against due criteria; **approval** is the authorized
controller decision; **integration** is the verified repository transition. Review PASS
creates neither approval nor integration. **Sent** records attempted transmission,
**delivered** records destination availability, and **consumed** records receiver use;
each requires observable supporting facts. Unknown stays unknown, without a new
acknowledgment ritual.

Each consequential disposition cites its supporting evidence and accounts for all
applicable unresolved obligations against the accepted required set, not just the
returned subset. Evaluate obligations when due: installed checks remain explicitly
pending before integration, rather than premature review blockers. An unresolved due
finding prevents correction-complete. Give judgment a brief checkable basis in existing
notes/results, not private reasoning or a new document. Preserve mechanical tool reasons,
exits and logs; explain meaningful changes through newly resolving evidence while
retaining prior failures. Dispatcher relay preserves unchanged authoritative references
rather than reconstructing acceptance matrices or evidence.

For selected adapter coverage, optional `required_outcomes` in the prepared request maps
accepted obligation IDs to boolean due flags. It requires `conformance`; mapped outcomes
carry unique `id` values. Every accepted obligation must appear; due obligations must
pass even if the adapter marks them advisory. Not-yet-due obligations may be `pending`
with `mandatory: false`, retaining visibility without premature gating. Without this
binding, adapters retain responsibility for independently proving required-set coverage.
This additive mapping does not certify semantic judgment, consumer adoption or honesty
of the accepted obligation inventory. Actual consumer adapters require their own tests.
