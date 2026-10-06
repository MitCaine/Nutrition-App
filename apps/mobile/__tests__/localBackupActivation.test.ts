type MockDatabase = {
  name: string;
  marker: string;
  closeAsync: jest.Mock<Promise<void>, []>;
  execAsync: jest.Mock<Promise<void>, [string]>;
};

type BackupArguments = {
  sourceDatabase: MockDatabase;
  sourceDatabaseName: string;
  destDatabase: MockDatabase;
  destDatabaseName: string;
};

const mockDatabaseDirectory =
  "file:///mock-databases";

const mockFiles = new Set<string>();
const mockDatabases =
  new Map<string, MockDatabase>();

const mockFileDelete =
  jest.fn<Promise<void>, [string]>();
const mockFileMove =
  jest.fn<Promise<void>, [string, string]>();

const mockSetItem =
  jest.fn<Promise<void>, [string, string]>();

const mockGetItem =
  jest.fn<Promise<string | null>, [string]>();

const mockValidate =
  jest.fn<
    Promise<unknown>,
    [MockDatabase, ("artifact" | "active")?]
  >();

const mockOpenDatabaseAsync =
  jest.fn<
    Promise<MockDatabase>,
    [string, unknown?, string?]
  >();

const mockDeleteDatabaseAsync =
  jest.fn<
    Promise<void>,
    [string, string?]
  >();

const mockBackupDatabaseAsync =
  jest.fn<
    Promise<void>,
    [BackupArguments]
  >();

function databaseUri(name: string): string {
  return `${mockDatabaseDirectory}/${name}`;
}

function database(
  name: string,
  marker = "",
): MockDatabase {
  const existing =
    mockDatabases.get(name);

  if (existing) {
    return existing;
  }

  const created: MockDatabase = {
    name,
    marker,
    closeAsync:
      jest.fn<Promise<void>, []>(
        async () => undefined,
      ),
    execAsync:
      jest.fn<Promise<void>, [string]>(
        async () => undefined,
      ),
  };

  mockDatabases.set(name, created);
  return created;
}

function seedDatabase(
  name: string,
  marker: string,
): MockDatabase {
  mockFiles.add(databaseUri(name));

  const seeded = database(name);
  seeded.marker = marker;

  return seeded;
}

jest.mock(
  "@react-native-async-storage/async-storage",
  () => ({
    __esModule: true,
    default: {
      setItem: (
        key: string,
        value: string,
      ) => mockSetItem(key, value),

      getItem: (
        key: string,
      ) => mockGetItem(key),
    },
  }),
);

jest.mock("expo-file-system", () => ({
  __esModule: true,

  File: class MockFile {
    uri: string;

    constructor(...parts: string[]) {
      this.uri =
        parts.length === 1
          ? parts[0]
          : `${parts[0].replace(/\/$/, "")}/${parts[1]}`;
    }

    get exists(): boolean {
      return mockFiles.has(this.uri);
    }

    async delete(): Promise<void> {
      await mockFileDelete(this.uri);
    }

    async copy(
      destination: { uri: string },
    ): Promise<void> {
      if (!this.exists) {
        throw new Error(
          "source file missing",
        );
      }

      mockFiles.add(destination.uri);
    }

    async move(
      destination: { uri: string },
    ): Promise<void> {
      await mockFileMove(
        this.uri,
        destination.uri,
      );
      this.uri = destination.uri;
    }
  },
}));

jest.mock("expo-sqlite", () => ({
  __esModule: true,

  defaultDatabaseDirectory:
    "file:///mock-databases",

  openDatabaseAsync: (
    name: string,
    options?: unknown,
    directory?: string,
  ) =>
    mockOpenDatabaseAsync(
      name,
      options,
      directory,
    ),

  deleteDatabaseAsync: (
    name: string,
    directory?: string,
  ) =>
    mockDeleteDatabaseAsync(
      name,
      directory,
    ),

  backupDatabaseAsync: (
    args: BackupArguments,
  ) =>
    mockBackupDatabaseAsync(args),
}));

jest.mock(
  "../src/storage/backup/localBackupValidation",
  () => ({
    NUTRITION_BACKUP_APPLICATION_ID:
      0x4e410001,

    NUTRITION_BACKUP_FORMAT_VERSION: 1,

    validateLocalBackupDatabase: (
      db: MockDatabase,
      mode?: "artifact" | "active",
    ) =>
      mockValidate(db, mode),
  }),
);

import {
  activatePendingLocalRestore,
  cancelPendingLocalRestore,
  createLocalBackupArtifact,
  deleteLocalBackupArtifact,
  hasPendingLocalRestore,
  LocalBackupActivationFatalError,
} from "../src/storage/backup/localBackup";

const SUMMARY = Object.freeze({
  formatVersion: 1 as const,
  schemaVersion: 4,
  ownerId:
    "00000000-0000-4000-8000-000000000001",
  totalRows: 73,
  rowCounts: Object.freeze({
    users: 1,
    user_profiles: 1,
    food_items: 8,
  }),
});

const ACTIVE_DATABASE =
  "nutrition.db";

const PENDING_DATABASE =
  "nutrition-restore-pending-v1.db";

const CONSUMED_PREFIX =
  `${mockDatabaseDirectory}/nutrition-restore-consumed-`;

function lastWrittenEvidence():
Record<string, unknown> {
  const calls =
    mockSetItem.mock.calls;

  const call =
    calls[calls.length - 1];

  if (!call) {
    throw new Error(
      "No restore evidence was written.",
    );
  }

  return JSON.parse(
    call[1],
  ) as Record<string, unknown>;
}

function consumedUris(): string[] {
  return [...mockFiles].filter((uri) =>
    uri.startsWith(CONSUMED_PREFIX),
  );
}

beforeEach(() => {
  // Reset implementations as well as call history.
  // This prevents an unconsumed *Once implementation
  // from leaking out of a test that aborted early.
  mockSetItem.mockReset();
  mockGetItem.mockReset();
  mockValidate.mockReset();
  mockOpenDatabaseAsync.mockReset();
  mockDeleteDatabaseAsync.mockReset();
  mockBackupDatabaseAsync.mockReset();
  mockFileDelete.mockReset();
  mockFileMove.mockReset();

  mockFiles.clear();
  mockDatabases.clear();

  mockSetItem.mockResolvedValue(undefined);
  mockGetItem.mockResolvedValue(null);
  mockValidate.mockResolvedValue(SUMMARY);

  mockOpenDatabaseAsync.mockImplementation(
    async (name: string) => {
      mockFiles.add(databaseUri(name));
      return database(name);
    },
  );

  mockDeleteDatabaseAsync.mockImplementation(
    async (
      name: string,
      directory = mockDatabaseDirectory,
    ) => {
      mockFiles.delete(
        `${directory.replace(/\/$/, "")}/${name}`,
      );

      if (name !== ACTIVE_DATABASE) {
        mockDatabases.delete(name);
      }
    },
  );

  mockBackupDatabaseAsync.mockImplementation(
    async ({
      sourceDatabase,
      destDatabase,
    }) => {
      destDatabase.marker =
        sourceDatabase.marker;
    },
  );

  mockFileDelete.mockImplementation(
    async (uri: string) => {
      mockFiles.delete(uri);
    },
  );

  mockFileMove.mockImplementation(
    async (
      sourceUri: string,
      destinationUri: string,
    ) => {
      if (!mockFiles.has(sourceUri)) {
        throw new Error(
          "source file missing",
        );
      }

      mockFiles.delete(sourceUri);
      mockFiles.add(destinationUri);

      const sourceName =
        sourceUri.split("/").pop();
      const destinationName =
        destinationUri.split("/").pop();
      const sourceDatabase = sourceName
        ? mockDatabases.get(sourceName)
        : undefined;

      if (
        sourceName &&
        sourceDatabase &&
        destinationName
      ) {
        mockDatabases.delete(sourceName);
        sourceDatabase.name = destinationName;
        mockDatabases.set(
          destinationName,
          sourceDatabase,
        );
      }
    },
  );
});

test(
  "successful pending restore replaces the local database only at activation",
  async () => {
    const active =
      seedDatabase(
        ACTIVE_DATABASE,
        "current-state",
      );

    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    expect(
      hasPendingLocalRestore(),
    ).toBe(true);

    expect(active.marker).toBe(
      "current-state",
    );

    const evidence =
      await activatePendingLocalRestore();

    expect(evidence).toMatchObject({
      status: "success",
      ownerId: SUMMARY.ownerId,
      schemaVersion: 4,
      totalRows: 73,
    });

    expect(active.marker).toBe(
      "backup-state",
    );

    // Current -> rollback, then pending -> active.
    expect(
      mockBackupDatabaseAsync,
    ).toHaveBeenCalledTimes(2);

    expect(
      hasPendingLocalRestore(),
    ).toBe(false);

    expect(consumedUris()).toEqual([]);

    expect(
      lastWrittenEvidence(),
    ).toMatchObject({
      status: "success",
      ownerId: SUMMARY.ownerId,
      schemaVersion: 4,
      totalRows: 73,
    });
  },
);

test(
  "cancellation falls back to File deletion when SQLite deletion fails",
  async () => {
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockDeleteDatabaseAsync.mockRejectedValueOnce(
      new Error("SQLite deletion failed"),
    );

    await cancelPendingLocalRestore();

    expect(mockFileDelete).toHaveBeenCalledWith(
      databaseUri(PENDING_DATABASE),
    );
    expect(hasPendingLocalRestore()).toBe(false);
  },
);

test(
  "cancellation rejects when both deletion routes fail and keeps pending state",
  async () => {
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockDeleteDatabaseAsync.mockRejectedValueOnce(
      new Error("SQLite deletion failed"),
    );
    mockFileDelete.mockRejectedValueOnce(
      new Error("File deletion failed"),
    );

    await expect(
      cancelPendingLocalRestore(),
    ).rejects.toThrow(
      "staged restore remains",
    );

    expect(hasPendingLocalRestore()).toBe(true);
  },
);

test(
  "cancellation verifies a misleading SQLite success before reporting success",
  async () => {
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    // The SQLite route resolves but leaves the file in place; the File route
    // must still remove it before cancellation can report success.
    mockDeleteDatabaseAsync.mockImplementationOnce(
      async () => undefined,
    );

    await cancelPendingLocalRestore();

    expect(mockFileDelete).toHaveBeenCalledWith(
      databaseUri(PENDING_DATABASE),
    );
    expect(hasPendingLocalRestore()).toBe(false);
  },
);

test(
  "cancellation rejects when both deletion routes report success but retain the file",
  async () => {
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockDeleteDatabaseAsync.mockImplementationOnce(
      async () => undefined,
    );
    mockFileDelete.mockImplementationOnce(
      async () => undefined,
    );

    await expect(
      cancelPendingLocalRestore(),
    ).rejects.toThrow(
      "staged restore remains",
    );

    expect(hasPendingLocalRestore()).toBe(true);
  },
);

test(
  "cancellation is idempotent when no staged restore exists",
  async () => {
    await expect(
      cancelPendingLocalRestore(),
    ).resolves.toBeUndefined();

    expect(hasPendingLocalRestore()).toBe(false);
  },
);

test(
  "failed cancellation leaves the staged restore activatable on a later startup",
  async () => {
    const active = seedDatabase(
      ACTIVE_DATABASE,
      "current-state",
    );
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockDeleteDatabaseAsync.mockRejectedValueOnce(
      new Error("SQLite deletion failed"),
    );
    mockFileDelete.mockRejectedValueOnce(
      new Error("File deletion failed"),
    );

    await expect(
      cancelPendingLocalRestore(),
    ).rejects.toThrow();
    expect(hasPendingLocalRestore()).toBe(true);

    const evidence =
      await activatePendingLocalRestore();

    expect(evidence).toMatchObject({
      status: "success",
    });
    expect(active.marker).toBe("backup-state");
    expect(hasPendingLocalRestore()).toBe(false);
  },
);

test(
  "successful cancellation leaves current data intact on a later startup",
  async () => {
    const active = seedDatabase(
      ACTIVE_DATABASE,
      "current-state",
    );
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    await cancelPendingLocalRestore();
    const evidence =
      await activatePendingLocalRestore();

    expect(evidence).toBeNull();
    expect(active.marker).toBe("current-state");
    expect(mockBackupDatabaseAsync).not.toHaveBeenCalled();
  },
);

test(
  "invalid staged backup is rejected before the active database is touched",
  async () => {
    const active =
      seedDatabase(
        ACTIVE_DATABASE,
        "current-state",
      );

    seedDatabase(
      PENDING_DATABASE,
      "invalid-backup",
    );

    mockValidate.mockRejectedValueOnce(
      new Error(
        "This file is not a supported Nutrition App backup.",
      ),
    );

    const evidence =
      await activatePendingLocalRestore();

    expect(evidence).toMatchObject({
      status: "failure",
    });

    expect(active.marker).toBe(
      "current-state",
    );

    expect(
      mockBackupDatabaseAsync,
    ).not.toHaveBeenCalled();

    expect(
      hasPendingLocalRestore(),
    ).toBe(false);

    expect(
      lastWrittenEvidence(),
    ).toMatchObject({
      status: "failure",
    });
  },
);

test(
  "failed post-replacement validation restores the original database",
  async () => {
    const active =
      seedDatabase(
        ACTIVE_DATABASE,
        "current-state",
      );

    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockValidate.mockImplementation(
      async (
        db: MockDatabase,
        mode?: "artifact" | "active",
      ) => {
        if (
          db.name === ACTIVE_DATABASE &&
          mode === "active"
        ) {
          throw new Error(
            "post-replacement validation failed",
          );
        }

        return SUMMARY;
      },
    );

    const evidence =
      await activatePendingLocalRestore();

    expect(evidence).toMatchObject({
      status: "failure",
    });

    // Replacement happened, validation failed,
    // then rollback restored the original bytes/state.
    expect(active.marker).toBe(
      "current-state",
    );

    // Current -> rollback,
    // pending -> active,
    // rollback -> active.
    expect(
      mockBackupDatabaseAsync,
    ).toHaveBeenCalledTimes(3);

    expect(
      hasPendingLocalRestore(),
    ).toBe(false);

    expect(
      lastWrittenEvidence(),
    ).toMatchObject({
      status: "failure",
    });
  },
);

test(
  "a cleanup failure after activation cannot replay the consumed restore",
  async () => {
    const active = seedDatabase(
      ACTIVE_DATABASE,
      "current-state",
    );
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    mockDeleteDatabaseAsync.mockImplementation(
      async (
        name: string,
        directory = mockDatabaseDirectory,
      ) => {
        if (
          name.startsWith("nutrition-restore-consumed-")
        ) {
          throw new Error(
            "consumed cleanup failed",
          );
        }

        mockFiles.delete(
          `${directory.replace(/\/$/, "")}/${name}`,
        );
        if (name !== ACTIVE_DATABASE) {
          mockDatabases.delete(name);
        }
      },
    );
    mockFileDelete.mockImplementation(
      async (uri: string) => {
        if (uri.includes("nutrition-restore-consumed-")) {
          throw new Error(
            "consumed file cleanup failed",
          );
        }
        mockFiles.delete(uri);
      },
    );

    const firstEvidence =
      await activatePendingLocalRestore();

    expect(firstEvidence).toMatchObject({
      status: "success",
    });
    expect(active.marker).toBe("backup-state");
    expect(hasPendingLocalRestore()).toBe(false);
    expect(consumedUris()).toHaveLength(1);

    active.marker = "mutated-after-restore";

    const secondEvidence =
      await activatePendingLocalRestore();

    expect(secondEvidence).toBeNull();
    expect(active.marker).toBe(
      "mutated-after-restore",
    );
    expect(mockBackupDatabaseAsync).toHaveBeenCalledTimes(2);

    // A later explicit staging may reuse the fixed pending namespace even
    // while the disposable consumed artifact from the first restore remains.
    seedDatabase(
      PENDING_DATABASE,
      "new-backup-state",
    );

    const thirdEvidence =
      await activatePendingLocalRestore();

    expect(thirdEvidence).toMatchObject({
      status: "success",
    });
    expect(active.marker).toBe("new-backup-state");
    expect(hasPendingLocalRestore()).toBe(false);
  },
);

test(
  "a durable consumption boundary failure fails closed before replacement",
  async () => {
    const active = seedDatabase(
      ACTIVE_DATABASE,
      "current-state",
    );
    seedDatabase(
      PENDING_DATABASE,
      "backup-state",
    );

    // A platform no-op must not be accepted as a one-use rename.
    mockFileMove.mockImplementationOnce(
      async () => undefined,
    );

    await expect(
      activatePendingLocalRestore(),
    ).rejects.toBeInstanceOf(
      LocalBackupActivationFatalError,
    );

    expect(active.marker).toBe("current-state");
    expect(hasPendingLocalRestore()).toBe(true);
    // The only copy was the rollback snapshot; the active authority was not
    // replaced while the consumption boundary was uncertain.
    expect(mockBackupDatabaseAsync).toHaveBeenCalledTimes(1);
  },
);

test(
  "backup creation failure removes its incomplete artifact and leaves source unchanged",
  async () => {
    const active =
      seedDatabase(
        ACTIVE_DATABASE,
        "current-state",
      );

    mockBackupDatabaseAsync
      .mockRejectedValueOnce(
        new Error(
          "backup copy failed",
        ),
      );

    await expect(
      createLocalBackupArtifact(),
    ).rejects.toThrow(
      "backup copy failed",
    );

    expect(active.marker).toBe(
      "current-state",
    );

    const destinationName =
      mockOpenDatabaseAsync
        .mock.calls[1]?.[0];

    expect(
      typeof destinationName,
    ).toBe("string");

    expect(
      mockFiles.has(
        databaseUri(
          destinationName as string,
        ),
      ),
    ).toBe(false);

    expect(
      mockValidate,
    ).not.toHaveBeenCalled();
  },
);

test(
  "successful backup is validated before being returned and can be explicitly cleaned up",
  async () => {
    seedDatabase(
      ACTIVE_DATABASE,
      "current-state",
    );

    const artifact =
      await createLocalBackupArtifact();

    expect(
      artifact.summary,
    ).toBe(SUMMARY);

    expect(
      artifact.fileName,
    ).toMatch(
      /^nutrition-backup-.*-v1\.nutritionbackup$/,
    );

    expect(
      mockValidate,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        marker: "current-state",
      }),
      "artifact",
    );

    expect(
      mockFiles.has(
        databaseUri(
          artifact.fileName,
        ),
      ),
    ).toBe(true);

    await deleteLocalBackupArtifact(
      artifact.fileName,
    );

    expect(
      mockFiles.has(
        databaseUri(
          artifact.fileName,
        ),
      ),
    ).toBe(false);
  },
);
