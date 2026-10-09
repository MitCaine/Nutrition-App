# Set up RI in a project

Use the [controller workflow](capsule-controller-workflow.md) for RI-assisted
capsule work, or the [consumer guide](https://github.com/MitCaine/repository-intelligence/blob/7d4c1bdeb70b53aa4555cfae7b4a6d9dbf2547a8/docs/consumer-guide.md) for ordinary navigation.
RI does not require an execution framework or every optional skill to be installed.

## Minimal setup

1. Select a compatible RI source/wheel and interpreter. Run the project's actual
   compatibility probe, or a representative RI query/comparison using that runtime.
   Retain a working compatible version rather than silently changing its schema.
2. Keep one short map at project-root `docs/local_project_map.md`; link it from
   the project README/AGENTS entrypoint. Record shared instruction
   commit/byte identity, runtime/source and contract, role permissions, standards,
   required tests, permitted Git/issue actions and completion route.
3. Supply each worker its [selected worker instructions](worker-instructions.md#role-index), complete task
   inputs and applicable project requirements under the [role-specific reading boundaries](worker-instructions.md#shared-worker-rules)
   through the supported local handoff.
   Bind role-resource locations/identities to the selected RI revision; workers
   do not repeat controller orientation.
   Install only useful [skills](skill-templates/README.md), comparing complete folders
   and preserving intentional adaptations. Instruction copies are not Work registration.
4. Confirm actual source access, relevant command availability and independent
   review. Rehearse known sandbox-sensitive commands narrowly; RI does not require
   a custom gateway, signed report or full adoption specimen chain.
5. Use native completion for native agents. For external jobs use a supported
   bounded wait, or the optional queue helper only when its destination works.
   Select task-appropriate deadlines rather than inheriting a five-minute cap.

Keep one working subagent at a time. Close completed agents where supported after
retaining results. If capacity cannot be released and fresh creation fails, the
workflow permits last-resort idle-agent reuse with reauthenticated context;
review remains independent of the candidate's author/implementor.

Task records must include the controller guide's [completion requirements](capsule-controller-workflow.md#required-task-completion),
including affected documentation, criterion-specific evidence and verified closeout.
Use the existing record; no extra mandatory artifact is needed.

Once setup is adopted, direct new issue controllers to [Start an issue](start-an-issue.md)
and `docs/local_project_map.md`. Do not repeat adoption or installation for each task.

## Kickoff inputs and selected configuration

Use the optional `ri-work-kickoff` or `ri-codex-dispatcher-kickoff` skill, or give
the same inputs directly with the selected document locations. Skills locate the
existing workflow; they add no stage and do not grant task authority.

For Work, supply **Repository** and **Issue(s)**: one issue, an explicit list or
an inclusive numerical range. Optional fields are **Capsule builder**,
**Independent reviewer**, **Implementor** (model/effort), **Controller selection**
(owner-confirmed existing selection), **Codex dispatcher**, task-specific
**Authority** (owner-supplied grant or selection of an applicable recorded grant),
**Constraints**, **Stopping conditions** and **Requested route**
(normal or maintenance), plus **Implementation execution** (`direct Work controller`
when permitted by the map). A maintenance request follows the controller
[eligibility decision](start-an-issue.md#optional-maintenance-route), not an automatic
waiver of project controls. Dependency/runtime or instruction changes alone do
not require a capsule; use the linked eligibility rule. Resolve concrete chat IDs
through the supported route; a display title is not an authenticated destination.
For a dispatcher, only **Repository** is initially required. **Work controller**
may be supplied or established by an authorized handoff; until then orient and
wait without inventing a destination. Its implementor selection comes solely
from that handoff, not a second dispatcher-side configuration.

The project's selected configuration owns defaults. Adopt this initial
configuration in the project map or its existing configuration record; these are
setup values, not runtime observations or a competing daily-procedure table:

| Role | Environment | Initial model / effort | Selector label |
| --- | --- | --- | --- |
| Controller | Work | `gpt-6.1-sol / low` | Sol 6.1 Light |
| Capsule builder | Work | `gpt-6.1-sol / low` | Sol 6.1 Light |
| Independent reviewer | Work | `gpt-6.1-sol / low` | Sol 6.1 Light |
| Implementor | Codex | `gpt-6-luna / max` | Luna 6 Max |

Accept full IDs and explicit efforts, or these unambiguous labels. Explicit owner
kickoff values select run-specific overrides within applicable permissions;
omitted worker values use the selected project defaults. If a default is missing,
resolve it rather than silently selecting upstream values. Kickoff cannot switch
the controller or dispatcher's already-running model. Resolve configuration once
per assignment and retain it in the existing checkpoint and handoffs.

Explicit owner invocation of the Work/Codex kickoff skill confirms the named
product selection for that chat, not its model or provider-effective telemetry.
Automatic loading or incidental mention supplies no confirmation. Distinguish
requested settings, owner-confirmed selection, host-confirmed settings and
unavailable telemetry under the project's
[accepted confirmation policy](start-an-issue.md#execution-routing-models-and-efforts).
Do not invent omitted controller telemetry, waive required confirmation, infer a
conflicting mode from tools/metadata or establish a model fallback. Each chat or
worker is assessed under its accepted launch/confirmation policy; a controller's
owner-confirmed selection does not measure a worker's runtime settings.
Do not ask the owner to reconfirm unchanged accepted selections.

### Access and task authority

Connector availability and task authority are separate. Include `@GitHub` in
kickoff where that host supports the connector selector; otherwise use the
project's permitted GitHub route. No particular connector is required, and access
does not authorize publication, integration or settings changes.

The optional **Authority** field may supply this reusable owner grant, or explicitly
select an applicable recorded grant by location/identity:

> For the named issue(s), I authorize publication of the required task
> authorization records, task branches and in-scope candidates; required
> qualification dispatches; integration after independent review and controller
> approval; issue closure; and safe cleanup of owned task refs through the
> project's protected procedures. This includes repository policy changes
> expressly within the issue scope, but not additional host/account/security
> permissions, unrelated scope or resuming paused work.

Explicit owner invocation must supply or select the grant; merely loading a skill
cannot manufacture it. Authenticate applicability and reuse the recorded grant
without asking again for each routine step. Without a covering grant, hold the
uncovered action and request only that authority. The grant does not bypass host
denials or project protections. Bidirectional chat messaging requires its own
bounded owner permission; publication authority is not disclosure authority.

### Accepted worker-launch routes

Project configuration names accepted launch routes separately from measured
runtime confirmation. Projects may adopt this policy:

> For an owner-confirmed Work controller, native `collaboration.spawn_agent` is
> an accepted route for Work builders and reviewers, with the configured model
> and effort explicitly requested. Missing environment-selector fields or
> effective telemetry remain unverified and do not block an otherwise accepted
> launch. Escalate actual launch failure, contradictory accepted evidence or a
> genuinely missing required capability.

Policy acceptance does not claim measured Work execution or effective model/effort.
Record what was requested, what is confirmed and what remains unverified. Do not
infer a conflicting mode from tool names. A missing instruction resource is a
reading prerequisite, not evidence that a launch route is unavailable. A real
launch failure follows bounded failure/capacity recovery as applicable, without
silent substitution or duplicate dispatch. Preserve fresh contexts and nonauthor
review. This policy takes effect only when selected by the consumer project.

### Chat source orientation

Apply [existing intake](start-an-issue.md#intake) to each chat's repository path,
HEAD and selected instructions separately; one chat's source does not establish
another's. Preserve parked branches. An unrelated checkout's failures do not
establish that the selected task commands are blocked. Check readiness in the
assigned task worktree/source without moving or overwriting a parked branch.
A dispatcher authenticates
only its assigned handoff/source within its reading scope, not original issue
requirements. Reconcile existing assignments before dispatch: absence of an issue
assignee or default checkpoint alone is not proof there is no active task. Use the
project's authoritative assignment/recovery locations; no new tracking system.

### Issue queues

Process ranges in numerical order; preserve explicit list order. Skip only issues
already closed or explicitly deferred under owner/project authority, without
reopening or closing them. Difficulty, age and transient failure are not deferral.
Complete the current issue before advancing; each new issue uses a fresh controller
through a supported, authorized handoff. Queue scope does not authorize indefinite
controller reuse. Keep recurring coordination limited to assignment, verified
closeout and advancement in existing operational records; no scheduler is needed.
If fresh-controller continuation is unavailable, report it. If an eligible issue
cannot proceed within existing authority, report the blocker and pause rather
than silently skip it or expand scope. At queue exhaustion or a stopping condition,
report completed, closed-skipped, deferred-skipped and unresolved items accurately.
Skill invocation does not grant Git, merge, settings or cross-chat disclosure
permissions; apply actual owner grants and project policy.

### Brief invocation examples

Use these only in the products actually selected by the owner. Installed skills
must be available through that host's supported selector; otherwise use direct
instructions with the same input contract.

```text
@ri-work-kickoff
Repository: MitCaine/poker-app
Issue(s): #447–#458, skipping closed or explicitly deferred issues
Controller selection: Work; gpt-6.1-sol / low, owner-confirmed
Authority: I select the reusable task grant for these issues.
Codex dispatcher: <concrete chat ID or supported reference>
```

```text
$ri-codex-dispatcher-kickoff
Repository: MitCaine/poker-app
Work controller: [designated chat, if already available]
```

The implementor uses the project's adopted initial selection through the
controller's resolved handoff. Additional fields are needed only when defaults
or existing authority do not cover the assignment. Direct document-based kickoff
remains supported: supply the same fields and actual product/controller selection
statement, then read the selected procedure through `docs/local_project_map.md`.
A direct statement is owner confirmation, not runtime telemetry.

## Recovery and resume

Record current phase, branch/source, task, criteria, tests, active job, results,
pending blockers and next authorized action in the existing checkpoint. Preserve
these and the selected instructions across compaction; authenticate live state
before resuming. No parallel mandatory state store is needed.

Routine coordination, factual clarification, diagnosis and permitted in-scope
correction are included in task authority. Hold execution at a blocker and make
one bounded read-only sweep before replanning. A terminal stop remains terminal;
a diagnostic-only follow-up can explain it without resuming that execution.
Ask only for an actually uncovered scope/permission/disclosure or reserved action.

## Replace an existing RI integration

Follow the controller guide's [replacement route](capsule-controller-workflow.md#replace-an-entangled-adoption).
Preserve product work and historical evidence. Remove duplicate procedure and
RI-only machinery, repair references and tests, and retain independently needed
project controls. Use focused verification and one independent review, then
owner-authorized integration. Retire obsolete prerequisite issues only after the
replacement eliminates their need; do not declare their failed attempts successful.

Changing the docs does not itself qualify a host or migrate a project's installed
instructions. Record the adopted source/bytes and verify the actual replacement.

## Standard project map

Use `docs/local_project_map.md` in every consumer project. Keep it short:

- Selected RI execution instructions: source commit/bytes and usable location.
- Compatible RI runtime/source and its invocation, plus selected role environments,
  models/efforts and permitted overrides from the
  [initial configuration](#kickoff-inputs-and-selected-configuration).
- Accepted worker-launch routes, including any adopted
  [native Work policy](#accepted-worker-launch-routes), plus confirmation for
  required environment/model/effort settings and the
  authorized disposition when confirmation is unavailable, as defined in the
  [shared reporting rule](start-an-issue.md#execution-routing-models-and-efforts).
- Shared capsule instructions: the capsule-format section of the selected RI
  daily procedure, plus the project's task-file storage location and necessary
  additional fields. If adopting the optional maintenance route, use that existing
  task record for its brief handoff and resolve capsule-only local validators
  explicitly. Record whether direct Work controller implementation is permitted;
  reconcile any local enforcement before using that exception. Do not maintain
  a competing local format.
- Project standards and required test commands or their authoritative locations;
  use focused selection-section links rather than unrelated historical reading.
- Role permissions, including the branch-creation actor and any explicit builder
  grant, candidate capture/publication and integration/issue actions.
- Supported completion route and existing active-task/checkpoint location.

Reference project-owned requirements rather than copying their text. This map
holds local bindings, not a second shared workflow. During migration, reconcile
an existing map into this file, repair incoming links, and leave old map locations
as pointers where needed; do not keep two authoritative maps. Preserve active
frozen task identities and historical records. Do not repin an active attempt
silently or infer authority from the map's mere presence.
