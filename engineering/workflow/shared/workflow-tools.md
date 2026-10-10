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
no-op. The consumer separately updates its declared selection/identity records,
checks local validators and links, reviews the full candidate and verifies
installed closeout. Resource equality alone does not prove usable skills, host
availability or adoption correctness.

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

The [evidence preflight helper](https://github.com/MitCaine/repository-intelligence/blob/ae8768d4f806dbdc212a50d5e55c74b386e4963f/docs/skill-templates/capsule-preflight/scripts&#47;evidence_preflight.py)
contains pure input-equivalence predicates; unknown relevant inputs are not
cacheable. Its extended packet validation remains optional and is not required
by these tools. [Documentation/link checks](https://github.com/MitCaine/repository-intelligence/blob/ae8768d4f806dbdc212a50d5e55c74b386e4963f/scripts&#47;check_docs_and_skills.py),
the [bounded source locator](https://github.com/MitCaine/repository-intelligence/blob/ae8768d4f806dbdc212a50d5e55c74b386e4963f/docs/consumer-guide.md) and
[review bundles](https://github.com/MitCaine/repository-intelligence/blob/ae8768d4f806dbdc212a50d5e55c74b386e4963f/docs/review-evidence.md) retain their existing separate scopes.
None authenticates task authority or proves runtime availability.
