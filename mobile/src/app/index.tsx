import { Redirect } from 'expo-router';
import { ScrollView } from 'react-native';

import { AuthenticatedAppGate, SetupState } from '@/components';
import { useAuth } from '@/providers/auth-provider';
import { useReelMateTheme } from '@/theme';

export default function EntryRoute() {
  const auth = useAuth();
  const theme = useReelMateTheme();

  if (!auth.isConfigured && !auth.isDemo) {
    return (
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'center',
          padding: theme.spacing.xl,
        }}
      >
        <SetupState
          title="Connect ReelMate"
          message={`${auth.configurationIssue} Follow docs/EXTERNAL_CONNECTIONS.md in the repository; no secret belongs in this app bundle.`}
        />
      </ScrollView>
    );
  }
  if (!auth.user) return <Redirect href="/sign-in" />;
  return (
    <AuthenticatedAppGate>
      <Redirect href="/coach" />
    </AuthenticatedAppGate>
  );
}
