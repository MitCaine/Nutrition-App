# Shared instruction identity

The Repository Intelligence instruction set for future task intake is selected at
`5749d2b411f0f12e1de6403c2ab9470cc3547b01`. This updates future intake only.
The GH-311 attempt's historical worker-instruction selection is
`686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f`, with local worker-instructions
SHA-256 `7d36722b9a855b7a7483ffd976322bdf8577c7522d27af0c46495b0eb943af81`.
This is attempt provenance and does not assert that the attempt or assignment remains active.
The GH-307 and GH-309 attempts retain their separately recorded
`5ff7f306df6080648e2cc5fbbfc119e55a293754` role/input identities. The completed
GH-305 implementor assignment retains its separate `f6e1064d3f43aee61796f8558a7cef8181426883`
Shared-worker and Implementor input. This adoption repins no active or historical
attempt. Producer/runtime identity is separate and remains pinned below.

The controller supplied a complete 24-file source tree selected from committed
RI revision 5749. Its bytes, Git blob IDs and SHA-256 values are inventoried here.
The root [README](../../../README.md) remains project-owned; upstream README is a
read-only example source. Optional template trees remain unadopted except for the
listed external links and the existing queue redirect.

| RI 5749 source resource | Git blob | Upstream bytes | Upstream SHA-256 | Local disposition |
| --- | --- | ---: | --- | --- |
| `README.md` | `fd892a382d07607847e4b22a2d59f293ef6ad8cf` | 12096 | `9339cb7bed66cad755b769a01161a632b7ff3c302e5b97003d02e4d130a56a78` | Read-only example source; not copied |
| `docs/start-an-issue.md` | `f6cc34784022ecd96c952acae6c8951f9131ebc6` | 29168 | `d7697cddfb20195d2153719362b25233fb61c4c2b9b413af6eb21a275b1f7e8e` | Installed at [local `start-an-issue.md`](start-an-issue.md) exactly; 29168 bytes, same SHA-256 |
| `docs/worker-instructions.md` | `6df8aef19e9540b07804284f6b4d399f8e9d6bfd` | 14315 | `094ac702eaca007e67fcb7a386be5693f2da459b4d30919ef4a51825948c2e0d` | Installed at [local `worker-instructions.md`](worker-instructions.md); only dispatcher locator is relocated to `../../../.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md`; 14323 bytes, SHA-256 `0061961a7b6989411e3546cc80878decdb2465a76b7a23bc429801ec139385ca` |
| `docs/capsule-controller-workflow.md` | `a4847392af036aa57cac3d623597305b983e7d18` | 14776 | `47c828a73a2072b3b52727650dc3f0f1653d5758b19cc624b8f61b0ac86dac71` | Installed at [local `capsule-controller-workflow.md`](capsule-controller-workflow.md) exactly; 14776 bytes, same SHA-256 |
| `docs/new-project-setup.md` | `f38d88206f86ff28f4da0fa242913bacd85903db` | 11346 | `3cb5551e2efdd509ce99d4af07b01bc290b25c6bdcb07a2dc69feb36f1e7d1cb` | Installed at [local `new-project-setup.md`](new-project-setup.md); consumer-guide locator is pinned to revision 5749; 11449 bytes, SHA-256 `a339de0754f2bb00abadb310e049ccbae4c068661d6979d7366d60b645bac564` |
| `docs/consumer-guide.md` | `19cf168338614208b2592c5e0111d223384da3a6` | 10705 | `069cd5607e52b2ef300f4c99d286faf30f4a6200b24a8b5ea0fa015a0e5980b3` | Pinned link from setup guidance; source is not copied |
| `docs/skill-templates/README.md` | `54db08ecb4f44ddb1df7d4aa22988daef1e89f47` | 8251 | `3b119ff01a9e22c090d3f2f27be4acd6ac4da0279ac5a4faf0da32adc54db6b1` | Installed at [local template README](skill-templates/README.md); kickoff links resolve to installed folders and optional links pin 5749; 9019 bytes, SHA-256 `ac1a76801086edd97bae633224726ae51a5d986571d5f8a053b561c2ece77276` |
| `docs/skill-templates/capsule-independent-review/SKILL.md` | `7c0e18ce6d9a5de1331354b899a723379c792a6d` | 2359 | `3d4da861fdfa9eeb90bd22e1731f9a061015ac92b14ec4870bbb188765b7f73e` | Optional template; linked to pinned source, not copied |
| `docs/skill-templates/capsule-independent-review/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Optional reference; not adopted or copied |
| `docs/skill-templates/capsule-preflight/SKILL.md` | `810da881c165ea06f7f748fabb9c2933d4a1b377` | 2458 | `2e6768bde22564f40dbcfd5bf901518aa216d51c23a4a4f5040fd0e33ad69c1a` | Optional template; linked to pinned source, not copied |
| `docs/skill-templates/capsule-preflight/references/evidence-contract.md` | `508b89b141a22ac783166bad559fc65db4b5ca1d` | 15809 | `294e821c038c3cd31c30a4d03515948e5882439e2d52c54594ee29c24211a59f` | Optional reference; linked to pinned source, not copied |
| `docs/skill-templates/capsule-preflight/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Optional reference; not adopted or copied |
| `docs/skill-templates/capsule-preflight/scripts/evidence%5Fpreflight.py` | `03daccc30278c67a7d3505ee10018096690d13b5` | 26640 | `97bf1454d3f98f6502ffc9818c9146e629ecc898ec901442dae7ea86dc684174` | Optional helper; not adopted or copied |
| `docs/skill-templates/capsule-queue/SKILL.md` | `a6c43878adf55b2b148daaa47e4e61bfbd7f66cd` | 8485 | `73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa` | Full instructions remain external through the local [queue redirect](skill-templates/capsule-queue/SKILL.md); local redirect identity is below |
| `docs/skill-templates/capsule-queue/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | External resource linked by the queue redirect |
| `docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py` | `acbaf960cff25c71fd1bdb1488b8e70dc34062b2` | 11872 | `b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de` | External resource linked by the queue redirect; no helper is installed |
| `docs/skill-templates/capsule-scope-review/SKILL.md` | `295253dda1a590f4b6bb303c9afba06e4d3acb41` | 1318 | `12fd1e9ff74a971f9d53dcdb68ac156a4bfbf9ecc31e3ec3f0eeac82695d4799` | Optional template; linked to pinned source, not copied |
| `docs/skill-templates/capsule-scope-review/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Optional reference; not adopted or copied |
| `docs/skill-templates/ri-codex-dispatcher-kickoff/SKILL.md` | `055e1048858c89c0346c810a6a03242fc9ce26b8` | 1502 | `79de7229dfa3bbe12a8c85e89c5020969ebb80f2b5223f1a8d66c366a2d627a8` | Installed at [project dispatcher skill](../../../.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md) exactly; 1502 bytes, same SHA-256 |
| `docs/skill-templates/ri-codex-dispatcher-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` | Installed in the dispatcher folder exactly; 1118 bytes, same SHA-256 |
| `docs/skill-templates/ri-evidence-handoff/SKILL.md` | `70ff680d4c2a1eef68905b6e1fe136061f998fe2` | 1321 | `701216b4fb1ce949078d38fa62f7022168b0b816d340e7c97fde19f7565719ce` | Optional template; linked to pinned source, not copied |
| `docs/skill-templates/ri-evidence-handoff/references/project-procedure.md` | `77fb46c51ff48596634b86765b3df7a4e59761aa` | 1545 | `e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677` | Optional reference; not adopted or copied |
| `docs/skill-templates/ri-work-kickoff/SKILL.md` | `d7891d4825337e6f8f2de979a6b4498978d55114` | 1417 | `22982297019547a3c050a4224c071ba7c419831fe9b2f1f6dd65be15b3444b5f` | Installed at [project Work kickoff skill](../../../.agents/skills/ri-work-kickoff/SKILL.md) exactly; 1417 bytes, same SHA-256 |
| `docs/skill-templates/ri-work-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` | Installed in the Work folder exactly; 1118 bytes, same SHA-256 |

Local installed-file identities use Git's blob hash over the current file bytes,
plus byte count and SHA-256. Exact copies therefore retain the selected blob; rows
with declared relocations have their own local blob identities.

| Local installed path | Local Git blob | Bytes | Local SHA-256 |
| --- | --- | ---: | --- |
| `engineering/workflow/shared/start-an-issue.md` | `f6cc34784022ecd96c952acae6c8951f9131ebc6` | 29168 | `d7697cddfb20195d2153719362b25233fb61c4c2b9b413af6eb21a275b1f7e8e` |
| `engineering/workflow/shared/worker-instructions.md` | `01c7a7ccba8d3d6e6783c7ac21eb6f98f9793040` | 14323 | `0061961a7b6989411e3546cc80878decdb2465a76b7a23bc429801ec139385ca` |
| `engineering/workflow/shared/capsule-controller-workflow.md` | `a4847392af036aa57cac3d623597305b983e7d18` | 14776 | `47c828a73a2072b3b52727650dc3f0f1653d5758b19cc624b8f61b0ac86dac71` |
| `engineering/workflow/shared/new-project-setup.md` | `690aac49d1ec785764bbdca08344886605d086a0` | 11449 | `a339de0754f2bb00abadb310e049ccbae4c068661d6979d7366d60b645bac564` |
| `engineering/workflow/shared/skill-templates/README.md` | `b8108f29b6a41c755cca72b640bba8f00cce265e` | 9019 | `ac1a76801086edd97bae633224726ae51a5d986571d5f8a053b561c2ece77276` |
| `engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md` | `edfec80e013d444c0b7851e00ef8d91cb9743210` | 2029 | `05068dbc4a3150f4fe4f2aeff9d5ff0f8c21bc67c25f4854bb05113d55eb21b8` |
| `.agents/skills/ri-work-kickoff/SKILL.md` | `d7891d4825337e6f8f2de979a6b4498978d55114` | 1417 | `22982297019547a3c050a4224c071ba7c419831fe9b2f1f6dd65be15b3444b5f` |
| `.agents/skills/ri-work-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |
| `.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md` | `055e1048858c89c0346c810a6a03242fc9ce26b8` | 1502 | `79de7229dfa3bbe12a8c85e89c5020969ebb80f2b5223f1a8d66c366a2d627a8` |
| `.agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md` | `c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d` | 1118 | `05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11` |

The complete two-file kickoff folders are installed at
`.agents/skills/ri-work-kickoff/` and
`.agents/skills/ri-codex-dispatcher-kickoff/`. All four installed files match the
selected revision 5749 resources byte-for-byte. The dispatcher SKILL and both
references remain unchanged from the prior installed files. This proves installed
file contents only. Work import/selection remains unverified without actual host
evidence; document-based kickoff remains supported.

The optional template links in [the template entrypoint](skill-templates/README.md)
pin these RI 5749 resources because their trees are not copied. The queue redirect
links the full selected upstream skill, its project-procedure reference and its
helper; the helper is not installed, imported or newly qualified here. The local
[map](../../../docs/local_project_map.md) supplies Nutrition actors, settings,
confirmation policy and permission boundaries.

The compatible producer is separately pinned in
`engineering/tooling/ri-lock.json` at
`20a5039e7731eaa1303443b782caa81a383a0af1`, navigation 7, inventory 16,
adapter 13, mapping v13. The authenticated committed archive SHA-256 is
`dbe424d6fa816c7ab96ab849800fd6f3a8c959f05786edfe706b1d8bba7db54d`; the lock
records all 21 installed source-file hashes and the exact public wheel closure.
Instruction, producer and dependency identities remain separate provenance.
