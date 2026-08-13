const { loadExpoPublicConfig } = require("./config/runtimeConfig");

module.exports = ({ config }) => {
  const runtime = loadExpoPublicConfig(process.env);

  return {
    ...config,
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
