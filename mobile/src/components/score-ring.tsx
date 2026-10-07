import { Text, View, type ViewStyle } from 'react-native';

import { useReelMateTheme } from '@/theme';

const SEGMENT_COUNT = 24;
const SEGMENTS = Array.from({ length: SEGMENT_COUNT }, (_, index) => index);

export type ScoreRingProps = {
  score: number;
  maximum?: number;
  label?: string;
  size?: number;
  style?: ViewStyle;
};

export function ScoreRing({
  score,
  maximum = 100,
  label = 'Reel score',
  size = 128,
  style,
}: ScoreRingProps) {
  const theme = useReelMateTheme();
  const safeMaximum = maximum > 0 ? maximum : 100;
  const safeScore = Math.min(Math.max(score, 0), safeMaximum);
  const percentage = safeScore / safeMaximum;
  const activeSegments = Math.round(percentage * SEGMENT_COUNT);
  const progressColor =
    percentage >= 0.7
      ? theme.colors.success
      : percentage >= 0.45
        ? theme.colors.warning
        : theme.colors.danger;
  const segmentWidth = Math.max(3, Math.round(size * 0.035));
  const segmentHeight = Math.max(7, Math.round(size * 0.09));
  const innerSize = size - Math.max(30, Math.round(size * 0.26));

  return (
    <View
      accessible
      accessibilityLabel={`${label}: ${Math.round(safeScore)} out of ${safeMaximum}`}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: safeMaximum, now: safeScore }}
      style={[
        {
          width: size,
          height: size,
          alignItems: 'center',
          justifyContent: 'center',
        },
        style,
      ]}
    >
      {SEGMENTS.map((index) => (
        <View
          accessibilityElementsHidden
          key={index}
          style={{
            position: 'absolute',
            width: size,
            height: size,
            alignItems: 'center',
            transform: [{ rotate: `${(360 / SEGMENT_COUNT) * index}deg` }],
          }}
        >
          <View
            style={{
              width: segmentWidth,
              height: segmentHeight,
              borderRadius: segmentWidth,
              backgroundColor:
                index < activeSegments
                  ? progressColor
                  : theme.colors.surfaceMuted,
            }}
          />
        </View>
      ))}
      <View
        accessibilityElementsHidden
        style={{
          width: innerSize,
          height: innerSize,
          borderRadius: innerSize,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: theme.colors.surfaceRaised,
          borderWidth: 1,
          borderColor: theme.colors.separator,
        }}
      >
        <Text
          selectable
          style={{
            color: theme.colors.text,
            fontSize: Math.max(26, Math.round(size * 0.29)),
            lineHeight: Math.max(30, Math.round(size * 0.31)),
            fontWeight: '800',
            letterSpacing: -1,
            fontVariant: ['tabular-nums'],
          }}
        >
          {Math.round(safeScore)}
        </Text>
        <Text
          numberOfLines={1}
          style={{
            color: theme.colors.textMuted,
            fontSize: Math.max(9, Math.round(size * 0.085)),
            lineHeight: Math.max(12, Math.round(size * 0.105)),
            fontWeight: '700',
          }}
        >
          {label}
        </Text>
      </View>
    </View>
  );
}
