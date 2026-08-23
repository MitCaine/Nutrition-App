# Active task capsules

Store full schema-v1 capsules here from `DRAFT` through `REVIEWED`. A capsule remains active while
blocked, under bounded correction, awaiting verification or review, or awaiting integration.

Terminal closeout writes the durable terminal result to `../HISTORY.md` and removes the full active
capsule in the same closeout change. Do not create or retain a per-task completed-capsule archive,
and never reuse an ID already recorded in history.

Do not store generated logs, review ZIPs, credentials, dependency trees, or agent scratch files
here.
