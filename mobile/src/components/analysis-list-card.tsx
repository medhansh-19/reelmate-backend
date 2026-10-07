import { Image } from 'expo-image';
import {
  Pressable,
  Text,
  View,
  useWindowDimensions,
  type PressableProps,
  type ViewStyle,
} from 'react-native';

import { ReelMateMark } from './brand-mark';
import { StatusBadge, type AnalysisStatus } from './status-badge';

import { useReelMateTheme } from '@/theme';
import type { AnalysisMode } from '@/types/media';

const ANALYSIS_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

function formatAnalysisDate(value: Date | string) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime()))
    return typeof value === 'string' ? value : 'Unknown date';

  return ANALYSIS_DATE_FORMATTER.format(date);
}

export type AnalysisListCardProps = Omit<
  PressableProps,
  'children' | 'style'
> & {
  title?: string;
  createdAt: Date | string;
  status: AnalysisStatus;
  mode?: AnalysisMode;
  score?: number | null;
  niche?: string | null;
  durationLabel?: string;
  thumbnailUri?: string | null;
  style?: ViewStyle;
};

export function AnalysisListCard({
  title,
  createdAt,
  status,
  mode = 'video_coach',
  score,
  niche,
  durationLabel,
  thumbnailUri,
  onPress,
  disabled,
  accessibilityLabel,
  style,
  ...rest
}: AnalysisListCardProps) {
  const theme = useReelMateTheme();
  const { width } = useWindowDimensions();
  const compact = width < theme.layout.compactBreakpoint;
  const resolvedTitle =
    title ??
    (mode === 'story_song'
      ? 'Story song match'
      : niche
        ? `${niche} reel`
        : 'Video coaching');
  const createdLabel = formatAnalysisDate(createdAt);
  const hasScore = typeof score === 'number';

  return (
    <Pressable
      accessibilityLabel={
        accessibilityLabel ??
        `${resolvedTitle}, ${createdLabel}, ${status.replaceAll('_', ' ')}${hasScore ? `, score ${score}` : ''}`
      }
      accessibilityRole={onPress ? 'button' : 'summary'}
      disabled={disabled || !onPress}
      onPress={onPress}
      style={({ pressed }) => [
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: compact ? theme.spacing.md : theme.spacing.lg,
          padding: theme.spacing.md,
          borderRadius: theme.radii.lg,
          borderCurve: 'continuous',
          backgroundColor: pressed
            ? theme.colors.surfaceMuted
            : theme.colors.surfaceRaised,
          borderWidth: 1,
          borderColor: theme.colors.separator,
          boxShadow: theme.shadows.subtle,
          opacity: disabled ? 0.55 : 1,
          transform: [{ scale: pressed ? 0.99 : 1 }],
        },
        style,
      ]}
      {...rest}
    >
      <View
        accessibilityElementsHidden
        style={{
          width: compact ? 68 : 82,
          aspectRatio: 9 / 12,
          overflow: 'hidden',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: theme.radii.md,
          borderCurve: 'continuous',
          backgroundColor: theme.colors.accentSoft,
        }}
      >
        {thumbnailUri ? (
          <Image
            accessibilityLabel={`Preview for ${resolvedTitle}`}
            cachePolicy="memory-disk"
            contentFit="cover"
            source={{ uri: thumbnailUri }}
            style={{ width: '100%', height: '100%' }}
            transition={160}
          />
        ) : mode === 'story_song' ? (
          <Text
            style={{ color: theme.colors.accent, fontSize: compact ? 30 : 36 }}
          >
            ♫
          </Text>
        ) : (
          <ReelMateMark decorative size={compact ? 34 : 40} />
        )}
      </View>

      <View
        accessibilityElementsHidden
        style={{ flex: 1, alignSelf: 'stretch', gap: 7 }}
      >
        <Text
          numberOfLines={2}
          style={{ color: theme.colors.text, ...theme.typography.bodyStrong }}
        >
          {resolvedTitle}
        </Text>
        <Text
          selectable
          numberOfLines={1}
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          {createdLabel}
          {durationLabel ? `  ·  ${durationLabel}` : ''}
        </Text>
        <StatusBadge status={status} />
      </View>

      {hasScore ? (
        <View
          accessibilityElementsHidden
          style={{
            minWidth: compact ? 46 : 54,
            alignItems: 'center',
            justifyContent: 'center',
            paddingHorizontal: theme.spacing.sm,
            paddingVertical: theme.spacing.md,
            borderRadius: theme.radii.md,
            borderCurve: 'continuous',
            backgroundColor: theme.colors.highlightSoft,
          }}
        >
          <Text
            selectable
            style={{
              color: theme.colors.text,
              fontSize: compact ? 22 : 26,
              lineHeight: compact ? 25 : 29,
              fontWeight: '800',
              letterSpacing: -0.7,
              fontVariant: ['tabular-nums'],
            }}
          >
            {Math.round(score)}
          </Text>
          {!compact ? (
            <Text
              style={{
                color: theme.colors.textMuted,
                fontSize: 10,
                fontWeight: '700',
              }}
            >
              {mode === 'story_song' ? 'MATCH' : 'SCORE'}
            </Text>
          ) : null}
        </View>
      ) : (
        <Text
          accessibilityElementsHidden
          style={{
            color: theme.colors.textSubtle,
            fontSize: 20,
            fontWeight: '500',
          }}
        >
          ›
        </Text>
      )}
    </Pressable>
  );
}
