import { NativeTabs } from 'expo-router/unstable-native-tabs';

import { useReelMateTheme } from '@/theme';

export default function AppTabs() {
  const theme = useReelMateTheme();
  return (
    <NativeTabs
      minimizeBehavior="onScrollDown"
      tintColor={theme.colors.accent}
      backgroundColor={theme.colors.backgroundElevated}
      indicatorColor={theme.colors.accentSoft}
    >
      <NativeTabs.Trigger name="(coach)">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'sparkles', selected: 'sparkles' }}
          md="auto_awesome"
        />
        <NativeTabs.Trigger.Label>Coach</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="(library)" role="history">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'rectangle.stack', selected: 'rectangle.stack.fill' }}
          md="video_library"
        />
        <NativeTabs.Trigger.Label>Library</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="(profile)">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'person', selected: 'person.fill' }}
          md="person"
        />
        <NativeTabs.Trigger.Label>You</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
