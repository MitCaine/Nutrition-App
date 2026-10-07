# Shared instruction identity

The complete owner-selected Repository Intelligence instructions are pinned at
commit `fd982035de66e23d5d924e2c437f844803f399ec`, independently of the compatible
producer runtime. These three local files retain the exact published upstream
bytes. Instruction updates require an explicit reviewed pin change.

| Local file / upstream source | Role | Bytes | SHA-256 |
| --- | --- | --- | --- |
| RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md) | Daily execution in established projects | 21690 | `0bb501fd64843e6b35683ea5bda6ca1f9175e9bfe550fc1fc8ad8e0b0f3fb666` |
| RI `docs/worker-instructions.md` → [local `engineering/workflow/shared/worker-instructions.md`](worker-instructions.md) | Shared worker rules and assigned role sections | 10862 | `21ddbbbf72c7c679f0845dc0da11a7a197f3a35a7e0c618ed37d714bcb151db3` |
| RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md) | Conditional adoption and replacement | 14229 | `3e2b4904cc134846c0814dc25ba6df6b359d7b53c58078e007f603628b36fe77` |

The [local map](../../../docs/local_project_map.md) supplies Nutrition values,
commands, standards and permission boundaries. The [template entrypoint](skill-templates/README.md)
reconciles shared daily routing and the conditional queue target. The redirect
resolves to these complete resources at the same RI commit; queue remains
conditional, and no helper or installed-skill parity is implied. Global skills
are not overwritten.

The conditional upstream queue targets are authenticated by the adoption evidence
at the same commit. They are references, not local installs:

| RI upstream resource | Git blob | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `74f082ff91bbe32dd7be0b1ac1c0d36f0143a54f` | 1523 | `44d314b860eb51a8c7a5df8baf43570403af6a697ba0b3f9d6d2070997e6dce0` |
| [RI queue helper](https://github.com/MitCaine/repository-intelligence/blob/fd982035de66e23d5d924e2c437f844803f399ec/docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py) | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` |

The producer remains `2f28da4d326ff12da5dc9270eb57910303e4a737`, navigation 6,
inventory 13, adapter 10, mapping v10, separately recorded in
`engineering/tooling/ri-lock.json`. Historical instruction/evidence identities
remain provenance, never current task authority.
