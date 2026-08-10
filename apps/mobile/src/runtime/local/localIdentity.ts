import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import { localAuthorityIdentity, type RuntimeAuthorityIdentity } from "../authorityIdentity";
import { parseUuid, type CanonicalUuid } from "../../shared/exact/canonicalValues";
import { withLocalWriteTransaction } from "./localWriteCoordinator";
import { LocalRuntimeError } from "./localErrors";

/** Reserved local placeholder; local mode does not authenticate over HTTP. */
export const LOCAL_OWNER_EMAIL = "local-owner@local.invalid";
export const LOCAL_OWNER_DISPLAY_NAME = "Local Owner";

type UserRow = Readonly<{ id: string; email: string }>;

export type LocalOwnerIdentity = Readonly<{
  /** The one durable runtime/owner UUID used as `user_id` in every scoped table. */
  ownerId: CanonicalUuid;
  /** Alias for APIs that use the persisted column name. */
  userId: CanonicalUuid;
  authority: RuntimeAuthorityIdentity;
}>;

function identityConflict(): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "constraint_failed",
    message: "The local owner identity is inconsistent and cannot be selected safely.",
  });
}

/**
 * Create the one local owner row and its profile exactly once.
 *
 * A local database is single-owner by contract.  An empty `users` table gets
 * one cryptographically generated UUID; one existing row is reused on every
 * reopen.  More than one row is an integrity conflict rather than an
 * arbitrary owner selection.
 */
export async function ensureLocalOwner(database: SQLiteDatabase): Promise<LocalOwnerIdentity> {
  return withLocalWriteTransaction(database, async (transaction) => {
    const users = await transaction.getAllAsync<UserRow>(
      `SELECT "id", "email" FROM "users" ORDER BY "id"`,
    );
    if (users.length > 1) {
      throw identityConflict();
    }

    let ownerId: CanonicalUuid;
    const existing = users[0];
    if (existing) {
      try {
        ownerId = parseUuid(existing.id);
        if (existing.id !== ownerId) {
          throw identityConflict();
        }
      } catch {
        throw identityConflict();
      }
    } else {
      try {
        ownerId = parseUuid(Crypto.randomUUID());
      } catch {
        throw identityConflict();
      }
      await transaction.runAsync(
        `INSERT INTO "users" ("id", "email", "display_name") VALUES (?, ?, ?)`,
        [ownerId, LOCAL_OWNER_EMAIL, LOCAL_OWNER_DISPLAY_NAME],
      );
    }

    const profile = await transaction.getFirstAsync<{ user_id: string }>(
      `SELECT "user_id" FROM "user_profiles" WHERE "user_id" = ?`,
      [ownerId],
    );
    if (!profile) {
      await transaction.runAsync(
        `INSERT INTO "user_profiles" ("user_id") VALUES (?)`,
        [ownerId],
      );
    } else {
      try {
        parseUuid(profile.user_id);
        if (profile.user_id !== ownerId) {
          throw identityConflict();
        }
      } catch {
        throw identityConflict();
      }
    }

    return Object.freeze({
      ownerId,
      userId: ownerId,
      authority: localAuthorityIdentity(ownerId),
    });
  });
}
