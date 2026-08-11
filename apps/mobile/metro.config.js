const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

// E2-15 keeps its frozen cross-language artifacts at the repository contract
// boundary rather than duplicating them inside the mobile application.
config.watchFolders = [
  ...config.watchFolders,
  path.resolve(__dirname, "../../packages/shared-contracts"),
];

module.exports = config;
