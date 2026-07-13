import { AppNavigator } from "./app/navigation/AppNavigator";
import { AppProviders } from "./app/providers/AppProviders";
import { StatusBar } from "react-native";
import { statusBarStyle, useAppTheme } from "./app/theme/AppTheme";

function ThemedApp() {
  const theme = useAppTheme();
  return <><StatusBar barStyle={statusBarStyle(theme)} backgroundColor={theme.colors.background} /><AppNavigator /></>;
}

export default function App() {
  return (
    <AppProviders>
      <ThemedApp />
    </AppProviders>
  );
}
