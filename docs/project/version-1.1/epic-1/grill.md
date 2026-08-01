# Version 1.1 Epic 1 — Daily Logging Flow Grill record

> **Document role: Planning Record.** This record closes Grill for Epic 1 of the
> [Version 1.1 Product Roadmap](../version-1.1-roadmap.md). It resolves product behavior and scope
> before a Feature PRD is written. It is not a PRD, architecture design, task breakdown, or
> implementation plan. The roadmap remains authoritative; this record refines its Epic 1 intent
> without authorizing work outside the roadmap or the repository workflow.

**Grill status:** Complete  
**Shared understanding:** Confirmed  
**Next permitted workflow stage:** Feature PRD

## Product outcome

Epic 1 makes the Daily Log the authoritative starting and returning point for recording and
reviewing consumption. Every creation path converges on one explicit Log Food confirmation flow,
preserves the selected Daily Log date, and produces a historically stable entry only after the
user confirms it.

The Epic improves speed by removing unnecessary navigation, not by bypassing review, weakening
nutrition correctness, or adding analytics instrumentation.

## Core product rules

### Authoritative date context

- Add Food launched from a Daily Log receives that Log's calendar date as immutable flow context.
  The date is displayed throughout the flow and before commit, but is not editable there.
- To log against another date, the user cancels, navigates to that Daily Log, and begins again.
- A successful create returns to the originating Daily Log date and immediately presents the
  confirmed entry. No component may substitute the current date implicitly.
- The passage of time never changes the user's active date. At midnight, the application updates
  its definition of Today and date-dependent controls but does not navigate or retarget an active
  workflow.
- Every visible entry, total, and target state must belong to the selected date. When the date
  changes, data from the former date is retired immediately and replaced by date-specific loading,
  failure, or success states.
- Previous day and Next day use calendar-date arithmetic in the authoritative time zone, not
  24-hour duration arithmetic. Next day stops at Today during ordinary browsing. A Today shortcut
  appears whenever another date is active, and the date picker remains available for direct
  navigation.

### Authoritative user calendar

- Today, past, future, rollover, navigation boundaries, and mutation validity derive from one
  user-confirmed IANA time-zone identifier. Device clock or time-zone changes do not silently alter
  Daily Log semantics.
- Before the first Version 1.1 Daily Log mutation, the user must confirm an authoritative time
  zone. The client time zone is proposed but never silently adopted.
- Before confirmation, history remains browsable in a read-only provisional mode using adjacent
  navigation and the date picker. Today and future classifications may be previewed from the
  clearly identified proposed zone, but Add, Repeat, Edit, Delete, and all other mutations are
  unavailable.
- Confirming the initial zone re-evaluates the currently viewed date and controls without
  navigating away or discarding viewing context.
- Changing the authoritative zone requires confirmation that shows the current and proposed named
  zones, whether Today changes, the number of entries that would become future-dated, a way to
  review affected dates or entries, and an explanation that entries are reclassified—not moved,
  modified, or deleted.
- A zone change may reclassify existing entries as future-dated. Those entries are preserved and
  enter legacy cleanup mode. The change itself is not blocked by that consequence.
- An Add or Edit flow active during a zone change preserves its selected date and entered values,
  discloses the context change, and revalidates immediately before commit. A newly future date is
  blocked; no substitute date is chosen.
- If later architecture review finds that this required calendar behavior needs a persistence
  redesign, fundamental data-model change, or architectural rewrite, the Epic returns to roadmap
  review. Its scope must not expand silently.

### Future-date boundary and legacy cleanup

- No Version 1.1 mutation may result in a newly persisted future-dated entry.
- Existing or time-zone-reclassified future entries are compatibility data tolerated only until
  resolved. They may be viewed or deleted. They may be edited only when the same save moves them to
  Today or an earlier date. A save that leaves the entry in the future is rejected regardless of
  which fields changed.
- Moving an entry between future dates and using a future entry as the source of Repeat are
  prohibited. Once moved into the supported date range, an otherwise eligible entry can return to
  Recent Entries under the normal rules.
- Future dates use a dedicated legacy cleanup interface, never the normal Daily Log. With entries,
  it presents a flat identifying list and only View, Delete, and Edit-to-move actions. It includes
  the Food or Recipe, date, serving and amount, note preview, unsupported-meal notice, and other
  identifying metadata.
- An empty future date presents a dedicated “No legacy entries on this future date” state and
  navigation back to the supported range.
- Future-date screens omit meal groups, Add Food, Repeat, totals, target progress, and the ordinary
  empty-day state.

## User workflows

### Normal Daily Log

- Breakfast, Lunch, Dinner, and Snack appear in that fixed order even when empty, remain expanded,
  and each provides Add Food. Unassigned appears after them only when it contains entries and does
  not provide its own Add action.
- A general Add Food action is the canonical entry point for no meal assignment. It opens with meal
  unset. A named meal-group action carries that group as an editable initial meal.
- A day with no entries says “No food logged for this date.” It still presents the four named meal
  groups and their Add actions. Absence of records is unknown consumption, not confirmed zero
  intake or successful 0% target progress.
- Groups are organizational only. Nutrition and target calculations remain day-level. All entries
  remain visible; groups cannot be collapsed, filtered, manually reordered, or rearranged.
- Within each group, entries are ordered by creation time ascending with the stable entry
  identifier as the deterministic tie-breaker. Editing an entry does not change its creation time.

### Add Food discovery

- Browse mode, used when the query is empty, presents: Recent Entries, Favorites, Recent Foods,
  then Saved Foods. Search mode, used for a non-empty query, replaces those shortcuts with clearly
  separated Saved Foods and USDA result groups. Clearing the query restores browse mode without
  losing Daily Log context.
- Selecting a saved Food, Favorite, or Recent Food proceeds directly to Log Food confirmation
  without an intervening Food Detail step.
- A saved Food may be logged directly. A USDA result first passes through the existing explicit
  import flow. A successful import creates a reusable Food and then continues automatically to Log
  Food confirmation; import alone never creates a Log entry.
- Custom Food and Scan Label are discovery handoffs to their existing creation behavior, not
  redesigns of those flows. Successful creation continues to Log Food confirmation. Cancelling
  confirmation leaves the new Food saved but creates no Log entry.
- Scan Label is presented and qualified on supported iOS clients. It is absent on Android; Android
  exposes no route into unsupported OCR behavior.
- Every acquisition path converges on the same confirmation step. The user reviews the current
  authoritative source, serving, amount, meal, notes, and other log-specific values before commit.
- If a selected Food or serving changes while confirmation is open, the application never chooses
  a replacement silently. It blocks save, refreshes the current definition, clears any ambiguous
  nutrition-affecting selection, and requires explicit review. If the source is no longer loggable,
  the user returns to discovery with the target date preserved.
- Add Food remains available for a valid date when existing entries fail to load, with a clear
  warning that the day cannot be reviewed and duplicate logging is possible. Recent Entries is
  unavailable until its data loads; other discovery sources retain their independent availability.
  Unresolved uncertain-mutation restrictions take precedence.

### Confirmation and cancellation

- Daily Log → Add Food discovery → Log Food confirmation is a three-level hierarchy. Cancelling
  confirmation returns one level to discovery; cancelling discovery returns to the originating
  Daily Log.
- Returning to discovery restores the immutable date, originating meal default, browse or search
  mode, query, discovery section state, scroll position, and other transient discovery context.
- Creating or importing a Food and creating a Daily Log entry are separate user-confirmed
  transactions. No cancellation, acquisition handoff, or selection commits a Log entry.
- Unsubmitted workflow state is transient. It is preserved during ordinary backgrounding only
  while the process remains alive. Process termination may discard it and never creates a partial
  entry. Durable draft and resume behavior is not part of Version 1.1.

### Repeat through Recent Entries

- Repeat is the sole history-derived authoring workflow; Version 1.1 has no Duplicate Log Entry
  capability. It prepares exactly one new entry and always requires Log Food confirmation.
- Recent Entries contains the 10 most recently created eligible entries, ordered newest first by
  creation time without a rolling-day cutoff or deduplication. Each historical event remains a
  distinct choice and shows enough context to distinguish it: log date, meal when present, serving
  and amount, and whether a note exists.
- Eligibility depends on whether the underlying Food or active published Recipe is currently
  loggable and whether the source entry is on Today or an earlier date. It does not require every
  historical value to remain reusable.
- Repeat uses the current authoritative Food or active published Recipe revision at commit, not the
  original entry's nutrition snapshots. The target date is the currently viewed Daily Log date and
  remains immutable.
- Food, an unambiguously resolvable serving and amount, and meal may be prefilled. When serving or
  amount cannot be mapped safely, those fields remain unselected until the user chooses current
  valid values.
- Explicit meal-group context overrides the historical meal. General Add uses a supported
  historical meal when available; otherwise meal remains unset. The user may change or clear it.
- Notes are blank by default. A historical note may appear as read-only reference with an explicit
  Copy notes action only when it already satisfies the current note contract. It is never copied
  automatically or truncated.
- Copy Meal, Copy Day, bulk Repeat, bulk reassignment, and bulk deletion are excluded. Each new
  entry is authored and confirmed individually.

### Editing and moving

- Entries are historically stable against later Food or Recipe changes but remain editable through
  explicit user action. The source Food or Recipe identity is fixed for the entry's lifetime.
- Edit may change date, meal, notes, and—when the same source remains resolvable—serving and amount.
  Correcting the source requires confirmed deletion and a new Add Food flow.
- Metadata-only changes preserve the existing nutritional snapshots. A date move transfers Daily
  Log ownership and leaves snapshots unchanged; meal and notes likewise do not affect nutrition.
- Nutrition-affecting edits atomically replace the nutritional snapshots from the same current
  authoritative source. The application does not retain prior versions of the edited entry.
- If a source is unavailable, edits that preserve the nutritional snapshot remain permitted:
  supported meal assignment, notes, a valid date move, and deletion. Any change requiring nutrition
  recalculation is rejected.
- A successful date move navigates to the destination Daily Log and makes the entry visible there.
  The source and destination day totals and target progress are refreshed independently from their
  resulting entry sets. An edit without a date change remains on the current day.
- A backdated create or nutrition edit uses the authoritative source definition at commit time.
  The consumption date does not select or reconstruct a historical Food or Recipe definition.

### Deleting

- Delete requires explicit confirmation identifying the entry and date with sufficient context,
  such as name, meal, serving, and amount.
- The confirmation explains that only the Daily Log entry and its historical nutritional snapshots
  are removed. The reusable Food, Recipe, USDA import, and other catalog data remain unchanged.
- After confirmed deletion, the user remains on the same date and the groups or empty state update.
- Confirmed deletion is permanent. Undo, recycle bin, soft delete, and a recovery window are not
  included.

## Field contracts and compatibility

### Meal assignment

- The only assigned meal identifiers are `breakfast`, `lunch`, `dinner`, and `snack`. Assignment is
  optional. Unassigned is the presentation of the canonical absence of a value, not a fifth value.
- Meal is assigned only through explicit user intent. No time-of-day inference is permitted.
- Unsupported legacy meal values are preserved until an explicit meal edit, projected into
  Unassigned, and displayed in a safely escaped, visually bounded notice. Unrelated metadata edits
  do not force cleanup. Selecting a supported meal or clearing it replaces the legacy value.
- Unsupported legacy values are never offered as Version 1.1 choices or propagated into Repeat.

### Notes

- Notes are optional plain text. Line breaks are preserved; leading and trailing whitespace is
  trimmed; a trimmed empty value means no note.
- New or explicitly edited notes are limited to 1,000 Unicode code points. Overlength input is
  rejected with clear validation before save, and the same contract applies across clients and the
  server.
- Rich text, formatting, hyperlink behavior, mentions, images, files, and attachments are excluded.
- Entries with notes show at most two visual preview lines. Overflow uses an ellipsis and Show more;
  expansion reveals the full note in place and offers Show less. Expansion is independent per entry,
  read-only, and never enters Edit. Entries without notes reserve no note space.
- Existing overlength notes remain intact and readable until the note itself is edited. Unrelated
  metadata edits do not require shortening. Repeat may show such a note as reference but must not
  offer Copy notes.

### Entry time and ordering

- Version 1.1 records a calendar date and optional meal, not a user-authored consumption time.
- Creation time is immutable operational metadata for deterministic ordering and audit purposes.
  It does not state or imply when consumption occurred.

## Loading, failure, and write recovery

### Independent read states

- Entries, nutrition totals, and target progress are independently loadable. Each section presents
  its own loading, success, failure, stale, and retry behavior without misrepresenting another.
- Entry-load failure is never shown as an empty day. Totals or target failure does not hide loaded
  entries. Retrying one section should not unnecessarily discard successful content elsewhere.
- During a refresh of the same date, previously confirmed content may remain visible when clearly
  marked stale or potentially stale. This allowance never applies across date navigation.

### Confirmed mutations and refreshes

- Create, edit, move, and delete use one post-commit model. Once authoritatively confirmed, the
  mutation response is reflected immediately. Subsequent view refreshes are independent reads.
- A refresh failure may leave surrounding day information stale or incompletely synchronized, but
  cannot make a confirmed mutation uncertain. A confirmed create remains visible; a confirmed move
  remains at its destination; a confirmed edit remains changed; and a confirmed delete remains
  absent.

### Uncertain mutations

- A submission with an indeterminate commit outcome becomes an uncertain mutation. Its exact
  submitted payload and identity remain locked until authoritative reconciliation. It cannot be
  edited or casually resubmitted.
- Retry status/save uses the same intent. Confirmed success completes it; confirmed non-commit makes
  it safely retryable. Edit and delete reconciliation refresh the affected entry; move reconciliation
  checks both source and destination dates. Optimistic local state is never treated as proof.
- The originating client durably retains only the minimal locked recovery record needed across
  process termination. This is not a draft, resume feature, offline queue, or source of new work,
  and it is not synchronized to other clients.
- Dismissing recovery prompts does not erase or resolve uncertainty. A deliberately separate action
  that might duplicate or conflict with it requires an explicit warning that the first operation
  may already have committed.
- Other clients rely on authoritative server state. Pending client intents, collaborative editing,
  field-level merging, and cross-device recovery coordination are excluded.
- If another client changes or deletes an entry before commit, the current workflow stops, refreshes
  authoritative state, and requires review before another mutation. No automatic merge is attempted.

## Accessibility release qualification

Epic 1 is not complete until users can operate every supported workflow with VoiceOver on iOS and
TalkBack on Android. Qualification covers date navigation and picker, meal groups, general and
meal-specific Add Food, browse and search, Recent Entries and Repeat, acquisition handoffs, Log Food
confirmation, editing, moves, notes, errors and retries, uncertain-operation recovery, and destructive
confirmation.

iOS qualification includes Scan Label. Android qualification covers the shared workflow and omits
Scan Label because that unsupported action is absent. Dynamic text and large accessibility sizes,
keyboard navigation where supported, appropriate labels and roles, logical focus order, and useful
announcements for dynamic changes are release requirements. Assistive-technology users follow the
same logical workflow with equivalent capability.

## Success criteria

Epic 1 succeeds when all of the following user-visible outcomes hold:

1. A user can navigate a trustworthy date-only Daily Log, distinguish empty, loading, failed, and
   stale states, and never see one date's data presented as another's.
2. A user can begin from the general or a named meal Add action, discover a Food through every
   supported source, and reach one explicit confirmation without unrelated detail navigation.
3. The immutable target date, explicit meal precedence, current source definition, and entered log
   fields are visible and respected through confirmation, cancellation, commit, and return.
4. A user can repeat one eligible historical action through Recent Entries without copying stale
   nutrition, unsupported meal values, event-specific notes, identifiers, timestamps, or provenance.
5. A user can view and edit meal and notes, make permitted serving or amount corrections, move an
   entry between valid dates, and permanently delete an entry with clear consequences.
6. No normal mutation creates a future-dated entry, while legacy or time-zone-reclassified future
   entries remain discoverable and resolvable through the restricted cleanup experience.
7. Partial read failures preserve independent usable content, and confirmed versus uncertain write
   outcomes remain unambiguous without accidental duplicate or conflicting mutations.
8. The authoritative time-zone workflow gives all active clients one consistent interpretation of
   Today and the supported logging range.
9. VoiceOver, TalkBack, large text, and supported keyboard workflows provide equivalent access to
   the complete platform-supported capability.

No elapsed-time target, tap-count target, or new analytics instrumentation is required. Faster
logging is demonstrated by direct handoffs, preserved context, convergence on one confirmation,
and immediate presentation of confirmed results.

## Explicit non-goals

- Meal planning, schedules, reminders, notifications, automatic meal classification, custom meals,
  per-meal nutrition analysis, or consumption times.
- Offline authoring, offline mutation queues, durable unsubmitted drafts, or synchronization.
- Copy Meal, Copy Day, bulk operations, a separate Duplicate action, source replacement during Edit,
  group filtering or collapse, and manual or drag-and-drop ordering.
- Undo, recycle bin, soft delete, or deleted-entry recovery.
- Automatic recalculation of historical Logs from changed Foods or Recipes, or reconstruction of a
  historical source definition based on consumption date.
- Redesign of USDA import, Custom Food creation, or Scan Label internals; Android OCR.
- Collaborative editing, automatic conflict merging, synchronized pending intents, or multi-device
  workflow continuity.
- Rich-text notes, attachments, analytics instrumentation, architectural rewrites, technology
  migrations, or persistence redesigns.

## Assumptions and challenged boundaries

- Existing authoritative Log, Food, Recipe revision, nutrition snapshot, ownership, and explicit
  confirmation concepts remain the foundation. This Epic changes user-visible workflow, not their
  authority.
- A single owner may use more than one active client. Correctness therefore depends on refreshing
  authoritative state and explicit review, not on assuming one process or merging concurrent edits.
- The roadmap's Low architectural-impact estimate remains a planning assumption, not a conclusion.
  The Grill exposed authoritative time-zone state and durable client-local uncertain recovery as
  required behavior. Their compatibility with existing boundaries must be evaluated at the later
  architecture-review stage.
- Product terminology uses **historically stable** for entries protected from source changes.
  Entries are not append-only: explicit permitted edits can replace metadata or nutritional
  snapshots without retaining previous entry versions.

## Remaining questions and workflow gate

No unresolved product question remains from Grill. The accepted decisions are sufficiently bounded
for a Feature PRD.

Two matters are deliberately reserved for later workflow stages rather than answered here:

1. The PRD must express these decisions as testable requirements without expanding their scope.
2. Architecture review must determine whether the authoritative time-zone and client-local uncertain
   recovery requirements fit the existing evolutionary boundary. If they require a rewrite or
   persistence redesign, work stops and returns to roadmap review.

No Feature PRD, architecture change, task breakdown, or implementation is authorized by this
record alone.
