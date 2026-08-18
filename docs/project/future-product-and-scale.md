# Future Product and Scalability Options

> **Document role: Idea Register.** This is not an active roadmap, backlog, or implementation commitment.

This document records product and architecture options deliberately deferred while Nutrition App remains optimized for a personal, local-first use case. Moving an item from this register into implementation requires a newly scoped decision, acceptance criteria, and architecture review where authority, persistence, synchronization, privacy, or trust boundaries are affected.

Implemented behavior belongs in the current project, architecture, feature, and operations guides. If an item here becomes implemented, remove or narrow the speculative entry rather than allowing this register to describe completed work as future scope.

## Current product simplifications

### Advanced per-nutrient tracking controls

The target model supports recommended, custom, amount-only, and ignored tracking states. The current UI intentionally exposes a simpler target-editing workflow rather than the complete per-nutrient state machine.

Current product behavior includes:

- the canonical nutrient catalog in Daily Log tracking;
- personalized RDA or AI recommendations where the supported profile permits them;
- permitted FDA Daily Value/reference fallbacks where appropriate;
- total-consumed presentation without goal progress when no authoritative daily goal exists;
- manual target overrides;
- retained model support for explicit amount-only and ignored preferences.

A broader future product may expose:

- per-nutrient Show / Hide;
- when shown, Daily nutrient goal: Recommended / Custom / No goal;
- dynamic helper text explaining the active recommendation basis;
- nutrient search, grouping, presets, and bulk visibility controls;
- migration/reset UX for previously saved advanced preferences.

The existing persistence/model capability should remain available so a future UI does not require redesigning target storage.

### Fatty-acid expansion

The current catalog already includes source-reported Total Omega-3 as a real nutrient identity, with ALA, EPA, and DHA presented as components beneath it. Linoleic acid remains an Omega-6 fatty acid rather than being grouped beneath Total Omega-3.

The application must not fabricate total Omega-3 by summing an incomplete ALA/EPA/DHA subset.

Future catalog work may include:

- source-reported Total Omega-6 when a defensible upstream or label value exists;
- additional individually reported fatty-acid identities;
- further grouping or display refinements where supported by real source semantics.

Any aggregate nutrient must represent an actual reported or otherwise authoritative value rather than an inferred incomplete sum.

## Public accounts and multi-user operation

The completed Version 1.1/Epic 2 program intentionally excluded public account architecture and general multi-user deployment.

Potential future work includes:

- public account creation and authentication;
- account recovery and credential lifecycle;
- multi-user or tenant ownership and authorization;
- privacy/export/delete-account workflows;
- production deployment of the remote runtime for general users;
- operational support and abuse/security boundaries appropriate to a public service.

Existing owner scoping is a useful foundation but is not by itself a commercial account system.

## Multi-device data, synchronization, and cloud durability

The current application selects exactly one application-data authority for a running context and intentionally provides no synchronization, dual-write, automatic authority fallback, background replication, or multi-device merge.

Local SQLite backup and restore are implemented as bounded durability/recovery operations. They do not create a second live authority and are not synchronization.

Potential future capabilities include:

- multi-device synchronization;
- explicit conflict resolution and merge semantics;
- cross-device draft continuation;
- cross-device mutation recovery;
- collaborative recovery or editing;
- remote-mode offline authoring and a durable mutation queue;
- optional cloud-hosted backup storage;
- scheduled or automated backup policy beyond the current bounded local mechanism.

Cloud backup must remain conceptually separate from synchronization. A backup is point-in-time durability and recovery; synchronization is an ongoing consistency protocol between live authorities.

The completed PostgreSQL-to-SQLite transfer is likewise a bounded migration mechanism, not a sync journal.

## Logging and authoring expansion

The completed Daily Logging work intentionally excluded several broader workflows that may become useful in a larger product:

- meal planning and future scheduling;
- custom meal definitions;
- automatic meal inference;
- consumption timestamps;
- per-meal analytics;
- durable unsubmitted drafts;
- bulk logging and other batch workflows;
- changing or replacing the source Food during Edit;
- undo and deleted-entry recovery;
- rich-text notes;
- note attachments.

The current application does protect unsaved in-memory authoring state when navigating away from guarded Food, Recipe, Target, and OCR confirmation flows. That protection is not durable draft persistence: terminating the application does not turn those drafts into stored application records.

Future durable draft work should be introduced only when the product need justifies its persistence, lifecycle, recovery, and synchronization semantics.

### Manual retraction of Daily Log completion

Epic 4 introduces `Complete` as a positive user assertion that a day has finished logging, with automatic invalidation when nutrition changes. Initial Epic 4 does not require a second explicit interaction for manually retracting an already asserted Complete state.

A future refinement may add manual un-completion/retraction if real use shows a meaningful need—for example, if the user marks a day Complete prematurely but wants to reopen its status before making any nutrition-affecting edit. That capability should remain lightweight and should not introduce locking, workflow states, or new nutritional meaning beyond retracting the user's prior assertion.

## Nutrition analytics and guidance

The current target system provides informational nutrition targets and daily comparisons. It deliberately does not provide therapeutic recommendations, diagnosis, longitudinal analytics, or medical-condition-specific target prescription.

Potential future work includes:

- longitudinal nutrition analytics;
- trends and adherence summaries;
- per-meal or time-of-day analysis;
- configurable insights and recommendations;
- non-clinical coaching features;
- analytics instrumentation or telemetry for a commercial product.

Any therapeutic, disease-specific, medication-specific, deficiency-diagnosis, or clinician-directed feature requires a separate safety and product boundary. It must not be inferred from the current general profile fields, DRI data, or calorie estimation.

## Platform and acquisition expansion

Nutrition-label OCR remains iOS-specific.

The current iOS flow already includes guided camera capture, framing assistance, on-device Apple Vision recognition, and bounded image-quality warnings before or around recognition. Those capabilities are current behavior, not future work.

Potential future work includes:

- Android-native OCR parity;
- broader device/platform qualification;
- manual crop/edit interactions if evidence shows they materially improve recognition;
- additional capture assistance beyond the current bounded framing and quality checks;
- alternative recognition engines where a concrete quality or platform requirement justifies them.

Manual crop should not be introduced casually because the current OCR image lifecycle intentionally minimizes retained image state.

## Accessibility expansion

The application already contains some platform-level accessibility labels, roles, status semantics, touch-target treatment, and Dynamic Type-aware UI work. Comprehensive accessibility-focused product design and qualification are not currently active scope for the personal-use application.

Potential future work includes:

- screen-reader-specific semantics for charts and historical data visualizations;
- dedicated accessible alternatives for dense or gesture-driven analytical controls;
- systematic VoiceOver navigation/focus qualification across primary flows;
- broader Dynamic Type and text-scaling qualification for dense nutrition surfaces;
- contrast and non-color-cue audits across target/limit/history presentation;
- accessibility-specific chart summaries and exact-value navigation;
- accessibility settings where a concrete user need justifies app-specific controls rather than relying on platform behavior.

These should be introduced as explicit product requirements when needed rather than expanding unrelated feature Epics by default.

## Durable drafts and queued work

Current mutation recovery determines whether an already submitted mutation committed. Separately, navigation guards protect unsaved in-memory drafts from accidental abandonment.

Neither mechanism is a durable offline-work queue.

Future requirements may justify:

- durable unsubmitted Food, Recipe, Log, Target, or OCR-review drafts;
- explicit autosave semantics;
- restart-resumable draft state;
- cross-device draft resume;
- background retry for intentionally queued remote work;
- user-visible queue management and cancellation.

Durable drafts, queued mutations, and uncertain-mutation reconciliation must remain distinct concepts so unsubmitted work is never mistaken for a mutation that may already have committed.

## Architecture invariants that are not scaling shortcuts

The following should not be treated as optional future simplifications:

- immutable historical Daily Log nutrition;
- immutable Recipe publication revisions;
- exact-decimal nutrition semantics;
- explicit unknown versus zero;
- provenance preservation;
- ownership isolation;
- deterministic mutation outcomes;
- no silent authority fallback;
- no shadow or dual writes;
- no automatic historical recalculation from current Food definitions.

A future synchronization, account, cloud, analytics, or multi-user architecture must be designed around these invariants rather than weakening them.

## Promotion rule

Before promoting an item from this document into a roadmap or implementation issue, define:

1. the concrete user outcome;
2. authoritative data ownership;
3. persistence and migration consequences;
4. offline, failure, and recovery behavior;
5. privacy and security implications;
6. accessibility requirements;
7. local/remote parity or an explicit reason for divergence;
8. qualification and physical-device evidence where applicable.

This document exists to preserve useful future options without forcing the current personal-use application to pay their complexity cost prematurely.
