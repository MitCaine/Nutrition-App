import { useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { isZeroDecimalString } from "../../../shared/forms/decimalString";
import { nutrientFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import { NutrientAmountRow } from "../../../shared/nutrition/NutrientAmountRow";

import type { FoodNutrientInput, NutrientDefinition } from "../api/types";

type Props = {
  nutrients: NutrientDefinition[];
  values: FoodNutrientInput[];
  onChange: (values: FoodNutrientInput[]) => void;
  focusProps?: (key: string) => FocusTargetRegistration;
  disabled?: boolean;
  validationTarget?: string | null;
  validationError?: string | null;
};

export function NutrientEntryList({ nutrients, values, onChange, focusProps, disabled = false, validationTarget, validationError }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const byId = new Map(values.map((value) => [value.nutrient_id, value]));

  function update(nutrientId: string, patch: Partial<FoodNutrientInput>) {
    const current = byId.get(nutrientId);
    const definition = nutrients.find((nutrient) => nutrient.id === nutrientId);
    if (!current || !definition) {
      return;
    }
    const next = values.map((value) => {
      if (value.nutrient_id !== nutrientId) {
        return value;
      }
      const amountChanged = Object.prototype.hasOwnProperty.call(patch, "amount");
      const nextAmount = amountChanged ? patch.amount : value.amount;
      const nextStatus = patch.data_status ?? (
        amountChanged
          ? nextAmount == null || nextAmount === ""
            ? "unknown"
            : isZeroDecimalString(nextAmount)
              ? "zero"
              : "known"
          : value.data_status
      );
      return {
        ...value,
        ...patch,
        amount: nextStatus === "unknown" ? null : nextAmount ?? null,
        data_status: nextStatus,
        unit: patch.unit ?? value.unit,
      };
    });
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
        const invalid = validationTarget === `nutrient.${nutrient.id}.amount`;
        return (
          <View key={nutrient.id} style={[styles.row, indent]}>
            <NutrientAmountRow
              {...(focusProps ? focusProps(nutrientFocusKey(nutrient.id)) : {})}
              label={nutrient.display_name}
              containerStyle={styles.amountRow}
              inputStyle={styles.amountInput}
              hitSlop={{ top: 2, bottom: 2, left: 0, right: 0 }}
              validationTarget={`nutrient.${nutrient.id}.amount`}
              unit={value.unit}
              value={value.amount ?? ""}
              onChangeText={(text) => update(nutrient.id, { amount: text })}
              accessibilityState={{ disabled }}
              editable={!disabled}
              keyboardType="decimal-pad"
              placeholderTextColor={theme.colors.placeholder}
              invalid={invalid}
              error={invalid ? validationError : null}
              action={(
                <AccessiblePressable
                  accessibilityLabel={`Omit ${nutrient.display_name}`}
                  accessibilityHint="Removes the amount and marks this nutrient as unknown"
                  disabled={disabled}
                  onPress={() => update(nutrient.id, { amount: null, data_status: "unknown" })}
                >
                  <Text style={styles.omitText}>Omit</Text>
                </AccessiblePressable>
              )}
            />
          </View>
        );
      })}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  childRow: {
    paddingLeft: 16,
  },
  container: {
    gap: 10,
  },
  amountRow: {
    gap: 3,
  },
  amountInput: {
    height: 40,
    minHeight: 40,
    paddingHorizontal: 8,
    width: 112,
  },
  row: {
    borderBottomColor: theme.colors.border,
    borderBottomWidth: 1,
    gap: 8,
    paddingBottom: 8,
  },
  omitText: {
    color: theme.colors.accent,
    fontWeight: "700",
  },
}); }
