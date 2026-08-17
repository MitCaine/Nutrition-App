import type {
  DailyTargetComparisonItem,
  TargetValue,
} from "./api/types";


type TargetReferenceLike = Pick<
  TargetValue | DailyTargetComparisonItem,
  "authority"
  | "referenceType"
  | "sourceVersion"
>;


export function targetBasisLabel(
  target: TargetReferenceLike,
): string {
  if (target.authority === "manual_override") {
    return "Manual target";
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
