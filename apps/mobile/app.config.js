const base = require("./app.json");
const { loadExpoPublicConfig } = require("./config/runtimeConfig");

const runtime = loadExpoPublicConfig(process.env);

module.exports = {
  ...base.expo,
  extra: {
    ...(base.expo.extra || {}),
    nutrition: {
      deploymentMode: runtime.deploymentMode,
      apiBaseUrl: runtime.apiBaseUrl,
      privateCredentialConfigured: Boolean(runtime.privateAuthToken),
    },
  },
};
