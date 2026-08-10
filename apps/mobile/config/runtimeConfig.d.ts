export type MobileDeploymentMode =
  | "development"
  | "private_single_user"
  | "production"
  | "test";

export type MobileDataAuthority = "local" | "remote";

export interface LocalMobileRuntimeConfig {
  dataAuthority: "local";
  deploymentMode: MobileDeploymentMode;
  apiBaseUrl?: never;
  privateAuthToken?: never;
}

export interface RemoteMobileRuntimeConfig {
  dataAuthority: "remote";
  deploymentMode: MobileDeploymentMode;
  apiBaseUrl: string;
  privateAuthToken?: string;
}

export type MobileRuntimeConfig = LocalMobileRuntimeConfig | RemoteMobileRuntimeConfig;

export function validateMobileConfig(input: {
  dataAuthority?: string;
  deploymentMode?: string;
  apiUrl?: string;
  privateAuthToken?: string;
}): MobileRuntimeConfig;

export function loadExpoPublicConfig(env: Record<string, string | undefined>): MobileRuntimeConfig;
export function resolveDataAuthority(value?: string): MobileDataAuthority;
export function requireRemoteMobileConfig(config: MobileRuntimeConfig): RemoteMobileRuntimeConfig;
export function isLocalOnlyHost(hostname: string): boolean;
export function normalizeApiBaseUrl(value: string | undefined, mode: MobileDeploymentMode): string;
