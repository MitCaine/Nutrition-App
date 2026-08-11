import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  hasE216FoundationCheckpoint,
  openE216QualificationDatabase,
  resetE216QualificationDatabase,
  writeE216FoundationCheckpoint,
} from "./e216QualificationFoundation";
import {
  qualifyE216Database,
  serializeE216IntegrityResult,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import type { NutritionDatabaseHandle } from "../../storage/sqlite/migrations";
import { bootstrapOpenedLocalRuntimeFoundation } from "../../runtime/local/localRuntimeFoundation";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function E216NativeQualificationScreen() {
  const [handle, setHandle] = useState<NutritionDatabaseHandle | null>(null);
  const [result, setResult] = useState<E216DirectIntegrityResult | null>(null);
  const [checkpoint, setCheckpoint] = useState(hasE216FoundationCheckpoint());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const handleRef = useRef<NutritionDatabaseHandle | null>(null);
  handleRef.current = handle;

  useEffect(() => () => {
    void handleRef.current?.close();
  }, []);

  async function openDatabase(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      const opened = await openE216QualificationDatabase();
      try {
        await bootstrapOpenedLocalRuntimeFoundation(opened);
      } catch (error) {
        await opened.close();
        throw error;
      }
      handleRef.current = opened;
      setHandle(opened);
      setResult(null);
      setMessage("E2-16A qualification database migrated with one synthetic local owner/profile.");
    } catch (error) {
      setMessage(`Open failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runQualifier(): Promise<void> {
    const current = handleRef.current;
    if (!current) {
      setMessage("Open the isolated qualification database first.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const next = await qualifyE216Database(current.database);
      setResult(next);
      setMessage(next.status === "pass" ? "Direct integrity qualifier passed." : "Direct integrity qualifier failed.");
    } catch (error) {
      setMessage(`Qualifier failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function writeCheckpoint(): void {
    try {
      writeE216FoundationCheckpoint();
      setCheckpoint(true);
      setMessage("Host-visible foundation_ready checkpoint written.");
    } catch (error) {
      setMessage(`Checkpoint failed: ${errorMessage(error)}`);
    }
  }

  async function reset(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await resetE216QualificationDatabase();
      handleRef.current = null;
      setHandle(null);
      setResult(null);
      setCheckpoint(hasE216FoundationCheckpoint());
      setMessage("E2-16A isolated database and checkpoint reset completed.");
    } catch (error) {
      setMessage(`Reset failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.title}>Nutrition App E2-16</Text>
      <Text style={styles.subtitle}>E2-16A native qualification safety foundation</Text>
      <Text style={styles.warning}>
        Temporary development-only infrastructure. Later E2-16 lifecycle, feature, filesystem,
        accessibility, and OCR scenarios are not implemented here.
      </Text>

      <View style={styles.card}>
        <Text style={styles.heading}>Isolated boundary</Text>
        <Text selectable style={styles.detail}>Bundle: com.portfolio.nutritionapp.e216</Text>
        <Text selectable style={styles.detail}>Database: e2_16_foundation_&lt;platform&gt;.db</Text>
        <Text style={styles.detail}>Root: Expo SQLite default root / E2-16</Text>
        <Text style={styles.detail}>Normal nutrition.db is never opened or deleted.</Text>
      </View>

      <View style={styles.actions}>
        <Pressable accessibilityRole="button" accessibilityLabel="Open isolated qualification database" style={styles.button} disabled={busy} onPress={() => void openDatabase()}>
          <Text style={styles.buttonText}>OPEN / MIGRATE</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Run direct integrity qualifier" style={styles.button} disabled={busy || handle === null} onPress={() => void runQualifier()}>
          <Text style={styles.buttonText}>RUN INTEGRITY QUALIFIER</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Write host-visible foundation checkpoint" style={styles.button} disabled={busy} onPress={writeCheckpoint}>
          <Text style={styles.buttonText}>WRITE CHECKPOINT</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Reset isolated qualification database" style={[styles.button, styles.resetButton]} disabled={busy} onPress={() => void reset()}>
          <Text style={styles.buttonText}>RESET ISOLATED STATE</Text>
        </Pressable>
      </View>

      {busy ? <ActivityIndicator accessibilityLabel="E2-16A operation in progress" /> : null}
      <Text style={styles.status}>Database: {handle ? "open" : "closed"}</Text>
      <Text style={styles.status}>Checkpoint: {checkpoint ? "foundation_ready" : "absent"}</Text>
      {message ? <Text accessibilityRole="alert" style={styles.message}>{message}</Text> : null}
      {result ? (
        <View style={styles.resultCard}>
          <Text style={styles.heading}>Bounded qualifier evidence</Text>
          <Text selectable style={styles.result}>{serializeE216IntegrityResult(result)}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    gap: 16,
    padding: 24,
    paddingBottom: 48,
  },
  title: {
    color: "#102a43",
    fontSize: 28,
    fontWeight: "700",
  },
  subtitle: {
    color: "#334e68",
    fontSize: 18,
    fontWeight: "600",
  },
  warning: {
    color: "#7c2d12",
    fontSize: 15,
    lineHeight: 22,
  },
  card: {
    backgroundColor: "#f0f4f8",
    borderRadius: 8,
    gap: 6,
    padding: 16,
  },
  heading: {
    color: "#102a43",
    fontSize: 17,
    fontWeight: "700",
  },
  detail: {
    color: "#243b53",
    fontFamily: "monospace",
    fontSize: 13,
  },
  actions: {
    gap: 10,
  },
  button: {
    alignItems: "center",
    backgroundColor: "#0b69a3",
    borderRadius: 6,
    minHeight: 48,
    justifyContent: "center",
    paddingHorizontal: 16,
  },
  resetButton: {
    backgroundColor: "#9b2c2c",
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 14,
    fontWeight: "700",
  },
  status: {
    color: "#334e68",
    fontSize: 15,
  },
  message: {
    color: "#102a43",
    fontSize: 15,
    lineHeight: 22,
  },
  resultCard: {
    backgroundColor: "#f7fafc",
    borderColor: "#bcccdc",
    borderRadius: 8,
    borderWidth: 1,
    padding: 12,
  },
  result: {
    color: "#102a43",
    fontFamily: "monospace",
    fontSize: 11,
    lineHeight: 16,
  },
});
