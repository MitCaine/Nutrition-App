import * as contract from "../../../packages/shared-contracts/e2-15/transfer-contract.json";
import representativePackage from "../../../packages/shared-contracts/e2-15/representative-package.json";

import {
  buildTransferSection,
  canonicalTransferJson,
  sha256CanonicalValue,
  withOverallDigest,
} from "../src/transfer/e2_15/transferPackage";
import {
  parseAndValidateTransferPackage,
} from "../src/transfer/e2_15/transferPackageValidator";

const OWNER = "00000000-0000-4000-8000-000000000001";
const INSTANT = "2026-08-10T12:34:56.123456Z";

function traceDecision(
  fieldKey: string,
  confirmedValue: string | null,
  nutrientId: string | null = null,
  unit: string | null = null,
): Record<string, unknown> {
  return {
    field_key: fieldKey,
    nutrient_id: nutrientId,
    suggested_value: confirmedValue,
    confirmed_value: confirmedValue,
    unit,
    decision: confirmedValue === null ? "omitted" : "accepted",
    parse_status: confirmedValue === null ? "missing" : "parsed",
    comparison: null,
    confidence: confirmedValue === null ? "0" : "1",
    source_text: "",
    source_observation_ids: [],
    warning_codes: [],
    resolution: null,
  };
}

function validTrace(): Record<string, unknown> {
  return {
    schema_version: "ocr_nutrition_confirmation_v1",
    field_decisions: [
      traceDecision("food.name", "OCR Food"),
      traceDecision("food.brand", null),
      traceDecision("food.notes", null),
      traceDecision("serving.display", "1 serving"),
      traceDecision("serving.quantity", "1"),
      traceDecision("serving.unit", "serving"),
      traceDecision("serving.gram_weight", null),
      traceDecision("nutrient.calories", "100", "calories", "kcal"),
    ],
    unknown_nutrients: [],
    parser_warning_codes: [],
  };
}

async function minimalDocument(): Promise<Record<string, unknown>> {
  const values: Record<string, readonly Readonly<Record<string, unknown>>[]> = {};
  for (const section of contract.sections) values[section.name] = [];
  values.users = [{ id: OWNER, email: "owner@example.invalid", display_name: "Owner", created_at: INSTANT }];
  values.user_profiles = [{
    user_id: OWNER,
    birth_date: null,
    height_cm: null,
    weight_kg: null,
    biological_sex_for_reference_calculations: null,
    activity_level: null,
    energy_estimation_context: "general_adult",
    authoritative_time_zone: "America/Los_Angeles",
    calendar_revision: 0,
    created_at: INSTANT,
    updated_at: INSTANT,
  }];
  const sections = [];
  for (const section of contract.sections) {
    sections.push(await buildTransferSection(section.name, values[section.name]));
  }
  const dailyTotalsPreimage = { count: 0, name: "daily_totals", records: [] };
  return withOverallDigest({
    format: contract.format,
    format_version: contract.format_version,
    codec_version: contract.codec_version,
    source: {
      postgres_major: contract.source.postgres_major,
      alembic_revision: contract.source.alembic_revision,
      schema_contract: contract.source.schema_contract,
      schema_contract_digest: contract.source.schema_descriptor_digest,
    },
    target: contract.target,
    exported_at: INSTANT,
    owner_id: OWNER,
    nutrient_catalog_digest: contract.nutrient_catalog_digest,
    idempotency_policy: {
      version: contract.idempotency.policy_version,
      copied_portable_count: 0,
      translated_log_update_count: 0,
      reconstructed_log_create_count: 0,
      excluded_log_delete_count: 0,
    },
    sections,
    qualification: {
      daily_totals: {
        ...dailyTotalsPreimage,
        digest: await sha256CanonicalValue(dailyTotalsPreimage),
      },
    },
  });
}

test("validates and deeply freezes a complete canonical package before SQLite", async () => {
  const source = await minimalDocument();
  const document = canonicalTransferJson(source);
  const validated = await parseAndValidateTransferPackage(document);
  expect(validated.owner_id).toBe(OWNER);
  expect(Object.isFrozen(validated)).toBe(true);
  expect(Object.isFrozen(validated.sections)).toBe(true);
});

test("rejects noncanonical, tampered, unsupported, and duplicate-key documents", async () => {
  const source = await minimalDocument();
  const canonical = canonicalTransferJson(source);
  await expect(parseAndValidateTransferPackage(`${canonical}\n`)).rejects.toMatchObject({
    code: "noncanonical_package",
  });
  await expect(parseAndValidateTransferPackage(canonical.replace(contract.format, "wrong")))
    .rejects.toMatchObject({ code: "unsupported_package" });
  const duplicate = canonical.replace(
    `"codec_version":"${contract.codec_version}"`,
    `"codec_version":"${contract.codec_version}","codec_version":"${contract.codec_version}"`,
  );
  await expect(parseAndValidateTransferPackage(duplicate)).rejects.toMatchObject({
    code: "noncanonical_package",
  });
  const parsed = JSON.parse(canonical) as Record<string, unknown>;
  parsed.owner_id = "00000000-0000-4000-8000-000000000002";
  await expect(parseAndValidateTransferPackage(canonicalTransferJson(parsed))).rejects.toMatchObject({
    code: "owner_graph_invalid",
  });
});

async function mutatedRepresentative(
  mutate: (value: Record<string, unknown>, sections: Map<string, Record<string, unknown>>) => void,
): Promise<string> {
  const value = JSON.parse(JSON.stringify(representativePackage)) as Record<string, unknown>;
  const sections = new Map(
    (value.sections as Record<string, unknown>[]).map((section) => [section.name as string, section]),
  );
  mutate(value, sections);
  value.sections = await Promise.all(contract.sections.map(async ({ name }) => {
    const section = sections.get(name) as Record<string, unknown>;
    return buildTransferSection(name, section.records as Record<string, unknown>[]);
  }));
  return canonicalTransferJson(await withOverallDigest(value));
}

async function traceMutation(
  mutate: (trace: Record<string, unknown>) => void,
): Promise<string> {
  return mutatedRepresentative((_value, sections) => {
    const traces = sections.get("ocr_nutrition_confirmation_traces")!.records as Record<string, unknown>[];
    const trace = validTrace();
    mutate(trace);
    traces[0].trace_snapshot = canonicalTransferJson(trace);
  });
}

async function updateReceiptMutation(
  mutate: (receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => void,
): Promise<string> {
  return mutatedRepresentative((_value, sections) => {
    const receipts = sections.get("create_operation_idempotency")!.records as Record<string, unknown>[];
    const receipt = receipts.find((row) => row.operation === "log.update")!;
    const snapshot = JSON.parse(receipt.response_snapshot as string) as Record<string, unknown>;
    mutate(receipt, snapshot);
    receipt.response_snapshot = canonicalTransferJson(snapshot);
  });
}

function foodResponse(
  food: Record<string, unknown>,
  sourceKind: string,
  servings: Record<string, unknown>[] = [],
): Record<string, unknown> {
  return {
    id: food.id,
    name: food.name,
    brand: food.brand,
    notes: food.notes,
    source_type: food.source_type,
    source_id: food.source_id,
    is_recipe: food.is_recipe,
    source_kind: sourceKind,
    source_label: sourceKind,
    is_favorite: false,
    can_favorite: true,
    created_at: food.created_at,
    updated_at: food.updated_at,
    serving_definitions: servings,
    nutrients: [],
  };
}

function recipeResponse(
  recipe: Record<string, unknown>,
  name: unknown = recipe.name,
  publishedFoodId: unknown = null,
): Record<string, unknown> {
  return {
    id: recipe.id,
    user_id: recipe.user_id,
    published_food_item_id: publishedFoodId,
    name,
    notes: recipe.notes,
    serving_count_yield: recipe.serving_count_yield,
    final_cooked_weight_grams: recipe.final_cooked_weight_grams,
    final_cooked_weight_display_quantity: recipe.final_cooked_weight_display_quantity,
    final_cooked_weight_display_unit: recipe.final_cooked_weight_display_unit,
    needs_republish: false,
    created_at: recipe.created_at,
    updated_at: recipe.updated_at,
    ingredients: [],
  };
}

type ReceiptTamper = (
  receipt: Record<string, unknown>,
  snapshot: Record<string, unknown>,
) => void;

function portableReceiptMutation(operation: string, tamper?: ReceiptTamper) {
  return (_value: Record<string, unknown>, sections: Map<string, Record<string, unknown>>) => {
    const foods = new Map(
      (sections.get("food_items")!.records as Record<string, unknown>[])
        .map((row) => [row.id as string, row]),
    );
    const recipes = new Map(
      (sections.get("recipes")!.records as Record<string, unknown>[])
        .map((row) => [row.id as string, row]),
    );
    const receipts = sections.get("create_operation_idempotency")!.records as Record<string, unknown>[];
    const receipt = receipts.find((row) => row.operation === "food.create_manual")!;
    receipt.operation = operation;
    let snapshot: Record<string, unknown>;
    if (operation === "food.create_manual") {
      receipt.resource_id = "00000000-0000-4000-8000-000000000011";
      snapshot = foodResponse(foods.get(receipt.resource_id as string)!, "manual");
    } else if (operation === "food.duplicate") {
      receipt.resource_id = "00000000-0000-4000-8000-000000000011";
      const duplicate = foods.get(receipt.resource_id as string)!;
      duplicate.source_id = "00000000-0000-4000-8000-000000000010";
      snapshot = foodResponse(duplicate, "duplicate");
    } else if (operation === "food.add_serving") {
      receipt.resource_id = "00000000-0000-4000-8000-000000000029";
      snapshot = foodResponse(
        foods.get("00000000-0000-4000-8000-000000000010")!,
        "usda",
        [{
          id: receipt.resource_id,
          label: "Historical cup",
          quantity: "1.000000",
          unit: "cup",
          gram_weight: "125.000000",
          is_default: false,
          source: "manual",
          is_user_confirmed: true,
        }],
      );
    } else if (operation === "recipe.create") {
      receipt.resource_id = "00000000-0000-4000-8000-000000000050";
      snapshot = recipeResponse(recipes.get(receipt.resource_id as string)!);
    } else {
      expect(operation).toBe("recipe.publish");
      receipt.resource_id = "00000000-0000-4000-8000-000000000060";
      const food = {
        ...foods.get("00000000-0000-4000-8000-000000000012")!,
        name: "Base v1",
      };
      snapshot = {
        recipe: recipeResponse(
          recipes.get("00000000-0000-4000-8000-000000000050")!,
          "Base v1",
          "00000000-0000-4000-8000-000000000012",
        ),
        food: foodResponse(food, "recipe"),
      };
    }
    tamper?.(receipt, snapshot);
    receipt.response_snapshot = canonicalTransferJson(snapshot);
  };
}

test("validates the representative graph and rejects re-signed graph, OCR, and receipt tampering", async () => {
  await expect(parseAndValidateTransferPackage(
    canonicalTransferJson(representativePackage),
  )).resolves.toMatchObject({ owner_id: OWNER });

  const crossOwner = await mutatedRepresentative((_value, sections) => {
    const foods = sections.get("food_items")!.records as Record<string, unknown>[];
    foods[0].user_id = "00000000-0000-4000-8000-000000000002";
  });
  await expect(parseAndValidateTransferPackage(crossOwner)).rejects.toMatchObject({
    code: "owner_graph_invalid",
  });

  const malformedTrace = await mutatedRepresentative((_value, sections) => {
    const traces = sections.get("ocr_nutrition_confirmation_traces")!.records as Record<string, unknown>[];
    const trace = JSON.parse(traces[0].trace_snapshot as string) as Record<string, unknown>;
    trace.raw_capture = "not transferable";
    traces[0].trace_snapshot = canonicalTransferJson(trace);
  });
  await expect(parseAndValidateTransferPackage(malformedTrace)).rejects.toMatchObject({
    code: "ocr_trace_invalid",
  });

  const wrongReceipt = await mutatedRepresentative((_value, sections) => {
    const receipts = sections.get("create_operation_idempotency")!.records as Record<string, unknown>[];
    const create = receipts.find((row) => row.operation === "log.create")!;
    create.id = "4d1e8758-17dc-52c2-88bb-c67f6c627c2f";
  });
  await expect(parseAndValidateTransferPackage(wrongReceipt)).rejects.toMatchObject({
    code: "idempotency_policy_invalid",
  });
});

test.each([
  ["empty decisions", (trace: Record<string, unknown>) => { trace.field_decisions = []; }],
  ["missing required decision", (trace: Record<string, unknown>) => {
    trace.field_decisions = (trace.field_decisions as Record<string, unknown>[])
      .filter((row) => row.field_key !== "food.name");
  }],
  ["duplicate key", (trace: Record<string, unknown>) => {
    const decisions = trace.field_decisions as Record<string, unknown>[];
    decisions.push({ ...decisions[0] });
  }],
  ["invalid nutrient", (trace: Record<string, unknown>) => {
    const decision = (trace.field_decisions as Record<string, unknown>[]).at(-1)!;
    decision.field_key = "nutrient.not-a-nutrient";
    decision.nutrient_id = "not-a-nutrient";
  }],
  ["invalid unit", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[]).at(-1)!.unit = "mg";
  }],
  ["invalid decision", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.decision = "unresolved";
  }],
  ["invalid parse status", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.parse_status = "invalid";
  }],
  ["invalid confidence", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.confidence = "1.01";
  }],
  ["ambiguous without resolution", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.parse_status = "ambiguous";
  }],
  ["invalid unknown nutrient", (trace: Record<string, unknown>) => {
    trace.unknown_nutrients = [{
      original_name: "Mystery",
      source_text: "Mystery 1g",
      source_observation_ids: [],
      warning_codes: [],
      decision: "accepted",
    }];
  }],
  ["excessive list", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.source_observation_ids = Array(21).fill("x");
  }],
  ["excessive string", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[0]!.suggested_value = "x".repeat(257);
  }],
  ["omitted confirmed mismatch", (trace: Record<string, unknown>) => {
    (trace.field_decisions as Record<string, unknown>[])[1]!.confirmed_value = "Brand";
  }],
  ["omitted calories", (trace: Record<string, unknown>) => {
    const calories = (trace.field_decisions as Record<string, unknown>[]).at(-1)!;
    calories.decision = "omitted";
    calories.confirmed_value = null;
  }],
] as const)("rejects intrinsically invalid E2-13 trace: %s", async (_name, mutate) => {
  await expect(parseAndValidateTransferPackage(await traceMutation(mutate)))
    .rejects.toMatchObject({ code: "ocr_trace_invalid" });
});

test("accepts a minimal intrinsically valid E2-13 trace", async () => {
  await expect(parseAndValidateTransferPackage(await traceMutation(() => {})))
    .resolves.toBeDefined();
});

test("accepts log.update replay with a current or later-deleted Daily Log", async () => {
  await expect(parseAndValidateTransferPackage(
    await updateReceiptMutation(() => {}),
  )).resolves.toBeDefined();
  const historicalId = "00000000-0000-4000-8000-000000000199";
  await expect(parseAndValidateTransferPackage(await updateReceiptMutation((receipt, snapshot) => {
    receipt.resource_id = historicalId;
    (snapshot.result as Record<string, unknown>).id = historicalId;
  }))).resolves.toBeDefined();
});

test.each([
  ["malformed result", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    delete (snapshot.result as Record<string, unknown>).amount_unit;
  }],
  ["resource mismatch", (receipt: Record<string, unknown>) => {
    receipt.resource_id = "00000000-0000-4000-8000-000000000199";
  }],
  ["invalid source date", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    snapshot.source_logged_date = "2026-99-99";
  }],
  ["invalid destination date", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    snapshot.destination_logged_date = "not-a-date";
  }],
] as const)("rejects log.update receipt with %s", async (_name, mutate) => {
  await expect(parseAndValidateTransferPackage(await updateReceiptMutation(mutate)))
    .rejects.toMatchObject({ code: "idempotency_policy_invalid" });
});

test.each([
  ["food.create_manual", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    snapshot.extra = true;
  }],
  ["food.duplicate", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    snapshot.source_id = "00000000-0000-4000-8000-000000000099";
  }],
  ["food.add_serving", (receipt: Record<string, unknown>) => {
    receipt.resource_id = "00000000-0000-4000-8000-000000000028";
  }],
  ["recipe.create", (_receipt: Record<string, unknown>, snapshot: Record<string, unknown>) => {
    snapshot.user_id = "00000000-0000-4000-8000-000000000002";
  }],
  ["recipe.publish", (receipt: Record<string, unknown>) => {
    receipt.resource_id = "00000000-0000-4000-8000-000000000062";
  }],
] as const)("validates %s exact replay shape and rejects tampering", async (operation, tamper) => {
  await expect(parseAndValidateTransferPackage(
    await mutatedRepresentative(portableReceiptMutation(operation)),
  )).resolves.toBeDefined();
  await expect(parseAndValidateTransferPackage(
    await mutatedRepresentative(portableReceiptMutation(operation, tamper)),
  )).rejects.toMatchObject({ code: "idempotency_policy_invalid" });
});

test("accepts bounded historical serving and publication receipt resources", async () => {
  await expect(parseAndValidateTransferPackage(
    await mutatedRepresentative(portableReceiptMutation("food.add_serving")),
  )).resolves.toBeDefined();
  await expect(parseAndValidateTransferPackage(
    await mutatedRepresentative(portableReceiptMutation("recipe.publish")),
  )).resolves.toBeDefined();
});

test("uses E2-13 ensure-ascii sizing and rejects private OCR references", async () => {
  const unicodeTrace = async (count: number) => mutatedRepresentative((_value, sections) => {
    const traces = sections.get("ocr_nutrition_confirmation_traces")!.records as Record<string, unknown>[];
    const trace = JSON.parse(traces[0].trace_snapshot as string) as Record<string, unknown>;
    trace.parser_warning_codes = ["é".repeat(count)];
    traces[0].trace_snapshot = canonicalTransferJson(trace);
  });
  await expect(parseAndValidateTransferPackage(await unicodeTrace(7_000))).resolves.toBeDefined();
  await expect(parseAndValidateTransferPackage(await unicodeTrace(9_000))).rejects.toMatchObject({
    code: "ocr_trace_invalid",
  });

  const privateReference = await mutatedRepresentative((_value, sections) => {
    const traces = sections.get("ocr_nutrition_confirmation_traces")!.records as Record<string, unknown>[];
    const trace = JSON.parse(traces[0].trace_snapshot as string) as Record<string, unknown>;
    trace.parser_warning_codes = ["file:///private/raw-label.png"];
    traces[0].trace_snapshot = canonicalTransferJson(trace);
  });
  await expect(parseAndValidateTransferPackage(privateReference)).rejects.toMatchObject({
    code: "privacy_violation",
  });
});
