import * as fixture from "../../../packages/shared-contracts/e2-15/parity-fixtures.json";
import * as contract from "../../../packages/shared-contracts/e2-15/transfer-contract.json";

import {
  E2_15_MAXIMUM_TRANSFER_BYTES,
  E2_15_SECTION_NAMES,
  buildTransferSection,
  canonicalizeTransferScalar,
  canonicalTransferJson,
  sha256CanonicalValue,
  sortTransferRecords,
  withOverallDigest,
} from "../src/transfer/e2_15/transferPackage";

test("the mobile package boundary consumes the fixed shared contract", () => {
  expect(contract.format).toBe("nutrition-personal-transfer");
  expect(contract.format_version).toBe("1");
  expect(contract.codec_version).toBe("e2-02.v1");
  expect(E2_15_MAXIMUM_TRANSFER_BYTES).toBe(64 * 1024 * 1024);
  expect(E2_15_SECTION_NAMES).toEqual(contract.sections.map((section) => section.name));
  expect(E2_15_SECTION_NAMES).toHaveLength(17);
  expect(contract.source.expected_public_tables).toHaveLength(31);
});

test("Python and TypeScript emit identical canonical bytes and digests", async () => {
  for (const testCase of fixture.canonical_json_cases) {
    expect(canonicalTransferJson(testCase.value)).toBe(testCase.canonical);
    await expect(sha256CanonicalValue(testCase.value)).resolves.toBe(testCase.sha256);
  }
  for (const testCase of fixture.section_cases) {
    expect(canonicalTransferJson({
      count: testCase.sorted_records.length,
      name: testCase.section_name,
      records: testCase.sorted_records,
    })).toBe(testCase.preimage);
    await expect(buildTransferSection(testCase.section_name, testCase.sorted_records)).resolves.toEqual({
      count: testCase.sorted_records.length,
      digest: testCase.digest,
      name: testCase.section_name,
      records: testCase.sorted_records,
    });
  }
  for (const testCase of fixture.scalar_cases) {
    expect(canonicalizeTransferScalar(testCase.kind, testCase.input)).toBe(testCase.canonical);
  }
  for (const testCase of fixture.record_order_cases) {
    expect(sortTransferRecords(testCase.unsorted_records, testCase.primary_key)).toEqual(
      testCase.sorted_records,
    );
  }
  for (const testCase of fixture.overall_digest_cases) {
    expect(canonicalTransferJson(testCase.unsigned_document)).toBe(testCase.preimage);
    await expect(sha256CanonicalValue(testCase.unsigned_document)).resolves.toBe(testCase.digest);
    await expect(withOverallDigest(testCase.unsigned_document)).resolves.toEqual(
      testCase.completed_document,
    );
  }
  for (const testCase of fixture.unsafe_integer_cases) {
    expect(() => canonicalTransferJson(Number(testCase.input))).toThrow();
  }
});
