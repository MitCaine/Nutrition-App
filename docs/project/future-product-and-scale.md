# Future Product and Scalability Options

> **Document role: Idea Register.** This is not an active roadmap, backlog, or implementation commitment.

This document records product and architecture options deliberately deferred while Nutrition App
remains optimized for a personal, local-first use case. Moving an item from this register into
implementation requires a newly scoped decision, acceptance criteria, and architecture review where
authority, persistence, synchronization, privacy, safety, or trust boundaries are affected.

Implemented behavior belongs in the current project, architecture, feature, and operations guides.
If an item here becomes implemented, remove or narrow the speculative entry rather than allowing
this register to describe completed work as future scope.

The register separates ideas that have standalone value for the existing personal application from
complexity primarily justified by multi-user, multi-device, hosted, collaborative, or commercial
operation. Placement here does not promote an idea into active roadmap scope.

## Personal app / product evolution

These ideas can provide value to the existing single-user local-first product without requiring a
commercial or multi-user architecture.

### Advanced per-nutrient tracking controls

The target model already supports recommended, custom, amount-only, and ignored tracking states.
The current UI intentionally exposes a simpler target-editing workflow rather than the complete
per-nutrient state machine.

Current behavior includes:

- the canonical nutrient catalog in Daily Log tracking;
- personalized RDA or AI recommendations where the supported profile permits them;
- permitted FDA Daily Value/reference fallbacks where appropriate;
- total-consumed presentation without goal progress when no authoritative daily goal exists;
- manual target overrides; and
- retained model support for explicit amount-only and ignored preferences.

Potential personal-product refinements include:

- per-nutrient Show / Hide;
- when shown, Daily nutrient goal: Recommended / Custom / No goal;
- dynamic helper text explaining the active recommendation basis;
- nutrient search, grouping, presets, and bulk visibility controls; and
- migration/reset UX for previously saved advanced preferences.

These are presentation/product refinements over existing persistence capability; they should not
require deleting stored nutrient observations or fabricating goals where no authoritative goal
exists.

### Fatty-acid expansion

The current catalog already includes source-reported Total Omega-3 as a real nutrient identity, with
ALA, EPA, and DHA presented as components beneath it. Linoleic acid remains an Omega-6 fatty acid
rather than being grouped beneath Total Omega-3.

The application must not fabricate total Omega-3 by summing an incomplete ALA/EPA/DHA subset.

Potential future catalog work includes:

- source-reported Total Omega-6 when a defensible upstream or label value exists;
- additional individually reported fatty-acid identities; and
- further grouping or display refinements where supported by real source semantics.

Any aggregate nutrient must represent an actual reported or otherwise authoritative value rather
than an inferred incomplete sum.

### Logging, meal, and authoring expansion

Potential personal-product workflows include:

- meal planning and future scheduling;
- custom meal definitions;
- automatic meal inference where justified;
- explicit consumption timestamps;
- bulk logging and other batch workflows;
- changing or replacing the source Food during Edit where a safe semantic is defined;
- undo and deleted-entry recovery;
- richer notes; and
- note attachments.

These are not current commitments and should be promoted only when their concrete user outcome and
mutation/history semantics are specified.

#### Manual retraction of Daily Log completion

`Complete` is currently a positive user assertion that a non-empty Daily Log date has finished
logging, with automatic invalidation when nutrition changes. There is no separate manual
un-completion action.

A future refinement may add lightweight manual retraction when a user marks a day Complete
prematurely and wants to reopen that assertion before making a nutrition-affecting edit. Retraction
should not invent new nutritional meaning, rewrite immutable Log snapshots, or require a broader
workflow-state model.

### History and personal analytics

Nutrition History and Trends already provides:

- 7-day and 30-day calendar ranges ending yesterday;
- Complete-day and Logged-day denominator semantics;
- overview and focused nutrient charts;
- exact daily History values;
- navigation from a daily History row to the authoritative Daily Log date; and
- current-reference context that remains separate from immutable historical intake.

Those capabilities are current behavior, not future work.

Potential personal-product expansion includes:

- 90-day and custom History ranges;
- prior-period comparisons;
- optional non-clinical trend or adherence summaries;
- per-meal or time-of-day analysis; and
- carefully scoped configurable insights where the output remains informational rather than
  diagnostic or therapeutic.

Any therapeutic, disease-specific, medication-specific, deficiency-diagnosis, or clinician-directed
feature requires a separate safety and product boundary. It must not be inferred from current
general profile fields, DRI data, calorie estimation, or historical intake alone.

### Platform and OCR expansion

Nutrition-label OCR remains iOS-specific.

The current iOS flow already includes guided camera capture, framing assistance, on-device Apple
Vision recognition, and bounded image-quality warnings before or around recognition. Those
capabilities are current behavior.

Potential personal-product expansion includes:

- Android-native OCR parity;
- broader device/platform qualification;
- manual crop/edit interactions only if physical evidence shows a material recognition benefit;
- additional capture assistance when measured quality evidence justifies it; and
- alternative recognition engines when a concrete quality or platform requirement justifies them.

Manual crop should not be introduced casually because the current OCR image lifecycle intentionally
minimizes retained image state.

### Accessibility expansion

Current accessibility behavior already includes platform accessibility labels, roles, status
semantics, touch-target treatment, Dynamic Type-aware work, non-color-only status treatment in
implemented flows, chart accessibility labels and selected-state semantics, and accessible
exact-value text for focused History. Current History exact-value navigation is therefore not an
absent accessibility feature.

Potential future work is systematic qualification and broader coverage, including:

- systematic VoiceOver navigation and focus qualification across primary flows;
- broader Dynamic Type and text-scaling qualification for dense nutrition surfaces;
- contrast and non-color-cue audits across target, limit, Recipe, and History presentation;
- dedicated accessible alternatives for future dense or gesture-driven analytical controls; and
- app-specific accessibility settings only where a concrete user need cannot be met through
  platform behavior.

Future accessibility work should extend and qualify existing semantics rather than describing
already implemented chart labels, selected state, focused exact-value text, or daily-value
navigation as missing functionality.

### Durable local drafts and restart recovery

Current navigation guards protect unsaved in-memory Food, Recipe, Target, and OCR-confirmation
drafts from accidental abandonment. Current mutation recovery separately determines whether an
already submitted mutation committed. Neither mechanism is durable draft persistence.

Potential personal-product work includes:

- durable local unsubmitted drafts;
- explicit autosave semantics; and
- restart-resumable Food, Recipe, Log, Target, or OCR-review authoring state.

Durable drafts and uncertain-mutation reconciliation must remain distinct so unsubmitted work is
never mistaken for a mutation that may already have committed.

## Scalability / multi-user / commercial architecture

These ideas are primarily justified by moving beyond the current personal local-first product into
hosted, multi-user, multi-device, collaborative, or commercial operation.

### Public accounts and hosted multi-user operation

Potential future work includes:

- public account creation and production authentication;
- account recovery and credential lifecycle;
- tenant/multi-user ownership and authorization;
- privacy, export, and delete-account workflows;
- public production deployment of the remote runtime; and
- production operational, support, security, and abuse boundaries.

Existing owner scoping is a useful foundation but is not by itself a public or commercial account
system.

### Multi-device synchronization, remote queues, and cloud durability

The current application selects exactly one application-data authority for a running context and
intentionally provides no synchronization, dual write, automatic authority fallback, background
replication, or multi-device merge.

Local SQLite backup/restore is already implemented as bounded point-in-time durability and recovery.
The completed PostgreSQL-to-SQLite transfer is a bounded migration mechanism. Neither is
synchronization.

Potential scale-facing capabilities include:

- multi-device synchronization;
- explicit conflict resolution and merge semantics;
- cross-device draft continuation and recovery;
- remote-mode offline mutation queues with user-visible queue management and cancellation;
- optional cloud-hosted backup;
- scheduled cloud durability/backup policy;
- collaborative editing or collaborative recovery; and
- explicit cross-device recovery semantics.

Backup and synchronization must remain distinct. A backup is point-in-time durability and recovery;
synchronization is an ongoing consistency protocol among live authorities. Queueing a remote
mutation is also distinct from both: it represents intentionally unsubmitted or pending work, not a
second authoritative store and not uncertain-mutation reconciliation.

### Commercial analytics and operations

Commercial product operation may eventually justify:

- analytics instrumentation and telemetry;
- privacy-governed product/operational metrics;
- support tooling;
- abuse and security response boundaries; and
- hosted-service operational evidence beyond the current personal/reference deployment model.

Commercial telemetry is distinct from optional personal non-clinical trend summaries. Neither is
implicitly authorized by this register.

## Architecture invariants that are not scaling shortcuts

The following are current invariants, not optional future simplifications:

- immutable historical Daily Log nutrition;
- immutable Recipe publication revisions;
- exact-decimal nutrition semantics;
- explicit unknown versus zero;
- provenance preservation;
- ownership isolation;
- deterministic mutation outcomes;
- exactly one selected application-data authority for a running context unless a future approved
  synchronization architecture explicitly defines otherwise;
- no silent authority fallback;
- no shadow or dual writes; and
- no automatic historical recalculation from current Food definitions.

Future synchronization, account, cloud, analytics, multi-user, or commercial architecture must be
designed around these invariants rather than weakening them.

## Promotion rule

Before promoting an item from this document into a roadmap or implementation issue, define:

1. the concrete user outcome;
2. authoritative data ownership;
3. persistence and migration consequences;
4. offline, failure, and recovery behavior;
5. privacy and security implications;
6. accessibility requirements;
7. local/remote parity or an explicit reason for divergence; and
8. qualification and physical-device evidence where applicable.

This document exists to preserve useful future options without forcing the current personal-use
application to pay their complexity cost prematurely.
