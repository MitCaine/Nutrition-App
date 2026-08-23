# Task capsules

> **Document role: Engineering Process.** This directory stores active execution contracts and the
> durable terminal-task history index.

| Path | Purpose |
| --- | --- |
| [TEMPLATE.md](TEMPLATE.md) | Canonical active capsule schema version 1 template |
| [active/](active/README.md) | Full capsules for `DRAFT` through `REVIEWED`, including blocked/correction work |
| [HISTORY.md](HISTORY.md) | Durable records for terminal `MERGED`, `RETROSPECTED`, and `CANCELLED` outcomes |

## Validation

```bash
python3 scripts/validate-task-capsules.py --all
python3 scripts/validate-task-capsules.py \
  --execution engineering/capsules/active/TASK-ID.md
```

Both commands support `--json` and `--output`.

Repository-wide validation checks all active capsules plus `HISTORY.md`. It verifies terminal-record
structure, unique task IDs, historical full-capsule recovery locators and SHA-256 bindings, and
rejects retained per-task terminal capsules under `engineering/capsules/completed/`.

A repository with no active capsules and no terminal history is valid. Strict execution preflight
still requires one clean, committed `READY` capsule as the only overlay above its exact
implementation baseline.

## Execution handoff

After strict preflight passes, render the durable executor bundle:

```bash
python3 scripts/render-task-handoff.py \
  engineering/capsules/active/TASK-ID.md
```

The renderer writes `handoff.md`, `handoff.json`, the exact capsule, validation evidence, and
checksums outside the repository. `handoff.md` is the executor prompt. Generation fails closed when
the capsule, branch, base commit, worktree, or committed overlay is invalid.

Use the stable task ID as the filename, for example
`engineering/capsules/active/E1-17-stage-3.md`; front matter `id` must match the filename stem.
Never reuse an ID, including an ID already recorded in `HISTORY.md`.

## Terminal closeout

Keep the full capsule in `active/` through `REVIEWED` or the last non-terminal state.

After successful integration, terminal closeout adds exactly one `MERGED` record to `HISTORY.md`.
That record preserves the final outcome, review and verification evidence, integration evidence,
and an exact Git commit/path plus SHA-256 from which the full capsule can be recovered.

The same closeout change removes the full active capsule. Do not move or copy it into a per-task
completed archive.

Cancellation follows the same pattern with a `CANCELLED` history record and an exact recovery
locator for the full capsule. A later retrospective updates the existing unique history record to
`RETROSPECTED`; it does not recreate the full capsule.

A capsule or history record never overrides product, architecture, operations, backlog, or GitHub
authority.
