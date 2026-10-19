# Workflow role skills and optional helpers

Controllers use [Start an issue](../start-an-issue.md); workers use their
[selected worker instructions](../worker-instructions.md#role-index).
The four role skills below are authoritative worker procedures at the selected
RI revision. Installation is optional: a supported handoff can supply their exact
resources directly. Read the complete assigned skill, its locator and the bounded
Shared worker rules; do not also load obsolete role procedures. Other skills are
optional helpers, not new packet/export/protected-launcher gates.

Kickoff fields and queue/configuration rules have one owner in
[new-project setup](../new-project-setup.md#kickoff-inputs-and-selected-configuration).
The kickoff skills are locators, not copies of the controller/dispatcher workflow.

These resources support the [controller workflow](../capsule-controller-workflow.md).
Selected role skills own shared role duties; the project map supplies commands,
accepted review lanes, supported hosts and authority. Optional helper templates
remain examples to select against that contract, not RI package behavior or new
permission policy. Read each selected `SKILL.md`, resolve contradictions before
dispatch, and distinguish shared instructions from independently required local
controls rather than silently selecting a conflicting procedure.
Start with the [new-project setup checklist](../new-project-setup.md) when
adopting the workflow in a consumer repository.
Follow the [daily publication sequence](../start-an-issue.md#execute-serially):
the controller creates and publishes the task branch; the authorized actor publishes
the planning capsule before implementation on the normal capsule route and the exact
candidate before review. The adopted [maintenance route](../start-an-issue.md#optional-maintenance-route)
instead uses a brief controller handoff without planning-only publication.
The [experimental route](../start-an-issue.md#experimental-engineering-route) instead
uses controller engineering, independent planning review and selected assignments
where explicitly adopted; the same reviewer skill has separate review modes.
The project map assigns actors, tracked task storage and commands; implementor
commit/push requires an explicit grant. Keep private operational records out of
publication unless authorized. Keep planning, implementation and fresh review
roles separate; no subagent publishes directly to main.

| Template | Role | Copy when |
| --- | --- | --- |
| [ri-capsule-creator](../../../../.agents/skills/ri-capsule-creator/SKILL.md) | Capsule creator | Normal planning: complete original inputs and source evidence. |
| [ri-implementor](../../../../.agents/skills/ri-implementor/SKILL.md) | Implementation actor | Accepted capsule, selected maintenance handoff or approved engineering assignment. |
| [ri-independent-reviewer](../../../../.agents/skills/ri-independent-reviewer/SKILL.md) | Fresh independent reviewer | Assigned plan or implementation review mode, originals and actual proof; only assigned checks may execute. |
| [ri-dispatcher](../../../../.agents/skills/ri-dispatcher/SKILL.md) | Codex relay | One controller-authorized implementation assignment. |
| [ri-work-kickoff](../../../../.agents/skills/ri-work-kickoff/SKILL.md) | Owner-selected Work controller | Explicit owner kickoff for an issue or bounded queue through adopted project instructions. |
| [ri-codex-dispatcher-kickoff](../../../../.agents/skills/ri-codex-dispatcher-kickoff/SKILL.md) | Owner-designated Codex dispatcher | Bounded orientation and waiting for a controller implementation handoff. |
| [capsule-preflight](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-preflight/SKILL.md) | Controller, capsule builder, or implementor | The project has an active capsule workflow with exact base/scope checks. |
| [capsule-scope-review](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-scope-review/SKILL.md) | Fresh read-only scope challenger | The impact inventory needs independent challenge before implementation authorization. |
| [ri-evidence-handoff](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/ri-evidence-handoff/SKILL.md) | Controller, implementor, or reviewer | RI locations or comparisons will enter a handoff. |
| [capsule-independent-review](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-independent-review/SKILL.md) | Fresh inspection-only reviewer | The selected candidate-bound review route permits inspection-only review using controller-supplied evidence; this skill does not execute tests. |
| [capsule-queue](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-queue/SKILL.md) | External gate watcher | A long non-subagent job has no native completion and its exact Codex controller destination is verified. Use a tested Work bridge or bounded wait for a Work controller. Native subagent handoffs use their completion events. |

For a project-scoped Codex installation, copy the chosen **whole skill folders**
to that project's `.agents/skills/` (or the skill location supported by its
actual Codex installation). Every folder includes `references/project-procedure.md`, which resolves the
caller’s selected role instructions through its handoff and the project map. The queue folder
also includes its required helper script. For personal local Codex use, install under the local Codex skills
directory instead. After copying, check every relative resource link in the installed folder, then
from the consuming workspace resolve the selected role resource through the
existing handoff/map and verify its recorded identity. Workers read the whole selected role skill, its locator, bounded Shared worker
rules and role/task inputs; the controller reads the full procedure. Template-tree validation alone does not prove
installed-layout validity. Validate each copied folder with the available skill
validator and try one realistic, non-destructive invocation before relying on
it. Do not replace an existing project skill without comparing its instructions.
Record the RI commit and template path used for each copied skill in the
consumer's existing maintenance notes, along with local adaptations. On a
later RI update, compare the installed folder with that recorded template
revision and the new template before editing it. A plain `diff -ru` or Git
comparison is enough; do not automatically overwrite a consumer's authority
rules or change skills during an active attempt. From the actual consuming
workspace, verify that a fresh agent discovers the intended instructions and
selects the intended skill for a representative request.

ChatGPT Work has a separate skill lifecycle; copying files into a Mac checkout
does not make them available in a Work chat. Give the conditional scope challenger, controller, capsule builder,
implementor, and reviewer their applicable instructions through the supported
workspace route, then verify availability. Native subagents return to their parent; mixed Work/Codex routing uses the
[selected dispatcher handoff](../start-an-issue.md#work-to-codex-implementation-handoff). Use the queue template for a long external gate that
lacks native completion and has a verified destination; it is unnecessary for
these subagents.

The preflight folder includes a read-only [evidence checker and adapter contract](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-preflight/references/evidence-contract.md).
Its [closeout checks](https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/skill-templates/capsule-preflight/references/evidence-contract.md#closeout-and-installed-workflow-probes)
cover consumer-exported history metadata and required installed-workflow probes.
Copy its supporting resources with the skill and connect it to the consumer's
trusted records before treating it as a blocking gate. The scope-review skill
handles purpose and missing dependencies that deterministic checks cannot infer.

Measure complete required reading per role, including always-loaded skill text,
the locator, Shared worker rules, project constraints and unconditional references.
Conditional references count when applicable. A smaller entry file alone proves
no reduction or reliability gain. Compare unchanged tasks, source, tools, settings
and authority; report observed omissions/proof preconditions/artifact survival,
premature readiness, corrections, usage/context and unmeasured data separately.
Start with a bounded creator presentation pilot before actual remaining-role
handoffs, distinguish format effects from grouping effects, and label held-out or
compaction exercises by what actually ran. Do not restart active experiments.

Keep the templates narrow. A project need not install every template, and no skill
creates capsule authority, review independence, or a successful qualification
merely by being present.

## Mechanical validation boundary

The offline checker supports inline and reference links, same-page fragments
and visible inline-code words in heading anchors. RI template frontmatter uses
a deliberately narrow YAML subset: exactly one top-level `name` and
`description`, each a nonempty single-line plain or quoted string. Complex YAML,
extra/nested fields, duplicate keys and ambiguous scalars are rejected; double
quoted strings use JSON-compatible escapes. This subset is not a general YAML
parser or validation of arbitrary installed skills. Linked helpers must exist.
Installation trials still check actual copied resources and skill behavior.

## Kickoff availability and adoption

Use the host's supported installation/skill selection interface and verify each
name is discoverable before claiming availability. See the
[official skill-loading guidance](https://learn.chatgpt.com/docs/build-skills).
Codex folder installation and copied-layout checks do not prove Work registration
or live invocation. Work installation needs its own supported import/registration;
if no such interface is available, report that remaining step and use direct
document-based kickoff. Do not build a new plugin or service merely to bridge it.
Keep the installed source commit/path and declared local relocations in the existing
maintenance record. After RI publication, consumers explicitly adopt the selected
controller/worker/setup resources, update identities and configuration defaults,
resolve the kickoff locators through their map, and check their supported host
availability. Do not repin an active attempt or change runtime merely for kickoff.
