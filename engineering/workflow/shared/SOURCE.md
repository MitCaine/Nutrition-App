# Shared instruction identity

The complete owner-selected Repository Intelligence instructions are pinned at
commit `cdf64f5d27ef43e7e58e7b11f371a81d15687bdd` independently of the compatible
producer runtime. These files retain exact authenticated upstream Git blob bytes.
Instruction updates require an explicit reviewed pin change.

| Local file / upstream source | Role | Bytes | SHA-256 |
| --- | --- | --- | --- |
| RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md) | Daily execution in established projects | 17374 | `cc5f69f8c8dd3f508feda911dbf93f1558e31c1ba4b9bd480b107ac81e136779` |
| RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md) | Conditional adoption and replacement | 14131 | `64e3b311c5a9524c8b14708d1805c3676425347d3ba498fb101274ea946f1179` |

The [local map](../../../docs/local_project_map.md) supplies Nutrition values,
commands, standards and permission boundaries. The [template entrypoint](skill-templates/README.md)
reconciles shared daily routing and the conditional queue target. That target is a
small redirect to the complete pinned upstream skill and its required resources;
no helper or installed-skill parity is implied. Global skills are not overwritten.

The producer remains `2f28da4d326ff12da5dc9270eb57910303e4a737`, navigation 6,
inventory 13, adapter 10, mapping v10, separately recorded in
`engineering/tooling/ri-lock.json`. Historical instruction/evidence identities
remain provenance, never current task authority.
