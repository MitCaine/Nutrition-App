import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { File } from "expo-file-system";
import type { SQLiteDatabase } from "expo-sqlite";
import { Platform } from "react-native";

import type { FoodCreateInput } from "../../features/foods/api/types";
import type { DailyLogDeleteInput, DailyLogUpdateInput } from "../../features/logging/api/types";
import {
  LOG_MUTATION_RECOVERY_STORAGE_KEY,
  createLogMutationRecoveryRecord,
  loadLogMutationRecoveryJournal,
  persistRecoveryBeforeTransmission,
  reconcileLogMutationRecoveryRecord,
  type LogMutationRecoveryRecord,
  type RecoveryReconcileResult,
} from "../../features/logging/recovery/logMutationRecovery";
import type { OcrConfirmationInput, TraceFieldDecisionInput } from "../../features/ocr/api/types";
import type { TargetConfigurationInput } from "../../features/targets/api/types";
import {
  canonicalJsonStringify,
  parseUuid,
} from "../../shared/exact/canonicalValues";
import {
  bootstrapOpenedLocalRuntimeFoundation,
} from "../../runtime/local/localRuntimeFoundation";
import { createLocalCalendarRuntime } from "../../runtime/local/localCalendarRuntime";
import { createLocalDailyLogsRuntime } from "../../runtime/local/localDailyLogsRuntime";
import { createLocalFoodsRuntime } from "../../runtime/local/localFoodsRuntime";
import { createLocalOcrRuntime } from "../../runtime/local/localOcrRuntime";
import { createLocalRecipesRuntime } from "../../runtime/local/localRecipesRuntime";
import { createLocalTargetsRuntime } from "../../runtime/local/localTargetsRuntime";
import type { NutritionDatabaseHandle } from "../../storage/sqlite/migrations";
import {
  qualifyE216Database,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import {
  E216_STAGE_D_CHECKPOINT_FILE_NAME,
  E216_STAGE_D_CHECKPOINT_SCHEMA,
  E216_STAGE_D_CONTROL_CHECKPOINT_FILE_NAME,
  E216_STAGE_D_CONTROL_CHECKPOINT_SCHEMA,
  openE216QualificationDatabase,
  qualificationDatabaseDirectory,
  qualificationDatabaseName,
  resetE216QualificationDatabase,
} from "./e216QualificationFoundation";

export type E216StageDMutationFamily =
  | "food_create"
  | "recipe_publish"
  | "daily_log_edit"
  | "daily_log_delete"
  | "target_update"
  | "ocr_confirmation";

export type E216StageDTerminationCheckpoint = "during_transaction" | "post_commit";

export type E216StageDCaseId =
  `${E216StageDMutationFamily}_${E216StageDTerminationCheckpoint}`;

export type E216StageDCheckpointReached =
  | "before_mutation"
  | "inside_transaction_before_commit"
  | "after_durable_commit"
  | "after_restart_reconciliation";

type E216StageDCaseDefinition = Readonly<{
  id: E216StageDCaseId;
  family: E216StageDMutationFamily;
  checkpoint: E216StageDTerminationCheckpoint;
  title: string;
  transactionStage: string | null;
  description: string;
}>;

const FAMILY_DEFINITIONS = Object.freeze([
  {
    family: "food_create" as const,
    title: "Food create",
    transactionStage: "after_servings",
    description: "Food row, serving children, nutrient children, and create receipt remain one atomic write.",
  },
  {
    family: "recipe_publish" as const,
    title: "Recipe publication",
    transactionStage: "after_projection_nutrients",
    description: "The prior active revision/projection survives or the complete successor revision/projection commits.",
  },
  {
    family: "daily_log_edit" as const,
    title: "Daily Log nutrition edit",
    transactionStage: "after_old_snapshots_removed",
    description: "Snapshot replacement uses the established scoped transaction, durable journal, and mutation status.",
  },
  {
    family: "daily_log_delete" as const,
    title: "Daily Log delete",
    transactionStage: "after_delete_snapshots_removed",
    description: "Log and snapshots delete atomically under the established journal and mutation-status path.",
  },
  {
    family: "target_update" as const,
    title: "Target update",
    transactionStage: "after_write",
    description: "Profile and manual target rows commit together; restart reconciliation is authoritative reread only.",
  },
  {
    family: "ocr_confirmation" as const,
    title: "OCR confirmation",
    transactionStage: "before_trace",
    description: "The complete Food graph and immutable confirmation trace share the production transaction.",
  },
] as const);

export const E216_STAGE_D_CASE_DEFINITIONS: readonly E216StageDCaseDefinition[] = Object.freeze(
  FAMILY_DEFINITIONS.flatMap((definition) => ([
    Object.freeze({
      ...definition,
      id: `${definition.family}_during_transaction` as E216StageDCaseId,
      checkpoint: "during_transaction" as const,
    }),
    Object.freeze({
      ...definition,
      id: `${definition.family}_post_commit` as E216StageDCaseId,
      checkpoint: "post_commit" as const,
      transactionStage: null,
    }),
  ])),
);

type E216StageDContext = Readonly<{
  ownerId: string;
  requestId: string | null;
  resourceId: string | null;
  servingId: string | null;
  sourceDate: string | null;
}>;

type E216StageDPreMutationControlContext = Readonly<{
  ownerId: string;
  requestId: string;
  fixtureResourceId: string;
}>;

export type E216StageDMutationState = Readonly<Record<string, unknown>>;

export type E216StageDReceiptEvidence = Readonly<{
  operation: string;
  present: boolean;
  resourceId: string | null;
  completed: boolean;
}> | null;

export type E216StageDRecoveryEvidence = Readonly<{
  beforeReconciliation: readonly Readonly<{
    id: string;
    state: string;
  }>[];
  mutationStatus: string;
  reconciliation: RecoveryReconcileResult;
  afterReconciliation: readonly Readonly<{
    id: string;
    state: string;
  }>[];
}> | null;

export type E216StageDIdempotencyEvidence = Readonly<{
  applicable: boolean;
  replayed: boolean;
  unchangedAfterReplay: boolean | null;
  interpretation: string;
}>;

export type E216StageDCaseResult = Readonly<{
  caseId: E216StageDCaseId;
  family: E216StageDMutationFamily;
  checkpoint: E216StageDTerminationCheckpoint;
  terminationCheckpointReached: "inside_transaction_before_commit" | "after_durable_commit";
  checkpointStage: string;
  checkpointReached: "after_restart_reconciliation";
  expectedDurableState: "pre_mutation" | "post_commit";
  preMutationState: E216StageDMutationState;
  postCommitState: E216StageDMutationState | null;
  authoritativeDurableState: E216StageDMutationState;
  receipt: E216StageDReceiptEvidence;
  recovery: E216StageDRecoveryEvidence;
  idempotency: E216StageDIdempotencyEvidence;
  directIntegrity: E216DirectIntegrityResult;
  status: "pass" | "fail";
  diagnostics: readonly string[];
}>;

export type E216StageDCheckpointMarker = Readonly<{
  schema: typeof E216_STAGE_D_CHECKPOINT_SCHEMA;
  stage: "E2-16D";
  caseId: E216StageDCaseId;
  family: E216StageDMutationFamily;
  checkpoint: E216StageDTerminationCheckpoint;
  checkpointReached: E216StageDCheckpointReached;
  checkpointStage: string;
  platform: "ios";
  databaseName: "e2_16_termination_ios.db";
  processSessionId: string;
  state: "ready_to_arm" | "awaiting_termination" | "completed";
  expectedDurableState: "pre_mutation" | "post_commit";
  context: E216StageDContext;
  preMutationState: E216StageDMutationState;
  postCommitState: E216StageDMutationState | null;
  result: E216StageDCaseResult | null;
}>;

/**
 * One shared control case proves process death before any mutation-under-test
 * has been invoked.  It deliberately has its own marker so the twelve
 * family-specific Stage-D cases retain their accepted schema and matrix.
 */
export type E216StageDPreMutationControlResult = Readonly<{
  caseId: "pre_mutation_control";
  checkpointReached: "after_restart_reconciliation";
  expectedDurableState: "pre_mutation";
  preMutationState: E216StageDMutationState;
  authoritativeDurableState: E216StageDMutationState;
  receipt: E216StageDReceiptEvidence;
  idempotency: E216StageDIdempotencyEvidence;
  unexpectedResource: boolean;
  unexpectedReceipt: boolean;
  directIntegrity: E216DirectIntegrityResult;
  status: "pass" | "fail";
  diagnostics: readonly string[];
}>;

export type E216StageDPreMutationControlCheckpointMarker = Readonly<{
  schema: typeof E216_STAGE_D_CONTROL_CHECKPOINT_SCHEMA;
  stage: "E2-16D";
  caseId: "pre_mutation_control";
  checkpoint: "before_mutation";
  checkpointReached: "before_mutation" | "after_restart_reconciliation";
  checkpointStage: "fixture_committed_before_mutation" | "authoritative_reread_and_direct_integrity";
  platform: "ios";
  databaseName: "e2_16_termination_ios.db";
  processSessionId: string;
  state: "awaiting_termination" | "completed";
  expectedDurableState: "pre_mutation";
  context: E216StageDPreMutationControlContext;
  preMutationState: E216StageDMutationState;
  result: E216StageDPreMutationControlResult | null;
}>;

const PROCESS_SESSION_ID = parseUuid(Crypto.randomUUID());
const FOOD_REQUEST_ID = "00000000-0000-4000-8000-00000000d101";
const RECIPE_BASELINE_REQUEST_ID = "00000000-0000-4000-8000-00000000d201";
const RECIPE_REQUEST_ID = "00000000-0000-4000-8000-00000000d202";
const DAILY_SETUP_REQUEST_ID = "00000000-0000-4000-8000-00000000d301";
const DAILY_EDIT_REQUEST_ID = "00000000-0000-4000-8000-00000000d302";
const DAILY_DELETE_REQUEST_ID = "00000000-0000-4000-8000-00000000d303";
const OCR_REQUEST_ID = "00000000-0000-4000-8000-00000000d501";
const PRE_MUTATION_CONTROL_REQUEST_ID = "00000000-0000-4000-8000-00000000d601";
const FIXTURE_DATE = "2026-08-11";
const FOOD_NAME = "E2-16D Food termination fixture";
const RECIPE_NAME = "E2-16D Recipe termination fixture";
const DAILY_FOOD_NAME = "E2-16D Daily Log source";
const OCR_FOOD_NAME = "E2-16D OCR confirmation fixture";
const PRE_MUTATION_CONTROL_FIXTURE_NAME = "E2-16D pre-mutation committed fixture";
const PRE_MUTATION_CONTROL_CANDIDATE_NAME = "E2-16D pre-mutation candidate";

let activeStageDHandle: NutritionDatabaseHandle | null = null;
let activeStageDMutationPending = false;

function assertIos(): void {
  if (Platform.OS !== "ios") {
    throw new Error("E2-16D process-termination qualification is supported only on iOS.");
  }
}

function definitionFor(caseId: E216StageDCaseId): E216StageDCaseDefinition {
  const definition = E216_STAGE_D_CASE_DEFINITIONS.find((candidate) => candidate.id === caseId);
  if (!definition) throw new Error("E2-16D case identifier is invalid.");
  return definition;
}

function stageDCheckpointFile(): File {
  return new File(qualificationDatabaseDirectory(), E216_STAGE_D_CHECKPOINT_FILE_NAME);
}

function stageDControlCheckpointFile(): File {
  return new File(
    qualificationDatabaseDirectory(),
    E216_STAGE_D_CONTROL_CHECKPOINT_FILE_NAME,
  );
}

function freezeMarker(marker: E216StageDCheckpointMarker): E216StageDCheckpointMarker {
  return Object.freeze(marker);
}

function freezeControlMarker(
  marker: E216StageDPreMutationControlCheckpointMarker,
): E216StageDPreMutationControlCheckpointMarker {
  return Object.freeze(marker);
}

/** The process identity is intentionally module-local; callers can only compare against it. */
export function isE216StageDCurrentProcessSession(processSessionId: string): boolean {
  return processSessionId === PROCESS_SESSION_ID;
}

/** Synchronous native write plus exact readback before a checkpoint becomes owner-visible. */
export function writeE216StageDCheckpoint(
  marker: E216StageDCheckpointMarker,
): E216StageDCheckpointMarker {
  const file = stageDCheckpointFile();
  const document = canonicalJsonStringify(marker);
  file.create({ intermediates: true, overwrite: true });
  file.write(document);
  if (!file.exists || file.textSync() !== document) {
    throw new Error("E2-16D checkpoint marker was not durably written and verified.");
  }
  return marker;
}

/** Synchronous native write plus exact readback for the shared pre-mutation control. */
export function writeE216StageDPreMutationControlCheckpoint(
  marker: E216StageDPreMutationControlCheckpointMarker,
): E216StageDPreMutationControlCheckpointMarker {
  const file = stageDControlCheckpointFile();
  const document = canonicalJsonStringify(marker);
  file.create({ intermediates: true, overwrite: true });
  file.write(document);
  if (!file.exists || file.textSync() !== document) {
    throw new Error("E2-16D pre-mutation control marker was not durably written and verified.");
  }
  return marker;
}

function isMutationFamily(value: unknown): value is E216StageDMutationFamily {
  return FAMILY_DEFINITIONS.some((definition) => definition.family === value);
}

function isCaseId(value: unknown): value is E216StageDCaseId {
  return typeof value === "string"
    && E216_STAGE_D_CASE_DEFINITIONS.some((definition) => definition.id === value);
}

function isContext(value: unknown): value is E216StageDContext {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<E216StageDContext>;
  const nullableUuid = (entry: unknown) => entry === null
    || (typeof entry === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(entry));
  return nullableUuid(candidate.ownerId)
    && candidate.ownerId !== null
    && nullableUuid(candidate.requestId)
    && nullableUuid(candidate.resourceId)
    && nullableUuid(candidate.servingId)
    && (candidate.sourceDate === null || typeof candidate.sourceDate === "string");
}

function isPreMutationControlContext(value: unknown): value is E216StageDPreMutationControlContext {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<E216StageDPreMutationControlContext>;
  const uuid = (entry: unknown) => typeof entry === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(entry);
  return uuid(candidate.ownerId) && uuid(candidate.requestId) && uuid(candidate.fixtureResourceId);
}

function isMarkerStateCoherent(
  marker: Partial<E216StageDCheckpointMarker>,
  definition: E216StageDCaseDefinition,
): boolean {
  if (marker.expectedDurableState !== (definition.checkpoint === "during_transaction" ? "pre_mutation" : "post_commit")) {
    return false;
  }
  if (marker.state === "ready_to_arm") {
    return marker.checkpointReached === "before_mutation"
      && marker.checkpointStage === "fixture_committed_before_mutation"
      && marker.postCommitState === null
      && marker.result === null;
  }
  if (marker.state === "awaiting_termination") {
    return definition.checkpoint === "during_transaction"
      ? marker.checkpointReached === "inside_transaction_before_commit"
        && marker.checkpointStage === definition.transactionStage
        && marker.postCommitState === null
        && marker.result === null
      : marker.checkpointReached === "after_durable_commit"
        && marker.checkpointStage === "production_mutation_promise_resolved"
        && typeof marker.postCommitState === "object"
        && marker.postCommitState !== null
        && marker.result === null;
  }
  return marker.state === "completed"
    && marker.checkpointReached === "after_restart_reconciliation"
    && marker.checkpointStage === "authoritative_reread_reconciliation_and_direct_integrity"
    && typeof marker.result === "object"
    && marker.result !== null;
}

export function readE216StageDCheckpoint(): E216StageDCheckpointMarker | null {
  const file = stageDCheckpointFile();
  if (!file.exists) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(file.textSync()) as unknown;
  } catch {
    throw new Error("E2-16D checkpoint marker is unreadable.");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("E2-16D checkpoint marker is invalid.");
  }
  const marker = parsed as Partial<E216StageDCheckpointMarker>;
  const definition = isCaseId(marker.caseId) ? definitionFor(marker.caseId) : null;
  if (
    marker.schema !== E216_STAGE_D_CHECKPOINT_SCHEMA
    || marker.stage !== "E2-16D"
    || definition === null
    || marker.family !== definition.family
    || marker.checkpoint !== definition.checkpoint
    || !isMutationFamily(marker.family)
    || !["before_mutation", "inside_transaction_before_commit", "after_durable_commit", "after_restart_reconciliation"].includes(marker.checkpointReached as string)
    || marker.platform !== "ios"
    || marker.databaseName !== "e2_16_termination_ios.db"
    || typeof marker.processSessionId !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(marker.processSessionId)
    || !isContext(marker.context)
    || typeof marker.preMutationState !== "object"
    || marker.preMutationState === null
    || !["ready_to_arm", "awaiting_termination", "completed"].includes(marker.state as string)
    || !["pre_mutation", "post_commit"].includes(marker.expectedDurableState as string)
    || !isMarkerStateCoherent(marker, definition)
  ) {
    throw new Error("E2-16D checkpoint marker is invalid.");
  }
  return freezeMarker(marker as E216StageDCheckpointMarker);
}

function isControlMarkerStateCoherent(
  marker: Partial<E216StageDPreMutationControlCheckpointMarker>,
): boolean {
  if (marker.state === "awaiting_termination") {
    return marker.checkpointReached === "before_mutation"
      && marker.checkpointStage === "fixture_committed_before_mutation"
      && marker.result === null;
  }
  return marker.state === "completed"
    && marker.checkpointReached === "after_restart_reconciliation"
    && marker.checkpointStage === "authoritative_reread_and_direct_integrity"
    && typeof marker.result === "object"
    && marker.result !== null;
}

export function readE216StageDPreMutationControlCheckpoint(): E216StageDPreMutationControlCheckpointMarker | null {
  const file = stageDControlCheckpointFile();
  if (!file.exists) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(file.textSync()) as unknown;
  } catch {
    throw new Error("E2-16D pre-mutation control marker is unreadable.");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("E2-16D pre-mutation control marker is invalid.");
  }
  const marker = parsed as Partial<E216StageDPreMutationControlCheckpointMarker>;
  if (
    marker.schema !== E216_STAGE_D_CONTROL_CHECKPOINT_SCHEMA
    || marker.stage !== "E2-16D"
    || marker.caseId !== "pre_mutation_control"
    || marker.checkpoint !== "before_mutation"
    || !["before_mutation", "after_restart_reconciliation"].includes(marker.checkpointReached as string)
    || !["fixture_committed_before_mutation", "authoritative_reread_and_direct_integrity"].includes(marker.checkpointStage as string)
    || marker.platform !== "ios"
    || marker.databaseName !== "e2_16_termination_ios.db"
    || typeof marker.processSessionId !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(marker.processSessionId)
    || !isPreMutationControlContext(marker.context)
    || typeof marker.preMutationState !== "object"
    || marker.preMutationState === null
    || !["awaiting_termination", "completed"].includes(marker.state as string)
    || marker.expectedDurableState !== "pre_mutation"
    || !isControlMarkerStateCoherent(marker)
  ) {
    throw new Error("E2-16D pre-mutation control marker is invalid.");
  }
  return freezeControlMarker(marker as E216StageDPreMutationControlCheckpointMarker);
}

export function clearE216StageDCheckpoint(): void {
  const file = stageDCheckpointFile();
  if (file.exists) file.delete();
  if (file.exists) throw new Error("E2-16D checkpoint marker could not be removed.");
}

export function clearE216StageDPreMutationControlCheckpoint(): void {
  const file = stageDControlCheckpointFile();
  if (file.exists) file.delete();
  if (file.exists) throw new Error("E2-16D pre-mutation control marker could not be removed.");
}

function stateEqual(left: E216StageDMutationState, right: E216StageDMutationState): boolean {
  return canonicalJsonStringify(left) === canonicalJsonStringify(right);
}

async function receiptEvidence(
  database: SQLiteDatabase,
  ownerId: string,
  operation: string,
  requestId: string | null,
): Promise<E216StageDReceiptEvidence> {
  if (requestId === null) return null;
  const row = await database.getFirstAsync<{
    resource_id: string;
    response_snapshot: string | null;
    completed_at: string | null;
  }>(
    `SELECT "resource_id", "response_snapshot", "completed_at"
       FROM "create_operation_idempotency"
      WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
    [ownerId, operation, requestId],
  );
  return Object.freeze({
    operation,
    present: row !== null,
    resourceId: row?.resource_id ?? null,
    completed: row?.response_snapshot != null && row?.completed_at != null,
  });
}

async function count(
  database: SQLiteDatabase,
  sql: string,
  parameters: readonly (string | number | null)[] = [],
): Promise<number> {
  const row = await database.getFirstAsync<{ count: number }>(sql, [...parameters]);
  return row?.count ?? -1;
}

async function captureFoodState(
  database: SQLiteDatabase,
  context: E216StageDContext,
): Promise<E216StageDMutationState> {
  const receipt = await receiptEvidence(database, context.ownerId, "food.create_manual", context.requestId);
  const row = await database.getFirstAsync<{ id: string; name: string; deleted_at: string | null }>(
    `SELECT "id", "name", "deleted_at" FROM "food_items"
      WHERE "user_id" = ? AND "name" = ? ORDER BY "id" LIMIT 1`,
    [context.ownerId, FOOD_NAME],
  );
  return Object.freeze({
    family: "food_create",
    resourceId: row?.id ?? null,
    name: row?.name ?? null,
    deletedAt: row?.deleted_at ?? null,
    foodCount: await count(database, `SELECT COUNT(*) AS "count" FROM "food_items" WHERE "user_id" = ? AND "name" = ?`, [context.ownerId, FOOD_NAME]),
    servingCount: row ? await count(database, `SELECT COUNT(*) AS "count" FROM "serving_definitions" WHERE "food_item_id" = ?`, [row.id]) : 0,
    nutrientCount: row ? await count(database, `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ?`, [row.id]) : 0,
    receipt,
  });
}

async function captureRecipeState(
  database: SQLiteDatabase,
  context: E216StageDContext,
): Promise<E216StageDMutationState> {
  const recipe = await database.getFirstAsync<{
    active_publication_revision_id: string | null;
    published_food_item_id: string | null;
    needs_republish: number;
  }>(
    `SELECT "active_publication_revision_id", "published_food_item_id", "needs_republish"
       FROM "recipes" WHERE "id" = ? AND "user_id" = ?`,
    [context.resourceId, context.ownerId],
  );
  const projection = recipe?.published_food_item_id
    ? await database.getFirstAsync<{ recipe_publication_revision_id: string | null }>(
      `SELECT "recipe_publication_revision_id" FROM "food_items" WHERE "id" = ? AND "user_id" = ?`,
      [recipe.published_food_item_id, context.ownerId],
    )
    : null;
  return Object.freeze({
    family: "recipe_publish",
    recipeId: context.resourceId,
    activeRevisionId: recipe?.active_publication_revision_id ?? null,
    projectionId: recipe?.published_food_item_id ?? null,
    projectionRevisionId: projection?.recipe_publication_revision_id ?? null,
    needsRepublish: recipe?.needs_republish ?? null,
    revisionCount: await count(database, `SELECT COUNT(*) AS "count" FROM "recipe_publication_revisions" WHERE "recipe_id" = ? AND "user_id" = ?`, [context.resourceId, context.ownerId]),
    activeAmountCount: recipe?.active_publication_revision_id ? await count(database, `SELECT COUNT(*) AS "count" FROM "recipe_publication_amount_definitions" WHERE "revision_id" = ?`, [recipe.active_publication_revision_id]) : 0,
    activeNutrientCount: recipe?.active_publication_revision_id ? await count(database, `SELECT COUNT(*) AS "count" FROM "recipe_publication_nutrients" WHERE "revision_id" = ?`, [recipe.active_publication_revision_id]) : 0,
    projectionServingCount: recipe?.published_food_item_id ? await count(database, `SELECT COUNT(*) AS "count" FROM "serving_definitions" WHERE "food_item_id" = ?`, [recipe.published_food_item_id]) : 0,
    projectionNutrientCount: recipe?.published_food_item_id ? await count(database, `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ?`, [recipe.published_food_item_id]) : 0,
    receipt: await receiptEvidence(database, context.ownerId, "recipe.publish", context.requestId),
  });
}

async function captureDailyLogState(
  database: SQLiteDatabase,
  context: E216StageDContext,
  operation: "update" | "delete",
): Promise<E216StageDMutationState> {
  const row = await database.getFirstAsync<{
    logged_date: string;
    amount_quantity: string;
    amount_unit: string;
    serving_definition_id: string | null;
    notes: string | null;
  }>(
    `SELECT "logged_date", "amount_quantity", "amount_unit", "serving_definition_id", "notes"
       FROM "daily_logs" WHERE "id" = ? AND "user_id" = ?`,
    [context.resourceId, context.ownerId],
  );
  return Object.freeze({
    family: operation === "update" ? "daily_log_edit" : "daily_log_delete",
    logId: context.resourceId,
    present: row !== null,
    loggedDate: row?.logged_date ?? null,
    amountQuantity: row?.amount_quantity ?? null,
    amountUnit: row?.amount_unit ?? null,
    servingId: row?.serving_definition_id ?? null,
    notes: row?.notes ?? null,
    snapshotCount: await count(database, `SELECT COUNT(*) AS "count" FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`, [context.resourceId]),
    receipt: await receiptEvidence(database, context.ownerId, `log.${operation}`, context.requestId),
  });
}

async function captureTargetState(
  database: SQLiteDatabase,
  context: E216StageDContext,
): Promise<E216StageDMutationState> {
  const profile = await database.getFirstAsync<Record<string, unknown>>(
    `SELECT "birth_date", "height_cm", "weight_kg",
            "biological_sex_for_reference_calculations", "activity_level",
            "energy_estimation_context"
       FROM "user_profiles" WHERE "user_id" = ?`,
    [context.ownerId],
  );
  const targets = await database.getAllAsync<Record<string, unknown>>(
    `SELECT "nutrient_id", "target_amount", "unit", "basis", "source"
       FROM "nutrition_targets"
      WHERE "user_id" = ? AND "target_type" = 'manual_override'
      ORDER BY "nutrient_id"`,
    [context.ownerId],
  );
  return Object.freeze({ family: "target_update", profile: profile ?? null, manualTargets: targets });
}

async function captureOcrState(
  database: SQLiteDatabase,
  context: E216StageDContext,
): Promise<E216StageDMutationState> {
  const trace = await database.getFirstAsync<{ id: string; food_item_id: string; request_fingerprint: string }>(
    `SELECT "id", "food_item_id", "request_fingerprint"
       FROM "ocr_nutrition_confirmation_traces"
      WHERE "user_id" = ? AND "client_request_id" = ?`,
    [context.ownerId, context.requestId],
  );
  const food = trace
    ? await database.getFirstAsync<{ name: string; deleted_at: string | null }>(
      `SELECT "name", "deleted_at" FROM "food_items" WHERE "id" = ? AND "user_id" = ?`,
      [trace.food_item_id, context.ownerId],
    )
    : null;
  return Object.freeze({
    family: "ocr_confirmation",
    traceId: trace?.id ?? null,
    foodId: trace?.food_item_id ?? null,
    requestFingerprint: trace?.request_fingerprint ?? null,
    foodName: food?.name ?? null,
    foodDeletedAt: food?.deleted_at ?? null,
    namedFoodCount: await count(database, `SELECT COUNT(*) AS "count" FROM "food_items" WHERE "user_id" = ? AND "name" = ?`, [context.ownerId, OCR_FOOD_NAME]),
    servingCount: trace ? await count(database, `SELECT COUNT(*) AS "count" FROM "serving_definitions" WHERE "food_item_id" = ?`, [trace.food_item_id]) : 0,
    nutrientCount: trace ? await count(database, `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ?`, [trace.food_item_id]) : 0,
    traceCount: await count(database, `SELECT COUNT(*) AS "count" FROM "ocr_nutrition_confirmation_traces" WHERE "user_id" = ? AND "client_request_id" = ?`, [context.ownerId, context.requestId]),
  });
}

async function captureMutationState(
  database: SQLiteDatabase,
  family: E216StageDMutationFamily,
  context: E216StageDContext,
): Promise<E216StageDMutationState> {
  switch (family) {
    case "food_create": return captureFoodState(database, context);
    case "recipe_publish": return captureRecipeState(database, context);
    case "daily_log_edit": return captureDailyLogState(database, context, "update");
    case "daily_log_delete": return captureDailyLogState(database, context, "delete");
    case "target_update": return captureTargetState(database, context);
    case "ocr_confirmation": return captureOcrState(database, context);
  }
}

function preMutationControlFixtureInput(): FoodCreateInput {
  return {
    name: PRE_MUTATION_CONTROL_FIXTURE_NAME,
    brand: "Qualification",
    notes: "Committed setup fixture for the E2-16D pre-mutation control.",
    serving_definitions: [{ label: "1 serving", quantity: "1", unit: "serving", gram_weight: "45", is_default: true }],
    nutrients: [
      { nutrient_id: "calories", amount: "150", unit: "kcal", basis: "per_serving", data_status: "known" },
      { nutrient_id: "protein", amount: "8", unit: "g", basis: "per_serving", data_status: "known" },
    ],
  };
}

async function capturePreMutationControlState(
  database: SQLiteDatabase,
  context: E216StageDPreMutationControlContext,
): Promise<E216StageDMutationState> {
  const fixture = await database.getFirstAsync<{
    id: string;
    name: string;
    deleted_at: string | null;
  }>(
    `SELECT "id", "name", "deleted_at" FROM "food_items"
      WHERE "id" = ? AND "user_id" = ?`,
    [context.fixtureResourceId, context.ownerId],
  );
  const candidate = await database.getFirstAsync<{
    id: string;
    name: string;
    deleted_at: string | null;
  }>(
    `SELECT "id", "name", "deleted_at" FROM "food_items"
      WHERE "user_id" = ? AND "name" = ? ORDER BY "id" LIMIT 1`,
    [context.ownerId, PRE_MUTATION_CONTROL_CANDIDATE_NAME],
  );
  const candidateReceipt = await receiptEvidence(
    database,
    context.ownerId,
    "food.create_manual",
    context.requestId,
  );
  return Object.freeze({
    family: "pre_mutation_control",
    fixture: fixture
      ? Object.freeze({ id: fixture.id, name: fixture.name, deletedAt: fixture.deleted_at })
      : null,
    fixtureServingCount: fixture
      ? await count(database, `SELECT COUNT(*) AS "count" FROM "serving_definitions" WHERE "food_item_id" = ?`, [fixture.id])
      : 0,
    fixtureNutrientCount: fixture
      ? await count(database, `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ?`, [fixture.id])
      : 0,
    candidate: candidate
      ? Object.freeze({ id: candidate.id, name: candidate.name, deletedAt: candidate.deleted_at })
      : null,
    candidateFoodCount: await count(
      database,
      `SELECT COUNT(*) AS "count" FROM "food_items" WHERE "user_id" = ? AND "name" = ?`,
      [context.ownerId, PRE_MUTATION_CONTROL_CANDIDATE_NAME],
    ),
    candidateServingCount: candidate
      ? await count(database, `SELECT COUNT(*) AS "count" FROM "serving_definitions" WHERE "food_item_id" = ?`, [candidate.id])
      : 0,
    candidateNutrientCount: candidate
      ? await count(database, `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ?`, [candidate.id])
      : 0,
    receipt: candidateReceipt,
  });
}

function foodInput(): FoodCreateInput {
  return {
    name: FOOD_NAME,
    brand: "Qualification",
    notes: "E2-16D real local Food mutation",
    client_request_id: FOOD_REQUEST_ID,
    serving_definitions: [{ label: "1 cup", quantity: "1", unit: "cup", gram_weight: "50", is_default: true }],
    nutrients: [
      { nutrient_id: "calories", amount: "200", unit: "kcal", basis: "per_serving", data_status: "known" },
      { nutrient_id: "protein", amount: "10", unit: "g", basis: "per_serving", data_status: "known" },
    ],
  };
}

function dailySourceFoodInput(): FoodCreateInput {
  return {
    name: DAILY_FOOD_NAME,
    brand: null,
    notes: null,
    serving_definitions: [{ label: "1 serving", quantity: "1", unit: "serving", gram_weight: "40", is_default: true }],
    nutrients: [
      { nutrient_id: "calories", amount: "100", unit: "kcal", basis: "per_serving", data_status: "known" },
      { nutrient_id: "protein", amount: "5", unit: "g", basis: "per_serving", data_status: "known" },
    ],
  };
}

function targetInput(calories: string): TargetConfigurationInput {
  return {
    profile: {
      birth_date: "1996-01-15",
      sex_for_equation: "male",
      height_cm: "175",
      height_unit: "cm",
      weight_kg: "70",
      weight_unit: "kg",
      activity_level: "sedentary",
      energy_estimation_context: "general_adult",
    },
    manual_overrides: {
      calories,
      protein: null,
      total_carbohydrate: null,
      total_fat: null,
    },
  };
}

function basicOcrDecision(
  fieldKey: string,
  confirmedValue: string | null,
  unit: string | null = null,
): TraceFieldDecisionInput {
  return {
    field_key: fieldKey,
    nutrient_id: null,
    suggested_value: null,
    confirmed_value: confirmedValue,
    unit,
    decision: confirmedValue === null ? "omitted" : "edited",
    parse_status: "missing",
    comparison: null,
    confidence: "0",
    source_text: "",
    source_observation_ids: [],
    warning_codes: [],
    resolution: null,
  };
}

function ocrInput(): OcrConfirmationInput {
  const food = {
    name: OCR_FOOD_NAME,
    brand: "Qualification",
    notes: null,
    serving_definitions: [{ label: "1 cup (30g)", quantity: "1", unit: "cup", gram_weight: "30", is_default: true }],
    nutrients: [
      { nutrient_id: "calories", amount: "120", unit: "kcal" as const, basis: "per_serving" as const, data_status: "known" as const },
      { nutrient_id: "sodium", amount: "0", unit: "mg" as const, basis: "per_serving" as const, data_status: "zero" as const },
    ],
  };
  return {
    parser_version: "nutrition_label_v1",
    image_source_type: "camera",
    client_request_id: OCR_REQUEST_ID,
    food,
    field_decisions: [
      basicOcrDecision("food.name", food.name),
      basicOcrDecision("food.brand", food.brand),
      basicOcrDecision("food.notes", null),
      basicOcrDecision("serving.display", "1 cup (30g)"),
      basicOcrDecision("serving.quantity", "1"),
      basicOcrDecision("serving.unit", "cup"),
      basicOcrDecision("serving.gram_weight", "30", "g"),
      {
        ...basicOcrDecision("nutrient.calories", "120", "kcal"),
        nutrient_id: "calories",
        suggested_value: "120",
        decision: "accepted",
        parse_status: "parsed",
        confidence: "0.98",
        source_text: "Calories 120",
        source_observation_ids: ["obs-calories"],
      },
      {
        ...basicOcrDecision("nutrient.sodium", "0", "mg"),
        nutrient_id: "sodium",
        suggested_value: "0",
        decision: "accepted",
        parse_status: "parsed",
        confidence: "0.97",
        source_text: "Sodium 0mg",
        source_observation_ids: ["obs-sodium"],
      },
    ],
    unknown_nutrients: [],
    parser_warning_codes: [],
  };
}

async function clearStageDJournal(): Promise<void> {
  await AsyncStorage.removeItem(LOG_MUTATION_RECOVERY_STORAGE_KEY);
}

async function prepareFixture(
  database: SQLiteDatabase,
  family: E216StageDMutationFamily,
  ownerId: string,
): Promise<E216StageDContext> {
  const base: E216StageDContext = {
    ownerId,
    requestId: null,
    resourceId: null,
    servingId: null,
    sourceDate: null,
  };
  if (family === "food_create") return { ...base, requestId: FOOD_REQUEST_ID };
  if (family === "recipe_publish") {
    const recipes = createLocalRecipesRuntime(database, ownerId);
    const recipe = await recipes.create({
      name: RECIPE_NAME,
      notes: "E2-16D immutable publication",
      serving_count_yield: "2",
      final_cooked_weight_grams: "100",
      ingredients: [],
    });
    await recipes.publish({ recipeId: recipe.id, clientRequestId: RECIPE_BASELINE_REQUEST_ID });
    return { ...base, requestId: RECIPE_REQUEST_ID, resourceId: recipe.id };
  }
  if (family === "daily_log_edit" || family === "daily_log_delete") {
    await createLocalCalendarRuntime(database, ownerId).establishTimeZone("UTC");
    const food = await createLocalFoodsRuntime(database, ownerId).create(dailySourceFoodInput());
    const serving = food.serving_definitions.find((candidate) => candidate.is_default);
    if (!serving) throw new Error("E2-16D Daily Log fixture has no default serving.");
    const log = await createLocalDailyLogsRuntime(database, ownerId).create({
      client_request_id: DAILY_SETUP_REQUEST_ID,
      food_item_id: food.id,
      logged_date: FIXTURE_DATE,
      amount_quantity: "1",
      amount_unit: "serving",
      serving_definition_id: serving.id,
      meal_type: "breakfast",
      notes: "before termination",
    });
    return {
      ...base,
      requestId: family === "daily_log_edit" ? DAILY_EDIT_REQUEST_ID : DAILY_DELETE_REQUEST_ID,
      resourceId: log.id,
      servingId: serving.id,
      sourceDate: log.logged_date,
    };
  }
  if (family === "target_update") {
    await createLocalTargetsRuntime(database, ownerId).updateConfiguration(targetInput("2000"));
    return base;
  }
  return { ...base, requestId: OCR_REQUEST_ID };
}

export async function prepareE216StageDCase(
  caseId: E216StageDCaseId,
): Promise<E216StageDCheckpointMarker> {
  assertIos();
  const definition = definitionFor(caseId);
  await clearStageDJournal();
  await resetE216QualificationDatabase("termination");
  const handle = await openE216QualificationDatabase("termination");
  try {
    const runtime = await bootstrapOpenedLocalRuntimeFoundation(handle);
    const context = await prepareFixture(handle.database, definition.family, runtime.identity.ownerId);
    const preMutationState = await captureMutationState(handle.database, definition.family, context);
    const marker = freezeMarker({
      schema: E216_STAGE_D_CHECKPOINT_SCHEMA,
      stage: "E2-16D",
      caseId,
      family: definition.family,
      checkpoint: definition.checkpoint,
      checkpointReached: "before_mutation",
      checkpointStage: "fixture_committed_before_mutation",
      platform: "ios",
      databaseName: "e2_16_termination_ios.db",
      processSessionId: PROCESS_SESSION_ID,
      state: "ready_to_arm",
      expectedDurableState: definition.checkpoint === "during_transaction" ? "pre_mutation" : "post_commit",
      context,
      preMutationState,
      postCommitState: null,
      result: null,
    });
    writeE216StageDCheckpoint(marker);
    return marker;
  } finally {
    await handle.close();
  }
}

/**
 * Prepare the single shared before-mutation process-death control.  The setup
 * Food is committed through the production runtime, then the candidate
 * mutation is deliberately never called before this marker is exposed.
 */
export async function prepareE216StageDPreMutationControl(): Promise<E216StageDPreMutationControlCheckpointMarker> {
  assertIos();
  if (activeStageDMutationPending) {
    throw new Error("E2-16D cannot prepare its pre-mutation control while a mutation transaction is pending.");
  }
  await clearStageDJournal();
  await resetE216QualificationDatabase("termination");
  const handle = await openE216QualificationDatabase("termination");
  try {
    const runtime = await bootstrapOpenedLocalRuntimeFoundation(handle);
    const fixture = await runtime.foods.create(preMutationControlFixtureInput());
    const context: E216StageDPreMutationControlContext = {
      ownerId: runtime.identity.ownerId,
      requestId: PRE_MUTATION_CONTROL_REQUEST_ID,
      fixtureResourceId: fixture.id,
    };
    const preMutationState = await capturePreMutationControlState(handle.database, context);
    if (
      preMutationState.fixture === null
      || preMutationState.fixtureServingCount !== 1
      || preMutationState.fixtureNutrientCount !== 2
      || preMutationState.candidate !== null
      || preMutationState.candidateFoodCount !== 0
      || (preMutationState.receipt as E216StageDReceiptEvidence)?.present === true
    ) {
      throw new Error("E2-16D pre-mutation control setup found an unexpected candidate resource or receipt.");
    }
    const marker = freezeControlMarker({
      schema: E216_STAGE_D_CONTROL_CHECKPOINT_SCHEMA,
      stage: "E2-16D",
      caseId: "pre_mutation_control",
      checkpoint: "before_mutation",
      checkpointReached: "before_mutation",
      checkpointStage: "fixture_committed_before_mutation",
      platform: "ios",
      databaseName: "e2_16_termination_ios.db",
      processSessionId: PROCESS_SESSION_ID,
      state: "awaiting_termination",
      expectedDurableState: "pre_mutation",
      context,
      preMutationState,
      result: null,
    });
    writeE216StageDPreMutationControlCheckpoint(marker);
    return marker;
  } finally {
    await handle.close();
  }
}

function dailyUpdateInput(context: E216StageDContext): Partial<DailyLogUpdateInput> {
  return {
    client_request_id: DAILY_EDIT_REQUEST_ID,
    amount_quantity: "2",
    amount_unit: "serving",
    serving_definition_id: context.servingId,
    notes: "after durable edit",
  };
}

function dailyDeleteInput(): DailyLogDeleteInput {
  return { client_request_id: DAILY_DELETE_REQUEST_ID };
}

function dailyRecoveryRecord(
  marker: E216StageDCheckpointMarker,
): LogMutationRecoveryRecord {
  const isDelete = marker.family === "daily_log_delete";
  return createLogMutationRecoveryRecord({
    authority: { kind: "local", recoveryScope: `local:${marker.context.ownerId}` },
    clientRequestId: marker.context.requestId!,
    mutationType: isDelete ? "delete" : "edit",
    targetId: marker.context.resourceId,
    sourceDate: marker.context.sourceDate!,
    destinationDate: marker.context.sourceDate,
    displayContext: {
      item_name: DAILY_FOOD_NAME,
      amount_label: isDelete ? "delete" : "2 servings",
      meal_label: "Breakfast",
    },
    payload: isDelete
      ? { operation: "delete", log_id: marker.context.resourceId!, input: dailyDeleteInput() }
      : { operation: "update", log_id: marker.context.resourceId!, input: dailyUpdateInput(marker.context) },
  });
}

function waitingMarker(
  marker: E216StageDCheckpointMarker,
  checkpointReached: "inside_transaction_before_commit" | "after_durable_commit",
  checkpointStage: string,
  postCommitState: E216StageDMutationState | null,
): E216StageDCheckpointMarker {
  return freezeMarker({
    ...marker,
    checkpointReached,
    checkpointStage,
    state: "awaiting_termination",
    postCommitState,
  });
}

/**
 * Persist the host-visible marker, verify it byte-for-byte, then never resolve.
 * Because callers await this promise from an existing runtime stage callback,
 * the real native transaction remains open until simctl terminates the process.
 */
export function holdE216TransactionForExternalTermination(
  marker: E216StageDCheckpointMarker,
  onCheckpoint?: (marker: E216StageDCheckpointMarker) => void,
): Promise<never> {
  writeE216StageDCheckpoint(marker);
  onCheckpoint?.(marker);
  return new Promise<never>(() => undefined);
}

async function runMutation(
  handle: NutritionDatabaseHandle,
  marker: E216StageDCheckpointMarker,
  onCheckpoint?: (marker: E216StageDCheckpointMarker) => void,
): Promise<void> {
  const definition = definitionFor(marker.caseId);
  const hold = async (stage: string): Promise<void> => {
    if (definition.checkpoint !== "during_transaction" || stage !== definition.transactionStage) return;
    await holdE216TransactionForExternalTermination(waitingMarker(
      marker,
      "inside_transaction_before_commit",
      stage,
      null,
    ), onCheckpoint);
  };
  const { ownerId, resourceId } = marker.context;
  switch (marker.family) {
    case "food_create":
      await createLocalFoodsRuntime(handle.database, ownerId, { onMutationStage: hold }).create(foodInput());
      return;
    case "recipe_publish":
      await createLocalRecipesRuntime(handle.database, ownerId, { onPublicationStage: hold }).publish({
        recipeId: resourceId!,
        clientRequestId: RECIPE_REQUEST_ID,
      });
      return;
    case "daily_log_edit":
      await createLocalDailyLogsRuntime(handle.database, ownerId, { onNutritionEditStage: hold }).update(
        resourceId!,
        dailyUpdateInput(marker.context),
      );
      return;
    case "daily_log_delete":
      await createLocalDailyLogsRuntime(handle.database, ownerId, { onDeleteStage: hold }).delete(
        resourceId!,
        dailyDeleteInput(),
      );
      return;
    case "target_update":
      await createLocalTargetsRuntime(handle.database, ownerId, { onMutationStage: hold }).updateConfiguration(targetInput("2400"));
      return;
    case "ocr_confirmation": {
      const foods = createLocalFoodsRuntime(handle.database, ownerId);
      await createLocalOcrRuntime(handle.database, ownerId, foods, { onConfirmationStage: hold })
        .confirmNutritionLabel(ocrInput());
    }
  }
}

export async function armE216StageDCase(
  onCheckpoint?: (marker: E216StageDCheckpointMarker) => void,
): Promise<E216StageDCheckpointMarker> {
  assertIos();
  const marker = readE216StageDCheckpoint();
  if (!marker || marker.state !== "ready_to_arm" || marker.checkpointReached !== "before_mutation") {
    throw new Error("Prepare one E2-16D case before arming its mutation.");
  }
  if (marker.processSessionId !== PROCESS_SESSION_ID) {
    throw new Error("E2-16D prepared state belongs to another process session; prepare the case again.");
  }
  const handle = await openE216QualificationDatabase("termination");
  activeStageDHandle = handle;
  activeStageDMutationPending = true;
  try {
    await bootstrapOpenedLocalRuntimeFoundation(handle);
    if (marker.family === "daily_log_edit" || marker.family === "daily_log_delete") {
      await persistRecoveryBeforeTransmission(dailyRecoveryRecord(marker));
    }
    await runMutation(handle, marker, onCheckpoint);
    activeStageDMutationPending = false;
    if (marker.checkpoint !== "post_commit") {
      throw new Error("E2-16D during-transaction barrier resolved without external process termination.");
    }
    const postCommitState = await captureMutationState(handle.database, marker.family, marker.context);
    const waiting = waitingMarker(
      marker,
      "after_durable_commit",
      "production_mutation_promise_resolved",
      postCommitState,
    );
    writeE216StageDCheckpoint(waiting);
    onCheckpoint?.(waiting);
    return waiting;
  } catch (error) {
    activeStageDMutationPending = false;
    await handle.close();
    activeStageDHandle = null;
    throw error;
  }
}

function receiptFromState(state: E216StageDMutationState): E216StageDReceiptEvidence {
  const value = state.receipt;
  if (value === null || typeof value === "object") return value as E216StageDReceiptEvidence;
  return null;
}

async function reconcileDailyLog(
  marker: E216StageDCheckpointMarker,
  runtime: Awaited<ReturnType<typeof bootstrapOpenedLocalRuntimeFoundation>>,
): Promise<E216StageDRecoveryEvidence> {
  const before = await loadLogMutationRecoveryJournal(runtime.authority);
  const record = before.find((candidate) => candidate.client_request_id === marker.context.requestId);
  if (!record) {
    return {
      beforeReconciliation: [],
      mutationStatus: "journal_record_missing",
      reconciliation: "pending",
      afterReconciliation: [],
    };
  }
  const operation = marker.family === "daily_log_delete" ? "delete" : "update";
  const status = await runtime.dailyLogs.getMutationStatus(marker.context.requestId!, operation);
  const reconciliation = await reconcileLogMutationRecoveryRecord(record, null, {
    authority: runtime.authority,
    dailyLogs: runtime.dailyLogs,
  });
  const after = await loadLogMutationRecoveryJournal(runtime.authority);
  return Object.freeze({
    beforeReconciliation: before.map((candidate) => ({ id: candidate.id, state: candidate.state })),
    mutationStatus: status.status,
    reconciliation,
    afterReconciliation: after.map((candidate) => ({ id: candidate.id, state: candidate.state })),
  });
}

async function replayIdempotentMutation(
  marker: E216StageDCheckpointMarker,
  runtime: Awaited<ReturnType<typeof bootstrapOpenedLocalRuntimeFoundation>>,
  durableState: E216StageDMutationState,
): Promise<E216StageDIdempotencyEvidence> {
  if (marker.checkpoint !== "post_commit") {
    return Object.freeze({
      applicable: marker.family !== "target_update",
      replayed: false,
      unchangedAfterReplay: null,
      interpretation: "Expected non-commit case; authoritative absence or prior state is the reconciliation result.",
    });
  }
  if (marker.family === "target_update") {
    return Object.freeze({
      applicable: false,
      replayed: false,
      unchangedAfterReplay: null,
      interpretation: "Target restart ownership is authoritative reread; no receipt or replay subsystem exists.",
    });
  }
  if (marker.family === "daily_log_edit" || marker.family === "daily_log_delete") {
    return Object.freeze({
      applicable: true,
      replayed: false,
      unchangedAfterReplay: null,
      interpretation: "Daily Log completion is interpreted by its durable receipt and established journal reconciliation.",
    });
  }
  if (marker.family === "food_create") {
    await runtime.foods.create(foodInput());
  } else if (marker.family === "recipe_publish") {
    await runtime.recipes.publish({ recipeId: marker.context.resourceId!, clientRequestId: RECIPE_REQUEST_ID });
  } else {
    await runtime.ocr.confirmNutritionLabel(ocrInput());
  }
  const afterReplay = await captureMutationState(runtime.database, marker.family, marker.context);
  return Object.freeze({
    applicable: true,
    replayed: true,
    unchangedAfterReplay: stateEqual(durableState, afterReplay),
    interpretation: "The existing production receipt/trace replay returned without creating a second semantic graph.",
  });
}

function recoveryPass(
  marker: E216StageDCheckpointMarker,
  recovery: E216StageDRecoveryEvidence,
): boolean {
  if (marker.family !== "daily_log_edit" && marker.family !== "daily_log_delete") return true;
  if (!recovery) return false;
  if (marker.checkpoint === "during_transaction") {
    return recovery.mutationStatus === "confirmed_non_commit"
      && recovery.reconciliation === "retryable"
      && recovery.afterReconciliation.length === 1
      && recovery.afterReconciliation[0]?.state === "confirmed_non_commit";
  }
  return recovery.mutationStatus === "confirmed_success"
    && recovery.reconciliation === "confirmed"
    && recovery.afterReconciliation.length === 0;
}

export async function completeE216StageDCaseAfterRelaunch(): Promise<E216StageDCaseResult> {
  assertIos();
  const marker = readE216StageDCheckpoint();
  if (!marker || marker.state !== "awaiting_termination") {
    throw new Error("E2-16D has no termination checkpoint awaiting restart inspection.");
  }
  if (marker.processSessionId === PROCESS_SESSION_ID) {
    throw new Error("E2-16D completion requires a new process session after simctl termination and launch.");
  }
  const handle = await openE216QualificationDatabase("termination");
  let result: E216StageDCaseResult;
  try {
    const runtime = await bootstrapOpenedLocalRuntimeFoundation(handle);
    const authoritativeDurableState = await captureMutationState(handle.database, marker.family, marker.context);
    const expected = marker.expectedDurableState === "pre_mutation"
      ? marker.preMutationState
      : marker.postCommitState;
    const diagnostics: string[] = [];
    const durableStateMatches = expected !== null && stateEqual(expected, authoritativeDurableState);
    if (!durableStateMatches) diagnostics.push("authoritative durable state differs from the checkpoint expectation");
    const recovery = marker.family === "daily_log_edit" || marker.family === "daily_log_delete"
      ? await reconcileDailyLog(marker, runtime)
      : null;
    if (!recoveryPass(marker, recovery)) diagnostics.push("Daily Log journal/status reconciliation did not reach its expected bounded outcome");
    const idempotency = await replayIdempotentMutation(marker, runtime, authoritativeDurableState);
    if (idempotency.unchangedAfterReplay === false) diagnostics.push("idempotent replay changed the authoritative semantic state");
    const directIntegrity = await qualifyE216Database(handle.database, {
      databaseName: qualificationDatabaseName("ios", "termination"),
    });
    if (directIntegrity.status !== "pass") diagnostics.push("E2-16 direct-integrity qualifier failed after restart");
    result = Object.freeze({
      caseId: marker.caseId,
      family: marker.family,
      checkpoint: marker.checkpoint,
      terminationCheckpointReached: marker.checkpointReached as "inside_transaction_before_commit" | "after_durable_commit",
      checkpointStage: marker.checkpointStage,
      checkpointReached: "after_restart_reconciliation",
      expectedDurableState: marker.expectedDurableState,
      preMutationState: marker.preMutationState,
      postCommitState: marker.postCommitState,
      authoritativeDurableState,
      receipt: receiptFromState(authoritativeDurableState),
      recovery,
      idempotency,
      directIntegrity,
      status: diagnostics.length === 0 ? "pass" : "fail",
      diagnostics: Object.freeze(diagnostics),
    });
  } finally {
    await handle.close();
  }
  writeE216StageDCheckpoint(freezeMarker({
    ...marker,
    processSessionId: PROCESS_SESSION_ID,
    checkpointReached: "after_restart_reconciliation",
    checkpointStage: "authoritative_reread_reconciliation_and_direct_integrity",
    state: "completed",
    result,
  }));
  return result;
}

export async function completeE216StageDPreMutationControlAfterRelaunch(): Promise<E216StageDPreMutationControlResult> {
  assertIos();
  const marker = readE216StageDPreMutationControlCheckpoint();
  if (!marker || marker.state !== "awaiting_termination") {
    throw new Error("E2-16D has no pre-mutation control awaiting restart inspection.");
  }
  if (isE216StageDCurrentProcessSession(marker.processSessionId)) {
    throw new Error("E2-16D pre-mutation control completion requires a new process session after simctl termination and launch.");
  }
  const handle = await openE216QualificationDatabase("termination");
  let result: E216StageDPreMutationControlResult;
  try {
    await bootstrapOpenedLocalRuntimeFoundation(handle);
    const authoritativeDurableState = await capturePreMutationControlState(handle.database, marker.context);
    const receipt = authoritativeDurableState.receipt as E216StageDReceiptEvidence;
    const unexpectedResource = authoritativeDurableState.candidate !== null
      || authoritativeDurableState.candidateFoodCount !== 0;
    const unexpectedReceipt = receipt?.present === true;
    const diagnostics: string[] = [];
    if (!stateEqual(marker.preMutationState, authoritativeDurableState)) {
      diagnostics.push("authoritative durable state differs from the pre-mutation control state");
    }
    if (unexpectedResource) diagnostics.push("the pre-mutation candidate Food resource exists after restart");
    if (unexpectedReceipt) diagnostics.push("the pre-mutation candidate mutation receipt exists after restart");
    const directIntegrity = await qualifyE216Database(handle.database, {
      databaseName: qualificationDatabaseName("ios", "termination"),
    });
    if (directIntegrity.status !== "pass") diagnostics.push("E2-16 direct-integrity qualifier failed after restart");
    result = Object.freeze({
      caseId: "pre_mutation_control",
      checkpointReached: "after_restart_reconciliation",
      expectedDurableState: "pre_mutation",
      preMutationState: marker.preMutationState,
      authoritativeDurableState,
      receipt,
      idempotency: Object.freeze({
        applicable: false,
        replayed: false,
        unchangedAfterReplay: null,
        interpretation: "No mutation-under-test was invoked before this control checkpoint; receipt absence is the expected pre-mutation idempotency state.",
      }),
      unexpectedResource,
      unexpectedReceipt,
      directIntegrity,
      status: diagnostics.length === 0 ? "pass" : "fail",
      diagnostics: Object.freeze(diagnostics),
    });
  } finally {
    await handle.close();
  }
  writeE216StageDPreMutationControlCheckpoint(freezeControlMarker({
    ...marker,
    processSessionId: PROCESS_SESSION_ID,
    checkpointReached: "after_restart_reconciliation",
    checkpointStage: "authoritative_reread_and_direct_integrity",
    state: "completed",
    result,
  }));
  return result;
}

export async function resetE216StageDQualification(): Promise<void> {
  assertIos();
  if (activeStageDMutationPending) {
    throw new Error("E2-16D cannot close or reset while its native mutation transaction is pending; terminate the process externally.");
  }
  if (activeStageDHandle) {
    await activeStageDHandle.close();
    activeStageDHandle = null;
  }
  await clearStageDJournal();
  await resetE216QualificationDatabase("termination");
  clearE216StageDCheckpoint();
  clearE216StageDPreMutationControlCheckpoint();
}
