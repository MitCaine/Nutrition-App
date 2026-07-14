process.env["EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE"] = "test";
process.env["EXPO_PUBLIC_NUTRITION_API_URL"] = "http://localhost:8000/api/v1";
delete process.env["EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN"];

jest.mock(
  "@react-native-async-storage/async-storage",
  () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

jest.mock("expo-crypto", () => ({
  randomUUID: jest.fn(() => "00000000-0000-4000-8000-000000000000"),
}));

jest.mock("expo-modules-core", () => ({
  requireOptionalNativeModule: jest.fn(() => null),
}));
