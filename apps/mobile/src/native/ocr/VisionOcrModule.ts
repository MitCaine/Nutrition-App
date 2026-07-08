import { NativeModules, Platform } from "react-native";

import type { VisionOcrInput, VisionOcrResult } from "./types";

type NativeVisionOcrModule = {
  scanNutritionLabel(input: VisionOcrInput): Promise<VisionOcrResult>;
};

const nativeModule = NativeModules.VisionOcrModule as NativeVisionOcrModule | undefined;

export async function scanNutritionLabel(input: VisionOcrInput): Promise<VisionOcrResult> {
  if (Platform.OS !== "ios") {
    throw new Error("Apple Vision OCR is only available on iOS in the Stage 1 architecture.");
  }

  if (!nativeModule) {
    throw new Error("VisionOcrModule is not linked yet. Stage 5 implements the native bridge.");
  }

  return nativeModule.scanNutritionLabel(input);
}
