const DEPLOYMENT_MODES = new Set([
  "development",
  "private_single_user",
  "production",
  "test",
]);

const LOCAL_ONLY_HOSTS = new Set([
  "localhost",
  "0.0.0.0",
  "10.0.2.2",
  "10.0.3.2",
  "host.docker.internal",
  "::1",
]);

function configurationError(message) {
  return new Error(`Mobile configuration error: ${message}`);
}

function isLocalOnlyHost(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    LOCAL_ONLY_HOSTS.has(normalized) ||
    normalized.endsWith(".localhost") ||
    /^127(?:\.\d{1,3}){3}$/.test(normalized)
  );
}

function normalizeApiBaseUrl(value, deploymentMode) {
  if (!value || !value.trim()) {
    throw configurationError("EXPO_PUBLIC_NUTRITION_API_URL is required");
  }

  let parsed;
  try {
    parsed = new URL(value.trim());
  } catch {
    throw configurationError("EXPO_PUBLIC_NUTRITION_API_URL must be an absolute URL");
  }
  if (!new Set(["http:", "https:"]).has(parsed.protocol)) {
    throw configurationError("API URL must use HTTP or HTTPS");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw configurationError("API URL must not contain credentials, query parameters, or a fragment");
  }

  const releaseMode = deploymentMode === "private_single_user" || deploymentMode === "production";
  if (releaseMode && isLocalOnlyHost(parsed.hostname)) {
    throw configurationError("release API URL must not use localhost or an emulator-only host");
  }
  if (releaseMode && parsed.protocol !== "https:") {
    throw configurationError("release API URL must use HTTPS");
  }

  const path = parsed.pathname.replace(/\/+$/g, "");
  if (path !== "" && path !== "/api/v1") {
    throw configurationError("API URL path must be empty or exactly /api/v1");
  }
  parsed.pathname = "/api/v1";
  return parsed.toString().replace(/\/$/, "");
}

function validateMobileConfig(input) {
  const deploymentMode = input.deploymentMode;
  if (!deploymentMode || !DEPLOYMENT_MODES.has(deploymentMode)) {
    throw configurationError(
      "EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE must be development, private_single_user, production, or test",
    );
  }

  const apiBaseUrl = normalizeApiBaseUrl(input.apiUrl, deploymentMode);
  const token = input.privateAuthToken && input.privateAuthToken.trim();
  if (deploymentMode === "private_single_user" && (!token || token.length < 32)) {
    throw configurationError(
      "private_single_user mode requires EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN with at least 32 characters",
    );
  }
  if (deploymentMode === "production") {
    throw configurationError(
      "public production authentication is not implemented in this build",
    );
  }

  return {
    deploymentMode,
    apiBaseUrl,
    privateAuthToken: deploymentMode === "private_single_user" ? token : undefined,
  };
}

function loadExpoPublicConfig(env) {
  return validateMobileConfig({
    deploymentMode: env.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE,
    apiUrl: env.EXPO_PUBLIC_NUTRITION_API_URL,
    privateAuthToken: env.EXPO_PUBLIC_NUTRITION_PRIVATE_AUTH_TOKEN,
  });
}

module.exports = { isLocalOnlyHost, loadExpoPublicConfig, normalizeApiBaseUrl, validateMobileConfig };
