# Nutrition local project map

Use the complete [shared procedure](../engineering/workflow/shared/capsule-controller-workflow.md), RI commit
`7f096e430d5a436550d0c783c3da9e4051a77b9d`, with its
[byte identity](../engineering/workflow/shared/SOURCE.md), SHA-256
`5623e53ef9bc72978b5d78e646966238dae72b55684bf2a51a722b6d00736339`, 9024 bytes.
This is the sole authoritative local routing map at the owner-required standard path
`docs/local_project_map.md`. The location and six-stage routing below are local adaptations; the published shared
procedure remains unchanged. Its source commit and digest record provenance, not a
mandatory cryptographic receipt chain. This owner-authorized replacement is the sole normal RI route.
It supersedes the 2026-09-27 attached RI default; historical stops are preserved.
RI supplies ordinary exact-source navigation, never approval. The [review route](engineering/REVIEW_RUNTIME_SELECTION.md) is an ordinary native subagent.
Read [AGENTS](../AGENTS.md)
for domain/security standards and [AUTHORITY](../engineering/workflow/AUTHORITY.md) for protected Git acceptance.

## Local route

| Stage / actor | Literal interface and inputs | Output / permission / completion |
| --- | --- | --- |
| Orient / controller | Read issue, current checkout, owner authorization, this map and shared instructions; use `./scripts/ri query` when useful | Identify objective, exact base/branch, permitted actions and relevant project checks; preserve dirty work and paused states |
| Capsule / planner | One native subagent; [Markdown task template](../engineering/tasks/TEMPLATE.md), issue and relevant source/diff | Bounded Markdown task/capsule under `engineering/tasks/`, branch/base, scope, criteria, checks and gaps; native terminal return; no integration permission |
| Implement / implementor | One native subagent with task, shared instructions, AGENTS and permitted checkout | In-scope edits, source/diff and real command results, exact candidate/path list and limitations; native terminal return; no settings or issue authority |
| Independent review / reviewer | Fresh different native subagent, exact candidate and complete diff, task, AGENTS and retained command results | Read-only verdict covering every criterion and applicable standards; native terminal return; no custom gateway, signed receipt chain or fixed review timeout |
| Authorized integration / controller | Reviewed candidate, owner authorization and the actually supported Nutrition integration route | Integrate only within live repository protections and project-required checks; no implied bypass or settings permission; retain exact resulting source identity |
| Verify closeout / controller | Installed result, current links/entrypoints, actual project check results and authorized issue actions | Verify installed behavior and remaining obligations, record limitations, retain useful evidence, and close/clean only when authorized and safe; no product resumption from this maintenance |

Native assignment uses `collaboration.spawn_agent`; each role returns its terminal handoff
through native final completion to the controller. Native roles use the user/default configured model and effort settings. This map selects
no forced SDK model, account route or model service. Record actual settings when relevant.
One assignment runs at a time. RI requires no multiple human operators, cryptographic
receipts or custom gateways. Ordinary Markdown records, source/diffs and command logs
are sufficient. Deliver the complete shared file, this map, task and
standards to each role and confirm it can actually read them. Use native completion;
a supported bounded blocking wait is optional. For an external qualification/CI job without
native completion, use the supported terminal queue/callback route bound to its job and
evidence identity; its delivery wakes the controller for authentication and consumption.
Do not poll unchanged jobs. Deadlines follow task size and actual host limits; there is no inherited RI review timeout.

For failures, hold dependent edits/integration, inspect the bounded actionable error,
then correct in scope and rerun affected checks/review. On cancellation, stop the active
assignment, preserve its terminal return and changed bytes, then clean only its disposable
resources. Sticky stops remain attached to the original attempt; success elsewhere cannot
clear them. After compaction reread the shared bytes, map, task and live state before action.

Only the controller may perform explicitly owner-authorized issue transitions, integration
and safe merged-branch cleanup. Native workers do not inherit those permissions.

## Task and checkpoint locations

New portable task records live at `engineering/tasks/TASK-ID.md`, using the
[template](../engineering/tasks/TEMPLATE.md). Record the current task path, branch/base/C,
phase, actors, authority, checks, stops, pending obligations and evidence identities there.
The trusted controller's supported private state is `~/.nutrition-app/task-controller/issue-N.json`,
or the explicitly selected `NUTRITION_TASK_STATE_DIR` / `--state-dir`; authenticate that actual
selection before resuming. Select the active task's portable record and authenticate
its matching controller state/checkpoint; this map does not select a permanent task.
Completed migration [RI-SIMPLIFICATION-072](../engineering/tasks/RI-SIMPLIFICATION-072.md)
retains its preparation snapshot with an explicit verified completion annotation.
Private evidence stays in the selected controller workspace; it is not portable source
or an additional gate, and private diagnostics must not be copied into this repository.

## Checks and boundaries

The lightweight route above does not add an approval service or security workflow.
Nutrition's existing trusted controller (`./scripts/task prepare`, `authorize`, `qualify`,
`verify`, `review`, `integrate`) and [AUTHORITY](../engineering/workflow/AUTHORITY.md)
separately enforce live owner authorization, exact-SHA dedicated-App qualification,
project-selected profiles and protected expected-main integration. They are existing
Nutrition constraints, not RI requirements. This documentation does not retire or weaken
them. The existing path classifier selects the profiles for each exact candidate; historical
profile results never transfer to changed source.

The lightweight adoption was installed at
`9b7022943ae26269bd8b53903f0d00eb048895f4`, after exact backend + repository
qualification through dedicated App4708441 and fresh independent review. Installed
entrypoints, links, standard CLI preparation and the pinned RI launcher were verified;
#257 is completed. The prior bootstrap `2f1dd7fe120491d76059c1ab1a5fc42044c3508e`
passed backend + repository + iOS-native, with the original repository rule restored.
No protection exception, operator arrangement, custom gateway or infrastructure
prerequisite is part of normal RI adoption.

Authenticated installed completion is retained in the existing controller checkpoint
`adoption-installation/supervision-prerequisite/adoption-continuation053/execution-map.json`
and `normal-adoption-installed-verification/CLOSEOUT.md` in that workspace, alongside
[the public closeout](https://github.com/MitCaine/Nutrition-App/issues/257#issuecomment-5983050352).
Authenticate the selected current checkpoint and live source before action; these
completion records do not authorize a new task. Historical bootstrap failures and
preparation stops retain their original identities and outcomes.

Run focused checks on changed interfaces and the profiles selected by the existing
[trusted qualification](operations/testing.md#trusted-task-controller-bootstrap).
Do not equate skips, RI output, fixture success or automatic push CI with mandatory
candidate qualification. Source changes under review invalidate that candidate's verdict.
Record actual commands, interpreter, source/job/log identities, failures/skips and remaining
obligations in the existing task/controller record. Native subagent evidence is sufficient
for RI; controller review records are explicit decisions, not test-inferred approval.

Use [RI tooling](../engineering/tooling/RI.md): producer `2f28da4d326ff12da5dc9270eb57910303e4a737`,
navigation 6, inventory 13, adapter 10, mapping v10; no silent dependency upgrade.
The [repository standards](../AGENTS.md), [domain invariants](project/invariants.md),
[session contract](operations/session-contract.md) and [testing guide](operations/testing.md)
own normal test commands and required profiles. Unsupported RI coverage requires direct
source/diff inspection.

The actual compatible launcher uses Python 3.14 (installed closeout tested 3.14.8), a verified external
runtime manifest and an exact commit. From the selected repository root:

```bash
NUTRITION_CONTROLLER_PYTHON=/absolute/python3.14 ./scripts/ri query \
  --runtime /absolute/private-tooling/nutrition-ri/manifest.json \
  --repo-root /absolute/candidate --revision EXACT_40_CHARACTER_COMMIT \
  --path scripts/task.py --query qualification --limit 2 \
  --output-dir /absolute/controller-evidence/unique-navigation
```

Readiness must exercise this actual launcher and its nested macOS network-denied sandbox.
The ordinary outer sandbox previously denied the nested launch (exit 71). The tested route
is the platform's explicitly authorized outer execution (`require_escalated`), which leaves
RI's nested network denial intact. Use it only under applicable host/task authority; otherwise
report the denial and hold the dependent command. Generic environment or catalog probes are
insufficient. Retained navigation proofs keep their original C/command/runtime identities;
unchanged setup proof is retained rather than claimed as newly executed or product approval.

#246 and #256 remain paused. Their capsules, branches, C/R/T recovery, historical evidence,
authority decisions, attempts and consumed allowances remain unchanged. Historical attached
transport is not a route for new tasks. [STATES](../engineering/workflow/STATES.md) and [TASK_CAPSULE](../engineering/workflow/TASK_CAPSULE.md)
retain paused-capsule recovery contracts; the [history](../engineering/capsules/HISTORY.md) remains
immutable provenance. No product resumption, acceptance or closure follows this maintenance.
