# Shared instruction identity

The selected Repository Intelligence instructions are pinned at commit
`20a5039e7731eaa1303443b782caa81a383a0af1`, independently of the compatible
producer runtime. The three shared local files below are the exact committed
upstream bytes; selection provenance does not replace the active task handoff.

| Local file / upstream source | Role | Git blob | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md) | Daily execution in established projects | `469ccc803ee830451ebc37c4cf42efdf922e8cc6` | 25291 | `15c71e4b64a328f40e243285e4022cdc370907552ab29fd5d305d2ef4e2f29f8` |
| RI `docs/worker-instructions.md` → [local `engineering/workflow/shared/worker-instructions.md`](worker-instructions.md) | Shared worker rules and assigned role sections | `567868e2ccaafd0c9d17d44d55451b3e83a67bc3` | 12325 | `7260bf6b463ce33871ff85d9547bded4b3caf3e2b1f7658240a04e713de8cd65` |
| RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md) | Conditional adoption and replacement | `e3aa4549ad86e6e04f13ba7e970e9f65cb028b03` | 14254 | `4d11d1433756cc333ee966444276555cf733ae67bd8d51af07739bc11e0f8e13` |

The [local map](../../../docs/local_project_map.md) supplies Nutrition actors,
commands, standards, confirmation policy and permission boundaries. The
[template entrypoint](skill-templates/README.md) adapts the upstream optional
template guidance to this route; it does not install or claim parity for local
or global skills.

The complete upstream `docs/skill-templates/capsule-queue/` tree contains these
three required redirect resources. A full-tree comparison from `fd982035` to
`20a5039` found no queue-resource changes; their current blob, byte and SHA-256
identities remain:

| RI upstream resource | Git blob | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `74f082ff91bbe32dd7be0b1ac1c0d36f0143a54f` | 1523 | `44d314b860eb51a8c7a5df8baf43570403af6a697ba0b3f9d6d2070997e6dce0` |
| [RI queue helper](https://github.com/MitCaine/repository-intelligence/blob/20a5039e7731eaa1303443b782caa81a383a0af1/docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py) | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` |

The upstream optional-template README used to reconcile the local entrypoint is
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
