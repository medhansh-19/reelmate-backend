import { router } from 'expo-router';
import { ScrollView } from 'react-native';

import { EmptyState } from '@/components';
import { useReelMateTheme } from '@/theme';

export default function NotFoundRoute() {
  const theme = useReelMateTheme();
  return (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        flexGrow: 1,
        justifyContent: 'center',
        padding: theme.spacing.xl,
      }}
    >
      <EmptyState
        title="That page slipped the edit"
        message="The screen you opened is no longer available."
        actionLabel="Back to coach"
        onAction={() => router.replace('/coach')}
      />
    </ScrollView>
  );
}
