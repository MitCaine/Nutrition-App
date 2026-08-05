# Task capsules

> **Document role: Engineering Process.** This directory stores durable execution contracts.

| Path | Purpose |
| --- | --- |
| [TEMPLATE.md](TEMPLATE.md) | Canonical schema version 1 template |
| [active/](active/README.md) | `DRAFT` through `REVIEWED`, including blocked/correction work |
| [completed/](completed/README.md) | `MERGED`, `RETROSPECTED`, or `CANCELLED` records |

Use the stable task ID as the filename, for example
`engineering/capsules/active/E1-17-stage-3.md`; front matter `id` must match the filename stem.
Never reuse an ID.

Copy the template, fill authority/boundaries/acceptance/verification/evidence/escalation,
advance state under [Task States](../workflow/STATES.md), execute only from `READY`, record
completion, then move the capsule to `completed/`. A capsule never overrides product,
architecture, operations, backlog, or GitHub authority.
