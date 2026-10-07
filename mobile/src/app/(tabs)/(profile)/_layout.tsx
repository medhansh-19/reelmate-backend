import { Stack } from 'expo-router/stack';

import { useReelMateTheme } from '@/theme';

export default function ProfileStack() {
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
      <Stack.Screen name="profile" options={{ title: 'You' }} />
    </Stack>
  );
}
