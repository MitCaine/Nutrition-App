import { clientOwnerScope } from "../src/shared/api/client";
import {
  isReservedLocalAuthorityScope,
  remoteAuthorityIdentity,
} from "../src/runtime/authorityIdentity";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";

test("remote authority preserves the existing recovery scope byte-for-byte", () => {
  expect(remoteNutritionRuntime.authority.recoveryScope).toBe(clientOwnerScope());
});

test("the reserved local namespace cannot collide with a remote authority", () => {
  expect(isReservedLocalAuthorityScope("local:installation-1:profile-1")).toBe(true);
  expect(isReservedLocalAuthorityScope(clientOwnerScope())).toBe(false);
  expect(() => remoteAuthorityIdentity("local:installation-1:profile-1")).toThrow(
    "collides with the reserved local namespace",
  );
});
