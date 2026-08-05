# Task capsules

> **Document role: Engineering Process.** This directory stores durable execution contracts.

| Path | Purpose |
| --- | --- |
| [TEMPLATE.md](TEMPLATE.md) | Canonical schema version 1 template |
| [active/](active/README.md) | `DRAFT` through `REVIEWED`, including blocked/correction work |
| [completed/](completed/README.md) | `MERGED`, `RETROSPECTED`, or `CANCELLED` records |

## Validation

```bash
python3 scripts/validate-task-capsules.py --all
python3 scripts/validate-task-capsules.py \
  --execution engineering/capsules/active/TASK-ID.md
```

Both commands support `--json` and `--output`. A repository with no task capsules is valid and
reports zero validated capsules. Execution preflight requires one clean, committed `READY` capsule
as the only overlay above its exact implementation baseline.

Use the stable task ID as the filename, for example
`engineering/capsules/active/E1-17-stage-3.md`; front matter `id` must match the filename stem.
Never reuse an ID.

Copy the template, fill authority/boundaries/acceptance/verification/evidence/escalation, advance
state under [Task States](../workflow/STATES.md), execute only from a preflight-qualified `READY`
capsule, record completion, then move the capsule to `completed/`. A capsule never overrides
product, architecture, operations, backlog, or GitHub authority.
