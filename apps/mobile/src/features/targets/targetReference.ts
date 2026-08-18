import type {
  DailyTargetComparisonItem,
  TargetValue,
} from "./api/types";


type TargetReferenceLike = Pick<
  TargetValue | DailyTargetComparisonItem,
  "authority"
  | "referenceType"
  | "sourceVersion"
  | "trackingMode"
  | "reasonCode"
>;


export function targetBasisLabel(
  target: TargetReferenceLike,
): string {
  if (target.trackingMode === "ignored") {
    return "Not shown in daily tracking";
  }

  if (target.trackingMode === "amount_only") {
    if (
      target.reasonCode
      === "target_reference_not_established"
    ) {
      return "No established daily goal";
    }

    return "Total consumed only";
  }

  if (target.authority === "manual_override") {
    return "Custom target";
  }

  if (target.authority === "calculated_estimate") {
    return "Estimated calories";
  }

  if (target.authority === "dri") {
    return target.referenceType
      ?? "DRI recommendation";
  }

  if (target.authority === "daily_value") {
    return "FDA Daily Value";
  }

  if (
    target.reasonCode
    === "target_profile_incomplete"
  ) {
    return "Profile incomplete";
  }

  if (
    target.reasonCode
      === "target_estimate_unsupported_age"
    || target.reasonCode
      === "target_estimate_unsupported_context"
  ) {
    return "Unavailable for profile";
  }

  return "Unavailable";
}


export function readableSourceVersion(
  version: string,
): string {
  if (
    version
    === "nasem_dri_adults_2026_v1"
  ) {
    return "NASEM DRI adults 2026 v1";
  }

  if (
    version
    === "fda_daily_values_2016_v1"
  ) {
    return "FDA Daily Values 2016 v1";
  }

  return version.replaceAll("_", " ");
}


export function targetSourceVersionLabel(
  target: TargetReferenceLike,
  fdaCatalogVersion?: string | null,
): string | null {
  if (
    target.authority === "dri"
    && target.sourceVersion
  ) {
    return readableSourceVersion(
      target.sourceVersion,
    );
  }

  if (
    target.authority === "daily_value"
    && fdaCatalogVersion
  ) {
    return readableSourceVersion(
      fdaCatalogVersion,
    );
  }

  return null;
}
