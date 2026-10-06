# Shared instruction identity

The complete owner-selected Repository Intelligence instructions are pinned at
commit `6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0` independently of the compatible
producer runtime. These files retain exact authenticated upstream Git blob bytes.
Instruction updates require an explicit reviewed pin change. The selected seven
resource identities are also retained in the external
`issue-266-evidence/selected-ri/identity.json` manifest.

| Local file / upstream source | Role | Bytes | SHA-256 |
| --- | --- | --- | --- |
| RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md) | Daily execution in established projects | 17807 | `2e828c4b5fb657dc1f8db84889db5177980bbaae2cb6406a16bed82b42c1ea15` |
| RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md) | Conditional adoption and replacement | 14205 | `1472330ab29885faf41c397a2ebb23d71aeefdae47ca703b6879498ff8f7b691` |
| RI `docs/roles/README.md` → [local `engineering/workflow/shared/roles/README.md`](roles/README.md) | Role handoff index | 1034 | `94d7c852cd5e54065ec2687a96f4b4a6bf3961e3492f4882cdeadb17d79eb30b` |
| RI `docs/roles/capsule-builder.md` → [local `engineering/workflow/shared/roles/capsule-builder.md`](roles/capsule-builder.md) | Capsule builder assignment | 1241 | `d5ce88828336036d5f9389b6dc2f0b06a1a1bc90cbda0c122bf1421a2d9de402` |
| RI `docs/roles/implementor.md` → [local `engineering/workflow/shared/roles/implementor.md`](roles/implementor.md) | Implementor assignment | 1454 | `f190b26662b7332484885537039063c3d001b576336229481d5879c48bdae5ad` |
| RI `docs/roles/reviewer.md` → [local `engineering/workflow/shared/roles/reviewer.md`](roles/reviewer.md) | Independent reviewer assignment | 1492 | `f778d52573f9aaaacbb339e0cfb5cd4f7d448526812951f2bee7ab5e8f8cec0f` |
| RI `docs/roles/shared-rules.md` → [local `engineering/workflow/shared/roles/shared-rules.md`](roles/shared-rules.md) | Shared worker assignment rules | 1595 | `487b1a23118560dd20fc28bb5f4f536810ab957ed8ceeb87609e078622e9b679` |

The [local map](../../../docs/local_project_map.md) supplies Nutrition values,
commands, standards and permission boundaries. The [template entrypoint](skill-templates/README.md)
reconciles shared daily routing and the conditional queue target. That target is a
small redirect to the complete pinned upstream skill and its required resources;
no helper or installed-skill parity is implied. Global skills are not overwritten.

The producer remains `2f28da4d326ff12da5dc9270eb57910303e4a737`, navigation 6,
inventory 13, adapter 10, mapping v10, separately recorded in
`engineering/tooling/ri-lock.json`. Historical instruction/evidence identities
remain provenance, never current task authority.
