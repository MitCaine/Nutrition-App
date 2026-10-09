# Shared instruction identity

The Repository Intelligence instruction set for future task intake is selected at
`841d57571983b5b7cec0071263fad7f78d809e20`. This updates future intake only.
The GH-311 attempt's historical worker-instruction selection is
`686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f`, with local worker-instructions
SHA-256 `7d36722b9a855b7a7483ffd976322bdf8577c7522d27af0c46495b0eb943af81`.
This is attempt provenance and does not assert that the attempt or assignment remains active.
The GH-307 and GH-309 attempts retain their separately recorded
`5ff7f306df6080648e2cc5fbbfc119e55a293754` role/input identities. The completed
GH-305 implementor assignment retains its separate `f6e1064d3f43aee61796f8558a7cef8181426883`
Shared-worker and Implementor input. This adoption repins no active or historical
attempt. Producer/runtime identity is separate and remains pinned below.


Completed GH-311 adopted RI `5749d2b411f0f12e1de6403c2ab9470cc3547b01`; its original copied-resource identities and failures remain in the exact installed Git baseline `86b7e9c16c4f4d8fc31481d960e1a9b4bbb0ea83`, task record and external controller evidence. This follow-up does not amend that record or repin any historical attempt.

The controller inspected the full prior-selected-to-target diff and supplied the complete 24-file selected source tree. Upstream README is a read-only example source; Nutrition README remains project-owned. Optional template trees remain unadopted except for pinned links and the existing queue redirect.

| RI 841d575 source resource | Git blob | Upstream bytes | Upstream SHA-256 | Local disposition |
| --- | --- | ---: | --- | --- |
| `README.md` | `d04e157f6b22abc70c8aeb0067398b224794153e` | 12880 | `bb57c19350e9590c0ebceea52d0a98d8392ea5eb7247a0ff646ea06e19c8bbdd` | Read-only example source; project README remains Nutrition-owned |
| `docs/start-an-issue.md` | `1f44ab796d55826f4eaa87dc10188d244fd3c7b6` | 30240 | `4cdbc4ef8b881040516da836135af395a2a312ea1be4c3a9d72420eaf9d9bade` | Installed at [local `start-an-issue.md`](start-an-issue.md); exact selected bytes; 30240 bytes, SHA-256 `4cdbc4ef8b881040516da836135af395a2a312ea1be4c3a9d72420eaf9d9bade` |
| `docs/worker-instructions.md` | `d5ec5fb55d69da2988147600b322ad5847a43d16` | 14783 | `59cb6bef5bffe5fb9c8157a761519088247c73a90634453602ce7943c2108cab` | Installed at [local `worker-instructions.md`](worker-instructions.md); only dispatcher kickoff locator relocated to the installed project skill; 14791 bytes, SHA-256 `52860da27cb05d5411d1b12f36d20846aa0fecaab7bb2860e836d9c41fb0bf7d` |
| `docs/capsule-controller-workflow.md` | `ce7f0e7d261b44de9575255e5eff77edc6c78bc7` | 14954 | `88df7ce7c7f568eb9cf1470390675fbadc7d093857d107390f8212799c1b21d6` | Installed at [local `capsule-controller-workflow.md`](capsule-controller-workflow.md); exact selected bytes; 14954 bytes, SHA-256 `88df7ce7c7f568eb9cf1470390675fbadc7d093857d107390f8212799c1b21d6` |
| `docs/new-project-setup.md` | `57da18cf5b1f5fc87e715e9ddd4fec9ace290464` | 15148 | `4efed81ba904cbf23f6cc886cf190c0e8bc67e7367b8c9b2fec7cf50c3f0a6dd` | Installed at [local `new-project-setup.md`](new-project-setup.md); consumer guide link pinned to this revision; 15251 bytes, SHA-256 `9f2dea919b4230e6d144304968361e41baf232aeb4755506ec0210018d70d7e7` |
| `docs/consumer-guide.md` | `19cf168338614208b2592c5e0111d223384da3a6` | 10705 | `069cd5607e52b2ef300f4c99d286faf30f4a6200b24a8b5ea0fa015a0e5980b3` | Pinned setup link; source not copied |
| `docs/skill-templates/README.md` | `54db08ecb4f44ddb1df7d4aa22988daef1e89f47` | 8251 | `3b119ff01a9e22c090d3f2f27be4acd6ac4da0279ac5a4faf0da32adc54db6b1` | Installed at `engineering/workflow/shared/skill-templates/README.md`; kickoff links relocated; unadopted optional-resource links pinned; 9019 bytes, SHA-256 `ec9b75b80e29f9ad9217cb38adea6169eb895b7e517a29ee3169462da5b5e508` |
| `docs/skill-templates/capsule-independent-review/SKILL.md` | `7c0e18ce6d9a5de1331354b899a723379c792a6d` | 2359 | `3d4da861fdfa9eeb90bd22e1731f9a061015ac92b14ec4870bbb188765b7f73e` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-independent-review/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-preflight/SKILL.md` | `810da881c165ea06f7f748fabb9c2933d4a1b377` | 2458 | `2e6768bde22564f40dbcfd5bf901518aa216d51c23a4a4f5040fd0e33ad69c1a` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-preflight/references/evidence-contract.md` | `508b89b141a22ac783166bad559fc65db4b5ca1d` | 15809 | `294e821c038c3cd31c30a4d03515948e5882439e2d52c54594ee29c24211a59f` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-preflight/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-preflight/scripts/evidence%5Fpreflight.py` | `03daccc30278c67a7d3505ee10018096690d13b5` | 26640 | `97bf1454d3f98f6502ffc9818c9146e629ecc898ec901442dae7ea86dc684174` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` | Pinned external queue resource; only existing local redirect copied, no helper installed/imported |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Pinned external queue resource; only existing local redirect copied, no helper installed/imported |
| `docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py` | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` | Pinned external queue resource; only existing local redirect copied, no helper installed/imported |
| `docs/skill-templates/capsule-scope-review/SKILL.md` | `295253dda1a590f4b6bb303c9afba06e4d3acb41` | 1318 | `12fd1e9ff74a971f9d53dcdb68ac156a4bfbf9ecc31e3ec3f0eeac82695d4799` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/capsule-scope-review/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/ri-codex-dispatcher-kickoff/SKILL.md` | `5abe72319146eed679ee4876e152831af041a31f` | 1640 | `01d7933a5811c1d8341afe41dbe52556105bb4c338b8ba5cb2575c3859d5d31a` | Installed at `.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md`; exact selected bytes; 1640 bytes, SHA-256 `01d7933a5811c1d8341afe41dbe52556105bb4c338b8ba5cb2575c3859d5d31a` |
| `docs/skill-templates/ri-codex-dispatcher-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` | Installed at `.agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md`; exact selected bytes; 1118 bytes, SHA-256 `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |
| `docs/skill-templates/ri-evidence-handoff/SKILL.md` | `70ff680d4c2a1eef68905b6e1fe136061f998fe2` | 1321 | `701216b4fb1ce949078d38fa62f7022168b0b816d340e7c97fde19f7565719ce` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/ri-evidence-handoff/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Pinned optional source resource; not adopted or copied |
| `docs/skill-templates/ri-work-kickoff/SKILL.md` | `545db0cdaf99ea6fa07b0f506ea628eb23a19291` | 1523 | `0941127280d8e38bbb37b8d3437b54b212498e17a91b908beb19778a8257a1be` | Installed at `.agents/skills/ri-work-kickoff/SKILL.md`; exact selected bytes; 1523 bytes, SHA-256 `0941127280d8e38bbb37b8d3437b54b212498e17a91b908beb19778a8257a1be` |
| `docs/skill-templates/ri-work-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` | Installed at `.agents/skills/ri-work-kickoff/references/project-procedure.md`; exact selected bytes; 1118 bytes, SHA-256 `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |

Local Git blob identities cover actual installed bytes, including the explicitly declared relocations.

| Local installed path | Local Git blob | Bytes | Local SHA-256 |
| --- | --- | ---: | --- |
| `engineering/workflow/shared/start-an-issue.md` | `1f44ab796d55826f4eaa87dc10188d244fd3c7b6` | 30240 | `4cdbc4ef8b881040516da836135af395a2a312ea1be4c3a9d72420eaf9d9bade` |
| `engineering/workflow/shared/worker-instructions.md` | `c98c32eeb90c15b6aab34dc90602ad37adfcd5a1` | 14791 | `52860da27cb05d5411d1b12f36d20846aa0fecaab7bb2860e836d9c41fb0bf7d` |
| `engineering/workflow/shared/capsule-controller-workflow.md` | `ce7f0e7d261b44de9575255e5eff77edc6c78bc7` | 14954 | `88df7ce7c7f568eb9cf1470390675fbadc7d093857d107390f8212799c1b21d6` |
| `engineering/workflow/shared/new-project-setup.md` | `0fdb5b5326a6638c21373419bf5b9c97d3bfab43` | 15251 | `9f2dea919b4230e6d144304968361e41baf232aeb4755506ec0210018d70d7e7` |
| `engineering/workflow/shared/skill-templates/README.md` | `67d84508ff78273d12e9d005825928f4d9a36535` | 9019 | `ec9b75b80e29f9ad9217cb38adea6169eb895b7e517a29ee3169462da5b5e508` |
| `.agents/skills/ri-work-kickoff/SKILL.md` | `545db0cdaf99ea6fa07b0f506ea628eb23a19291` | 1523 | `0941127280d8e38bbb37b8d3437b54b212498e17a91b908beb19778a8257a1be` |
| `.agents/skills/ri-work-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |
| `.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md` | `5abe72319146eed679ee4876e152831af041a31f` | 1640 | `01d7933a5811c1d8341afe41dbe52556105bb4c338b8ba5cb2575c3859d5d31a` |
| `.agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |
| `engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md` | `5931012fc612cb58efdd5052e7e0402a63c569b5` | 2029 | `713b58752dedbd15be0b6b796dd095b5288b0ec4ad75e858d260bb54ab99b4fc` |

Both complete kickoff folders are installed at `.agents/skills/ri-work-kickoff/` and `.agents/skills/ri-codex-dispatcher-kickoff/`; all four installed files match the selected revision 841d575 resources byte-for-byte. Both SKILL files change to the inspected target; both references remain unchanged exact copies. This proves file contents only: Work import/selection remains unverified absent actual host evidence, and document-based kickoff remains supported.

The optional templates and queue redirect pin this exact target. No optional helper is installed, imported or newly qualified. The [local map](../../../docs/local_project_map.md) selects Nutrition permissions, native Work launch policy and existing actor/model defaults. Owner grants and measured telemetry remain distinct from source contents and policy acceptance.

The compatible producer is separately pinned in
`engineering/tooling/ri-lock.json` at
`20a5039e7731eaa1303443b782caa81a383a0af1`, navigation 7, inventory 16,
adapter 13, mapping v13. The authenticated committed archive SHA-256 is
`dbe424d6fa816c7ab96ab849800fd6f3a8c959f05786edfe706b1d8bba7db54d`; the lock
records all 21 installed source-file hashes and the exact public wheel closure.
Instruction, producer and dependency identities remain separate provenance.
