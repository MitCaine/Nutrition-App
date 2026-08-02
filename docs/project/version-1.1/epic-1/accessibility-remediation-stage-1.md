# E1-17 Accessibility Remediation — Stage 1 Shared Foundations

## Status and boundary

Stage 1 establishes shared accessibility infrastructure for the later E1-17 workflow passes. It
does not qualify E1-17 and does not claim that any complete Epic 1 workflow passes VoiceOver,
TalkBack, large-text, or hardware-keyboard testing.

The implementation preserves the architecture and product contracts approved by the
[Feature PRD](feature-prd.md), [Architecture Review](architecture-review.md), and
[Epic 1 grill](grill.md). It does not change navigation ownership, backend behavior, calendar
authority, mutation intent, recovery durability, or historical nutrition.

Stages 2–4 and E1-18 remain unstarted.

## Shared primitives

### Route and element focus

`src/shared/accessibility/focus.ts` provides:

- `focusAccessibilityElement`, a cancellable delayed request built on React Native native handles
  and `AccessibilityInfo.setAccessibilityFocus`;
- `createAccessibilityFocusRequester`, the injected-driver test seam;
- `useAccessibilityScreenFocus`, which focuses once for each active route key and does not refocus
  on ordinary rerenders or query refreshes; and
- `firstAvailableAccessibilityTarget`, the deterministic preferred-target/fallback rule.

Pending requests are cancelled when their owning effect or component is cleaned up. Keyboard
focus is optional and centralized in the same request rather than being independently improvised by
screens. A zero-delay request is synchronous; this gives unmount-time modal return focus a bounded
request with no orphaned timer.

`RootScreenHeader` is the representative screen-entry integration. Its title is now a registered
heading and requests one focus move for each mounted root title. Later stages must register the
remaining non-root route headings and explicit return targets.

### Accessible modal

`src/shared/accessibility/AccessibleModal.tsx` supplies:

- native `Modal` behavior;
- `accessibilityViewIsModal` and Android importance metadata;
- an explicit heading;
- optional initial-control focus, otherwise heading focus;
- native `Modal.onShow` as the entry-focus boundary;
- preferred return focus with deterministic fallback;
- busy and disabled heading state; and
- cancellation of obsolete entry/return focus requests.

Changing `visible` to true prepares a modal lifecycle but does not request focus. The first native
`onShow` for that opening requests focus once; visible rerenders do not repeat it, and closing then
reopening permits a new request. Close cancels pending entry work. Normal return focus is owned
until it completes, the modal reopens, or the destination lifecycle unmounts. Unmount while
presented performs one synchronous bounded return request and releases its cancellation owner;
closing before `onShow` performs no stale entry or return focus. A caller-supplied `onShow` callback
is preserved.

`DatePickerModal` is the ordinary representative migration. Its product behavior is unchanged;
the iOS modal now uses the wrapper and explicit Cancel/Done names, while the Android native picker
has an explicit accessible name. Destructive deletion, recovery acknowledgment, and serving-unit
modal migrations are deferred.

### Cross-platform announcements

`src/shared/accessibility/announcements.ts` provides:

- `announceAccessibility` and `useAccessibilityAnnouncement`;
- iOS announcement options when available and the supported React Native API on Android;
- polite and assertive priorities;
- bounded kinds for success, warning, error, stale, review-required, and mutation outcomes;
- same-key/same-message suppression for 1,500 milliseconds by default;
- a 100-entry insertion-ordered bound on deduplication state;
- immediate announcement when a keyed message changes;
- optional delayed delivery; and
- explicit settlement ownership for immediate, completed delayed, cancelled, and obsolete work.

`createAccessibilityAnnouncementOwner` is the deterministic ownership seam used by the hook.
Immediate and completed announcements leave the pending set immediately, cancellation removes its
record, and component cleanup cancels only genuinely pending work. Completed timer handles and
cancellation closures are not retained until unmount.

Routine refresh is never announced merely by importing or calling the service. A caller must
request an announcement. `TransientSuccessBanner` is the representative integration and announces
each changed success message once.

### Semantic section states

`src/shared/accessibility/AccessibilityStatus.tsx` represents loading, refreshing, stale, empty,
initial failure, retryable failure, unavailable, and busy states. It provides appropriate alert,
live-region, busy, and disabled props; accepts optional explicit announcement behavior; and creates
a contextual Retry name from the resource being retried.

Each rendered status selects one proactive announcement strategy. When an explicit announcer is
provided, the shared service owns the announcement and that message node uses live-region `none`
while retaining its alert role and readable state. Without an explicit announcer, initial/retryable
failures use native alert/assertive semantics and stale, unavailable, and busy states use native
polite semantics. Loading, refreshing, and empty states are non-chatty.

`TargetProgressSection` is the representative integration. Its existing loading, empty, stale,
failure, unavailable, and retry behavior is retained through the shared component. Routine target
refresh remains non-announcing by default.

### User-facing error translation

`src/shared/errors/userFacingError.ts` defines `UserFacingError` and
`userFacingEpicOneError`. The result contains a safe summary, optional recovery instruction,
severity, optional logical target, and bounded announcement text. Known Epic 1 conflicts cover
calendar changes, future-date blocking, stale sources and amounts, unavailable sources, stale
entries, unresolved mutations, and recovery-storage failure.

Unknown exceptions use a caller-provided safe fallback. Raw API bodies, codes, and exception text
are not used as the primary presentation. Target progress is the bounded representative consumer;
other existing translators remain in place until their owning workflow stage.

### Structured validation and persistent fields

`src/shared/forms/validation.ts` defines `ValidationIssue`, including:

- stable logical target;
- code and user-facing message;
- announcement choice;
- focus-move choice; and
- whether entered values remain valid.

`applyValidationIssue` maps that result to screen-owned focus registration and the shared
announcement service. Domain validation remains independent of React refs.

`src/shared/forms/LabeledField.tsx` provides a persistent visible label, explicit accessibility
label and hint, required/invalid state, associated error ID, disabled/read-only state, multiline
support, and a stable logical validation target.

Disabled and read-only are separate contracts. Both prevent editing. Disabled exposes
`accessibilityState.disabled`; read-only does not, remains readable/focusable according to native
behavior, exposes `aria-readonly`, and adds “Read only” to its accessibility hint. A field that is
both disabled and read-only resolves honestly as disabled, while read-only warnings can remain
invalid and associated with their visible message.

The bounded Custom Food integration migrates Name, Brand, and Notes. Food validation maps the
logical `food.name` target to the existing `food:name` registered input. Invalid submission keeps
form values, focuses the registered input, associates the visible error, and announces the message.
Serving and nutrient field migration remains deferred.

`KeyboardSafeScrollView` now exposes a narrow `focusTarget` handle. It reuses the existing target
registry and cancels a pending accessibility-focus request on cleanup; it does not introduce a
global focus manager.

### Minimum touch targets

`src/shared/accessibility/AccessiblePressable.tsx` enforces a 44-by-44-point minimum layout target,
forwards role, label, style, and state, and removes activation while disabled or busy. It allows
callers to provide additional non-overlapping `hitSlop` when appropriate.

Target progress settings, retry, and disclosure actions and Date Picker actions are the bounded
representative integrations. Repository-wide Pressable migration is deferred.

### Contextual repeated-action labels

`src/shared/accessibility/contextualActionLabels.ts` centralizes the current English construction
for edit, repeat, delete, move, and note-disclosure actions. It accepts structured subject, meal,
amount, and date context and cleanly omits unavailable values.

One Daily Log Edit action is the representative integration. The remaining Daily Log, Repeat,
cleanup, acquisition, and recovery actions are deferred to their workflow stages.

## Native keyboard and focus contract

The shared foundation follows these expectations:

- Native source order owns ordinary forward and reverse traversal; no desktop-style tab system is
  introduced.
- Pressables and inputs rely on the platform-supported activation keys and accessibility actions.
- A modal must contain accessibility focus while open, expose system Back or Escape through
  `onRequestClose` where the platform supplies it, and restore focus after close.
- No custom control may create a focus trap.
- A genuine route activation may move focus once to its registered heading or initial control.
  Background refresh, cache updates, and ordinary rerenders must not move focus.
- If an invoking control is removed, the workflow must provide a documented safe successor.
- Native platform focus indication remains authoritative; Stage 1 does not add a custom focus ring.

These expectations are implementation contracts, not manual keyboard qualification. Hardware
keyboard testing remains pending.

## Representative integrations

| Surface | Stage 1 integration | Deferred work |
|---|---|---|
| Root screen header | Heading semantics and one-shot entry focus | All temporary/detail routes and full return-focus mapping |
| Date picker | Shared modal, entry semantics, named actions | Trigger return refs on every caller and every remaining modal |
| Success banner | Keyed cross-platform announcement | Mutation-specific outcome wording across workflows |
| Target progress | Shared loading, stale, empty, unavailable, failure, retry, and compact actions | Other Daily Log states and workflow-specific announcement policy |
| Custom Food | Name/Brand/Notes labeled fields and targeted Name validation | Serving, nutrient, save-state, and all other forms |
| Daily Log entry | Contextual Edit label | Other repeated actions and complete card semantics |

## Audit finding status after Stage 1

No audit finding is claimed fully resolved across the application. Stage 1 completes the reusable
foundation slice and partially addresses:

- AX-01: focus request and representative route integration exist; route-by-route migration is
  deferred.
- AX-02: modal wrapper and Date Picker integration exist; all remaining modals are deferred.
- AX-06: announcement service and success integration exist; workflow outcome adoption is deferred.
- AX-10: labeled-field and validation foundations plus three Custom Food fields exist; the full
  Custom Food editor remains deferred.
- AX-13: structured target and screen mapping are proven; Log Food remediation is deferred.
- AX-14: deterministic return/fallback focus infrastructure exists; deletion integration is
  deferred.
- AX-16: the minimum-target primitive and limited integrations exist; repository-wide target audit
  is deferred.
- AX-17: semantic state and bounded error contracts exist; comprehensive state migration is
  deferred.
- AX-18: the native focus/keyboard contract and hooks exist; manual qualification and workflow
  adoption are deferred.
- AX-20: deterministic tests cover the new seams; full workflow automation and all manual evidence
  remain deferred.

AX-03 through AX-05, AX-07 through AX-09, AX-11, AX-12, AX-15, and AX-19 receive no comprehensive
workflow remediation in Stage 1.

## Automated coverage

Focused tests directly assert:

- one focus request per route activation and cancellation after unmount;
- modal `onShow` entry, once-per-opening behavior, reopen, early close, preferred/fallback return,
  cancellation ownership, no duplicate unmount restoration, isolation metadata, heading semantics,
  and busy state;
- announcement priority, keyed deduplication, changed messages, bounded dedupe storage, immediate
  and delayed ownership settlement, cancellation, and component cleanup;
- explicit-versus-native status announcement modes, non-chatty refresh, loading/failure/stale/busy
  semantics, and contextual retry naming;
- validation target mapping, focus request, single announcement, and retained values;
- persistent label plus normal, required, invalid, disabled, read-only, read-only-warning, combined
  disabled/read-only, and error-association props;
- 44-point target sizing and disabled activation blocking; and
- distinct labels for visually similar repeated records.

The full mobile suite must exit normally without `--forceExit`, open-handle warnings, leaked timers,
or leaked listeners.

## Known limitations and next-stage guidance

- React Native ultimately delegates accessibility focus, keyboard traversal, modal isolation, and
  spoken timing to iOS and Android. Deterministic unit seams do not replace device qualification.
- Focus should be registered only for genuine route or modal entry. Query refresh code must not call
  the route hook.
- Announcements should describe important outcomes, not every state render. Use a stable key for one
  logical outcome, choose either explicit service or native live-region mode for a status, and
  cancel delayed announcements that become obsolete.
- Screens own logical-target-to-ref mapping. Validation and domain code must not import React refs.
- Use `AccessiblePressable` for compact actions unless the existing control already provides an
  equal or stricter effective target.
- Use contextual action construction instead of repeating hand-built English templates in screens.
- Later stages must preserve the existing calendar, mutation, recovery, and historical-nutrition
  boundaries while adopting these primitives.

Manual VoiceOver, TalkBack, maximum-text-size, contrast, touch measurement, and hardware-keyboard
qualification remain pending.
