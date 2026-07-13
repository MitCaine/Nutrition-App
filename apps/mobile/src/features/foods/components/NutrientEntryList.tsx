import { useMemo } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { nutrientFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";

import type { FoodNutrientInput, NutrientDefinition } from "../api/types";

type Props = {
  nutrients: NutrientDefinition[];
  values: FoodNutrientInput[];
  onChange: (values: FoodNutrientInput[]) => void;
  focusProps?: (key: string) => FocusTargetRegistration;
};

const statuses: FoodNutrientInput["data_status"][] = ["known", "zero", "estimated", "unknown"];

export function NutrientEntryList({ nutrients, values, onChange, focusProps }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const byId = new Map(values.map((value) => [value.nutrient_id, value]));

  function update(nutrientId: string, patch: Partial<FoodNutrientInput>) {
    const current = byId.get(nutrientId);
    const definition = nutrients.find((nutrient) => nutrient.id === nutrientId);
    if (!current || !definition) {
      return;
    }
    const next = values.map((value) =>
      value.nutrient_id === nutrientId
        ? {
            ...value,
            ...patch,
            amount: patch.data_status === "unknown" ? null : patch.amount ?? value.amount,
            unit: patch.unit ?? value.unit,
          }
        : value,
    );
    onChange(next);
  }

  return (
    <View style={styles.container}>
      {nutrients.map((nutrient) => {
        const value = byId.get(nutrient.id);
        if (!value) {
          return null;
        }
        const indent = nutrient.parent_nutrient_id ? styles.childRow : undefined;
        return (
          <View key={nutrient.id} style={[styles.row, indent]}>
            <Text style={styles.label}>{nutrient.display_name}</Text>
            <View style={styles.valueRow}>
              <TextInput
                {...(focusProps ? focusProps(nutrientFocusKey(nutrient.id)) : {})}
                placeholderTextColor={theme.colors.placeholder}
                value={value.amount ?? ""}
                onChangeText={(text) => update(nutrient.id, { amount: text })}
                editable={value.data_status !== "unknown" && value.data_status !== "zero"}
                keyboardType="decimal-pad"
                placeholder={value.data_status === "unknown" ? "unknown" : "0"}
                style={styles.amountInput}
              />
              <Text style={styles.unit}>{value.unit}</Text>
            </View>
            <View style={styles.statusRow}>
              {statuses.map((status) => (
                <Pressable
                  key={`${nutrient.id}-${status}`}
                  onPress={() =>
                    update(nutrient.id, {
                      data_status: status,
                      amount: status === "zero" ? "0" : status === "unknown" ? null : value.amount,
                    })
                  }
                  style={[styles.statusButton, value.data_status === status && styles.statusActive]}
                >
                  <Text style={styles.statusText}>{status}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        );
      })}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  amountInput: {
    backgroundColor: theme.colors.input, borderColor: theme.colors.border, color: theme.colors.text,
    borderRadius: 6,
    borderWidth: 1,
    minWidth: 88,
    padding: 10,
  },
  childRow: {
    paddingLeft: 20,
  },
  container: {
    gap: 12,
  },
  label: {
    color: theme.colors.text,
    fontSize: 15,
    fontWeight: "600",
  },
  row: {
    borderBottomColor: theme.colors.border,
    borderBottomWidth: 1,
    gap: 8,
    paddingBottom: 12,
  },
  statusActive: {
    backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent,
  },
  statusButton: {
    borderColor: theme.colors.border,
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  statusRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  statusText: {
    color: theme.colors.text,
    fontSize: 12,
  },
  unit: {
    color: theme.colors.text,
    paddingTop: 10,
  },
  valueRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: 8,
  },
}); }
