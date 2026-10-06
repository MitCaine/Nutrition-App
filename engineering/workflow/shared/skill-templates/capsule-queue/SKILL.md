# Conditional capsule queue redirect

Read the complete [pinned upstream queue skill](https://github.com/MitCaine/repository-intelligence/blob/6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0/docs/skill-templates/capsule-queue/SKILL.md)
only for an external job without reliable native completion. Its required resources are
the [project procedure locator](https://github.com/MitCaine/repository-intelligence/blob/6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0/docs/skill-templates/capsule-queue/references/project-procedure.md#waiting-and-recovery)
and [queue helper](https://github.com/MitCaine/repository-intelligence/blob/6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0/docs/skill-templates/capsule-queue/scripts/run%5Fand%5Fqueue.py).
All are selected from RI commit `6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0`.

The helper URL uses percent-encoded underscores so repository executable discovery
does not mistake that external resource for a locally installed script.
This is a resource redirect, not an installed executable skill. No helper is imported
or newly qualified here. Follow the [Nutrition map](../../../../../docs/local_project_map.md)
and complete [daily waiting rules](../../start-an-issue.md#wait-recover-and-resume).
Use a supported observer and verified delivery to the exact controller; CLI acceptance
alone is not consumption or idle wake-up. Otherwise retain event-based blocking waits.
Do not restart a completed job to attach a watcher or infer approval from notification.
