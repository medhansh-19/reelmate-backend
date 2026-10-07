import { Stack } from 'expo-router/stack';

import { useReelMateTheme } from '@/theme';

export default function LibraryStack() {
  const theme = useReelMateTheme();
  return (
    <Stack
      screenOptions={{
        headerLargeTitle: true,
        headerShadowVisible: false,
        headerStyle: { backgroundColor: theme.colors.background },
        contentStyle: { backgroundColor: theme.colors.background },
      }}
    >
      <Stack.Screen name="library" options={{ title: 'Library' }} />
    </Stack>
  );
}
