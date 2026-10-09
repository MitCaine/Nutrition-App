# Shared instruction identity

The selected Repository Intelligence instructions for future task intake are
pinned at `686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f`. The GH-307 and GH-309
attempts retain their separately recorded `5ff7f306df6080648e2cc5fbbfc119e55a293754`
role/input identities; this adoption does not repin an active or historical
attempt. The completed GH-305 implementor assignment used its separately
retained `f6e1064d3f43aee61796f8558a7cef8181426883` Shared-worker and Implementor
input. Producer/runtime identity is separate and remains pinned below. The local
source identities and declared transformations are:

| Local file / upstream source at 686 | Role and transformation | Git blob | Upstream bytes | Upstream SHA-256 | Local bytes | Local SHA-256 |
| --- | --- | --- | ---: | --- | ---: | --- |
| [local `start-an-issue.md`](start-an-issue.md) / `docs/start-an-issue.md` | Daily execution in established projects; exact upstream bytes | `090c34dc2e6371e514edb5d8e849c11c10bab708` | 28179 | `9897bbf45f4a4c698e14b9a693dc7fb94694ec392aa49939648dde742f87dd6e` | 28179 | `9897bbf45f4a4c698e14b9a693dc7fb94694ec392aa49939648dde742f87dd6e` |
| [local `worker-instructions.md`](worker-instructions.md) / `docs/worker-instructions.md` | Shared worker rules and assigned role sections; dispatcher kickoff locator points to the installed project skill | `4f8f3667561150a17868da9c2101d69297d769a5` | 13897 | `7dc48817966d77456f3ee294393fd0d987b9ae06227535e2f152ef8da83384f7` | 13905 | `7d36722b9a855b7a7483ffd976322bdf8577c7522d27af0c46495b0eb943af81` |
| [local `capsule-controller-workflow.md`](capsule-controller-workflow.md) / `docs/capsule-controller-workflow.md` | Conditional adoption and replacement; exact upstream bytes | `3587587a69fbef25587347a2ed11b76e1610d65d` | 14656 | `1292b9ee70de02db49efd14bd1d15f5c9f4501e98733e75fb81bd7fd5c1ead5f` | 14656 | `1292b9ee70de02db49efd14bd1d15f5c9f4501e98733e75fb81bd7fd5c1ead5f` |
| [local `new-project-setup.md`](new-project-setup.md) / `docs/new-project-setup.md` | New-project setup; consumer-guide locator is pinned to the selected 686 source | `4e2663dce26788f5104ef93af7b5955beb4a0ba2` | 11126 | `3b48e19c9dc836820a6902dcaf549a5f6b0551beb287a6c41ee6f01f99a9a74f` | 11229 | `a3b45abbe281476d8fb894a6aa99c37cf824f78241c29aed8a6d192bb2a24964` |
| [local skill-template README](skill-templates/README.md) / `docs/skill-templates/README.md` | Optional-template guidance; kickoff links resolve to installed project folders and optional source links pin 686 | `54db08ecb4f44ddb1df7d4aa22988daef1e89f47` | 8251 | `3b119ff01a9e22c090d3f2f27be4acd6ac4da0279ac5a4faf0da32adc54db6b1` | 9377 | `9eb8351f5627d86c69b990966812b19ebe1e358c66d4a10e4703fb9ba41d4e9e` |
| [local queue redirect](skill-templates/capsule-queue/SKILL.md) / `docs/skill-templates/capsule-queue/SKILL.md` | Conditional queue handoff; adapted to link to the pinned external resource | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` | 2029 | `ad4441425b1c6be2058ecbd32016daebafccbd8956ccfebc7f1e328c5a852fad` |
| [installed Work kickoff skill](../../../.agents/skills/ri-work-kickoff/SKILL.md) / `docs/skill-templates/ri-work-kickoff/SKILL.md` | Project-scoped kickoff locator; exact upstream bytes | `820bb078fa7bda36e4b24333327ec5f29e91b8b4` | 1392 | `cbb0762af66cb39dc52abd9400e41f8e49abfa35109576ee4dee05fca028a169` | 1392 | `cbb0762af66cb39dc52abd9400e41f8e49abfa35109576ee4dee05fca028a169` |
| [installed Codex dispatcher kickoff skill](../../../.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md) / `docs/skill-templates/ri-codex-dispatcher-kickoff/SKILL.md` | Project-scoped dispatcher kickoff locator; exact upstream bytes | `055e1048858c89c0346c810a6a03242fc9ce26b8` | 1502 | `79de7229dfa3bbe12a8c85e89c5020969ebb80f2b5223f1a8d66c366a2d627a8` | 1502 | `79de7229dfa3bbe12a8c85e89c5020969ebb80f2b5223f1a8d66c366a2d627a8` |
| Both installed skill `references/project-procedure.md` files / their matching `docs/skill-templates/{ri-work-kickoff,ri-codex-dispatcher-kickoff}/references/project-procedure.md` resources | Shared kickoff reference; exact upstream bytes | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |

The setup and optional-template entrypoints keep these resources as explicit
pinned upstream links because their optional trees were not copied into this
project. Their local callers and exact target identities are:

| Local caller | RI resource at 686 | Git blob | Bytes | SHA-256 | Local disposition |
| --- | --- | --- | ---: | --- | --- |
| `new-project-setup.md` consumer-guide link | `docs/consumer-guide.md` | `19cf168338614208b2592c5e0111d223384da3a6` | 10705 | `069cd5607e52b2ef300f4c99d286faf30f4a6200b24a8b5ea0fa015a0e5980b3` | Pinned link; source is not copied |
| `skill-templates/README.md` capsule-preflight link | `docs/skill-templates/capsule-preflight/SKILL.md` | `810da881c165ea06f7f748fabb9c2933d4a1b377` | 2458 | `2e6768bde22564f40dbcfd5bf901518aa216d51c23a4a4f5040fd0e33ad69c1a` | Optional template; source is not copied |
| `skill-templates/README.md` evidence-contract links | `docs/skill-templates/capsule-preflight/references/evidence-contract.md` | `508b89b141a22ac783166bad559fc65db4b5ca1d` | 15809 | `294e821c038c3cd31c30a4d03515948e5882439e2d52c54594ee29c24211a59f` | Optional reference; source is not copied |
| `skill-templates/README.md` capsule-scope-review link | `docs/skill-templates/capsule-scope-review/SKILL.md` | `295253dda1a590f4b6bb303c9afba06e4d3acb41` | 1318 | `12fd1e9ff74a971f9d53dcdb68ac156a4bfbf9ecc31e3ec3f0eeac82695d4799` | Optional template; source is not copied |
| `skill-templates/README.md` ri-evidence-handoff link | `docs/skill-templates/ri-evidence-handoff/SKILL.md` | `70ff680d4c2a1eef68905b6e1fe136061f998fe2` | 1321 | `701216b4fb1ce949078d38fa62f7022168b0b816d340e7c97fde19f7565719ce` | Optional template; source is not copied |
| `skill-templates/README.md` capsule-independent-review link | `docs/skill-templates/capsule-independent-review/SKILL.md` | `7c0e18ce6d9a5de1331354b899a723379c792a6d` | 2359 | `3d4da861fdfa9eeb90bd22e1731f9a061015ac92b14ec4870bbb188765b7f73e` | Optional template; source is not copied |

The upstream `README.md` was a read-only kickoff-example reference, not copied
as a local instruction: blob `6d2d666b91adb867857ffc3830904badec7b7c09`,
11738 bytes, SHA-256
`386b4a07ad573ed256c9b45f514c333c7282c8c3b57656c35912f912b893d4f3`.

The completed GH-305 implementor assignment used a separately retained f6
worker-instructions source with blob
`cae477e0ca3f898bdc3279716f8ab033a8ab8a9f`, 13008 bytes, SHA-256
`c1b0d0f6b2945ff9409e4893af3e2bdcb8c1cd4b299a17f9cb330d42448e349a`. Its Shared
and Implementor sections remain the historical assignment-specific input; the
686 adoption does not change that completed attempt.

The [local map](../../../docs/local_project_map.md) supplies Nutrition actors,
commands, standards, confirmation policy and permission boundaries.

The [template entrypoint](skill-templates/README.md) adapts the upstream optional
template guidance to this route. The project-scoped kickoff folders are
authenticated separately; that byte parity does not establish Work registration
or global skill availability.

The upstream `docs/skill-templates/capsule-queue/` tree contains the external
redirect resources below. Current blob, byte and SHA-256 identities at 686 are:

| RI upstream resource | Git blob | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` |
| [RI queue helper](https://github.com/MitCaine/repository-intelligence/blob/686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f/docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py) | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` |

Other optional template folders remain unadopted. The Work kickoff files are project-scoped
Codex sources only. Their presence does not prove Work import/registration,
availability, or invocation; those remain distinct post-installation
obligations and must be recorded as pending until host evidence exists.
The `ri-work-kickoff` and `ri-codex-dispatcher-kickoff` project-scoped folders were
compared with the selected 686 resources: all four files in the complete
two-file folders match upstream bytes and remain unchanged.

The compatible producer is separately pinned in
`engineering/tooling/ri-lock.json` at
`20a5039e7731eaa1303443b782caa81a383a0af1`, navigation 7, inventory 16,
adapter 13, mapping v13. The authenticated committed archive SHA-256 is
`dbe424d6fa816c7ab96ab849800fd6f3a8c959f05786edfe706b1d8bba7db54d`; the lock
records all 21 installed source-file hashes and the exact public wheel closure.
Instruction, producer, and dependency identities remain separate provenance.
