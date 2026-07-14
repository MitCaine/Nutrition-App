const PRIVATE_TOKEN = "private-test-credential-at-least-32-characters";

function successfulResponse() {
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
}

afterEach(() => {
  jest.resetModules();
  jest.restoreAllMocks();
  process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "test";
  process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "http://localhost:8000/api/v1";
  delete process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"];
});

test("private credential is attached only by the central API client", async () => {
  process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "private_single_user";
  process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "https://api.example.test";
  process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"] = PRIVATE_TOKEN;
  global.fetch = jest.fn().mockResolvedValue(successfulResponse());
  const { apiRequest } = require("../src/shared/api/client");

  await apiRequest("/nutrients");

  const request = (global.fetch as jest.Mock).mock.calls[0];
  const headers = request[1].headers as Record<string, string>;
  expect(Object.keys(headers).filter((name) => name.toLowerCase() === "authorization")).toHaveLength(1);
  expect(request[0]).toBe("https://api.example.test/api/v1/nutrients");
  expect(headers.Authorization?.startsWith("Bearer ")).toBe(true);
  expect(headers.Authorization?.slice("Bearer ".length) === PRIVATE_TOKEN).toBe(true);
});

test("caller headers are preserved and cannot override the central credential", async () => {
  process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "private_single_user";
  process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "https://api.example.test/api/v1";
  process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"] = PRIVATE_TOKEN;
  global.fetch = jest.fn().mockResolvedValue(successfulResponse());
  const { apiRequest } = require("../src/shared/api/client");

  await apiRequest("/foods", {
    headers: [["X-Request-ID", "request-1"], ["authorization", "Bearer caller-value"]],
  });

  const options = (global.fetch as jest.Mock).mock.calls[0][1];
  expect(options.headers["X-Request-ID"]).toBe("request-1");
  expect(options.headers.Authorization?.slice("Bearer ".length) === PRIVATE_TOKEN).toBe(true);
  expect(options.headers.authorization).toBeUndefined();
});

test("central authentication does not change API error parsing", async () => {
  process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "private_single_user";
  process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "https://api.example.test";
  process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"] = PRIVATE_TOKEN;
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 409,
    text: async () => JSON.stringify({ detail: "Existing error contract" }),
  });
  const { apiRequest } = require("../src/shared/api/client");

  await expect(apiRequest("/foods")).rejects.toMatchObject({
    status: 409,
    message: "Existing error contract",
  });
});

test.each(["development", "test"])(
  "explicit unauthenticated %s mode does not attach Authorization",
  async (deploymentMode) => {
    process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = deploymentMode;
    process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "http://localhost:8000";
    delete process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"];
    global.fetch = jest.fn().mockResolvedValue(successfulResponse());
    const { apiRequest } = require("../src/shared/api/client");

    await apiRequest("/nutrients");

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/nutrients",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
  },
);
