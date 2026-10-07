import { Text, View, type ViewStyle } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { useReelMateTheme } from '@/theme';

export type ProcessingStage =
  | 'awaiting_upload'
  | 'queued'
  | 'validating'
  | 'extracting'
  | 'scoring'
  | 'generating_feedback'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'expired';

export type TimelineStep = {
  stage: Exclude<ProcessingStage, 'failed' | 'cancelled' | 'expired'>;
  label: string;
  detail: string;
};

export const DEFAULT_PROCESSING_STEPS: readonly TimelineStep[] = [
  {
    stage: 'awaiting_upload',
    label: 'Upload',
    detail: 'Securely receive your reel',
  },
  {
    stage: 'queued',
    label: 'Queue',
    detail: 'Reserve a private analysis slot',
  },
  {
    stage: 'validating',
    label: 'Check',
    detail: 'Confirm format, size, and duration',
  },
  {
    stage: 'extracting',
    label: 'Read',
    detail: 'Measure scenes, motion, audio, and text',
  },
  {
    stage: 'scoring',
    label: 'Score',
    detail: 'Apply the versioned coaching rubric',
  },
  {
    stage: 'generating_feedback',
    label: 'Coach',
    detail: 'Turn measurements into concrete edits',
  },
] as const;

export const STORY_PROCESSING_STEPS: readonly TimelineStep[] = [
  {
    stage: 'awaiting_upload',
    label: 'Upload',
    detail: 'Securely receive your story image',
  },
  {
    stage: 'queued',
    label: 'Queue',
    detail: 'Reserve a private analysis slot',
  },
  {
    stage: 'validating',
    label: 'Check',
    detail: 'Confirm image format, size, and dimensions',
  },
  {
    stage: 'extracting',
    label: 'See',
    detail: 'Measure color, light, faces, texture, and composition',
  },
  {
    stage: 'scoring',
    label: 'Match',
    detail: 'Rank songs by visual-to-mood similarity',
  },
] as const;

export type ProcessingTimelineProps = {
  stage: ProcessingStage;
  steps?: readonly TimelineStep[];
  compact?: boolean;
  style?: ViewStyle;
};

export function ProcessingTimeline({
  stage,
  steps = DEFAULT_PROCESSING_STEPS,
  compact = false,
  style,
}: ProcessingTimelineProps) {
  const theme = useReelMateTheme();
  const terminalSuccess = stage === 'completed';
  const terminalFailure =
    stage === 'failed' || stage === 'cancelled' || stage === 'expired';
  const activeIndex = steps.findIndex((step) => step.stage === stage);
  const announcedStage = terminalSuccess
    ? 'Analysis complete'
    : terminalFailure
      ? `Analysis ${stage}`
      : (steps[Math.max(activeIndex, 0)]?.label ?? 'Preparing');

  return (
    <View
      accessible
      accessibilityLabel={`Analysis progress: ${announcedStage}`}
      accessibilityLiveRegion="polite"
      accessibilityRole="summary"
      style={[{ gap: compact ? theme.spacing.sm : theme.spacing.md }, style]}
    >
      {steps.map((step, index) => {
        const isDone =
          terminalSuccess || (!terminalFailure && activeIndex > index);
        const isCurrent =
          !terminalSuccess && !terminalFailure && activeIndex === index;
        const markerColor = isDone
          ? theme.colors.success
          : isCurrent
            ? theme.colors.accent
            : theme.colors.surfaceMuted;

        return (
          <Animated.View
            entering={FadeInDown.duration(240).delay(index * 35)}
            key={step.stage}
            style={{ flexDirection: 'row', gap: theme.spacing.md }}
          >
            <View
              accessibilityElementsHidden
              style={{ width: 24, alignItems: 'center' }}
            >
              <View
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 20,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: markerColor,
                  borderWidth: isDone || isCurrent ? 0 : 1,
                  borderColor: theme.colors.separator,
                }}
              >
                {isDone ? (
                  <Text
                    style={{
                      color: theme.colors.background,
                      fontSize: 12,
                      fontWeight: '900',
                    }}
                  >
                    ✓
                  </Text>
                ) : isCurrent ? (
                  <View
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 7,
                      backgroundColor: theme.colors.onAccent,
                    }}
                  />
                ) : null}
              </View>
              {index < steps.length - 1 ? (
                <View
                  style={{
                    width: 2,
                    flex: 1,
                    minHeight: compact ? 14 : 24,
                    marginTop: 3,
                    backgroundColor: isDone
                      ? theme.colors.success
                      : theme.colors.separator,
                  }}
                />
              ) : null}
            </View>
            <View
              accessibilityElementsHidden
              style={{
                flex: 1,
                gap: compact ? 0 : theme.spacing.xs,
                paddingBottom: theme.spacing.sm,
              }}
            >
              <Text
                style={{
                  color:
                    isCurrent || isDone
                      ? theme.colors.text
                      : theme.colors.textMuted,
                  ...theme.typography.bodyStrong,
                }}
              >
                {step.label}
              </Text>
              {!compact ? (
                <Text
                  style={{
                    color: theme.colors.textMuted,
                    ...theme.typography.caption,
                  }}
                >
                  {step.detail}
                </Text>
              ) : null}
            </View>
          </Animated.View>
        );
      })}
      {terminalFailure ? (
        <View
          style={{
            marginLeft: 36,
            padding: theme.spacing.md,
            borderRadius: theme.radii.md,
            borderCurve: 'continuous',
            backgroundColor: theme.colors.dangerSoft,
          }}
        >
          <Text
            selectable
            style={{ color: theme.colors.danger, ...theme.typography.caption }}
          >
            {stage === 'expired'
              ? 'The upload window expired. Start a new analysis to continue.'
              : stage === 'cancelled'
                ? 'This analysis was cancelled.'
                : 'Analysis stopped before completion. You can retry if the issue was temporary.'}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
