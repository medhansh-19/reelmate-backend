import { router } from 'expo-router';
import { useMemo } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';

import {
  Card,
  ErrorState,
  FeedbackCard,
  MetricBar,
  PrimaryButton,
  ProcessingTimeline,
  ScoreRing,
  SecondaryButton,
  StatusBadge,
  Surface,
} from '@/components';
import { STORY_PROCESSING_STEPS } from '@/components/processing-timeline';
import {
  useAnalysis,
  useCancelAnalysis,
  useDeleteAnalysis,
  useRetryAnalysis,
} from '@/hooks/use-analyses';
import { ApiError } from '@/lib/api-client';
import type { StorySongResult, VideoAnalysisResult } from '@/lib/api-schemas';
import { confirmAction, showMessage } from '@/lib/dialogs';
import { useReelMateTheme } from '@/theme';

const scoreTone = (score: number): 'success' | 'warning' | 'danger' =>
  score >= 75 ? 'success' : score >= 55 ? 'warning' : 'danger';

function VideoResultView({
  analysisId,
  result,
}: {
  analysisId: string;
  result: VideoAnalysisResult;
}) {
  const theme = useReelMateTheme();
  const remove = useDeleteAnalysis();
  const metrics = [
    ['Hook', result.sub_scores.hook, 'accent'],
    ['Pacing', result.sub_scores.pacing, 'highlight'],
    ['Audio sync', result.sub_scores.av_sync, 'info'],
    ['On-screen text', result.sub_scores.text, 'success'],
  ] as const;

  const confirmDelete = async () => {
    if (
      await confirmAction(
        'Delete this analysis?',
        'This removes its stored result and cannot be undone.',
        'Delete',
      )
    ) {
      try {
        await remove.mutateAsync(analysisId);
        router.replace('/library');
      } catch (error) {
        showMessage(
          'Couldn’t delete the analysis',
          error instanceof Error ? error.message : 'Try again.',
        );
      }
    }
  };

  return (
    <View style={{ gap: theme.spacing.xxxl }}>
      <Card
        padding="generous"
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: theme.spacing.xxl,
        }}
      >
        <ScoreRing score={result.score} size={148} />
        <View style={{ flex: 1, minWidth: 210, gap: theme.spacing.md }}>
          <StatusBadge
            label={result.score >= 75 ? 'Strong foundation' : 'Clear next edit'}
            tone={scoreTone(result.score)}
          />
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.display }}
          >
            {result.score >= 85
              ? 'Almost publish-ready.'
              : result.score >= 70
                ? 'A few smart trims away.'
                : 'The next cut is clear.'}
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            {Math.round(result.confidence * 100)}% signal confidence
            {result.niche_detected ? ` · ${result.niche_detected}` : ''}
          </Text>
          {result.personalization.score_delta !== null ? (
            <Text
              selectable
              style={{
                color:
                  result.personalization.score_delta > 0
                    ? theme.colors.success
                    : theme.colors.textMuted,
                ...theme.typography.bodyStrong,
              }}
            >
              {result.personalization.score_delta > 0 ? '+' : ''}
              {result.personalization.score_delta} from your previous reel
            </Text>
          ) : null}
        </View>
      </Card>

      <View style={{ gap: theme.spacing.lg }}>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.title }}
        >
          What the edit is doing
        </Text>
        <Card style={{ gap: theme.spacing.xl }}>
          {metrics.map(([label, value, tone]) =>
            value === null ? (
              <View key={label} style={{ gap: theme.spacing.xs }}>
                <Text
                  style={{
                    color: theme.colors.text,
                    ...theme.typography.caption,
                  }}
                >
                  {label}
                </Text>
                <Text
                  selectable
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  No audio signal available; excluded from the total.
                </Text>
              </View>
            ) : (
              <MetricBar key={label} label={label} value={value} tone={tone} />
            ),
          )}
        </Card>
      </View>

      <View style={{ gap: theme.spacing.lg }}>
        <View style={{ gap: theme.spacing.xs }}>
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            Your next edit pass
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            Every note points to a measured moment. Start with high-priority
            items, then preserve the strength.
          </Text>
        </View>
        {result.feedback.map((item, index) => (
          <FeedbackCard
            key={`${item.type}-${item.start_seconds}-${index}`}
            type={item.type}
            message={item.message}
            action={item.action}
            evidence={item.evidence}
            severity={item.severity}
            startSeconds={item.start_seconds}
            endSeconds={item.end_seconds}
          />
        ))}
      </View>

      {result.personalization.is_repeat_user ? (
        <Surface variant="accent" style={{ gap: theme.spacing.md }}>
          <Text
            style={{ color: theme.colors.accent, ...theme.typography.eyebrow }}
          >
            ReelMate remembers the pattern, not the footage
          </Text>
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            {result.personalization.editing_style
              ? `Your ${result.personalization.editing_style.replaceAll('-', ' ')} style is taking shape.`
              : 'Your creator baseline is taking shape.'}
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            Personalization is derived from structured scores and issue
            categories across completed analyses. Deleted source videos are not
            used.
          </Text>
        </Surface>
      ) : null}

      <Card style={{ gap: theme.spacing.sm }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          About this score
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          Reel readiness is an experimental editing-quality signal, not a
          promise of views. Trend prediction is intentionally excluded until
          there is real performance data.
        </Text>
        <Text
          selectable
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.caption,
          }}
        >
          Pipeline {result.versions.pipeline} · Rubric {result.versions.score} ·{' '}
          ReelMate local coaching · no GPT call
        </Text>
      </Card>

      <SecondaryButton
        fullWidth
        loading={remove.isPending}
        label="Delete analysis"
        onPress={() => void confirmDelete()}
      />
    </View>
  );
}

function StoryResultView({
  analysisId,
  result,
}: {
  analysisId: string;
  result: StorySongResult;
}) {
  const theme = useReelMateTheme();
  const remove = useDeleteAnalysis();
  const moods = Object.entries(result.image_summary.mood_profile)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  const confirmDelete = async () => {
    if (
      await confirmAction(
        'Delete this song match?',
        'This removes the stored mood profile and recommendations.',
        'Delete',
      )
    ) {
      try {
        await remove.mutateAsync(analysisId);
        router.replace('/library');
      } catch (error) {
        showMessage(
          'Couldn’t delete the song match',
          error instanceof Error ? error.message : 'Try again.',
        );
      }
    }
  };

  return (
    <View style={{ gap: theme.spacing.xxxl }}>
      <Surface variant="accent" style={{ gap: theme.spacing.lg }}>
        <StatusBadge label="Story song match" tone="success" />
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.display }}
        >
          Your frame sounds{' '}
          {result.recommendations[0].matched_moods.join(' + ')}.
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.body }}
        >
          {Math.round(result.confidence * 100)}% ranking confidence ·{' '}
          {result.image_summary.visual_tags.join(' · ')}
        </Text>
        {result.requested_vocal_preference === 'no_lyrics' ? (
          <StatusBadge label="Aesthetic · no lyrics only" tone="neutral" />
        ) : null}
      </Surface>

      <View style={{ gap: theme.spacing.lg }}>
        <View style={{ gap: theme.spacing.xs }}>
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            Best song matches
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            Ranked from image mood first
            {result.personalization.applied
              ? ', then lightly adjusted using your saved ReelMate music taste'
              : ''}
            . Search the exact title in Instagram Music.
          </Text>
        </View>
        {result.recommendations.map((song, index) => (
          <Card key={song.song_id} style={{ gap: theme.spacing.md }}>
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'flex-start',
                gap: theme.spacing.md,
              }}
            >
              <View
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 22,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor:
                    index === 0
                      ? theme.colors.accent
                      : theme.colors.surfaceMuted,
                }}
              >
                <Text
                  style={{
                    color:
                      index === 0 ? theme.colors.onAccent : theme.colors.text,
                    fontWeight: '900',
                  }}
                >
                  {index + 1}
                </Text>
              </View>
              <View style={{ flex: 1, gap: theme.spacing.xs }}>
                <Text
                  selectable
                  style={{
                    color: theme.colors.text,
                    ...theme.typography.title,
                  }}
                >
                  {song.title}
                </Text>
                <Text
                  selectable
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  {song.artist} · {song.language}
                  {song.bpm ? ` · ${song.bpm} BPM` : ''}
                </Text>
              </View>
              <StatusBadge
                label={`${song.match_score}%`}
                tone={index === 0 ? 'success' : 'neutral'}
              />
            </View>
            <View
              style={{
                flexDirection: 'row',
                flexWrap: 'wrap',
                gap: theme.spacing.sm,
              }}
            >
              {!song.has_lyrics ? (
                <StatusBadge label="No lyrics" tone="success" />
              ) : null}
              {song.aesthetic_tags.slice(0, 3).map((tag) => (
                <StatusBadge key={tag} label={tag} tone="neutral" />
              ))}
            </View>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.caption,
              }}
            >
              {song.why}
            </Text>
            <View
              style={{
                padding: theme.spacing.md,
                borderRadius: theme.radii.md,
                backgroundColor: theme.colors.surfaceMuted,
              }}
            >
              <Text
                style={{
                  color: theme.colors.textSubtle,
                  ...theme.typography.eyebrow,
                }}
              >
                SEARCH IN INSTAGRAM MUSIC
              </Text>
              <Text
                selectable
                style={{
                  color: theme.colors.text,
                  ...theme.typography.bodyStrong,
                }}
              >
                {song.search_query}
              </Text>
            </View>
          </Card>
        ))}
      </View>

      <View style={{ gap: theme.spacing.lg }}>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.title }}
        >
          What ReelMate measured
        </Text>
        <Card style={{ gap: theme.spacing.lg }}>
          {moods.map(([mood, value], index) => (
            <MetricBar
              key={mood}
              label={mood.charAt(0).toUpperCase() + mood.slice(1)}
              value={Math.round(value * 100)}
              tone={index === 0 ? 'accent' : 'highlight'}
            />
          ))}
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            Dominant colors: {result.image_summary.dominant_colors.join(', ')} ·{' '}
            {result.image_summary.face_count} face
            {result.image_summary.face_count === 1 ? '' : 's'} detected
          </Text>
        </Card>
      </View>

      <Card style={{ gap: theme.spacing.sm }}>
        <Text
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.eyebrow,
          }}
        >
          EXPLAINABLE LOCAL RANKING
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          Computer-vision features are projected into a mood vector, then
          matched with a diversified nearest-neighbour song ranker. No GPT or
          external inference API was used.
        </Text>
        <Text
          selectable
          style={{
            color: theme.colors.textSubtle,
            ...theme.typography.caption,
          }}
        >
          Vision {result.versions.pipeline} · Ranker{' '}
          {result.versions.ranking_model} · Catalog {result.versions.catalog}
        </Text>
      </Card>

      <SecondaryButton
        fullWidth
        loading={remove.isPending}
        label="Delete song match"
        onPress={() => void confirmDelete()}
      />
    </View>
  );
}

export function AnalysisScreen({ analysisId }: { analysisId: string }) {
  const theme = useReelMateTheme();
  const query = useAnalysis(analysisId);
  const cancel = useCancelAnalysis();
  const remove = useDeleteAnalysis();
  const retry = useRetryAnalysis();
  const response = query.data;
  const errorMessage = useMemo(() => {
    if (query.error instanceof ApiError) return query.error.message;
    return query.error instanceof Error
      ? query.error.message
      : 'The analysis could not be loaded.';
  }, [query.error]);

  const retryJob = async () => {
    try {
      await retry.mutateAsync(analysisId);
      await query.refetch();
    } catch (error) {
      showMessage(
        'Couldn’t retry the analysis',
        error instanceof Error ? error.message : 'Try again.',
      );
    }
  };

  const confirmCancel = async () => {
    if (
      await confirmAction(
        'Cancel this analysis?',
        'Processing will stop safely and the private source upload will be queued for deletion.',
        'Cancel analysis',
      )
    ) {
      try {
        await cancel.mutateAsync(analysisId);
      } catch (error) {
        showMessage(
          'Couldn’t cancel the analysis',
          error instanceof Error ? error.message : 'Try again.',
        );
      }
    }
  };

  const removeIncompleteUpload = async () => {
    try {
      await remove.mutateAsync(analysisId);
      router.replace('/upload');
    } catch (error) {
      showMessage(
        'Couldn’t remove the upload',
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
        gap: theme.spacing.xxxl,
      }}
    >
      {query.isPending ? (
        <Card
          padding="generous"
          style={{ alignItems: 'center', gap: theme.spacing.xl }}
        >
          <ActivityIndicator color={theme.colors.accent} size="large" />
          <Text
            selectable
            style={{ color: theme.colors.text, ...theme.typography.title }}
          >
            Opening your edit room…
          </Text>
        </Card>
      ) : query.isError ? (
        <ErrorState
          title="Couldn’t load this analysis"
          message={errorMessage}
          actionLabel="Try again"
          onAction={() => void query.refetch()}
        />
      ) : response?.status === 'completed' && response.result ? (
        response.result.mode === 'story_song' ? (
          <StoryResultView analysisId={analysisId} result={response.result} />
        ) : (
          <VideoResultView analysisId={analysisId} result={response.result} />
        )
      ) : response?.status === 'awaiting_upload' ? (
        <ErrorState
          title="The upload was not submitted"
          message="Remove this incomplete attempt and choose the media again. Any private object is queued for safe cleanup."
          actionLabel="Choose again"
          actionLoading={remove.isPending}
          onAction={() => void removeIncompleteUpload()}
        />
      ) : response?.status === 'failed' ||
        response?.status === 'expired' ||
        response?.status === 'cancelled' ? (
        <View style={{ gap: theme.spacing.xl }}>
          <ProcessingTimeline
            stage={response.stage}
            steps={
              response.mode === 'story_song'
                ? STORY_PROCESSING_STEPS
                : undefined
            }
          />
          <ErrorState
            title={
              response.status === 'failed'
                ? 'The analysis stopped'
                : response.status === 'expired'
                  ? 'The upload expired'
                  : 'Analysis cancelled'
            }
            message={
              response.failure_code
                ? `ReelMate stopped safely (${response.failure_code.replaceAll('_', ' ').toLowerCase()}).`
                : 'Start another analysis whenever you are ready.'
            }
            actionLabel={
              response.retryable ? 'Retry analysis' : 'Choose another file'
            }
            actionLoading={retry.isPending}
            onAction={
              response.retryable
                ? () => void retryJob()
                : () =>
                    router.replace({
                      pathname: '/upload',
                      params: { mode: response.mode },
                    })
            }
          />
        </View>
      ) : response ? (
        <View style={{ gap: theme.spacing.xxl }}>
          <View style={{ gap: theme.spacing.sm }}>
            <StatusBadge status={response.status} />
            <Text
              selectable
              style={{ color: theme.colors.text, ...theme.typography.display }}
            >
              {response.mode === 'story_song'
                ? 'Matching the frame to a musical mood.'
                : 'Reading the edit, not guessing the outcome.'}
            </Text>
            <Text
              selectable
              style={{
                color: theme.colors.textMuted,
                ...theme.typography.body,
              }}
            >
              You can leave this screen. ReelMate will keep processing and the
              result will stay in your library.
            </Text>
          </View>
          <Card padding="generous">
            <ProcessingTimeline
              stage={response.stage}
              steps={
                response.mode === 'story_song'
                  ? STORY_PROCESSING_STEPS
                  : undefined
              }
            />
          </Card>
          <PrimaryButton
            fullWidth
            label="Back to coach"
            onPress={() => router.replace('/coach')}
          />
          <SecondaryButton
            fullWidth
            loading={cancel.isPending}
            label="Cancel analysis"
            onPress={() => void confirmCancel()}
          />
        </View>
      ) : null}
    </ScrollView>
  );
}
