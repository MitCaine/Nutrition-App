# Execution permissions and recovery

Use [local project map](../../docs/local_project_map.md). The controller uses its complete shared
procedure; implementors and reviewers use Shared worker rules and their assigned unique level-two
section of the pinned [worker instructions](shared/worker-instructions.md#role-index), read through
the next level-two heading or end of file. The implementor works in the bounded checkout;
independent review uses a different read-only subagent. Ordinary source, Git diff and real logs are
the handoff. `task execution` and its
frozen local launcher are retired from current dispatch. No RI-only sandbox, serialized
planning packet, launch budget or model gateway is a prerequisite for this route.

## Automation eligibility

Automate only steps with stable input and result schemas, mechanically detectable success,
failure and stop conditions, idempotent or recoverable reruns, and inspectable evidence.
The step must first be manually exercised, and its maintenance cost must be lower than
repeated manual work. Every automation begins `EXPERIMENTAL`. Automation must not silently
make product-policy or irreversible decisions; the [owner authority](AUTHORITY.md#automation-authority)
for those decisions remains explicit.

## Checkpoints and recovery

Record branch/base, source identity, actor, phase, actual command/tool/host, outputs and
remaining obligations in the existing task/controller record. Native completion is the
terminal route. Stop dependent work on an authenticated stop; bounded cancellation,
cleanup and evidence preservation may continue. Do not clear old stops, replay consumed
attempts, or infer success from later unrelated work. Lost integration replies require
live-state reconciliation before another operation.

Preserve real host denials and mandatory product checks. A task-appropriate finite deadline
may be selected where the host requires one; there is no inherited 300-second RI cap.
A corrected launcher must be rehearsed in its actual environment when the changed interface
requires it; ordinary unrelated native reruns are not RI requirements.

Historical paused capsule execution/checkpoint contracts and receipts remain recoverable
from Git baseline `8a358139194d42004fbff289a51a1601b7715788` and retained private evidence.
They are neither a current dispatch route nor grants to resume #246/#256.
