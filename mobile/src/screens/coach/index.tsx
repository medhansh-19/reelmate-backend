import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { Pressable, ScrollView, Text, View } from 'react-native';

import {
  AnalysisListCard,
  Card,
  PreviewModeBanner,
  PrimaryButton,
  ReelMateMark,
  Surface,
} from '@/components';
import { useAnalyses } from '@/hooks/use-analyses';
import { useAuth } from '@/providers/auth-provider';
import { brandColors, useReelMateTheme } from '@/theme';

export function CoachScreen() {
  const theme = useReelMateTheme();
  const { isDemo, user } = useAuth();
  const analyses = useAnalyses();
  const recent =
    analyses.data?.pages.flatMap((page) => page.analyses).slice(0, 3) ?? [];

  return (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        width: '100%',
        maxWidth: theme.layout.contentMaxWidth,
        alignSelf: 'center',
        padding: theme.spacing.xl,
        paddingBottom: theme.spacing.hero,
        gap: theme.spacing.xxxl,
      }}
    >
      {isDemo ? <PreviewModeBanner /> : null}

      <LinearGradient
        colors={theme.isDark ? ['#2D1714', '#171B10'] : ['#FFE4DC', '#F1F8D5']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={{
          overflow: 'hidden',
          padding: theme.spacing.xxxl,
          borderRadius: theme.radii.xl,
          borderCurve: 'continuous',
          gap: theme.spacing.xl,
        }}
      >
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: theme.spacing.md,
          }}
        >
          <ReelMateMark decorative size={52} />
          <View style={{ flex: 1 }}>
            <Text
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.eyebrow,
              }}
            >
              Your edit room
            </Text>
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.title }}
            >
              Hey {user?.displayName.split(' ')[0] ?? 'Creator'}
            </Text>
          </View>
        </View>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.display }}
        >
          One creator toolkit. Two smart modes.
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.body }}
        >
          Coach a finished reel or match a story image with songs using
          ReelMate’s own local media intelligence.
        </Text>
      </LinearGradient>

      <View
        style={{
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: theme.spacing.lg,
        }}
      >
        <Surface
          variant="raised"
          style={{ flexGrow: 1, flexBasis: 270, gap: theme.spacing.lg }}
        >
          <Text style={{ color: brandColors.coral, fontSize: 36 }}>▶</Text>
          <View style={{ gap: theme.spacing.xs }}>
            <Text
              style={{
                color: theme.colors.textSubtle,
                ...theme.typography.eyebrow,
              }}
            >
              VIDEO COACH
            </Text>
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.title }}
            >
              Make the next cut obvious.
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              Measure the hook, pacing, text, audio, silence, and beat
              alignment.
            </Text>
          </View>
          <PrimaryButton
            fullWidth
            label="Coach a reel"
            onPress={() =>
              router.push({
                pathname: '/upload',
                params: { mode: 'video_coach' },
              })
            }
          />
        </Surface>

        <Surface
          variant="accent"
          style={{ flexGrow: 1, flexBasis: 270, gap: theme.spacing.lg }}
        >
          <Text style={{ color: theme.colors.highlight, fontSize: 40 }}>♫</Text>
          <View style={{ gap: theme.spacing.xs }}>
            <Text
              style={{
                color: theme.colors.textSubtle,
                ...theme.typography.eyebrow,
              }}
            >
              STORY SONG MATCH
            </Text>
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.title }}
            >
              Find the sound in your frame.
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              Turn light, color, mood, faces, and composition into ranked song
              matches.
            </Text>
          </View>
          <PrimaryButton
            fullWidth
            label="Match a story image"
            onPress={() =>
              router.push({
                pathname: '/upload',
                params: { mode: 'story_song' },
              })
            }
          />
        </Surface>
      </View>

      <View style={{ gap: theme.spacing.lg }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'baseline',
            justifyContent: 'space-between',
          }}
        >
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            Built by ReelMate
          </Text>
          <Text
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            No GPT recommendation call
          </Text>
        </View>
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: theme.spacing.md,
          }}
        >
          {[
            [
              '01',
              'Measure',
              'Scenes, motion, beats, silence, and readable text.',
            ],
            [
              '02',
              'Score',
              'A deterministic readiness score that stays comparable.',
            ],
            [
              '03',
              'Recommend',
              'Local ranked outputs with visible evidence and model versions.',
            ],
          ].map(([number, title, copy], index) => (
            <Surface
              key={number}
              variant={index === 1 ? 'accent' : 'raised'}
              style={{ flexGrow: 1, flexBasis: 190, gap: theme.spacing.md }}
            >
              <Text
                style={{
                  color:
                    index === 1 ? brandColors.coral : theme.colors.textSubtle,
                  ...theme.typography.eyebrow,
                }}
              >
                {number}
              </Text>
              <Text
                selectable
                style={{
                  color: theme.colors.text,
                  ...theme.typography.bodyStrong,
                }}
              >
                {title}
              </Text>
              <Text
                selectable
                style={{
                  color: theme.colors.textMuted,
                  ...theme.typography.caption,
                }}
              >
                {copy}
              </Text>
            </Surface>
          ))}
        </View>
      </View>

      <View style={{ gap: theme.spacing.lg }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            Recent activity
          </Text>
          {recent.length ? (
            <Pressable
              accessibilityRole="button"
              onPress={() => router.push('/library')}
              style={({ pressed }) => ({
                minWidth: theme.layout.tapTarget,
                minHeight: theme.layout.tapTarget,
                alignItems: 'flex-end',
                justifyContent: 'center',
                opacity: pressed ? 0.65 : 1,
              })}
            >
              <Text style={{ color: theme.colors.accent, fontWeight: '800' }}>
                View all
              </Text>
            </Pressable>
          ) : null}
        </View>
        {recent.length ? (
          recent.map((analysis) => (
            <AnalysisListCard
              key={analysis.analysis_id}
              createdAt={analysis.created_at}
              mode={analysis.mode}
              status={analysis.status}
              score={analysis.score}
              niche={analysis.niche_detected}
              onPress={() =>
                router.push({
                  pathname: '/analysis/[id]',
                  params: { id: analysis.analysis_id },
                })
              }
            />
          ))
        ) : (
          <Card style={{ gap: theme.spacing.sm }}>
            <Text
              selectable
              style={{
                color: theme.colors.text,
                ...theme.typography.bodyStrong,
              }}
            >
              Your first benchmark starts here.
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              Results will appear here after processing, ready to compare over
              time.
            </Text>
          </Card>
        )}
      </View>
    </ScrollView>
  );
}
