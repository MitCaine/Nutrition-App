const { loadExpoPublicConfig } = require("./config/runtimeConfig");

module.exports = ({ config }) => {
  const runtime = loadExpoPublicConfig(process.env);

  return {
    ...config,
    extra: {
      ...(config.extra || {}),
      nutrition: {
        deploymentMode: runtime.deploymentMode,
        apiBaseUrl: runtime.apiBaseUrl,
        privateCredentialConfigured: Boolean(runtime.privateAuthToken),
      },
    },
  };
};
