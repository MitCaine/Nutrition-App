import { validateMobileConfig } from "../config/runtimeConfig";

const PRIVATE_TOKEN = "private-test-credential-at-least-32-characters";

test("explicit development accepts simulator localhost and LAN HTTP URLs", () => {
  expect(
    validateMobileConfig({
      deploymentMode: "development",
      apiUrl: "http://localhost:8000",
    }).apiBaseUrl,
  ).toBe("http://localhost:8000/api/v1");
  expect(
    validateMobileConfig({
      deploymentMode: "development",
      apiUrl: "http://192.168.1.20:8000/api/v1/",
    }).apiBaseUrl,
  ).toBe("http://192.168.1.20:8000/api/v1");
});

test("mode and API URL never silently default", () => {
  expect(() => validateMobileConfig({ apiUrl: "http://localhost:8000" })).toThrow(
    "EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE",
  );
  expect(() => validateMobileConfig({ deploymentMode: "development" })).toThrow(
    "EXPO_PUBLIC_NUTRITION_API_URL",
  );
});

test.each([
  "https://localhost:8000",
  "https://127.0.0.1:8000/api/v1",
  "https://0.0.0.0:8000",
  "https://10.0.2.2:8000",
  "https://[::1]:8000",
])("private release rejects local-only API host %s", (apiUrl) => {
  expect(() =>
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl,
      privateAuthToken: PRIVATE_TOKEN,
    }),
  ).toThrow("must not use localhost or an emulator-only host");
});

test("private release requires HTTPS and its credential", () => {
  expect(() =>
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl: "http://api.example.test/api/v1",
      privateAuthToken: PRIVATE_TOKEN,
    }),
  ).toThrow("must use HTTPS");
  expect(() =>
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl: "https://api.example.test/api/v1",
    }),
  ).toThrow("PRIVATE_AUTH_TOKEN");
});

test("valid HTTPS private URL is normalized to one API boundary", () => {
  const config = validateMobileConfig({
    deploymentMode: "private_single_user",
    apiUrl: "https://api.example.test/",
    privateAuthToken: PRIVATE_TOKEN,
  });
  expect(config.apiBaseUrl).toBe("https://api.example.test/api/v1");
  expect(() =>
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl: "https://api.example.test/api/v1/api/v1",
      privateAuthToken: PRIVATE_TOKEN,
    }),
  ).toThrow("exactly /api/v1");
});

test.each([
  "https://user:password@api.example.test/api/v1",
  "https://api.example.test/api/v1?token=value",
  "https://api.example.test/api/v1#fragment",
])("private release rejects URL credentials, query values, and fragments: %s", (apiUrl) => {
  expect(() =>
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl,
      privateAuthToken: PRIVATE_TOKEN,
    }),
  ).toThrow("must not contain credentials, query parameters, or a fragment");
});

test("public production remains blocked without a real identity provider", () => {
  expect(() =>
    validateMobileConfig({
      deploymentMode: "production",
      apiUrl: "https://api.example.test",
    }),
  ).toThrow("production authentication is not implemented");
});

test("configuration errors do not reflect credential values", () => {
  const sensitive = `${PRIVATE_TOKEN}-do-not-print`;
  let message = "";
  try {
    validateMobileConfig({
      deploymentMode: "private_single_user",
      apiUrl: "not-a-url",
      privateAuthToken: sensitive,
    });
  } catch (error) {
    message = String(error);
  }
  expect(message).not.toContain(sensitive);
});
