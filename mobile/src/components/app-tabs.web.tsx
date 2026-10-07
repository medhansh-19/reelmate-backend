import {
  Tabs,
  TabList,
  TabSlot,
  TabTrigger,
  type TabTriggerSlotProps,
} from 'expo-router/ui';
import { Pressable, Text, View } from 'react-native';

import { ReelMateWordmark } from '@/components/brand-mark';
import { useReelMateTheme } from '@/theme';

function WebTab({ children, isFocused, ...props }: TabTriggerSlotProps) {
  const theme = useReelMateTheme();
  return (
    <Pressable
      {...props}
      style={({ pressed }) => ({
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: theme.spacing.sm,
        borderRadius: theme.radii.round,
        backgroundColor: isFocused ? theme.colors.accentSoft : 'transparent',
        opacity: pressed ? 0.65 : 1,
      })}
    >
      <Text
        style={{
          color: isFocused ? theme.colors.accent : theme.colors.textMuted,
          fontWeight: '800',
        }}
      >
        {children}
      </Text>
    </Pressable>
  );
}

export default function AppTabs() {
  const theme = useReelMateTheme();
  return (
    <Tabs>
      <TabList asChild>
        <View
          style={{
            zIndex: 10,
            flexDirection: 'row',
            alignItems: 'center',
            gap: theme.spacing.sm,
            paddingHorizontal: theme.spacing.xl,
            paddingVertical: theme.spacing.md,
            backgroundColor: theme.colors.backgroundElevated,
            borderBottomWidth: 1,
            borderBottomColor: theme.colors.separator,
          }}
        >
          <ReelMateWordmark size="compact" style={{ marginRight: 'auto' }} />
          <TabTrigger name="coach" href="/coach" asChild>
            <WebTab>Coach</WebTab>
          </TabTrigger>
          <TabTrigger name="library" href="/library" asChild>
            <WebTab>Library</WebTab>
          </TabTrigger>
          <TabTrigger name="profile" href="/profile" asChild>
            <WebTab>You</WebTab>
          </TabTrigger>
        </View>
      </TabList>
      <TabSlot style={{ flex: 1 }} />
    </Tabs>
  );
}
