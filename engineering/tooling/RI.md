# Repository Intelligence for Nutrition

> **Document role: Engineering Tooling.** Optional, controller-owned source navigation.

RI supplies locations and source facts. Nutrition owns domain meaning, edit scope, tests,
review and approval. Start from the [workflow entrypoint](../workflow/START_HERE.md), then
use this guide to assemble bounded source context. This does not promote the combined
workflow or implement the structural-delta gate owned by GH-192.

## Pinned installation and private access

[ri-lock.json](ri-lock.json) pins private repository `MitCaine/repository-intelligence`
at `1619dd0665eb779ce7ffd2c6cc71331259dcbd5a`: navigation5, inventory11, adapter8 and
`python-rust-javascript-typescript-java-go-csharp-c-cpp-source-callables-v8`. Package
version0.1.0 alone is insufficient. Later upstream commits and dirty checkout files are
not part of this installation. The pin records the archive digest, all19 installed RI
source-file hashes, and14 public parser/build/installer wheels with versions and hashes.
The [requirements file](ri-requirements.txt) is controller tooling, not an app dependency.

The qualified installation target is **macOS arm64 with Python3.12**. This wheel lock is
platform-specific. No CI host is selected to run RI; Nutrition's existing Linux product CI
remains supported and unchanged. Other RI hosts require a separately reviewed wheel lock
and actual qualification. Ordinary Python/TS/TSX/JS navigation does not launch rust-analyzer,
Cargo or any Rust build; the standalone package's Rust grammar wheel is just a pinned
package dependency.

The controller must already have authorized access to the private Git objects. RI has no
project license file at this pin: do not vendor its source or upload private source/wheels
into the public Nutrition repository, review bundles, issues or candidate CI artifacts.
Do not grant private RI credentials to candidate-controlled jobs. Missing access is a
prerequisite failure; neither an unpinned public package nor another local checkout is a
fallback. Any later CI access/redistribution decision needs explicit owner authorization.

Acquire the exact private archive outside every Git worktree using the authorized private
checkout. This reads committed objects only; it does not copy dirty files or mutate upstream:

```bash
git -C /absolute/private-ri-checkout -c tar.umask=0002 archive --format=tar \
  1619dd0665eb779ce7ffd2c6cc71331259dcbd5a > /absolute/private-tooling/ri-source.tar
```

The expected archive SHA256 is
`311b93ec1a55db897d68c0eac579e56883bf23c5809f6be6b11b334ffb248553`.
The repository URL and archive pin identify the selected dependency; merely writing that
revision into a local manifest does not establish an installation.

Acquire public wheels separately, on the qualified platform, with the selected Python3.12
interpreter. This explicit acquisition step uses PyPI; navigation never installs or downloads:

```bash
/absolute/python3.12 -m pip --isolated download --index-url https://pypi.org/simple \
  --only-binary=:all: --require-hashes -r engineering/tooling/ri-requirements.txt \
  --dest /absolute/private-tooling/wheelhouse
```

Then install offline from the verified inputs into a **new external directory**:

```bash
NUTRITION_CONTROLLER_PYTHON=/absolute/python3.12 ./scripts/ri bootstrap \
  --source-archive /absolute/private-tooling/ri-source.tar \
  --wheelhouse /absolute/private-tooling/wheelhouse \
  --destination /absolute/private-tooling/nutrition-ri
NUTRITION_CONTROLLER_PYTHON=/absolute/python3.12 ./scripts/ri verify \
  --runtime /absolute/private-tooling/nutrition-ri/manifest.json
```

Bootstrap checks all source/wheel hashes before creating the environment, uses exact hashed
requirements with no index and no build isolation, and denies network access to installer
commands through the native macOS sandbox. It preserves logs and any failure; an existing
destination is never overwritten. A complete manifest appears only after installed RI source,
dependency versions, Python and emitted contracts match. Private build materialization is
removed after installation; installed code and the manifest remain external controller state.

The controller-owned manifest binds all environment file bytes, including bytecode, executable
symlink targets, dependency versions and the public lock. Verify runs before and after each
query. Runtime drift fails closed. Protect the manifest and installation as trusted controller
state; self-consistent user-authored JSON is not independent installation provenance. Absolute
venv paths and build metadata can differ between installations; reproducibility means the same
pinned source/dependency/contracts, not byte-identical path-containing metadata. Base interpreter
libraries and OS dependencies remain qualified host dependencies, not full OS attestation.

## Navigate an exact source selection

Use an exact40-character commit and either a named scope or up to8 relative file/directory
prefixes. A dirty checkout does not change these committed-source observations.

```bash
NUTRITION_CONTROLLER_PYTHON=/absolute/python3.12 ./scripts/ri query \
  --runtime /absolute/private-tooling/nutrition-ri/manifest.json \
  --revision EXACT_COMMIT --path apps/backend/app/services/recipe_service.py \
  --query 'publish recipe revision' --limit 4 \
  --output-dir /absolute/controller-evidence/recipe-navigation
```

Scopes are `backend` (backend app), `tooling` (scripts/engineering), `mobile` (mobile src),
and `cross-runtime` (backend services plus mobile runtime adapters). Repeat `--path` for a
custom bounded selection. Narrow the scope when source budgets are exceeded; do not silently
truncate membership. The consumer selects only explicit committed Git regular files, then
materializes them outside the repository. Symlinks/submodules fail. Untracked/ignored working
files are never implicitly scanned. `.gitignore` is not treated as a membership authority.

Selected suffixes are Python, JS/JSX/MJS/CJS and TS/TSX/MTS/CTS. Hidden paths and directory
names node_modules, venv, __pycache__, target, dist, build and generated are excluded and
reported. Unsupported/other committed paths are reported separately. Limits are1000 selected
files,4MB per file,40MB total, query300characters, and1–20 matches. The bounded packet is at
most100KB, with excerpts up to2000raw bytes per match and bounded diagnostic/path samples;
full counts and the raw observation remain available. These are explicit consumer limits,
not claims about RI's entire language or size support.

Each match carries a repository-relative path, exact source SHA256/Git blob, parser metadata,
raw byte range and declaration hash. The consumer checks returned identities/ranges against
committed bytes and checks materialization before/after. Display line numbers and UTF-8
excerpts are navigation hints; raw byte hashes/ranges are the identity. The ephemeral source
copy is deleted after the query. Raw JSON, source-selection manifest and bounded packet remain
in the chosen external evidence directory; there is no saved navigation index. An existing
output directory is not overwritten, and output cannot be inside the installed runtime.

Use the packet's revision and digests when attaching it to a capsule handoff. Requery after
source changes. A location at P is not automatically a current location at C. Do not use the
wrapper to claim knowledge of uncommitted implementation edits; inspect those directly or
commit an authorized candidate and query that exact revision.

## Results and failure meaning

`navigation_only` yields exit0, including zero matches. `incomplete`, `unsupported` or
`excluded` yields exit2. Invalid input, runtime drift, source mismatch or failed acquisition
stops with exit1. No status proves semantic completeness; zero matches never proves absence.
Parser failures stay visible, and incomplete observations may contain useful neighboring
locations without qualifying structural completeness. Unsupported-only selections explicitly
return unsupported, rather than an empty success. Malformed source remains incomplete.

Raw RI directory JSON is larger than its match list and retains per-file metadata. The
consumer packet is bounded separately. Full diff/direct-source review is mandatory for Swift,
SQL, shell, YAML/JSON/configuration, migrations, generated/native outputs, and any unsupported
or excluded boundary. An empty callable result does not establish unchanged behavior.

## Nutrition authority map

| Concern | Read with the navigation result | Preserved rule |
| --- | --- | --- |
| Local versus remote runtime | `apps/mobile/src/runtime/local`, `apps/mobile/src/runtime/remote`, backend services | Local SQLite and remote server/PostgreSQL authority are distinct; no hidden fallback or dual write. |
| Historical nutrition and recipes | Daily Log and recipe publication services/repositories, local runtime equivalents | Logged nutrition and published revisions remain immutable; mutable compatibility projections are not historical authority. |
| Ownership and retries | Runtime authority identities, backend owner scoping, idempotency services | Enforce ownership at the selected boundary and preserve deterministic replay. |
| Persistence/concurrency | Current migrations, transaction owners, locks and executable tests | Native/file-backed SQLite and PostgreSQL16 concurrency evidence are not interchangeable. |
| Native/UI changes | Mobile native modules, permissions, generated platform surfaces and accessibility tests | Native/device checks remain explicit when triggered; TS syntax navigation does not provide native proof. |

The authoritative detailed rules remain in [AGENTS](../../AGENTS.md), current executable
contracts and the [testing guide](../../docs/operations/testing.md). This table is orientation,
not a new source of domain policy or permission to edit every matched path.

## Verified navigation examples and qualification

At planning revision `62f277b5aa6672e15129f524283fc337ca66b2c9`, actual pinned-package queries
returned `navigation_only` with no failures. Returned hashes/ranges were checked against Git
bytes; examples are historical observations, not enduring line-number authority:

| Selection/query | Independently inspect these source slices |
| --- | --- |
| Recipe service / publish recipe revision | `RecipeService.publish` and revision response/capture helpers. |
| DailyLogScreen.tsx / daily log | `DailyLogScreen`, `DailyLogEntryCard` and deletion reconciliation helpers. |
| Cross-runtime / recipe publish | Backend `RecipeService.publish`, remote `runtime.recipes.publish`, local `LocalRecipesRuntime.publish`. |
| task.py / qualify task | `qualify_task`, `integrate_task`, controller preparation/qualification entrypoints. |

Focused deterministic tests cover identity/contract/dependency drift, private-state placement,
Git membership, path/size/range limits, materialization mutation, aliases and honest result
semantics. Set `NUTRITION_RI_RUNTIME` to the actual private manifest to require the real-package
oracle in `scripts/tests/test_ri_consumer.py`; otherwise its explicit skip is not package proof.
The real oracle covers Python/TSX/JS source slices, zero matches, malformed source and SQL-only
input. Actual Nutrition examples and offline installation evidence are also required locally;
public CI does not need private source access to run deterministic consumer tests.

An upgrade needs a new explicit revision/contract/wheel lock, a clean external installation,
real source/failure oracles, baseline qualification and independent review. Do not edit an
accepted environment in place or point a manifest at the newer dirty upstream checkout.

### Pip security refresh (2026-09-26)

The controller lock now selects pip 26.2, which clears the pip affected ranges in
Dependabot alerts 19–22 and 24, including
[GHSA-qwm4-qh6w-59xr](https://github.com/advisories/GHSA-qwm4-qh6w-59xr).
Both the requirements file and wheel lock must change together; a requirements-only
Dependabot patch is not an installable RI lock update. Existing installation manifests
intentionally fail verification after a lock change. Bootstrap a fresh external environment
from the updated wheelhouse and requalify navigation before using it. Preserve previous
environments as historical evidence, not the selected runtime. RI source and parser
contracts are unchanged. Setuptools alert 23 is tracked separately by PR #196.

### Setuptools security refresh (2026-09-26)

The companion update selects setuptools 83.0.0 for Dependabot alert 23
([GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c)),
while retaining pip 26.2 and the existing RI/parser pins. The alert concerns Unicode
normalization when applying source-distribution exclusions on macOS. The fixed wheel
and its hash are synchronized in both lock files. As with the pip refresh, bootstrap
a new external runtime and requalify it; do not edit an accepted manifest or environment
in place. No private source distribution is published by this workflow.
