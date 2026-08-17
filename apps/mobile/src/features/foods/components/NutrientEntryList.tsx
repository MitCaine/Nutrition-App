import { useMemo, useState } from "react";
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
  hideUnknownByDefault?: boolean;
};

export function foodFormVisibleNutrients(
  nutrients: readonly NutrientDefinition[],
  values: readonly FoodNutrientInput[],
  revealedUnknownIds: ReadonlySet<string>,
  hideUnknownByDefault: boolean,
): NutrientDefinition[] {
  if (!hideUnknownByDefault) return [...nutrients];
  const byId = new Map(values.map((value) => [value.nutrient_id, value]));
  return nutrients.filter((nutrient) => {
    const value = byId.get(nutrient.id);
    return Boolean(value) && (value!.data_status !== "unknown" || revealedUnknownIds.has(nutrient.id));
  });
}

export function foodFormHiddenNutrients(
  nutrients: readonly NutrientDefinition[],
  values: readonly FoodNutrientInput[],
  revealedUnknownIds: ReadonlySet<string>,
): NutrientDefinition[] {
  const byId = new Map(values.map((value) => [value.nutrient_id, value]));
  return nutrients.filter((nutrient) => (
    byId.get(nutrient.id)?.data_status === "unknown"
    && !revealedUnknownIds.has(nutrient.id)
  ));
}

export function NutrientEntryList({
  nutrients,
  values,
  onChange,
  focusProps,
  disabled = false,
  validationTarget,
  validationError,
  hideUnknownByDefault = false,
}: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const [revealedUnknownIds, setRevealedUnknownIds] = useState<Set<string>>(() => new Set());
  const [showMissingNutrients, setShowMissingNutrients] = useState(false);
  const byId = new Map(values.map((value) => [value.nutrient_id, value]));
  const visibleNutrients = foodFormVisibleNutrients(
    nutrients,
    values,
    revealedUnknownIds,
    hideUnknownByDefault,
  );
  const hiddenNutrients = hideUnknownByDefault
    ? foodFormHiddenNutrients(nutrients, values, revealedUnknownIds)
    : [];

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
    if (hideUnknownByDefault && next.find((value) => value.nutrient_id === nutrientId)?.data_status === "unknown") {
      setRevealedUnknownIds((current) => {
        if (!current.has(nutrientId)) return current;
        const nextIds = new Set(current);
        nextIds.delete(nutrientId);
        return nextIds;
      });
    }
  }

  function revealNutrient(nutrientId: string) {
    setRevealedUnknownIds((current) => new Set(current).add(nutrientId));
    setShowMissingNutrients(false);
  }

  return (
    <View style={styles.container}>
      {visibleNutrients.map((nutrient) => {
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
      {hideUnknownByDefault && hiddenNutrients.length > 0 ? (
        <AccessiblePressable
          accessibilityLabel="Add missing nutrient"
          accessibilityState={{ expanded: showMissingNutrients }}
          disabled={disabled}
          onPress={() => setShowMissingNutrients((current) => !current)}
          style={styles.addNutrientButton}
        >
          <Text style={styles.addNutrientText}>Add missing nutrient</Text>
        </AccessiblePressable>
      ) : null}
      {hideUnknownByDefault && showMissingNutrients ? (
        <View style={styles.picker}>
          <Text accessibilityRole="header" style={styles.pickerHeading}>Choose a nutrient</Text>
          {hiddenNutrients.map((nutrient) => (
            <AccessiblePressable
              key={nutrient.id}
              accessibilityLabel={`Add ${nutrient.display_name}`}
              disabled={disabled}
              onPress={() => revealNutrient(nutrient.id)}
              style={styles.pickerOption}
            >
              <Text style={styles.addNutrientText}>
                {nutrient.display_name} ({nutrient.default_unit})
              </Text>
            </AccessiblePressable>
          ))}
        </View>
      ) : null}
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
  addNutrientButton: {
    alignSelf: "flex-start",
    justifyContent: "center",
    minHeight: 44,
  },
  addNutrientText: {
    color: theme.colors.accent,
    fontWeight: "700",
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
  picker: {
    borderColor: theme.colors.border,
    borderRadius: 8,
    borderWidth: 1,
    gap: 8,
    padding: 12,
  },
  pickerHeading: {
    color: theme.colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  pickerOption: {
    justifyContent: "center",
    minHeight: 44,
  },
}); }
