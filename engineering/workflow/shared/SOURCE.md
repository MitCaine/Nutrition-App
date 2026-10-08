# Shared instruction identity

The selected Repository Intelligence instructions are pinned at commit
`f6e1064d3f43aee61796f8558a7cef8181426883`, independently of the compatible
producer runtime pinned below. The three shared local files below are the exact committed
upstream bytes; selection provenance does not replace the active task handoff.

| Local file / upstream source | Role | Git blob | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md) | Daily execution in established projects | `afb62770a4b5e4fe5430fad134ef337527fe5727` | 25728 | `1e6d4cbe7b92e48ee354bb9c7b9e11a87ccb2643b3e406c51c9c80027e98a473` |
| RI `docs/worker-instructions.md` → [local `engineering/workflow/shared/worker-instructions.md`](worker-instructions.md) | Shared worker rules and assigned role sections | `cae477e0ca3f898bdc3279716f8ab033a8ab8a9f` | 13008 | `c1b0d0f6b2945ff9409e4893af3e2bdcb8c1cd4b299a17f9cb330d42448e349a` |
| RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md) | Conditional adoption and replacement | `4e3a69b17dd558cb1180e001ff88bab0bc949d0a` | 14334 | `f24d09a935a4661619b94ec2048d4ad1b6e386101ea32db9ef708717a3b6d148` |

The [local map](../../../docs/local_project_map.md) supplies Nutrition actors,
commands, standards, confirmation policy and permission boundaries. The
[template entrypoint](skill-templates/README.md) adapts the upstream optional
template guidance to this route; it does not install or claim parity for local
or global skills.

The complete upstream `docs/skill-templates/capsule-queue/` tree contains these
three required redirect resources. Comparing its complete identity inventory at the
previous instruction pin `20a5039e7731eaa1303443b782caa81a383a0af1` with selected
revision `f6e1064d3f43aee61796f8558a7cef8181426883` shows that the skill and helper bytes
are unchanged and the project-procedure locator changed. Current blob, byte and SHA-256
identities are:

| RI upstream resource | Git blob | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` |
| [RI queue helper](https://github.com/MitCaine/repository-intelligence/blob/f6e1064d3f43aee61796f8558a7cef8181426883/docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py) | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` |

The upstream optional-template README used to reconcile the local entrypoint at
selected revision `f6e1064d3f43aee61796f8558a7cef8181426883` is
`docs/skill-templates/README.md`, blob `3874eb0aaad5c653f9ed5d66e827249bf100fbab`,
6384 bytes, SHA-256
`2679cf0fdc5bd4dd370f617e30c729e5965ed7a5dbdd370c1aa259fd138f7086`.
Its Work, native and queue routing guidance is adapted locally; other optional
template folders remain unadopted.

The compatible producer is separately pinned in
`engineering/tooling/ri-lock.json` at
`20a5039e7731eaa1303443b782caa81a383a0af1`, navigation 7, inventory 16,
adapter 13, mapping v13. The authenticated committed archive SHA-256 is
`dbe424d6fa816c7ab96ab849800fd6f3a8c959f05786edfe706b1d8bba7db54d`; the lock
records all 21 installed source-file hashes and the exact public wheel closure.
Instruction, producer, and dependency identities remain separate provenance.
