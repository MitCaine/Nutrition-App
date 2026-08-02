# E1-17 Accessibility Remediation — Stage 2 Daily Log, Mutations, Cleanup, and Recovery

## Status and boundary

Stage 2 remediates the Daily Log, destructive mutation, legacy future-entry cleanup, and durable
uncertain-mutation recovery workflows. It adopts the approved Stage 1 foundations and preserves the
E1-01 through E1-16 calendar, mutation, replay, projection, durability, recovery, provenance, and
historical-nutrition contracts.

This record does not qualify E1-17 as complete. Stage 3 acquisition and form remediation, Stage 4
Dynamic Type, contrast, supported-keyboard work and final evidence, manual assistive-technology
qualification, and E1-18 remain unstarted.

## Findings addressed

Within the Stage 2 workflow boundary, the implementation completes the planned remediation for:

- AX-03: Daily Log controls now expose contextual names, button roles, disabled state, headings,
  calendar classification, and minimum targets.
- AX-04: entries expose coherent identity summaries, contextual repeated actions, and measured
  note-disclosure state.
- AX-05: recovery records expose distinct lifecycle summaries, contextual actions, dismissed and
  busy state, safety lockouts, and user-initiated focus outcomes.
- AX-14: permanent deletion uses the shared modal lifecycle, trigger return focus, bounded busy
  semantics, one confirmed outcome, and deterministic successor focus.

The implementation partially addresses application-wide AX-06 and AX-17 by completing their Daily
Log, mutation-return, cleanup, and recovery adoption. Acquisition/form surfaces remain for Stage 3,
and release-wide qualification remains for Stage 4. It also advances AX-01, AX-02, AX-16, AX-18,
and AX-20 without claiming application-wide completion.

## Screens and components remediated

- Normal Daily Log and authoritative/provisional date navigation.
- Daily Log entries, meal groups, notes, totals, and target progress.
- Permanent Daily Log deletion and unresolved-delete status handling.
- Legacy future-entry cleanup and restricted move-only context.
- Daily Log recovery panel and recovery-overlap acknowledgment.
- Real navigation returns after confirmed create, edit, and move.
- Date picker return focus for Daily Log and cleanup move.

The work reuses `AccessibleModal`, `AccessiblePressable`, `AccessibilityStatus`, the shared focus
requester and route-focus hook, the shared announcement owner, and the contextual-action-label
utility. It adds no competing accessibility system.

## Daily Log semantics

The Daily Log exposes a screen heading, selected-date heading, Entries, Totals, Target Progress,
and fixed meal-group headings. Unassigned remains conditional. The selected date identifies
provisional, authoritative Today, past, future browse-only, or legacy cleanup context in words.

Previous Day, Next Day, Today, direct date selection, Return to Today, meal Add Food, retry, entry,
cleanup, recovery, and modal actions use the shared 44-point pressable. Disabled Next Day is
programmatic rather than opacity-only. Date-picker cancellation and completion return focus to the
invoking date control.

Entries expose one concise accessible summary containing available name, meal, amount, date,
note, source, and compatibility context. Visual identity fields do not repeat that summary as
separate accessibility fragments. View source, Edit, Move, Delete, note disclosure, meal Add Food,
and recovery actions receive structured contextual labels.

Note disclosure is based on the rendered line count of a non-accessible measuring copy. Show more
appears only when the full note exceeds two rendered lines; the action exposes expanded state and
Show less restores the collapsed preview. This supports later large-text qualification without
performing the Stage 4 scaling pass.

Entries, totals, and target progress retain independent E1-07 states. Loading and routine refresh
remain quiet. Initial failure, stale retained data, unavailable dependent state, empty state, and
section-specific Retry actions use the Stage 1 status component. Unknown entries never produce
authoritative zero totals or target progress.

## Focus fallback rules

User-initiated date changes focus the new date heading. Background clock, calendar, and query
refreshes do not. Confirmed move return suppresses competing root-heading focus and targets the
destination date heading. Add, Edit, and cleanup Move cancellation carries a screen-owned logical
return key across the route remount and restores the invoking action when it still exists.
Confirmed create and same-date edit returns target the projected entry summary.

Confirmed deletion resolves focus in this order:

1. next entry in the same meal group;
2. previous entry;
3. meal-group heading;
4. empty-day heading;
5. Daily Log heading.

Cleanup resolution uses next cleanup entry, previous cleanup entry, then the completion heading.
Recovery actions initiated from the panel use the next record, previous record, or recovery
heading. Background reconciliation never requests focus. All Stage 2 focus requests are
cancellable and are released on unmount.

## Announcement policy

Confirmed create, edit, move, delete, cleanup, and user-initiated recovery outcomes use stable
mutation keys and the Stage 1 cross-platform announcement service. Recovery appearance is
announced once per panel appearance without moving focus. Confirmed non-commit and obsolete or
conflicting recovery results receive explicit user-facing messages.

Source review, invalidated amount, unavailable source, stale entry/calendar, future-date blocking,
and recovery-storage messages remain the established user-facing messages but now use one explicit
announcement owner on shared Log Food mutation returns. Their visible alert or warning nodes use a
non-live mode to avoid a second native live-region announcement. Routine cache invalidation and
refresh do not announce, and a later read failure does not recast a confirmed mutation as
uncertain.

## Permanent deletion

The destructive confirmation now uses `AccessibleModal`. Native presentation focuses its heading;
Cancel returns to the contextual Delete trigger. The dialog identifies the exact entry and date,
permanent snapshot removal, retained reusable catalog resources, totals and target consequences,
and the absence of Undo. Busy and disabled state appears on actions and a status surface, never on
the heading. Confirmed deletion is announced once and immediately selects the documented safe
successor. Uncertain and retryable deletes preserve their E1-14 exact-intent behavior.

## Legacy cleanup

The cleanup route exposes its own heading, selected future-date heading, compatibility explanation,
flat entry summaries, and only View, Move, and Delete entry capabilities. Generic Edit remains
absent. Loading, stale, failure, empty, retry, and completion states use the shared semantics.

The move-only route focuses its heading once, presents entry identity as readable rather than
disabled, preserves the restricted date-only payload, uses named minimum-target controls, and
returns date-picker focus to the destination trigger. A confirmed move returns to and focuses the
destination Daily Log date. Resolving the final cleanup entry focuses the completion heading.

## Durable recovery

Every newly created recovery record captures a bounded, immutable, presentation-only display
context containing the affected item name, amount label, and meal label when safely available.
This context is durably stored with the locked intent and survives process termination, dismissal,
reconciliation attempts, and exact retry without changing the exact mutation payload, request
identity, overlap rules, or authoritative recovery behavior. Existing version-2 records that
predate the display context remain readable and use a generic “Daily Log entry” fallback; internal
Log and Food identifiers are never substituted into user-facing recovery presentation.

Stored version-2 records validate recovery authority independently from this optional presentation
metadata. Absent, partial, invalid-field, non-object, and overlength display contexts are accepted
when the authoritative record remains valid, then normalized field by field to bounded strings or
null. Display metadata alone never increments the malformed-record count, activates the recovery
safety lock, quarantines an exact intent, or changes its payload, request identity, owner scope,
dates, or lifecycle. Strict validation and safety-lock behavior remain unchanged for genuinely
malformed authoritative recovery fields.

Each recovery record is a heading with a distinct summary of mutation type, user-facing item
identity, available meal and amount context, source and destination dates, lifecycle, dismissal,
unresolved status, and exact-retry availability. Check status, Retry exact operation, Dismiss, and
recovery-overlap actions identify the precise operation with the same immutable display context.
Busy state is programmatic and record-local; dismissed records remain reviewable and explicitly
described.

Unknown-version, malformed-record, and storage-failure health states are non-destructive safety
lockouts. They do not expose unsafe recovery actions or claim successful durability. Confirmed
projection continues to occur in the E1-16 recovery service before journal removal. Only a
user-initiated resolution moves focus; background reconciliation does not.

Recovery-overlap warnings now use `AccessibleModal`, describe the original uncertainty, distinguish
review from a separate action, and return focus to the attempted Save or Move control on cancel.
Acknowledgment still creates a separate request identity and does not alter or retry the original
record.

## Stage 1 primitive corrections

Stage 2 integration exposed two bounded Stage 1 defects:

- `AccessibleModal` previously applied busy and disabled state to its heading. The heading now
  remains a heading; callers place busy state on status and action surfaces.
- A native focus target can disappear during the same commit that removes a modal or collection
  row. Native-handle resolution now treats that race as an unavailable target instead of throwing.

`RootScreenHeader` also accepts an optional external heading ref and a bounded `autoFocus` switch so
the existing route-focus system can coordinate a move return to the destination-date heading
without a second focus system.

## Automated coverage

Workflow and regression coverage now asserts:

- date-control names, roles, disabled state, date and section headings;
- distinct entry summaries and action labels for similar entries;
- measured note truncation and expanded state;
- independent entries, totals, and target status semantics;
- shared deletion modal consequences, heading state, return target, and successor ordering;
- route-remount cancellation focus restoration for repeated Daily Log actions;
- cleanup headings, restricted actions, summaries, move-only read-only semantics, and completion;
- distinct recovery summaries, contextual actions, appearance announcement, dismissed and busy
  state, identifier-free legacy and malformed-metadata fallback, durable immutable display context,
  independent field-level display normalization, authoritative-record safety lockout, confirmed
  outcome announcement, and focus-safe removal;
- real navigator projection and announcement after confirmed create;
- contextual label construction, modal-heading correction, and safe focus-handle resolution; and
- preservation of the existing logging, cleanup, recovery, projection, and navigation regressions.

The full Jest suite is required to exit normally without `--forceExit` or open-handle warnings.

## Pending qualification

Manual VoiceOver, TalkBack, maximum Dynamic Type, contrast, physical touch measurement, and
hardware-keyboard qualification remain pending. No claim is made that AX findings outside the
Stage 2 surfaces are resolved. Stage 3, Stage 4, the final E1-17 evidence record, and E1-18 remain
unstarted.
