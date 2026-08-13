# E2-16 qualification closure and evidence

> **Document role:** Retained closure record for the bounded E2-16 work. This is evidence and
> scope history, not authorization for E2-17 or E2-18.

## Authority and boundary

Epic 2 preserves one application-data authority for each running context: the explicitly selected
local SQLite runtime **or** the remote FastAPI/PostgreSQL runtime, never both. There is no
synchronization, fallback, dual write, background sync, cloud backup, or authority mixing. The
control database remains an operational-evidence authority only; it is not a second application
backend. See the [Architecture Overview](../../../architecture/overview.md) and the
[Explicit mobile application-data authority decision](../../../architecture/decisions.md#explicit-mobile-application-data-authority).

Only SQLite schema version 1 exists in the mobile runtime. E2-16 did not add a second schema
stream, a production reset path, or a recovery queue. The temporary native qualification route,
isolated E2-16 database identity, checkpoint/direct-integrity helpers, failure fixtures, and
harness-only tests are removed by E2-16J. Production migration validation, local-authority
runtime seams, mutation callbacks, Daily Log recovery/status, OCR confirmation/parser/provenance,
runtime-hook protections, Apple Vision diagnostics, and E2-15 transfer qualification remain.

## Issue status

| Issue | Stage | Actual state at closure |
| --- | --- | --- |
| #66 | E2-16A — qualification foundation | Completed as temporary development-only infrastructure. Its isolated identity, guarded reset, host markers, and direct-integrity helpers are not retained in application/test source after E2-16J. |
| #67 | E2-16B — native SQLite lifecycle | Completed for the approved iOS lifecycle qualification scope; production `nutrition.db` and migration behavior remain ordinary startup behavior. No Android native run is claimed. |
| #68 | E2-16C — migration failure and fail-closed lifecycle | Completed in the bounded qualification work. Production migration rollback, future-version rejection, and fail-closed behavior remain covered by permanent tests. |
| #69 | E2-16D — mutation termination and restart reconciliation | Implemented as a temporary iOS harness with real transaction barriers and restart checkpoints. The harness is removed; no additional native run is claimed here. Daily Log journal/status reconciliation and other families' authoritative reread/idempotency behavior remain production behavior. |
| #70 | E2-16E — filesystem and full-database failure without reset | Implemented as a temporary isolated iOS harness using a bounded disposable database and `SQLITE_FULL`; the harness and filler/deletion helpers are removed. No host/device storage exhaustion was attempted. |
| #71 | E2-16F — feature durability and restart evidence | Automated semantic/lifecycle work was completed. Native evidence is split: an owner-observed Food create/update restart sequence exists, but the complete six-family native matrix did not complete, so no full native Stage-F pass is claimed. |
| #72 | E2-16G — manual VoiceOver qualification | Not planned for this personal project. Manual VoiceOver evidence is removed scope; automated accessibility contracts remain where permanent tests cover them. |
| #73 | E2-16H — manual TalkBack/Android qualification | Not planned for this personal project. Android native and manual TalkBack evidence are removed scope. |
| #74 | E2-16I — iOS OCR physical-device evidence | Accepted bounded evidence/limitations were recorded. The temporary qualifier's known false negative is retained as a limitation, not as restored OCR provenance; no new physical-device run is claimed by this cleanup. |
| #75 | E2-16J — bounded cleanup and documentation consolidation | Completed by this change: the temporary route, identity/configuration overrides, E2-16 source directory, and two harness-only test files are removed; this closure record and bounded documentation corrections are retained. |

## #62 acceptance coverage map

The following map assigns each acceptance criterion in the active E2-16 acceptance block to one
stage only. Evidence classes are separated so an automated result is not presented as native or
physical-device evidence.

| #62 acceptance criterion | Sole stage | Evidence/result |
| --- | --- | --- |
| Fresh install succeeds on supported targets | E2-16B | Automated migration/startup checks and approved iOS lifecycle evidence. Android native execution is intentionally not applicable. |
| Close/reopen and ordinary restart preserve data | E2-16B | Permanent local lifecycle tests plus the approved native iOS lifecycle scope; no invented simulator/device version is recorded. |
| Upgrade from every shipped SQLite schema succeeds | E2-16C | Permanent SQLite migration tests; only SQLite v1 exists, so there is no second shipped mobile schema to replay. |
| Injected migration failure rolls back | E2-16C | Permanent migration rollback tests. The removed failing-v2 fixture was qualification-only and is not production source. |
| Prior schema remains usable or startup fails closed without destructive reset | E2-16C | Permanent migration/fail-closed tests and static inspection of production reset boundaries. |
| Termination before, during, and after representative mutations preserves atomicity and supports reconciliation | E2-16D | Temporary iOS transaction barriers/checkpoints implemented the evidence path; no native execution is performed in this closure pass. |
| Food, Recipe publication, Daily Log edit/delete, Target, and OCR operations survive restart | E2-16F | Permanent semantic/idempotency/recovery tests; native Stage-F evidence is incomplete and is not represented as a full pass. |
| Direct integrity qualification passes after each lifecycle scenario | E2-16D | The temporary direct qualifier was removed with the harness; permanent SQLite integrity/FK checks remain. |
| Low-storage/filesystem failure is reported without automatic database reset | E2-16E | Temporary isolated path/open and bounded `SQLITE_FULL` design; no host/device volume exhaustion was manufactured. |
| Epic 1 accessibility workflows remain operable with VoiceOver and TalkBack where supported | E2-16G | Intentionally not applicable: manual VoiceOver/TalkBack and Android native qualification were removed personal-project scope. |
| OCR receives its established iOS physical-device qualification | E2-16I | Physical-device evidence was owner-coordinated and retained with glare/overlay limitations; exact device/build versions were not retained, so none are invented here. |
| Remediation remains bounded to approved Epic 2 behavior | E2-16J | Static diff/search and this closure record; no production authority, schema, recovery, or transaction redesign was introduced. |
| ChatGPT Work coordinates physical-device and manual accessibility evidence | E2-16J | Coordination responsibility is recorded; manual accessibility evidence is intentionally not applicable and native execution is owner-only. |
| Stop if native limitations make the preserved invariants or single-authority runtime unattainable | E2-16J | No architecture stop was reached. The one-authority boundary remains intact; E2-17/E2-18 are unclaimed. |

## Evidence classes and limitations

- **Automated:** permanent SQLite migration, local-authority, OCR, recovery, runtime-hook, and
  transfer tests; TypeScript and static source/config checks. The temporary E2-16 harness tests are
  deleted, not silently counted as current permanent coverage.
- **Simulator/native:** the retained record covers the approved iOS lifecycle qualification scope.
  This document does not invent an iOS, Xcode, simulator, or build version absent from the retained
  evidence. Native qualification is not executed by E2-16J.
- **Physical-device:** iOS OCR evidence remains owner-coordinated. Stage-I accepted glare/overlay
  limitations. A known qualifier false negative reported a missing persisted Potassium Food row
  after a later ordinary Food edit materialized a canonical placeholder row; that observation did
  not restore, reinterpret, or prove omitted OCR provenance. No full Stage-F native pass is claimed.
- **Static:** the ordinary unflagged Expo identity/configuration, production schema/migration
  source, authority selection, and absence of temporary E2-16 source are checked in this cleanup.
- **Intentionally not applicable:** Android native execution, manual TalkBack, manual VoiceOver,
  and full physical accessibility qualification are removed personal-project scope.

The exact environment recorded for this cleanup is macOS at `/Users/mipoo/Nutrition App`, with
Node `v24.19.0` used for mobile TypeScript/tests and an unflagged local Expo public configuration
resolving to `Nutrition App`, `com.portfolio.nutritionapp`, and `nutritionapp`. The retained E2-16
native records do not include an iOS, Xcode, simulator, or physical-device build version; that is
an evidence-retention limitation, not a reason to invent one.

## Deferred release claims

E2-17 remote/PostgreSQL regression and mixed-authority qualification remain **unclaimed**.
E2-18 final Epic 2 end-to-end release qualification remains **unclaimed**. Their backlog entries
remain planning records and are not started by E2-16J.

## Owner cleanup boundary

This Codex pass does not manipulate ignored generated native projects, Simulator data, or installed
apps. The owner should, after reviewing any retained evidence:

1. Remove the ignored generated project at `/Users/mipoo/Nutrition App/apps/mobile/ios` if it is no
   longer needed, then regenerate the ordinary project only when required. In particular, remove
   stale `NutritionAppE216.xcworkspace`/`NutritionAppE216.xcodeproj` outputs rather than editing
   production source to preserve them.
2. On each qualification simulator, uninstall only the retired E2-16 bundle
   `com.portfolio.nutritionapp.e216` and remove its isolated qualification data/checkpoints if
   present. Do **not** erase `com.portfolio.nutritionapp` or its ordinary `nutrition.db`.
3. On physical devices, uninstall only an installed E2-16 qualification app/data set, if any;
   leave the ordinary Nutrition App and its `nutrition.db` intact.
