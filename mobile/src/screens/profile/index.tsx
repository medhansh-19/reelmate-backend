import { router } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';

import {
  Card,
  PreviewModeBanner,
  ReelMateMark,
  SecondaryButton,
  StatusBadge,
  Surface,
} from '@/components';
import { useAnalyses, useAnalysis } from '@/hooks/use-analyses';
import { useMusicPreferences } from '@/hooks/use-music-preferences';
import type { MusicPreference } from '@/lib/api-schemas';
import { showMessage } from '@/lib/dialogs';
import { useAuth } from '@/providers/auth-provider';
import { resetQueryCache } from '@/providers/query-provider';
import { useReelMateTheme } from '@/theme';

function PreferencePill({ label }: { label: string }) {
  const theme = useReelMateTheme();
  return (
    <View
      style={{
        minHeight: 34,
        justifyContent: 'center',
        paddingHorizontal: theme.spacing.md,
        paddingVertical: 6,
        borderRadius: theme.radii.round,
        backgroundColor: theme.colors.accentSoft,
      }}
    >
      <Text
        style={{
          color: theme.colors.accent,
          ...theme.typography.caption,
          fontWeight: '700',
          textTransform: 'capitalize',
        }}
      >
        {label}
      </Text>
    </View>
  );
}

function MusicTasteSummary({ preference }: { preference: MusicPreference }) {
  const theme = useReelMateTheme();
  const labels = [
    ...preference.preferred_languages,
    ...preference.preferred_moods,
  ];
  const favoriteSummary = [
    ...preference.favorite_artists,
    ...preference.favorite_tracks,
  ];

  return (
    <Card padding="generous" style={{ gap: theme.spacing.xl }}>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'flex-start',
          gap: theme.spacing.md,
        }}
      >
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Text style={{ color: theme.colors.text, ...theme.typography.title }}>
            Your music profile
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            First-party choices that personalize close image-to-song matches.
          </Text>
        </View>
        <StatusBadge label="Ready" tone="success" />
      </View>

      {labels.length > 0 ? (
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: theme.spacing.sm,
          }}
        >
          {labels.map((label) => (
            <PreferencePill key={label} label={label} />
          ))}
        </View>
      ) : (
        <Surface variant="muted" style={{ gap: theme.spacing.xs }}>
          <Text
            style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
          >
            Image-led recommendations
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            You skipped taste filters, so ReelMate will rank entirely from the
            image.
          </Text>
        </Surface>
      )}

      <View style={{ gap: theme.spacing.xs }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          Default result
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          {preference.default_vocal_preference === 'no_lyrics'
            ? 'Aesthetic · no lyrics'
            : 'Best match overall'}
        </Text>
      </View>

      {favoriteSummary.length > 0 ? (
        <View style={{ gap: theme.spacing.xs }}>
          <Text
            style={{
              color: theme.colors.textSubtle,
              ...theme.typography.eyebrow,
            }}
          >
            Musical anchors
          </Text>
          <Text
            numberOfLines={3}
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            {favoriteSummary.join(' · ')}
          </Text>
        </View>
      ) : null}

      <SecondaryButton
        fullWidth
        label="Edit music taste"
        onPress={() =>
          router.push({ pathname: '/onboarding', params: { edit: '1' } })
        }
      />
    </Card>
  );
}

export function ProfileScreen() {
  const theme = useReelMateTheme();
  const auth = useAuth();
  const analyses = useAnalyses();
  const musicPreferences = useMusicPreferences();
  const allItems = analyses.data?.pages.flatMap((page) => page.analyses) ?? [];
  const latestCompletedId =
    allItems.find(
      (item) => item.status === 'completed' && item.mode === 'video_coach',
    )?.analysis_id ?? '';
  const latest = useAnalysis(latestCompletedId);
  const latestVideoResult =
    latest.data?.result?.mode === 'video_coach' ? latest.data.result : null;
  const profile = latestVideoResult?.personalization;

  const logOut = async () => {
    try {
      await auth.signOut();
      resetQueryCache();
      router.replace('/sign-in');
    } catch (error) {
      showMessage(
        'Could not sign out',
        error instanceof Error ? error.message : 'Try again.',
      );
    }
  };

  return (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        width: '100%',
        maxWidth: theme.layout.contentMaxWidth,
        alignSelf: 'center',
        padding: theme.spacing.xl,
        paddingBottom: theme.spacing.hero,
        gap: theme.spacing.xxl,
      }}
    >
      {auth.isDemo ? <PreviewModeBanner /> : null}

      <Card
        padding="generous"
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: theme.spacing.lg,
        }}
      >
        <ReelMateMark decorative size={62} />
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            {auth.user?.displayName ?? 'Creator'}
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            {auth.user?.email ?? 'Private preview account'}
          </Text>
        </View>
        <StatusBadge
          label={auth.isDemo ? 'Preview' : 'Connected'}
          tone={auth.isDemo ? 'warning' : 'success'}
        />
      </Card>

      <View style={{ gap: theme.spacing.lg }}>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.title }}
        >
          Creator baseline
        </Text>
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: theme.spacing.md,
          }}
        >
          {[
            [
              'Completed',
              profile?.submission_count ??
                allItems.filter((item) => item.status === 'completed').length,
            ],
            [
              'Style',
              profile?.editing_style?.replaceAll('-', ' ') ?? 'Learning',
            ],
            ['Energy', profile?.typical_energy ?? 'Learning'],
            [
              'Niche',
              profile?.inferred_niche ??
                latestVideoResult?.niche_detected ??
                'Learning',
            ],
          ].map(([label, value]) => (
            <Surface
              key={label}
              variant="raised"
              style={{ flexGrow: 1, flexBasis: 145, gap: theme.spacing.sm }}
            >
              <Text
                style={{
                  color: theme.colors.textSubtle,
                  ...theme.typography.eyebrow,
                }}
              >
                {label}
              </Text>
              <Text
                selectable
                style={{
                  color: theme.colors.text,
                  ...theme.typography.title,
                  textTransform: 'capitalize',
                }}
              >
                {value}
              </Text>
            </Surface>
          ))}
        </View>
      </View>

      {musicPreferences.data ? (
        <MusicTasteSummary preference={musicPreferences.data} />
      ) : (
        <Card style={{ gap: theme.spacing.sm }}>
          <Text style={{ color: theme.colors.text, ...theme.typography.title }}>
            Your music profile
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            {musicPreferences.isError
              ? 'Music preferences could not be loaded. Retry when you are online.'
              : 'Loading your private ReelMate preferences…'}
          </Text>
          {musicPreferences.isError ? (
            <SecondaryButton
              fullWidth
              label="Retry music preferences"
              onPress={() => void musicPreferences.refetch()}
            />
          ) : null}
        </Card>
      )}

      <Card style={{ gap: theme.spacing.md }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          Privacy promise
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          Your unpublished reel is not a public asset.
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          Originals stay in a private bucket and are durably queued for deletion
          when processing ends; cleanup retries until confirmed. ReelMate stores
          scores, structured signals, and coaching—not public video URLs or raw
          OCR text.
        </Text>
      </Card>

      <Card style={{ gap: theme.spacing.md }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          Connection
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          {auth.isDemo ? 'Local preview data' : 'Dedicated ReelMate services'}
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          Production uses only this app’s Supabase project, private R2 bucket,
          API deployment, and local media worker. No model API or credential is
          copied from another product.
        </Text>
      </Card>

      {auth.isDemo ? (
        <SecondaryButton
          fullWidth
          label="Back to coach"
          onPress={() => router.replace('/coach')}
        />
      ) : (
        <SecondaryButton
          fullWidth
          label="Sign out"
          onPress={() => void logOut()}
        />
      )}
    </ScrollView>
  );
}
