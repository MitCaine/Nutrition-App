export type MobileDeploymentMode =
  | "development"
  | "private_single_user"
  | "production"
  | "test";

export interface MobileRuntimeConfig {
  deploymentMode: MobileDeploymentMode;
  apiBaseUrl: string;
  privateAuthToken?: string;
}

export function validateMobileConfig(input: {
  deploymentMode?: string;
  apiUrl?: string;
  privateAuthToken?: string;
}): MobileRuntimeConfig;

export function loadExpoPublicConfig(env: Record<string, string | undefined>): MobileRuntimeConfig;
export function isLocalOnlyHost(hostname: string): boolean;
export function normalizeApiBaseUrl(value: string | undefined, mode: MobileDeploymentMode): string;
