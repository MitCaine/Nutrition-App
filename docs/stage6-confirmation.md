# Stage 6B–6C: reviewed OCR Food creation and reliability closeout

Stage 6B adds a production Saved Foods entry point named **Scan label**. The bounded flow is: choose a still photo or take one, run Apple Vision locally, send only ordered OCR text observations to the deterministic Stage 6A parser, review a separate confirmation draft, and explicitly create a Food. Cancellation before submission creates nothing. Recognition, parsing, confirmation, and transport failures keep recoverable state or return to acquisition without silently creating a Food.

## Parser authority and mobile boundary

Ordered observations are authoritative whenever the parse request contains any observations. `full_text` is used only when observations are absent; the parser never reconciles or supplements an observation-backed parse with `full_text`. Golden-corpus invariants test this by changing `full_text` without changing an observation-backed result.

Mobile maps Apple camel-case boxes to the parser's snake-case contract and validates every parser response with a strict Zod schema. Unknown or extra response shapes fail the parse step. Decimal JSON values become strings at this boundary and remain strings through editing and request construction.

## Confirmation and review

The confirmation draft is not a parser response, Manual Food form state, or API payload. It holds editable Food identity, serving fields, canonical nutrient suggestions, parser status/confidence/warnings, source text and observation IDs, comparison semantics, and one of four local review states: `accepted`, `edited`, `omitted`, or `unresolved`.

Calories always starts unresolved. Ambiguous, low-confidence, conflicting, and less-than suggestions start unresolved. Creation is blocked until the name is nonempty, the label serving has a positive gram weight, calories and every flagged canonical field are reviewed, unknown rows are dismissed, and retained values are finite and nonnegative. Printed zero is retained as `data_status=zero`; missing values stay omitted. A `<1g` suggestion is never accepted as exactly 1 g: the user must enter an exact replacement or omit it, and that resolution is traced.

Unknown nutrient rows remain visible with their source text. Dismissal records them in the trace, but they never become `food_nutrients`.

## Serving and nutrition basis

Confirmed nutrients use the label's per-serving basis. Every created Food receives the reviewed label serving as the default amount and requires its positive gram equivalent. It also receives the app's fixed non-default `100 g` amount. A grams-only label is represented as an explicit one-serving amount with its reviewed gram weight; no household-to-gram conversion is invented. A household measure without grams cannot be submitted in this flow.

The resulting record is an ordinary editable `source_type=manual` Food. Saved Foods, Food Detail, serving/gram logging, duplication, deletion, and nutrition resolution use existing Food behavior. The correction trace is creation provenance and is never current Food state or resolver input. Editing nutrients changes the ordinary Manual Food only; editing, duplicating, logging, Food Detail, and soft deletion never consult or rewrite the trace. A duplicate gets no copied trace, and soft deletion preserves the original trace.

## Correction trace and transaction

`POST /api/v1/ocr/nutrition-label/confirm` accepts the supported parser version, image source (`camera` or `photo_library`), a client request UUID, validated Food graph, enumerated field decisions, dismissed unknown rows, and bounded provenance. It creates the Food and its one-to-one, service-immutable / append-only `ocr_nutrition_confirmation_traces` record in one transaction. There is no public update/delete route or production mutation service, and the Food relationship cannot delete the trace as an orphan. This is an application-service guarantee, not database-level physical immutability.

The versioned `ocr_nutrition_confirmation_v1` JSON snapshot contains only sanitized decisions, unknown rows, source text/observation IDs, confidence, comparison/resolution, and warning codes. It is capped at 48 KB. Schema extras, unsupported nutrients/parser versions, incompatible units, unresolved ambiguity, mismatches between trace and Food values, source strings resembling local paths, and oversized fields are rejected. Image bytes, image URI/path, complete raw OCR text, marketing text, and arbitrary parser payloads are not persisted.

Per-user `(user_id, client_request_id)` uniqueness provides narrow confirmation idempotency. Only a violation of `uq_ocr_confirmation_user_request` enters race recovery; unrelated integrity failures propagate. An exact replay returns the original Food and trace; reuse with different content returns a structured conflict.

The request fingerprint canonically sorts mappings and uses JSON scalar serialization for Decimal and UUID values. Arrays remain ordered because nutrient review, unknown rows, decisions, and source provenance preserve user/source order. The fingerprint is private backend state.

Mobile binds a request ID to the canonical creation payload only when a valid network submission starts. An unchanged failed retry reuses that ID; changing identity, serving, nutrient review, ambiguity, unknown-dismissal, parser, image-source, or trace-decision content rotates it. Pre-request validation failures bind nothing. A synchronous ref guard permits one request, all controls and Cancel disable while pending, unmount suppresses stale navigation, and success navigates once.

Confirmation inputs expose screen-reader headings, specific field/action labels, review-state semantics, disabled/busy states, and assertive errors without making provenance lines noisy. Decimal strings reject exponent notation, infinity, unsupported punctuation, whitespace-only input, and malformed separators. Less-than suggestions still require an edit or omission, ambiguous fields require explicit resolution, and structured confirmation/parse errors become actionable messages while retaining the draft.

## QA boundary and limitations

Simulator QA should cover selected clean label images, unchanged/edit/omit/conflict/less-than review, grams-only and serving-plus-grams Foods, Saved Foods/Detail/log/edit behavior, cancellation, duplicate tapping, unchanged retry, edited retry, and parse/confirmation failure. Real camera capture and overlay alignment remain physical-device release QA. Parser behavior remains geometry-independent. Stage 6 is complete at the automated contract level; release-device QA remains outstanding. Stage 6 still excludes automatic creation, live OCR, Android OCR, image persistence, ingredient/allergen/claim extraction, barcode lookup, cloud/LLM parsing, and correction learning.
