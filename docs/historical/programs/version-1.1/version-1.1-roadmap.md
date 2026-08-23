# Version 1.1 product roadmap

> **Document role: Completed Program Record.** This was the authoritative parent document for
> Version 1.1 product scope, defining intended user-visible outcomes and sequencing rather than
> implementation design, feature requirements, or tasks. The Version 1.1 program is complete; this
> roadmap is retained as historical planning evidence, not current planning state. See
> [Current State](../../../project/current-state.md) for the current product line.

Version 1.1 is an evolutionary release built on the completed Version 1.0 baseline. Every Epic
below is subordinate to the [Project Constitution](../../../project/constitution.md),
[Project Invariants](../../../project/invariants.md), [Architecture Overview](../../../architecture/overview.md), and
[Architecture Decision Index](../../../architecture/decisions.md). If later discovery shows that an Epic
requires an architectural rewrite, technology migration, persistence redesign, public multi-user
model, or weakened historical guarantee, that scope is not authorized by this roadmap.

Technical Epic 2 has an architecture-gate **PASS** at qualified HEAD
`219311051e23cfcebdb09d28747874f0d3091faa`. The retained native/accessibility boundary is recorded
in the [E2-16 closure and evidence record](epic-2/e2-16-closure-evidence.md); remote/PostgreSQL and
mixed-authority qualification is complete; and the final totals, limitations, transfer-skip
disposition, traceability, and closure sequence are recorded in the
[E2-18 release qualification record](epic-2/e2-18-closure-evidence.md). This technical result does
not reorder or authorize the product Epics below. GitHub #64 and Epic #46 are closed; the durable
record is committed and the Epic 2 program is complete.

The implemented Version 1.1 program comprised Epic 1 (Daily Logging Flow) and the technical
Epic 2 (Local-First SQLite Runtime) documented in this directory. The remaining product Epics
recommended below — Nutrition History and Trends, Recipe Reuse and Discovery, and Nutrition Label
Capture Confidence — were not implemented as Version 1.1 program epics; parts of their scope were
taken up later as ordinary post-program issues.

## Assessment of Version 1.0

### Strengths

- The product has a coherent end-to-end nutrition model. Manual entry, USDA import, nutrition-label
  confirmation, duplication, and published Recipes all converge on reusable Foods.
- Historical nutrition is unusually trustworthy for a personal tracker. Daily Logs retain resolved
  nutrient snapshots, published Recipes retain immutable revisions, and unknown values remain
  distinct from measured zero.
- The main creation workflows are present: Food management, label-assisted entry, Recipe authoring
  and publication, logging, daily totals, targets, favorites, recents, and search.
- Retry, ownership, privacy, and failure behavior are treated as product correctness rather than
  incidental infrastructure concerns.
- The engineering, qualification, and documentation systems provide a stable base for incremental
  product work without reopening foundational decisions.

### Incomplete workflows and rough edges

- Daily logging is not yet a complete home workflow. A user can review a day but cannot begin Food
  discovery from that context; adding an entry requires navigating through a Food detail page.
- Daily Log entries are presented as a flat list. The existing Log contract already carries meal
  context and notes, but the mobile experience does not expose them. Day selection also favors a
  date picker over quick movement through adjacent days.
- The product explains one day well but does not help the user understand patterns across days or
  weeks. This limits the “understand nutrition” half of the project's purpose.
- Recipe behavior is technically strong but operational terminology leaks into the experience.
  “Publish as Food” and a separate published Food surface make reuse less direct than it should be.
  Recipe discovery exposes little beyond name, ingredient count, and publication state; Recipe
  favorites were explicitly deferred from Version 1.0.
- Label recognition has a safe privacy and confirmation model, but capture is deliberately basic.
  Historical release evidence leaves physical-device camera geometry and permission recovery as
  areas requiring renewed product confidence; manual VoiceOver/TalkBack qualification is removed
  personal-project scope.
- Loading, empty, failure, and retry behavior is mature in some discovery and target surfaces but
  uneven across the Daily Log and Recipe experience.

### Natural extensions

The strongest extensions are those that make existing trusted data easier to record, revisit, and
understand: a faster daily loop, multi-day insight, more direct Recipe reuse, and more confident
label capture. Pantry inventory, social features, coaching, and synchronization introduce new
product models rather than completing the current one.

## Version 1.1 vision

Version 1.1 should make Nutrition App useful as a daily habit, not merely a capable set of nutrition
tools. A user should be able to record food with less navigation, understand both today and recent
history, reuse Recipes without learning the compatibility model, and trust the label-capture flow
on a real device.

The release should deepen four existing product loops:

1. record the day;
2. understand recent history;
3. reuse personal Recipes; and
4. capture packaged-food data confidently.

## Recommended Epics

### Epic 1 — Daily Logging Flow

**Purpose:** Make the Daily Log the fastest and clearest place to record and review a day.

**User value:** Logging requires less navigation, entries carry useful everyday context, and moving
through recent days feels continuous rather than administrative.

**Success criteria:**

- A user can begin adding a Food from the Daily Log and reach saved Foods, favorites, recents, and
  search without first opening an unrelated detail flow.
- A user can assign and edit meal context and notes, and the day view presents those details clearly.
- Adjacent-day navigation, empty days, loading, failure, and retry states are understandable and
  accessible.
- Repeating a previously used Food creates a deliberate new Log entry with the same historical and
  retry guarantees as any other Log.
- Food or Recipe edits still never change previously recorded nutrition.

**Major capabilities:**

- Daily Log entry point for Food discovery and logging.
- Meal-oriented organization using the existing Log concept.
- User-visible Log notes.
- Quick adjacent-day movement and clear day-state feedback.
- Bounded repeat logging from recent entries.

**Explicit non-goals:**

- Meal planning, schedules, reminders, or notifications.
- Offline mutation queues or synchronization.
- Automatic meal classification.
- Recalculation of historical entries from current Food or Recipe definitions.

**Dependencies on other Epics:** None. This Epic improves the primary input loop used by later
history views.

**Recommended implementation order:** First.

**Estimated architectural impact:** **Low.** The authoritative Log, snapshot, meal-context, notes,
ownership, and idempotency concepts already exist. The Epic should extend the user workflow without
changing historical authority or redesigning persistence.

**Workflow status:** Complete. After the accepted scope and resolved decisions were recorded in
the [Epic 1 Daily Logging Flow Grill record](epic-1/grill.md), the Feature PRD, architecture
review, implementation backlog, and implementation issues (E1-08 through E1-18) were completed and
closed with the [Epic 1 release qualification](epic-1/release-qualification.md).

### Epic 2 — Nutrition History and Trends

**Purpose:** Turn trustworthy Daily Log history into an understandable view of recent nutrition
patterns.

**User value:** The user can see whether intake is consistent, changing, incomplete, or regularly
above or below a chosen reference without inspecting each date individually.

**Success criteria:**

- A user can review nutrition across useful recent time windows and move from a trend back to the
  contributing day.
- Trend values are derived only from immutable Daily Log snapshots.
- Estimated amounts and unknown contributors remain visible rather than being presented as precise
  totals.
- Target context clearly distinguishes personal overrides, calculated calorie estimates, FDA
  references, and unavailable comparisons.
- Empty or partially logged periods remain interpretable and are not silently treated as zero
  consumption.

**Major capabilities:**

- Recent-history summaries for calories, macronutrients, and selected tracked nutrients.
- Trend views with target/reference context.
- Data-completeness indicators across the selected period.
- Navigation from a period view to the relevant Daily Log date.

**Explicit non-goals:**

- Nutrition coaching, diagnoses, recommendations, forecasts, or adherence scores.
- Weight, body-measurement, exercise, or health-record tracking.
- Recalculation from current Food definitions.
- A general analytics or reporting platform.

**Dependencies on other Epics:** Epic 1 should precede this Epic so the primary data-entry loop and
meal context are coherent before the product adds richer interpretation.

**Recommended implementation order:** Second.

**Estimated architectural impact:** **Moderate.** This adds a broader read model over authoritative
history and new presentation, but it should require no change to the meaning or storage of existing
Daily Logs.

### Epic 3 — Recipe Reuse and Discovery

**Purpose:** Make Recipes feel like first-class reusable meals while preserving explicit publication
and immutable revisions.

**User value:** A user can find, understand, duplicate, update, and log Recipes without needing to
understand that a managed Food projection supports the experience.

**Success criteria:**

- Recipe lists clearly distinguish draft, published, and update-needed states.
- Frequently used Recipes can be found through a coherent favorites or recents experience.
- A Recipe can be logged directly from Recipe context with an explicit amount choice.
- Duplicating a Recipe creates an independent editable Recipe with understandable lineage.
- Updating a published Recipe remains deliberate; the user is never led to believe that draft edits
  changed prior Logs or the active published revision.

**Major capabilities:**

- Clear Recipe lifecycle and `needs_republish` presentation.
- Recipe favorites and recent-use discovery.
- Direct Recipe logging and serving-oriented reuse.
- Recipe duplication for personal variations.
- User-facing language that keeps publication explicit without exposing compatibility mechanics.

**Explicit non-goals:**

- Automatic publication or republication.
- Editing or replacing immutable revisions.
- Collaborative, shared, or public Recipes.
- Recipe web import, generated Recipes, meal plans, or instruction-authoring expansion.
- A new parallel hierarchy for loggable items.

**Dependencies on other Epics:** Epic 1 provides the preferred logging handoff. The Recipe Epic does
not depend on Nutrition History and Trends.

**Recommended implementation order:** Third.

**Estimated architectural impact:** **Moderate.** The Epic stays within the existing authored
Recipe, immutable revision, compatibility projection, ownership, and Log boundaries. Discovery and
duplication add surface area around a concurrency-sensitive domain, so architectural review remains
important even though no rewrite is intended.

### Epic 4 — Nutrition Label Capture Confidence

**Purpose:** Make label-assisted Food creation dependable and understandable on supported iOS
devices.

**User value:** The user gets better capture guidance, can recover from common camera and network
problems, and can review uncertain results without losing sight of what requires attention.

**Success criteria:**

- Supported physical iOS devices provide a reliable camera and photo-library flow across common
  orientation, permission, and retake scenarios.
- The review experience prioritizes unresolved, ambiguous, and low-confidence values while keeping
  confirmed values understandable.
- Common supported English-language nutrition-label layouts produce a reviewable result or a clear,
  recoverable failure.
- Keyboard and error-recovery behavior is qualified before the Epic is considered complete. Manual
  VoiceOver/TalkBack and Android native qualification are removed personal-project scope.
- Images, paths, full OCR text, and unbounded recognition responses remain outside durable storage.

**Major capabilities:**

- Capture guidance and intentional retake/reselect flow.
- Clear permission, recognition, parsing, and network recovery states.
- Review organization centered on fields that need user judgment.
- Expanded confidence in representative supported label layouts on real hardware.

**Explicit non-goals:**

- Barcode scanning or a new product database.
- Android native, web, or Expo Go OCR support.
- Manual VoiceOver/TalkBack qualification for this personal project.
- Cloud image recognition or retention of label images and raw OCR output.
- Automatic Food creation without confirmation.
- Offline parsing, confirmation, or synchronization.

**Dependencies on other Epics:** None. It can be discovered in parallel, but should follow the
higher-frequency daily and Recipe loops in implementation order.

**Recommended implementation order:** Fourth.

**Estimated architectural impact:** **Moderate.** The capability crosses the existing native,
mobile, parser, and confirmation boundaries, but must preserve their current responsibility split
and bounded provenance model.

## Epic ordering and rationale

| Order | Epic | Why now |
| --- | --- | --- |
| 1 | Daily Logging Flow | Highest-frequency user loop, immediate value, lowest architectural impact, and foundation for later insight. |
| 2 | Nutrition History and Trends | Advances the core purpose of understanding nutrition and consumes the trusted history already produced by logging. |
| 3 | Recipe Reuse and Discovery | Improves repeated use of a strong but conceptually complex domain after the logging destination is coherent. |
| 4 | Nutrition Label Capture Confidence | Closes a real-device confidence gap and improves acquisition, but is iOS-specific and crosses the native boundary, making it narrower and riskier than the preceding loops. |

The order favors frequent user value first, then interpretation, then deeper reuse, then a narrower
capture path. It also contains risk: the first Epic mostly exposes concepts already present, while
the later Epics introduce broader read behavior or touch concurrency-sensitive and native
boundaries. Nothing in this ordering relaxes the existing engineering workflow; selection of an
Epic merely authorizes it to enter Grill and later stages.

## Deferred to Version 1.2 or later

- Meal planning, pantry quantities, shopping lists, expiration tracking, and household inventory.
- Personalized recommendations, coaching, adherence scoring, notifications, and predictive goals.
- Barcode scanning and additional external food databases.
- Durable offline data, queued mutations, and synchronization.
- Public or multi-user accounts, households, sharing, social features, and collaborative Recipes.
- Weight, body measurements, exercise, health records, and medical integrations.
- Recipe generation, web import, and broad instruction-management features.
- Public production deployment and its identity, isolation, and account-lifecycle requirements.
- Technology migrations and dependency modernization except when separately required for security or
  supported-build maintenance; those are engineering maintenance, not Version 1.1 product Epics.

These ideas are deferred because they create new product or trust models, require disproportionate
architecture, or distract from completing the existing daily nutrition loop.

## Risks and assumptions

- **Scope discipline:** Each Epic can expand into a much larger product category. Later Grill and
  PRD work must preserve the explicit non-goals here.
- **Historical meaning:** Trends, repeat logging, and Recipe reuse must consume immutable snapshots
  and revisions; convenience cannot introduce current-definition recomputation.
- **Uncertainty:** Multi-day views can amplify false precision. Unknown, estimated, explicit-zero,
  missing-day, and untracked states must remain distinct.
- **Recipe complexity:** Discovery changes appear simple but still intersect owner scope, graph
  safety, publication state, and managed projections.
- **Native qualification:** Label-capture confidence depends on physical-device evidence that
  simulator and unit tests cannot replace.
- **External availability:** USDA remains a separate, network-dependent source; none of these Epics
  should make core saved-Food or historical views depend on live USDA availability.
- **Deployment boundary:** Version 1.1 remains personally controlled, private/internal, and
  single-user.
- **Measurement:** The repository does not currently define a product analytics system. Success
  criteria are therefore framed as observable user outcomes and release evidence, not telemetry
  targets.

## Recommendation

Begin Version 1.1 with **Epic 1 — Daily Logging Flow**.

It improves the most frequent product behavior, exposes useful concepts already present in the
authoritative Log model, carries the lowest architectural impact, and produces a cleaner foundation
for both Nutrition History and Recipe reuse. The next workflow step is Epic selection followed by
Grill; this roadmap does not authorize a PRD, task breakdown, or implementation.
