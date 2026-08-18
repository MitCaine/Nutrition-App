import { requireOptionalNativeModule } from "expo-modules-core";
import { Platform } from "react-native";

type NativeNutritionCameraModule = {
  preferredBackCameraLensName?(): string | null;
};

const nativeModule =
  requireOptionalNativeModule<NativeNutritionCameraModule>(
    "NutritionOcr",
  );

export function getPreferredBackCameraLensName():
  | string
  | undefined {
  if (Platform.OS !== "ios") {
    return undefined;
  }

  try {
    const lensName =
      nativeModule?.preferredBackCameraLensName?.();

    if (
      typeof lensName !== "string" ||
      lensName.trim().length === 0
    ) {
      return undefined;
    }

    return lensName.trim();
  } catch {
    // Lens selection is an acquisition enhancement. If discovery
    // is unavailable, let expo-camera use its normal fallback.
    return undefined;
  }
}
