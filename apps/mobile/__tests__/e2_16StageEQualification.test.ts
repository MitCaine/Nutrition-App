const mockFileContents = new Map<string, string>();

jest.mock("expo-sqlite", () => ({
  defaultDatabaseDirectory: "file:///qualification/SQLite",
  openDatabaseAsync: jest.fn(),
}));

jest.mock("expo-file-system", () => {
  class FakeDirectory {
    readonly uri: string;

    constructor(...parts: Array<string | { uri: string }>) {
      this.uri = parts.map((part) => typeof part === "string" ? part : part.uri)
        .join("/").replace(/([^:])\/+/g, "$1/");
    }
  }
  class FakeFile {
    readonly uri: string;

    constructor(...parts: Array<string | { uri: string }>) {
      this.uri = parts.map((part) => typeof part === "string" ? part : part.uri)
        .join("/").replace(/([^:])\/+/g, "$1/");
    }

    get exists(): boolean {
      return mockFileContents.has(this.uri);
    }

    create(options?: { overwrite?: boolean }): void {
      if (this.exists && !options?.overwrite) throw new Error("already exists");
      mockFileContents.set(this.uri, "");
    }

    write(value: string): void {
      mockFileContents.set(this.uri, value);
    }

    textSync(): string {
      const value = mockFileContents.get(this.uri);
      if (value === undefined) throw new Error("file does not exist");
      return value;
    }

    delete(): void {
      mockFileContents.delete(this.uri);
    }
  }
  return {
    Directory: FakeDirectory,
    File: FakeFile,
    Paths: { availableDiskSpace: 123456789 },
  };
});

import {
  E216_ALLOWED_DATABASE_NAMES,
  E216_STAGE_E_CHECKPOINT_SCHEMA,
  qualificationDatabaseDirectory,
  qualificationDatabaseName,
} from "../src/dev/e2_16/e216QualificationFoundation";
import {
  E216_STAGE_E_CASE_DEFINITIONS,
  E216_STAGE_E_FILLER_CLEANUP_STATEMENT,
  E216_STAGE_E_FILLER_TABLE,
  E216_STAGE_E_HARNESS_SETUP_STATEMENTS,
  E216_STAGE_E_SENTINEL_TABLE,
  E216_STAGE_E_SENTINEL_VALUE,
  buildE216StageEBoundedPageLimitPlan,
  classifyE216StageENativeError,
  isE216StageEResetDeleteEvidencePass,
  isE216StageESentinelPreserved,
  nativeE216StageEErrorText,
  readE216StageECheckpoint,
  withE216StageEHandle,
  writeE216StageECheckpoint,
  type E216StageECheckpointMarker,
} from "../src/dev/e2_16/e216StageEQualification";

describe("E2-16E qualification harness", () => {
  afterEach(() => mockFileContents.clear());

  it("keeps Stage-E on the isolated iOS database allowlist", () => {
    expect(E216_STAGE_E_CASE_DEFINITIONS).toHaveLength(2);
    expect(qualificationDatabaseName("ios", "storage")).toBe("e2_16_storage_ios.db");
    expect(qualificationDatabaseDirectory()).toBe("file://qualification/SQLite/E2-16");
    expect(E216_ALLOWED_DATABASE_NAMES).toContain("e2_16_storage_ios.db");
    expect(E216_ALLOWED_DATABASE_NAMES).not.toContain("nutrition.db");
    expect(() => qualificationDatabaseName("android", "storage")).toThrow("E2-16E");
  });

  it("classifies only owning-layer path/full native wording", () => {
    const pathError = Object.assign(new Error("SQLiteError: unable to open database: not a directory"), {
      code: "SQLITE_CANTOPEN",
    });
    const fullError = Object.assign(new Error("SQLiteError: database or disk is full"), {
      code: "SQLITE_FULL",
    });
    expect(classifyE216StageENativeError(pathError, "path_open")).toBe("native_path_open_failure");
    expect(classifyE216StageENativeError(fullError, "sqlite_full")).toBe("sqlite_full");
    expect(classifyE216StageENativeError(new Error("arbitrary JavaScript failure"), "path_open"))
      .toBe("unexpected_native_rejection");
    expect(nativeE216StageEErrorText(fullError)).toContain("SQLITE_FULL");
  });

  it("plans a bounded disposable page window and explicit filler cleanup", () => {
    const plan = buildE216StageEBoundedPageLimitPlan(42, 100, 8);
    expect(plan.boundedMaxPageCount).toBe(50);
    expect(() => buildE216StageEBoundedPageLimitPlan(100, 100)).toThrow("page-count");
    expect(E216_STAGE_E_HARNESS_SETUP_STATEMENTS.join("\n")).toContain(`"${E216_STAGE_E_SENTINEL_TABLE}"`);
    expect(E216_STAGE_E_HARNESS_SETUP_STATEMENTS.join("\n")).toContain(`"${E216_STAGE_E_FILLER_TABLE}"`);
    expect(E216_STAGE_E_FILLER_CLEANUP_STATEMENT).toContain(`DROP TABLE IF EXISTS "${E216_STAGE_E_FILLER_TABLE}"`);
  });

  it("requires the committed sentinel and no reset/delete during induced failure", () => {
    expect(isE216StageESentinelPreserved(E216_STAGE_E_SENTINEL_VALUE, E216_STAGE_E_SENTINEL_VALUE)).toBe(true);
    expect(isE216StageESentinelPreserved(E216_STAGE_E_SENTINEL_VALUE, null)).toBe(false);
    expect(isE216StageEResetDeleteEvidencePass({ duringFailureAndReopen: [] })).toBe(true);
    expect(isE216StageEResetDeleteEvidencePass({
      duringFailureAndReopen: [{
        kind: "delete",
        stage: "storage",
        databaseName: "e2_16_storage_ios.db",
      }],
    })).toBe(false);
  });

  it("writes and reads a host-visible marker before native failure", () => {
    const marker: E216StageECheckpointMarker = {
      schema: E216_STAGE_E_CHECKPOINT_SCHEMA,
      stage: "E2-16E",
      caseId: "native_path_open_failure",
      platform: "ios",
      databaseName: "e2_16_storage_ios.db",
      checkpointReached: "before_native_failure",
      state: "running",
      result: null,
    };
    writeE216StageECheckpoint(marker);
    expect(readE216StageECheckpoint()).toEqual(marker);
  });

  it("closes only after the operation settles, including rejection", async () => {
    let pendingNativeStatements = 0;
    let closeCalls = 0;
    const handle = {
      database: {} as never,
      close: async () => {
        expect(pendingNativeStatements).toBe(0);
        closeCalls += 1;
      },
    };
    await withE216StageEHandle(handle, async () => {
      pendingNativeStatements = 1;
      await Promise.resolve();
      pendingNativeStatements = 0;
    });
    expect(closeCalls).toBe(1);

    await expect(withE216StageEHandle(handle, async () => {
      pendingNativeStatements = 1;
      await Promise.resolve();
      pendingNativeStatements = 0;
      throw new Error("settled operation failure");
    })).rejects.toThrow("settled operation failure");
    expect(closeCalls).toBe(2);
  });
});
