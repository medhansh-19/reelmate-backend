import { Text, View, type ViewStyle } from 'react-native';

import { Card } from './surface';

import { useReelMateTheme, type ReelMateColors } from '@/theme';

export type FeedbackType = 'hook' | 'pacing' | 'audio' | 'text' | 'strength';
export type FeedbackSeverity = 'high' | 'medium' | 'low';

const TYPE_LABELS: Record<FeedbackType, string> = {
  hook: 'Hook',
  pacing: 'Pacing',
  audio: 'Audio',
  text: 'On-screen text',
  strength: 'Keep this',
};

function formatTime(seconds: number) {
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const remainingSeconds = rounded % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

function severityColors(severity: FeedbackSeverity, colors: ReelMateColors) {
  if (severity === 'high')
    return { foreground: colors.danger, background: colors.dangerSoft };
  if (severity === 'medium')
    return { foreground: colors.warning, background: colors.warningSoft };
  return { foreground: colors.textMuted, background: colors.surfaceMuted };
}

export type FeedbackCardProps = {
  type: FeedbackType;
  message: string;
  action: string;
  evidence?: string;
  severity?: FeedbackSeverity;
  startSeconds?: number;
  endSeconds?: number;
  style?: ViewStyle;
};

export function FeedbackCard({
  type,
  message,
  action,
  evidence,
  severity = 'low',
  startSeconds,
  endSeconds,
  style,
}: FeedbackCardProps) {
  const theme = useReelMateTheme();
  const isStrength = type === 'strength';
  const palette = isStrength
    ? { foreground: theme.colors.success, background: theme.colors.successSoft }
    : severityColors(severity, theme.colors);
  const timestamp =
    startSeconds === undefined
      ? undefined
      : endSeconds === undefined ||
          Math.round(startSeconds) === Math.round(endSeconds)
        ? formatTime(startSeconds)
        : `${formatTime(startSeconds)}–${formatTime(endSeconds)}`;

  return (
    <Card
      accessible
      accessibilityLabel={`${TYPE_LABELS[type]} feedback${timestamp ? ` at ${timestamp}` : ''}. ${message}. Action: ${action}${evidence ? `. Evidence: ${evidence}` : ''}`}
      padding="regular"
      style={[
        {
          gap: theme.spacing.lg,
          borderLeftWidth: 4,
          borderLeftColor: palette.foreground,
        },
        style,
      ]}
    >
      <View
        accessibilityElementsHidden
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: theme.spacing.sm,
        }}
      >
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: 6,
            paddingHorizontal: theme.spacing.md,
            paddingVertical: 5,
            borderRadius: theme.radii.round,
            backgroundColor: palette.background,
          }}
        >
          <View
            style={{
              width: 7,
              height: 7,
              borderRadius: 7,
              backgroundColor: palette.foreground,
            }}
          />
          <Text
            style={{ color: palette.foreground, ...theme.typography.eyebrow }}
          >
            {TYPE_LABELS[type]}
          </Text>
        </View>
        {timestamp ? (
          <Text
            selectable
            style={{
              marginLeft: 'auto',
              color: theme.colors.textMuted,
              ...theme.typography.caption,
              fontVariant: ['tabular-nums'],
            }}
          >
            {timestamp}
          </Text>
        ) : null}
      </View>

      <Text
        selectable
        style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
      >
        {message}
      </Text>

      {evidence ? (
        <View accessibilityElementsHidden style={{ gap: theme.spacing.xs }}>
          <Text
            style={{
              color: theme.colors.textSubtle,
              ...theme.typography.eyebrow,
            }}
          >
            Why
          </Text>
          <Text
            selectable
            style={{
              color: theme.colors.textMuted,
              ...theme.typography.caption,
            }}
          >
            {evidence}
          </Text>
        </View>
      ) : null}

      <View
        accessibilityElementsHidden
        style={{
          gap: theme.spacing.xs,
          padding: theme.spacing.md,
          borderRadius: theme.radii.md,
          borderCurve: 'continuous',
          backgroundColor: isStrength
            ? theme.colors.successSoft
            : theme.colors.accentSoft,
        }}
      >
        <Text
          style={{
            color: isStrength ? theme.colors.success : theme.colors.accent,
            ...theme.typography.eyebrow,
          }}
        >
          {isStrength ? 'Repeat it' : 'Try this'}
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.text, ...theme.typography.caption }}
        >
          {action}
        </Text>
      </View>
    </Card>
  );
}
