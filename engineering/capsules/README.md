# Task capsules

> **Document role: Engineering Process.** This directory stores active execution contracts and the
> durable terminal-task history index.

| Path | Purpose |
| --- | --- |
| [Historical template](TEMPLATE.md) | Preserved TOML recovery shape; not new task dispatch |
| [active/](active/README.md) | Full capsules for `DRAFT` through `REVIEWED`, including blocked/correction work |
| [HISTORY.md](HISTORY.md) | Durable records for terminal `MERGED`, `RETROSPECTED`, and `CANCELLED` outcomes |

## Current task records and historical validation

New tasks use the bounded Markdown [template](../tasks/TEMPLATE.md) under `engineering/tasks/`
and [local project map](../../docs/local_project_map.md). No JSON report or capsule-only READY overlay
is required for the ordinary route.

`python3 scripts/validate-task-capsules.py --all` remains a consistency/recovery reader
for existing active TOML capsules and HISTORY. It preserves terminal-record uniqueness,
reachable full-capsule Git bytes and SHA-256 bindings. Strict legacy execution validation
and its old renderer are historical tools, not current dispatch or permission.
#246/#256 remain paused. Do not replace their original contract with the new template.

## Terminal closeout

Keep the full capsule in `active/` through `REVIEWED` or the last non-terminal state.

After successful integration, terminal closeout adds exactly one `MERGED` record to `HISTORY.md`.
That record preserves the final outcome, review and verification evidence, integration evidence,
and an exact Git commit/path plus SHA-256 from which the full capsule can be recovered.

The same closeout change removes the full active capsule. Do not move or copy it into a per-task
completed archive.

The trusted `task finalize` controller command records the implementation C and terminal T
as separate protected updates. It verifies that T is a direct child of C and changes only
HISTORY and the active-capsule deletion, while a reachable R contains the full REVIEWED
capsule with all acceptance criteria checked. R's Git path and SHA-256 must match HISTORY.
The controller can resume after a partial remote push; it closes the issue only after
remote main is confirmed at T. Never transfer C's qualification or review to T.
Optional final cleanup accepts only an explicit clean terminal checkout and branch
at T after verified issue closure; recovery and unrelated work remain available.
Cancellation has a separate guarded `finalize-cancel` path: its full source capsule
records `CANCELLED` at R, its two-path terminal T has distinct authorization and
qualification, and no unimplemented acceptance criterion is marked passed.

Cancellation follows the same pattern with a `CANCELLED` history record and an exact recovery
locator for the full capsule. A later retrospective updates the existing unique history record to
`RETROSPECTED`; it does not recreate the full capsule.

A capsule or history record never overrides product, architecture, operations, backlog, or GitHub
authority.
