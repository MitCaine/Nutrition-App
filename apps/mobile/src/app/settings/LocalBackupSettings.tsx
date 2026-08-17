import { useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as Sharing from "expo-sharing";

import { useAppTheme } from "../theme/AppTheme";
import { AccessiblePressable } from "../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../shared/accessibility/AccessibilityStatus";
import {
  cancelPendingLocalRestore,
  createLocalBackupArtifact,
  deleteLocalBackupArtifact,
  hasPendingLocalRestore,
  inspectLocalBackupFromUri,
  readLastLocalRestoreEvidence,
  stageLocalRestoreFromUri,
  type LocalRestoreEvidence,
} from "../../storage/backup/localBackup";
import type {
  LocalBackupValidationSummary,
} from "../../storage/backup/localBackupValidation";

type RestoreCandidate = Readonly<{
  uri: string;
  name: string;
  summary: LocalBackupValidationSummary;
}>;

type BusyOperation =
  | "export"
  | "inspect"
  | "stage"
  | "cancel"
  | null;

function operationErrorMessage(error: unknown): string {
  const detail =
    error instanceof Error ? error.message : String(error);

  return `Local backup operation failed. ${detail}`;
}

export function LocalBackupSettings() {
  const theme = useAppTheme();
  const styles = useMemo(
    () => createStyles(theme),
    [theme],
  );

  const [busy, setBusy] =
    useState<BusyOperation>(null);
  const [error, setError] =
    useState<string | null>(null);
  const [message, setMessage] =
    useState<string | null>(null);
  const [candidate, setCandidate] =
    useState<RestoreCandidate | null>(null);
  const [restorePending, setRestorePending] =
    useState(() => hasPendingLocalRestore());
  const [lastEvidence, setLastEvidence] =
    useState<LocalRestoreEvidence | null>(null);

  useEffect(() => {
    let active = true;

    void readLastLocalRestoreEvidence().then(
      (evidence) => {
        if (active) {
          setLastEvidence(evidence);
        }
      },
    );

    return () => {
      active = false;
    };
  }, []);

  async function exportBackup() {
    if (busy) return;

    setBusy("export");
    setError(null);
    setMessage(null);

    let artifact:
      | Awaited<
          ReturnType<typeof createLocalBackupArtifact>
        >
      | null = null;

    try {
      artifact =
        await createLocalBackupArtifact();

      if (!(await Sharing.isAvailableAsync())) {
        throw new Error(
          "The system share sheet is unavailable on this device.",
        );
      }

      await Sharing.shareAsync(artifact.uri, {
        dialogTitle: "Save Nutrition App backup",
        mimeType: "application/octet-stream",
        UTI: "public.data",
      });

      setMessage(
        `Backup validated with ${artifact.summary.totalRows} application rows. ` +
        "The share sheet closed; confirm the backup exists in the destination you selected.",
      );
    } catch (caught) {
      setError(operationErrorMessage(caught));
    } finally {
      if (artifact) {
        try {
          await deleteLocalBackupArtifact(
            artifact.fileName,
          );
        } catch {
          // Temporary export cleanup is best effort.
        }
      }

      setBusy(null);
    }
  }

  async function chooseRestoreBackup() {
    if (busy) return;

    setBusy("inspect");
    setError(null);
    setMessage(null);
    setCandidate(null);

    try {
      const result =
        await DocumentPicker.getDocumentAsync({
          copyToCacheDirectory: true,
          multiple: false,
          type: "*/*",
        });

      if (result.canceled) {
        return;
      }

      const asset = result.assets[0];

      if (!asset) {
        throw new Error(
          "The selected backup could not be read.",
        );
      }

      const summary =
        await inspectLocalBackupFromUri(
          asset.uri,
        );

      setCandidate({
        uri: asset.uri,
        name: asset.name,
        summary,
      });
    } catch (caught) {
      setError(operationErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function confirmRestore() {
    if (!candidate || busy) return;

    setBusy("stage");
    setError(null);
    setMessage(null);

    try {
      const summary =
        await stageLocalRestoreFromUri(
          candidate.uri,
        );

      setCandidate(null);
      setRestorePending(true);
      setMessage(
        `Restore staged successfully with ${summary.totalRows} application rows. ` +
        "Fully close Nutrition App and reopen it to activate the validated backup.",
      );
    } catch (caught) {
      setError(operationErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  async function cancelPendingRestore() {
    if (busy) return;

    setBusy("cancel");
    setError(null);
    setMessage(null);

    try {
      await cancelPendingLocalRestore();
      setRestorePending(false);
      setMessage(
        "Pending restore canceled. The current local database was not changed.",
      );
    } catch (caught) {
      setError(operationErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <View style={styles.section}>
      <Text
        accessibilityRole="header"
        style={styles.sectionTitle}
      >
        Local data
      </Text>

      <View style={styles.card}>
        <Text
          accessibilityRole="header"
          style={styles.cardTitle}
        >
          Backup
        </Text>

        <Text style={styles.hint}>
          Export a complete validated snapshot of the local
          Nutrition App database. USDA credentials and other
          secrets are not included.
        </Text>

        <AccessiblePressable
          accessibilityLabel="Export local Nutrition App backup"
          accessibilityHint="Creates a validated local database snapshot and opens the system share sheet"
          busy={busy === "export"}
          disabled={busy !== null}
          onPress={exportBackup}
          style={({ pressed }) => [
            styles.primaryButton,
            pressed && styles.pressed,
            busy !== null && styles.disabled,
          ]}
        >
          <Text style={styles.primaryButtonText}>
            {busy === "export"
              ? "Preparing backup…"
              : "Export backup"}
          </Text>
        </AccessiblePressable>
      </View>

      <View style={styles.card}>
        <Text
          accessibilityRole="header"
          style={styles.cardTitle}
        >
          Restore
        </Text>

        <Text style={styles.hint}>
          A selected file is validated before restore can be
          staged. Staging does not modify the currently open
          database. The validated backup is activated only when
          the app is fully closed and reopened.
        </Text>

        {restorePending ? (
          <View style={styles.reviewCard}>
            <Text
              accessibilityRole="header"
              style={styles.reviewTitle}
            >
              Restore pending restart
            </Text>

            <Text style={styles.hint}>
              Fully close Nutrition App and reopen it to activate
              the staged backup. You can cancel the pending
              restore before restarting.
            </Text>

            <AccessiblePressable
              accessibilityLabel="Cancel pending local restore"
              accessibilityHint="Deletes the staged backup and keeps the current local database"
              busy={busy === "cancel"}
              disabled={busy !== null}
              onPress={cancelPendingRestore}
              style={({ pressed }) => [
                styles.secondaryButton,
                pressed && styles.pressed,
                busy !== null && styles.disabled,
              ]}
            >
              <Text style={styles.secondaryButtonText}>
                {busy === "cancel"
                  ? "Canceling…"
                  : "Cancel pending restore"}
              </Text>
            </AccessiblePressable>
          </View>
        ) : (
          <AccessiblePressable
            accessibilityLabel="Choose local Nutrition App backup to restore"
            accessibilityHint="Selects and validates a backup without changing current local data"
            busy={busy === "inspect"}
            disabled={busy !== null}
            onPress={chooseRestoreBackup}
            style={({ pressed }) => [
              styles.secondaryButton,
              pressed && styles.pressed,
              busy !== null && styles.disabled,
            ]}
          >
            <Text style={styles.secondaryButtonText}>
              {busy === "inspect"
                ? "Validating backup…"
                : "Choose backup to restore"}
            </Text>
          </AccessiblePressable>
        )}

        {candidate ? (
          <View style={styles.reviewCard}>
            <Text
              accessibilityRole="header"
              style={styles.reviewTitle}
            >
              Review validated backup
            </Text>

            <Text
              accessibilityLabel={
                `Validated backup file ${candidate.name}`
              }
              style={styles.reviewText}
            >
              File: {candidate.name}
            </Text>

            <Text style={styles.reviewText}>
              Format version:{" "}
              {candidate.summary.formatVersion}
            </Text>

            <Text style={styles.reviewText}>
              Schema version:{" "}
              {candidate.summary.schemaVersion}
            </Text>

            <Text style={styles.reviewText}>
              Application rows:{" "}
              {candidate.summary.totalRows}
            </Text>

            <Text style={styles.reviewText}>
              Local owner: {candidate.summary.ownerId}
            </Text>

            <Text style={styles.warning}>
              Confirming stages this backup to replace the
              current local authority on the next full app
              start. This is a replacement, not a merge.
            </Text>

            <View style={styles.actions}>
              <AccessiblePressable
                accessibilityLabel="Cancel restore review"
                disabled={busy !== null}
                onPress={() => setCandidate(null)}
                style={({ pressed }) => [
                  styles.secondaryButton,
                  styles.actionButton,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.secondaryButtonText}>
                  Cancel
                </Text>
              </AccessiblePressable>

              <AccessiblePressable
                accessibilityLabel="Stage validated local restore"
                accessibilityHint="Stages the validated backup for replacement on the next full app start"
                busy={busy === "stage"}
                disabled={busy !== null}
                onPress={confirmRestore}
                style={({ pressed }) => [
                  styles.destructiveButton,
                  styles.actionButton,
                  pressed && styles.pressed,
                  busy !== null && styles.disabled,
                ]}
              >
                <Text style={styles.destructiveButtonText}>
                  {busy === "stage"
                    ? "Staging…"
                    : "Stage restore"}
                </Text>
              </AccessiblePressable>
            </View>
          </View>
        ) : null}
      </View>

      {message ? (
        <Text
          accessibilityLabel={message}
          accessibilityLiveRegion="polite"
          style={styles.success}
        >
          {message}
        </Text>
      ) : null}

      {error ? (
        <AccessibilityStatus
          kind="retryable-failure"
          message={error}
        />
      ) : null}

      {lastEvidence ? (
        <View style={styles.evidenceCard}>
          <Text
            accessibilityRole="header"
            style={styles.reviewTitle}
          >
            Last restore result
          </Text>

          <Text
            accessibilityLabel={
              `Last restore ${lastEvidence.status}. ` +
              lastEvidence.message
            }
            style={
              lastEvidence.status === "success"
                ? styles.success
                : styles.warning
            }
          >
            {lastEvidence.status === "success"
              ? "Success"
              : "Not applied"}
            {" · "}
            {lastEvidence.message}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function createStyles(
  theme: ReturnType<typeof useAppTheme>,
) {
  return StyleSheet.create({
    section: {
      gap: 10,
    },
    sectionTitle: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      fontWeight: "700",
      marginTop: 8,
      textTransform: "uppercase",
    },
    card: {
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 10,
      borderWidth: 1,
      gap: 10,
      padding: 14,
    },
    cardTitle: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: "700",
    },
    hint: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 20,
    },
    primaryButton: {
      alignSelf: "stretch",
      backgroundColor: theme.colors.accent,
      borderRadius: 6,
      paddingHorizontal: 12,
      paddingVertical: 10,
    },
    primaryButtonText: {
      color: theme.colors.accentForeground,
      fontWeight: "700",
      textAlign: "center",
    },
    secondaryButton: {
      alignSelf: "stretch",
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      paddingHorizontal: 12,
      paddingVertical: 10,
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontWeight: "700",
      textAlign: "center",
    },
    destructiveButton: {
      alignSelf: "stretch",
      backgroundColor: theme.colors.destructive,
      borderRadius: 6,
      paddingHorizontal: 12,
      paddingVertical: 10,
    },
    destructiveButtonText: {
      color: theme.colors.primaryActionForeground,
      fontWeight: "700",
      textAlign: "center",
    },
    reviewCard: {
      backgroundColor: theme.colors.activeBackground,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 8,
      padding: 12,
    },
    reviewTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: "700",
    },
    reviewText: {
      color: theme.colors.text,
      fontSize: 14,
      lineHeight: 20,
    },
    warning: {
      color: theme.colors.warningText,
      fontSize: 14,
      fontWeight: "600",
      lineHeight: 20,
    },
    success: {
      color: theme.colors.successText,
      fontSize: 14,
      lineHeight: 20,
    },
    evidenceCard: {
      backgroundColor: theme.colors.secondarySurface,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 6,
      padding: 12,
    },
    actions: {
      flexDirection: "row",
      gap: 10,
    },
    actionButton: {
      flex: 1,
    },
    disabled: {
      opacity: 0.6,
    },
    pressed: {
      opacity: 0.8,
    },
  });
}
