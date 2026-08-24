# Version 1.1 Epic 1 — Daily Logging Flow Feature PRD

## 1. Purpose

Epic 1 makes the Daily Log the authoritative starting and returning point for recording and reviewing consumption. Users must be able to add, repeat, edit, move, and delete entries while preserving trustworthy date context, explicit confirmation, historical nutrition behavior, and recoverable mutation outcomes.

Faster logging must result from direct handoffs, retained workflow context, and immediate presentation of confirmed changes. It must not bypass confirmation, weaken nutrition correctness, or introduce analytics instrumentation.

## 2. Scope

The feature includes:

- Date-only Daily Log browsing through adjacent-day navigation and direct date selection.
- Meal-oriented organization of entries.
- General and meal-specific Add Food entry points.
- Food discovery through recent entries, favorites, recent Foods, saved Foods, USDA search, Custom Food, and supported label scanning.
- One shared Log Food confirmation workflow for every acquisition path.
- Repeat logging of individual eligible historical entries.
- Entry editing, valid date movement, and permanent deletion.
- User-visible notes.
- Authoritative time-zone confirmation and change behavior.
- Restricted cleanup of legacy future-dated entries.
- Independent loading, failure, stale, retry, and mutation-recovery states.
- Equivalent accessibility across platform-supported workflows.

Version 1.1 remains a personally controlled, private/internal, single-owner product. One owner may use multiple active clients.

## 3. Product invariants

### 3.1 Date authority

- A Daily Log Add Food flow must receive the originating Daily Log calendar date as immutable context.
- The selected date must remain visible throughout discovery and confirmation and before commit.
- The date must not be editable within the Add Food flow. Logging to another date requires cancellation and initiation from that date’s Daily Log.
- Successful creation must return to the originating date and immediately show the confirmed entry.
- No component may implicitly substitute the current date.
- Midnight rollover must update the definition of Today and related controls without navigating or retargeting an active view or workflow.
- Every visible entry, total, and target state must belong to the selected date.
- When the selected date changes, content from the prior date must be retired immediately and replaced with date-specific loading, failure, or success states.
- Previous and Next day navigation must use calendar-date arithmetic in the authoritative time zone, not elapsed 24-hour durations.
- During ordinary browsing, Next day must stop at Today.
- A Today shortcut must be available whenever a different supported date is selected.
- Direct date selection must remain available.

### 3.2 Authoritative user calendar

- Today, past, future, rollover, navigation limits, and mutation validity must derive from one authoritative user IANA time-zone identifier provided by the application.
- Device clock or time-zone changes must not silently change Daily Log semantics.
- Before the first Version 1.1 Daily Log mutation, an authoritative user time zone must be established.
- If the authoritative time zone has not yet been established, the application must require explicit establishment before permitting Daily Log mutations. The client's current time zone may be proposed but must never be silently adopted.
- Before confirmation, history must remain browsable in read-only provisional mode through adjacent navigation and direct date selection.
- Provisional Today and future classifications may use the clearly identified proposed zone.
- Add, Repeat, Edit, Delete, and all other Daily Log mutations must be unavailable until confirmation.
- Initial confirmation must re-evaluate the currently viewed date and controls without navigating away or discarding the viewing context.
- A time-zone change must require confirmation that shows:
  - the current and proposed named zones;
  - whether Today will change;
  - the number of entries that will become future-dated;
  - a way to review affected dates or entries; and
  - an explanation that entries will be reclassified, not moved, modified, or deleted.
- A zone change must not be blocked solely because it reclassifies entries as future-dated.
- An Add or Edit flow active during a zone change must retain its selected date and entered values, disclose the context change, and revalidate immediately before commit.
- If revalidation makes the selected date future-dated, commit must be blocked without choosing a substitute date.

### 3.3 Historical nutrition

- Food or Recipe changes must never automatically alter nutrition already recorded in a Daily Log.
- Existing entries are historically stable but not append-only: explicit permitted edits may replace metadata or nutritional snapshots.
- Metadata-only edits must preserve existing nutritional snapshots.
- Nutrition-affecting edits must atomically replace snapshots using the same current authoritative source.
- Repeat, backdated creation, and nutrition-affecting edits must use the authoritative source definition at commit time. The consumption date must not select or reconstruct a historical source definition.
- The source Food or Recipe identity of an existing entry must remain fixed for that entry’s lifetime.

## 4. Normal Daily Log

### 4.1 Date presentation and meal groups

- Breakfast, Lunch, Dinner, and Snack must appear in that fixed order on every supported date, including when empty.
- These groups must remain expanded and must each provide Add Food.
- Unassigned must appear after the named groups only when it contains entries.
- Unassigned represents the absence of a meal assignment and must not provide its own Add action.
- A general Add Food action must provide the canonical entry point without a meal assignment.
- A named group’s Add Food action must initialize confirmation with that meal selected. The user may change or clear it.
- Meal groups are organizational only. Nutrition totals and target comparisons must remain day-level.
- Entries must not be hidden through collapsing, filtering, manual reordering, or rearrangement.
- Within each group, entries must be ordered by creation time ascending, with the stable entry identifier as the deterministic tie-breaker.
- Editing an entry must not change its creation time.
- Creation time must not be presented as a user-authored consumption time or imply when consumption occurred.

### 4.2 Empty days

- A supported date with no entries must state: “No food logged for this date.”
- The four named meal groups and their Add Food actions must remain available.
- Absence of entries must represent unknown consumption, not confirmed zero intake or successful 0% target progress.

## 5. Add Food workflow

### 5.1 Discovery

The hierarchy must be:

1. Daily Log
2. Add Food discovery
3. Log Food confirmation

When the search query is empty, discovery must show these sections in order:

1. Recent Entries
2. Favorites
3. Recent Foods
4. Saved Foods

When the query is non-empty:

- Browse shortcuts must be replaced by clearly separated Saved Foods and USDA result groups.
- Clearing the query must restore browse mode without losing Daily Log context.

Selecting a saved Food, Favorite, or Recent Food must proceed directly to Log Food confirmation without an intervening Food Detail step.

USDA results must use the existing explicit import flow. Successful import must create a reusable Food and continue automatically to Log Food confirmation. Import alone must never create a Daily Log entry.

Custom Food and Scan Label must remain handoffs to their existing creation workflows. Successful creation must continue to Log Food confirmation. Cancelling confirmation after creation must leave the new Food saved without creating a Log entry.

Scan Label must be available and qualified on supported iOS clients. Android must not display Scan Label or expose a route into unsupported OCR behavior.

Core saved-Food and historical views must not depend on live USDA availability.

### 5.2 Confirmation

Every acquisition path must converge on the same confirmation step. Before commit, the user must review:

- the immutable target date;
- the current authoritative Food or active published Recipe source;
- serving;
- amount;
- meal assignment;
- notes; and
- any other log-specific values.

Creating or importing a Food and creating a Daily Log entry must remain separate, explicitly confirmed transactions. Selection, cancellation, or an acquisition handoff must never commit a Log entry.

If the selected Food or serving changes while confirmation is open:

- the application must not choose a replacement silently;
- save must be blocked;
- the current definition must be refreshed;
- ambiguous nutrition-affecting selections must be cleared; and
- the user must explicitly review the updated values.

If the source is no longer loggable, the user must return to discovery with the target date preserved.

### 5.3 Cancellation and transient context

- Cancelling confirmation must return to discovery.
- Cancelling discovery must return to the originating Daily Log.
- Returning to discovery must restore the target date, originating meal default, browse or search mode, query, section state, scroll position, and other transient discovery context.
- Unsubmitted workflow state must remain transient.
- It must be preserved during ordinary backgrounding while the process remains alive.
- Process termination may discard unsubmitted state and must never create a partial entry.
- Durable draft and resume behavior is not included.

### 5.4 Entry-load failure during Add

- Add Food must remain available for a valid date when existing entries fail to load.
- The user must receive a clear warning that the day cannot be reviewed and duplicate logging is possible.
- Recent Entries must remain unavailable until its required data loads.
- Other discovery sources must preserve their independent availability.
- Restrictions caused by unresolved uncertain mutations must take precedence.

## 6. Repeat through Recent Entries

- Repeat must be the only history-derived authoring workflow. Version 1.1 must not provide a separate Duplicate Log Entry capability.
- Each Repeat operation must prepare exactly one new entry and require Log Food confirmation.
- Recent Entries must contain the 10 most recently created eligible entries, ordered newest first.
- There must be no rolling-day cutoff or deduplication.
- Each historical event must remain a distinct choice and show its log date, meal when present, serving and amount, and whether a note exists.
- An entry is eligible only when:
  - its source date is Today or earlier; and
  - its underlying Food or active published Recipe is currently loggable.
- Eligibility must not require every historical value to remain reusable.
- Repeat must use the current authoritative Food or active published Recipe revision at commit, not the source entry’s nutritional snapshots.
- The target date must be the currently viewed Daily Log date and must remain immutable.
- Food, an unambiguously resolvable serving and amount, and meal may be prefilled.
- Serving or amount fields that cannot be mapped safely must remain unselected until the user chooses valid current values.
- Explicit meal-group context must override the historical meal.
- General Add may reuse a supported historical meal; otherwise meal must remain unset.
- Unsupported legacy meal values must never be propagated.
- Notes must be blank by default.
- A compliant historical note may be shown as read-only reference with an explicit Copy notes action.
- Notes must never be copied automatically or truncated.
- An overlength legacy note must not offer Copy notes.
- Repeat must not copy stale nutrition, entry identifiers, timestamps, or event provenance.
- Copy Meal, Copy Day, bulk Repeat, bulk reassignment, and bulk deletion are excluded.

## 7. Editing and moving entries

- Edit may change date, meal, notes, and—when the same source remains resolvable—serving and amount.
- Correcting the source identity must require confirmed deletion followed by a new Add Food flow.
- Date, meal, and note changes must preserve existing nutritional snapshots.
- A valid date move must transfer the entry to the destination Daily Log without changing its snapshots.
- Serving or amount changes must replace nutritional snapshots using the same current authoritative source.
- Prior versions of an edited entry are not retained.
- If the source is unavailable, the user may still:
  - assign a supported meal;
  - clear the meal;
  - edit notes;
  - move the entry to a valid date; or
  - delete the entry.
- Any edit requiring nutrition recalculation must be rejected while the source is unavailable.
- A successful date move must navigate to the destination Daily Log and show the entry there.
- Source and destination totals and target progress must refresh independently from their resulting entry sets.
- An edit without a date change must remain on the current Daily Log.

## 8. Deleting entries

- Delete must require explicit confirmation identifying the entry and date with sufficient context, including name and applicable meal, serving, and amount.
- Confirmation must explain that only the Daily Log entry and its historical nutritional snapshots will be removed.
- Reusable Foods, Recipes, USDA imports, and other catalog data must remain unchanged.
- After deletion, the user must remain on the same date and see the updated groups or empty state.
- Confirmed deletion must be permanent.
- Undo, recycle bin, soft delete, and recovery windows are excluded.

## 9. Field and validation requirements

### 9.1 Meal assignment

- The only supported assigned meal identifiers are `breakfast`, `lunch`, `dinner`, and `snack`.
- Meal assignment is optional.
- Unassigned must be represented as the canonical absence of a value, not as a fifth meal identifier.
- Meal assignment must result only from explicit user intent.
- Time-of-day inference and automatic meal classification are prohibited.

### 9.2 Notes

- Notes must be optional plain text.
- Line breaks must be preserved.
- Leading and trailing whitespace must be trimmed.
- A trimmed empty note must be treated as absent.
- New or explicitly edited notes must not exceed 1,000 Unicode code points.
- Overlength input must be rejected with clear validation before save.
- The same note contract must apply across supported clients and authoritative validation.
- Rich text, formatting, hyperlink behavior, mentions, images, files, and attachments are excluded.
- A note preview must use at most two visual lines.
- Overflow must use an ellipsis and provide Show more.
- Show more must reveal the full note in place and provide Show less.
- Expansion must be independent for each entry, remain read-only, and not enter Edit.
- Entries without notes must reserve no note space.

## 10. Compatibility behavior

### 10.1 Legacy future-dated entries

- No Version 1.1 mutation may create a newly persisted future-dated entry.
- Existing or time-zone-reclassified future entries must be preserved as compatibility data until resolved.
- A future entry may be viewed or deleted.
- It may be edited only when the same save moves it to Today or an earlier date.
- A save that leaves the entry future-dated must be rejected regardless of which fields changed.
- Moving an entry between future dates is prohibited.
- A future entry must not be used as a Repeat source.
- Once moved into the supported range, an otherwise eligible entry may return to Recent Entries.

Future dates must use a dedicated legacy cleanup experience rather than the normal Daily Log.

When entries exist, the cleanup experience must:

- present a flat identifying list;
- allow only View, Delete, and Edit-to-move actions; and
- show the Food or Recipe, date, serving and amount, note preview, unsupported-meal notice, and other identifying metadata.

An empty future date must show “No legacy entries on this future date” and provide navigation back to the supported range.

Future-date screens must omit meal groups, Add Food, Repeat, totals, target progress, and the ordinary empty-day state.

### 10.2 Unsupported legacy meals

- Unsupported legacy meal values must remain preserved until an explicit meal edit.
- They must be presented within Unassigned with a safely escaped, visually bounded notice.
- Unrelated metadata edits must not force meal cleanup.
- Selecting a supported meal or clearing the meal must replace the legacy value.
- Unsupported values must never be offered as Version 1.1 choices or propagated through Repeat.

### 10.3 Legacy overlength notes

- Existing notes longer than 1,000 Unicode code points must remain intact and readable until the note itself is edited.
- Unrelated metadata edits must not require shortening them.
- They may appear as read-only Repeat references but must not offer Copy notes.

## 11. Loading, failure, and recovery

### 11.1 Independent reads

- Entries, nutrition totals, and target progress must load independently.
- Each section must present its own loading, success, failure, stale, and retry state without misrepresenting another section.
- Entry-load failure must never appear as an empty day.
- Totals or target failure must not hide successfully loaded entries.
- Retrying one section should not unnecessarily discard successful content elsewhere.
- During same-date refresh, previously confirmed content may remain visible only when clearly marked stale or potentially stale.
- Content from another date must never remain visible during date navigation.

### 11.2 Confirmed mutations

- Create, edit, move, and delete must share one post-commit behavior.
- Once authoritatively confirmed, the mutation result must be reflected immediately.
- Subsequent view refreshes must be treated as independent reads.
- Refresh failure must not make a confirmed mutation uncertain:
  - a confirmed create remains visible;
  - a confirmed move remains at its destination;
  - a confirmed edit remains changed; and
  - a confirmed delete remains absent.

### 11.3 Uncertain mutations

- A submission with an indeterminate commit outcome must become an uncertain mutation.
- Its exact submitted payload and identity must remain locked until authoritative reconciliation.
- It must not be edited or casually resubmitted.
- Reconciliation or retry must use the same mutation intent.
- Confirmed success must complete the intent.
- Confirmed non-commit must make the intent safely retryable.
- Edit and delete reconciliation must refresh the affected entry.
- Move reconciliation must check both source and destination dates.
- Optimistic local state must never be treated as proof of commit.
- The originating client must retain only the minimal locked recovery record required across process termination.
- This recovery record must not function as a draft, resume mechanism, offline queue, or source of new work, and must not synchronize to other clients.
- Dismissing a recovery prompt must not erase or resolve uncertainty.
- A separate action that could duplicate or conflict with the unresolved mutation must require an explicit warning that the original operation may already have committed.
- Other clients must rely on authoritative state rather than the originating client’s pending intent.
- If another client changes or deletes an entry before commit, the active workflow must stop, refresh authoritative state, and require review before another mutation.
- Automatic merging, collaborative editing, field-level merging, synchronized pending intents, and cross-device recovery coordination are excluded.

## 12. Accessibility and release qualification

Epic 1 must not be considered complete until every supported workflow is operable with VoiceOver on iOS and TalkBack on Android.

Qualification must cover:

- date navigation and direct date selection;
- meal groups and general or meal-specific Add Food;
- browse, search, Recent Entries, and Repeat;
- supported acquisition handoffs;
- Log Food confirmation;
- editing, moving, notes, and deletion;
- loading, errors, stale states, and retries;
- uncertain-mutation recovery; and
- destructive confirmations.

iOS qualification must include Scan Label. Android qualification must cover the shared workflow while omitting the unsupported Scan Label action.

Dynamic text and large accessibility sizes, supported keyboard navigation, appropriate labels and roles, logical focus order, and useful announcements for dynamic changes are release requirements. Assistive-technology users must receive equivalent capability through the same logical workflows.

## 13. Non-goals

Epic 1 must not introduce:

- Meal planning, schedules, reminders, notifications, custom meals, automatic meal classification, per-meal nutrition analysis, or consumption times.
- Offline authoring, offline mutation queues, durable unsubmitted drafts, or synchronization.
- Copy Meal, Copy Day, bulk operations, a separate Duplicate action, source replacement during Edit, group filtering or collapse, or manual ordering.
- Undo, recycle bin, soft delete, or deleted-entry recovery.
- Automatic recalculation of historical Logs from changed Foods or Recipes.
- Reconstruction of historical source definitions based on consumption date.
- Redesign of USDA import, Custom Food creation, or Scan Label internals.
- Android OCR.
- Collaborative editing, automatic conflict merging, synchronized pending intents, or multi-device workflow continuity.
- Rich-text notes or attachments.
- New analytics instrumentation.
- Public or multi-user accounts, sharing, social features, or collaborative Recipes.
- Technology migrations, architectural rewrites, or persistence redesigns.

## 14. Architecture gate

Architecture Review must determine whether authoritative time-zone behavior and client-local uncertain-mutation recovery fit the roadmap’s evolutionary architectural boundary.

If authoritative time-zone support requires a persistence redesign, fundamental data-model change, architectural rewrite, or other expansion beyond that boundary, implementation must stop and return to roadmap review. The scope must not expand silently.

The same stop-and-review requirement applies if client-local uncertain-mutation recovery requires a persistence redesign or architectural rewrite.

## 15. Success criteria

Epic 1 is successful when release evidence demonstrates that:

1. Users can browse a trustworthy date-only Daily Log and distinguish empty, loading, failed, and stale states without seeing data from the wrong date.
2. Users can begin from general or meal-specific Add Food, use every platform-supported discovery source, and reach one explicit confirmation without unrelated detail navigation.
3. Date, meal precedence, authoritative source, and log fields remain visible and correct through confirmation, cancellation, commit, and return.
4. Users can repeat one eligible historical event without copying stale nutrition, unsupported meals, event-specific notes, identifiers, timestamps, or provenance.
5. Users can view and edit meal and notes, make permitted serving or amount corrections, move entries between valid dates, and permanently delete entries with clear consequences.
6. Normal mutations cannot create future-dated entries, while compatible future entries remain discoverable and resolvable through restricted cleanup.
7. Partial read failures preserve independently usable content, and confirmed and uncertain mutation outcomes remain unambiguous.
8. All active clients use one authoritative interpretation of Today and the supported logging range.
9. VoiceOver, TalkBack, large text, and supported keyboard workflows provide equivalent access to every platform-supported capability.

No elapsed-time target, tap-count target, or new product analytics instrumentation is required.