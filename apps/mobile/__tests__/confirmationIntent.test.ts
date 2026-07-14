import { bindConfirmationIntent, confirmationPayloadFingerprint } from "../src/features/ocr/confirmation/confirmationIntent";
import type { OcrConfirmationInput } from "../src/features/ocr/api/types";

function payload(): OcrConfirmationInput {
  return {
    parser_version: "nutrition_label_v1", image_source_type: "camera", client_request_id: "request-placeholder",
    food: {
      name: "Cereal", brand: null, notes: null,
      serving_definitions: [{ label: "1 cup", quantity: "1", unit: "cup", gram_weight: "30", is_default: true }],
      nutrients: [{ nutrient_id: "calories", amount: "100", unit: "kcal", basis: "per_serving", data_status: "known" }],
    },
    field_decisions: [{
      field_key: "nutrient.calories", nutrient_id: "calories", suggested_value: "100", confirmed_value: "100", unit: "kcal",
      decision: "accepted", parse_status: "parsed", comparison: null, confidence: "0.9", source_text: "Calories 100",
      source_observation_ids: ["obs-1"], warning_codes: [], resolution: null,
    }],
    unknown_nutrients: [], parser_warning_codes: [],
  };
}

test("unchanged retries reuse one confirmation intent", () => {
  const createId = jest.fn(() => "request-1");
  const first = bindConfirmationIntent(null, payload(), createId);
  const retry = bindConfirmationIntent(first, { ...payload(), client_request_id: "ignored" }, createId);
  expect(retry).toBe(first);
  expect(createId).toHaveBeenCalledTimes(1);
});

test.each([
  ["name", (value: OcrConfirmationInput) => { value.food.name = "Edited"; }],
  ["serving", (value: OcrConfirmationInput) => { value.food.serving_definitions[0]!.gram_weight = "31"; }],
  ["nutrient", (value: OcrConfirmationInput) => { value.food.nutrients[0]!.amount = "101"; value.field_decisions[0]!.confirmed_value = "101"; }],
  ["omission", (value: OcrConfirmationInput) => { value.food.nutrients = []; value.field_decisions[0]!.decision = "omitted"; value.field_decisions[0]!.confirmed_value = null; }],
  ["unknown dismissal", (value: OcrConfirmationInput) => { value.unknown_nutrients.push({ original_name: "Mystery", source_text: "Mystery 2mg", source_observation_ids: ["obs-2"], warning_codes: [], decision: "dismissed" }); }],
] as const)("changing %s rotates the confirmation intent", (_label, mutate) => {
  const ids = ["request-1", "request-2"];
  const firstPayload = payload();
  const first = bindConfirmationIntent(null, firstPayload, () => ids.shift()!);
  const changed = payload(); mutate(changed);
  const second = bindConfirmationIntent(first, changed, () => ids.shift()!);
  expect(second.requestId).toBe("request-2");
  expect(second.fingerprint).not.toBe(first.fingerprint);
});

test("fingerprint normalizes mapping keys but preserves array order", () => {
  const first = payload();
  first.field_decisions.push({ ...first.field_decisions[0]!, field_key: "food.name", nutrient_id: null });
  const mappingRebuilt = JSON.parse(JSON.stringify(first)) as OcrConfirmationInput;
  expect(confirmationPayloadFingerprint(mappingRebuilt)).toBe(confirmationPayloadFingerprint(first));
  mappingRebuilt.field_decisions = [...mappingRebuilt.field_decisions].reverse();
  expect(confirmationPayloadFingerprint(mappingRebuilt)).not.toBe(confirmationPayloadFingerprint(first));
});
