import { Redirect } from 'expo-router';
import type { PropsWithChildren } from 'react';
import { ScrollView } from 'react-native';

import { useMusicPreferences } from '@/hooks/use-music-preferences';
import { useAuth } from '@/providers/auth-provider';
import { useReelMateTheme } from '@/theme';

import { StatePanel } from './state-view';

export function AuthenticatedAppGate({ children }: PropsWithChildren) {
  const theme = useReelMateTheme();
  const { user } = useAuth();
  const preferences = useMusicPreferences(Boolean(user));

  if (!user) return <Redirect href="/sign-in" />;

  if (preferences.isPending || (preferences.isError && !preferences.data)) {
    return (
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'center',
          padding: theme.spacing.xl,
        }}
      >
        <StatePanel
          compact
          kind={preferences.isError ? 'error' : 'setup'}
          title={
            preferences.isError
              ? 'Your music profile is offline'
              : 'Loading your music profile'
          }
          message={
            preferences.isError
              ? 'ReelMate needs this private preference record before opening your workspace.'
              : 'Getting your private ReelMate choices ready…'
          }
          actionLabel={preferences.isError ? 'Try again' : undefined}
          onAction={
            preferences.isError ? () => void preferences.refetch() : undefined
          }
        />
      </ScrollView>
    );
  }

  if (!preferences.data?.onboarding_completed_at) {
    return <Redirect href="/onboarding" />;
  }

  return children;
}
