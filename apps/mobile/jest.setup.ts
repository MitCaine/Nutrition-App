process.env["EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY"] = "remote";
process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "test";
process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "http://localhost:8000/api/v1";
delete process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"];

jest.mock(
  "@react-native-async-storage/async-storage",
  () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

jest.mock("expo-crypto", () => ({
  randomUUID: jest.fn(() => "00000000-0000-4000-8000-000000000000"),
  CryptoDigestAlgorithm: { SHA1: "SHA-1", SHA256: "SHA-256" },
  digest: jest.fn(async (algorithm: string, data: Uint8Array) => {
    const name = algorithm === "SHA-1" ? "sha1" : "sha256";
    const bytes = require("node:crypto").createHash(name).update(data).digest();
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }),
  digestStringAsync: jest.fn(async (algorithm: string, data: string) => {
    const name = algorithm === "SHA-1" ? "sha1" : "sha256";
    return require("node:crypto").createHash(name).update(data, "utf8").digest("hex");
  }),
}));

jest.mock("expo-modules-core", () => ({
  requireOptionalNativeModule: jest.fn(() => null),
}));
