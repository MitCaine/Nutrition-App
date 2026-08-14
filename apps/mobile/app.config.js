const { loadExpoPublicConfig } = require("./config/runtimeConfig");

module.exports = ({ config }) => {
  const runtime = loadExpoPublicConfig(process.env);

  return {
    ...config,
    plugins: [
      ...(config.plugins || []),
      "expo-secure-store",
    ],
    extra: {
      ...(config.extra || {}),
      nutrition: {
        dataAuthority: runtime.dataAuthority,
        deploymentMode: runtime.deploymentMode,
        ...(runtime.dataAuthority === "remote" ? {
          apiBaseUrl: runtime.apiBaseUrl,
          privateCredentialConfigured: Boolean(runtime.privateAuthToken),
        } : {}),
      },
    },
  };
};