import { bindCreateIntent, createPayloadFingerprint } from "../src/shared/idempotency/createIntent";

test("create intent reuses a request ID for the same payload", () => {
  const createRequestId = jest.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
  const first = bindCreateIntent(null, { name: "Food" }, createRequestId);
  const retry = bindCreateIntent(first, { name: "Food" }, createRequestId);

  expect(retry).toBe(first);
  expect(createRequestId).toHaveBeenCalledTimes(1);
});

test("create intent rotates the request ID when payload changes", () => {
  const createRequestId = jest.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
  const first = bindCreateIntent(null, { name: "Food" }, createRequestId);
  const changed = bindCreateIntent(first, { name: "Changed" }, createRequestId);

  expect(changed.requestId).toBe("second");
  expect(createRequestId).toHaveBeenCalledTimes(2);
});

test("object reconstruction and backend-equivalent decimal formatting retain the ID", () => {
  const createRequestId = jest.fn().mockReturnValueOnce("first").mockReturnValueOnce("second");
  const first = bindCreateIntent(
    null,
    { name: "Food", nutrients: [{ amount: "1.000" }], quantity: "01.0" },
    createRequestId,
  );
  const reconstructed = bindCreateIntent(
    first,
    { quantity: "1", nutrients: [{ amount: "1" }], name: "Food" },
    createRequestId,
  );

  expect(reconstructed).toBe(first);
  expect(createRequestId).toHaveBeenCalledTimes(1);
});

test("list order and materially different decimals remain fingerprint-significant", () => {
  expect(createPayloadFingerprint({ ingredients: [{ amount_quantity: "1" }, { amount_quantity: "2" }] }))
    .not.toBe(createPayloadFingerprint({ ingredients: [{ amount_quantity: "2" }, { amount_quantity: "1" }] }));
  expect(createPayloadFingerprint({ gram_weight: "1" }))
    .not.toBe(createPayloadFingerprint({ gram_weight: "1.01" }));
});
