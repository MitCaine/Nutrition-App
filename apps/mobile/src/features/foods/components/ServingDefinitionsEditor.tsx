import { useMemo } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";

import type { ServingFormValue } from "../hooks/useFoodForm";
import { servingFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";

type Props = {
  servings: ServingFormValue[];
  updateServing: (key: string, patch: Partial<ServingFormValue>) => void;
  addServing: () => void;
  removeServing: (key: string) => void;
  focusProps: (key: string) => FocusTargetRegistration;
};

export function ServingDefinitionsEditor({
  servings,
  updateServing,
  addServing,
  removeServing,
  focusProps,
}: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View style={styles.container}>
      {servings.map((serving) => (
        <View key={serving.key} style={styles.servingBlock}>
          <View>
            <TextInput
              {...focusProps(servingFocusKey(serving.key, "label"))}
              placeholderTextColor={theme.colors.placeholder}
              value={serving.label}
              onChangeText={(label) => updateServing(serving.key, { label })}
              placeholder="Label"
              style={styles.input}
            />
          </View>
          <View style={styles.row}>
            <View style={styles.flex}>
              <TextInput
                {...focusProps(servingFocusKey(serving.key, "quantity"))}
                placeholderTextColor={theme.colors.placeholder}
                value={serving.quantity}
                onChangeText={(quantity) => updateServing(serving.key, { quantity })}
                keyboardType="decimal-pad"
                placeholder="Quantity"
                style={styles.input}
              />
            </View>
            <View style={styles.flex}>
              <TextInput
                {...focusProps(servingFocusKey(serving.key, "unit"))}
                placeholderTextColor={theme.colors.placeholder}
                value={serving.unit}
                onChangeText={(unit) => updateServing(serving.key, { unit })}
                placeholder="Unit"
                style={styles.input}
              />
            </View>
          </View>
          <View>
            <TextInput
              {...focusProps(servingFocusKey(serving.key, "gramWeight"))}
              placeholderTextColor={theme.colors.placeholder}
              value={serving.gram_weight ?? ""}
              onChangeText={(gram_weight) => updateServing(serving.key, { gram_weight })}
              keyboardType="decimal-pad"
              placeholder="Gram weight, if known"
              style={styles.input}
            />
          </View>
          <View style={styles.actions}>
            <Pressable onPress={() => updateServing(serving.key, { is_default: true })} style={[styles.button, serving.is_default && styles.active]}>
              <Text style={styles.text}>{serving.is_default ? "Default" : "Set default"}</Text>
            </Pressable>
            <Pressable onPress={() => removeServing(serving.key)} style={styles.button}>
              <Text style={styles.text}>Remove</Text>
            </Pressable>
          </View>
        </View>
      ))}
      <Pressable onPress={addServing} style={styles.addButton}>
        <Text style={styles.addText}>Add Serving</Text>
      </Pressable>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  actions: { flexDirection: "row", gap: 8 },
  active: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
  addButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, padding: 12 }, addText: { color: theme.colors.accent, fontWeight: "700" },
  button: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  container: { gap: 12 },
  flex: { flex: 1 },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  row: { flexDirection: "row", gap: 8 },
  servingBlock: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 8, paddingBottom: 12 },
}); }
