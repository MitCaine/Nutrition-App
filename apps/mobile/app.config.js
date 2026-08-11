const { loadExpoPublicConfig } = require("./config/runtimeConfig");

module.exports = ({ config }) => {
  const runtime = loadExpoPublicConfig(process.env);
  const e216Qualification = process.env.EXPO_PUBLIC_E216_NATIVE_QUALIFICATION === "1";
  if (e216Qualification && process.env.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE !== "development") {
    throw new Error("E2-16 qualification requires development deployment mode.");
  }

  return {
    ...config,
    ...(e216Qualification ? {
      name: "Nutrition App E2-16",
      slug: "nutrition-app-e2-16",
      scheme: "nutritionapp-e216",
      ios: {
        ...(config.ios || {}),
        bundleIdentifier: "com.portfolio.nutritionapp.e216",
      },
      android: {
        ...(config.android || {}),
        package: "com.portfolio.nutritionapp.e216",
      },
    } : {}),
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
