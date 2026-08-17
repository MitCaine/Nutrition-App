import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, {
  act,
  type ReactTestInstance,
} from "react-test-renderer";

const mockGetDocumentAsync = jest.fn();
const mockSharingAvailable = jest.fn();
const mockShareAsync = jest.fn();

const mockCreateBackup = jest.fn();
const mockDeleteBackup = jest.fn();
const mockInspectBackup = jest.fn();
const mockStageRestore = jest.fn();
const mockCancelRestore = jest.fn();
const mockReadEvidence = jest.fn();
const mockHasPendingRestore = jest.fn();

jest.mock("expo-document-picker", () => ({
  getDocumentAsync: (...args: unknown[]) =>
    mockGetDocumentAsync(...args),
}));

jest.mock("expo-sharing", () => ({
  isAvailableAsync: (...args: unknown[]) =>
    mockSharingAvailable(...args),
  shareAsync: (...args: unknown[]) =>
    mockShareAsync(...args),
}));

jest.mock("../src/storage/backup/localBackup", () => ({
  createLocalBackupArtifact: (...args: unknown[]) =>
    mockCreateBackup(...args),
  deleteLocalBackupArtifact: (...args: unknown[]) =>
    mockDeleteBackup(...args),
  inspectLocalBackupFromUri: (...args: unknown[]) =>
    mockInspectBackup(...args),
  stageLocalRestoreFromUri: (...args: unknown[]) =>
    mockStageRestore(...args),
  cancelPendingLocalRestore: (...args: unknown[]) =>
    mockCancelRestore(...args),
  readLastLocalRestoreEvidence: (...args: unknown[]) =>
    mockReadEvidence(...args),
  hasPendingLocalRestore: (...args: unknown[]) =>
    mockHasPendingRestore(...args),
}));

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual(
    "../src/app/theme/AppTheme",
  );

  return {
    ...actual,
    useAppTheme: () => ({
      ...actual.LIGHT_THEME,
      preference: "system",
      effectiveScheme: "light",
      setPreference: jest.fn(),
    }),
  };
});

import {
  LocalBackupSettings,
} from "../src/app/settings/LocalBackupSettings";

const SUMMARY = Object.freeze({
  formatVersion: 1 as const,
  schemaVersion: 4,
  ownerId:
    "00000000-0000-4000-8000-000000000001",
  totalRows: 42,
  rowCounts: Object.freeze({
    users: 1,
    food_items: 4,
  }),
});

function textContent(
  node: ReactTestInstance,
): string {
  return node.children
    .map((child) =>
      typeof child === "string"
        ? child
        : textContent(child),
    )
    .join("");
}

function visibleText(
  renderer: TestRenderer.ReactTestRenderer,
): string {
  return renderer.root
    .findAllByType(Text)
    .map(textContent)
    .join(" | ");
}

function button(
  renderer: TestRenderer.ReactTestRenderer,
  accessibilityLabel: string,
): ReactTestInstance {
  const found = renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel ===
        accessibilityLabel,
    );

  if (!found) {
    throw new Error(
      `Missing button ${accessibilityLabel}`,
    );
  }

  return found;
}

async function renderBackupSettings() {
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(LocalBackupSettings),
    );
  });

  return renderer;
}

beforeEach(() => {
  jest.clearAllMocks();

  mockHasPendingRestore.mockReturnValue(false);
  mockReadEvidence.mockResolvedValue(null);
  mockSharingAvailable.mockResolvedValue(true);
  mockShareAsync.mockResolvedValue(undefined);
  mockDeleteBackup.mockResolvedValue(undefined);
  mockCancelRestore.mockResolvedValue(undefined);

  mockCreateBackup.mockResolvedValue({
    fileName:
      "nutrition-backup-test-v1.nutritionbackup",
    uri: "file:///backup.nutritionbackup",
    summary: SUMMARY,
  });

  mockInspectBackup.mockResolvedValue(SUMMARY);
  mockStageRestore.mockResolvedValue(SUMMARY);

  mockGetDocumentAsync.mockResolvedValue({
    canceled: false,
    assets: [
      {
        uri: "file:///selected.nutritionbackup",
        name: "selected.nutritionbackup",
      },
    ],
  });
});

test("export validates, shares, and removes the temporary artifact", async () => {
  const renderer =
    await renderBackupSettings();

  await act(async () => {
    button(
      renderer,
      "Export local Nutrition App backup",
    ).props.onPress();
  });

  expect(mockCreateBackup).toHaveBeenCalledTimes(1);
  expect(mockSharingAvailable).toHaveBeenCalledTimes(1);

  expect(mockShareAsync).toHaveBeenCalledWith(
    "file:///backup.nutritionbackup",
    expect.objectContaining({
      dialogTitle: "Save Nutrition App backup",
    }),
  );

  expect(mockDeleteBackup).toHaveBeenCalledWith(
    "nutrition-backup-test-v1.nutritionbackup",
  );

  expect(visibleText(renderer)).toContain(
    "Backup validated with 42 application rows",
  );

  await act(async () => renderer.unmount());
});

test("selecting a backup only inspects it until explicit restore staging", async () => {
  const renderer =
    await renderBackupSettings();

  await act(async () => {
    button(
      renderer,
      "Choose local Nutrition App backup to restore",
    ).props.onPress();
  });

  expect(mockGetDocumentAsync).toHaveBeenCalledWith({
    copyToCacheDirectory: true,
    multiple: false,
    type: "*/*",
  });

  expect(mockInspectBackup).toHaveBeenCalledWith(
    "file:///selected.nutritionbackup",
  );

  expect(mockStageRestore).not.toHaveBeenCalled();

  expect(visibleText(renderer)).toContain(
    "Review validated backup",
  );
  expect(visibleText(renderer)).toContain(
    "Application rows: 42",
  );
  expect(visibleText(renderer)).toContain(
    "This is a replacement, not a merge.",
  );

  await act(async () => {
    button(
      renderer,
      "Stage validated local restore",
    ).props.onPress();
  });

  expect(mockStageRestore).toHaveBeenCalledWith(
    "file:///selected.nutritionbackup",
  );

  expect(visibleText(renderer)).toContain(
    "Restore pending restart",
  );
  expect(visibleText(renderer)).toContain(
    "Fully close Nutrition App and reopen it",
  );

  await act(async () => renderer.unmount());
});

test("canceling review never stages a restore", async () => {
  const renderer =
    await renderBackupSettings();

  await act(async () => {
    button(
      renderer,
      "Choose local Nutrition App backup to restore",
    ).props.onPress();
  });

  await act(async () => {
    button(
      renderer,
      "Cancel restore review",
    ).props.onPress();
  });

  expect(mockStageRestore).not.toHaveBeenCalled();
  expect(visibleText(renderer)).not.toContain(
    "Review validated backup",
  );

  await act(async () => renderer.unmount());
});

test("a pending restore can be canceled before restart", async () => {
  mockHasPendingRestore.mockReturnValue(true);

  const renderer =
    await renderBackupSettings();

  expect(visibleText(renderer)).toContain(
    "Restore pending restart",
  );

  await act(async () => {
    button(
      renderer,
      "Cancel pending local restore",
    ).props.onPress();
  });

  expect(mockCancelRestore).toHaveBeenCalledTimes(1);
  expect(visibleText(renderer)).toContain(
    "Pending restore canceled",
  );
  expect(visibleText(renderer)).not.toContain(
    "Restore pending restart",
  );

  await act(async () => renderer.unmount());
});

test("invalid selected backup fails closed without staging", async () => {
  mockInspectBackup.mockRejectedValue(
    new Error("This file is not a supported Nutrition App backup."),
  );

  const renderer =
    await renderBackupSettings();

  await act(async () => {
    button(
      renderer,
      "Choose local Nutrition App backup to restore",
    ).props.onPress();
  });

  expect(mockStageRestore).not.toHaveBeenCalled();
  expect(visibleText(renderer)).toContain(
    "This file is not a supported Nutrition App backup.",
  );

  await act(async () => renderer.unmount());
});

test("last restore evidence remains visible on Settings", async () => {
  mockReadEvidence.mockResolvedValue({
    status: "success",
    recordedAt: "2026-08-17T00:00:00Z",
    message:
      "Local backup restored successfully. 42 application rows were validated.",
    ownerId: SUMMARY.ownerId,
    schemaVersion: 4,
    totalRows: 42,
  });

  const renderer =
    await renderBackupSettings();

  await act(async () => {
    await Promise.resolve();
  });

  expect(visibleText(renderer)).toContain(
    "Last restore result",
  );
  expect(visibleText(renderer)).toContain(
    "Local backup restored successfully",
  );

  await act(async () => renderer.unmount());
});
