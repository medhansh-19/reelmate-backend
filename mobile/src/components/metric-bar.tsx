import { Text, View, type ColorValue, type ViewStyle } from 'react-native';

import { useReelMateTheme } from '@/theme';

export type MetricTone =
  'accent' | 'highlight' | 'info' | 'success' | 'warning' | 'danger';

export type MetricBarProps = {
  label: string;
  value: number;
  maximum?: number;
  displayValue?: string;
  caption?: string;
  tone?: MetricTone;
  style?: ViewStyle;
};

export function MetricBar({
  label,
  value,
  maximum = 100,
  displayValue,
  caption,
  tone = 'accent',
  style,
}: MetricBarProps) {
  const theme = useReelMateTheme();
  const safeMaximum = maximum > 0 ? maximum : 100;
  const safeValue = Math.min(Math.max(value, 0), safeMaximum);
  const percentage = (safeValue / safeMaximum) * 100;
  const toneMap: Record<MetricTone, ColorValue> = {
    accent: theme.colors.accent,
    highlight: theme.colors.highlight,
    info: theme.colors.info,
    success: theme.colors.success,
    warning: theme.colors.warning,
    danger: theme.colors.danger,
  };

  return (
    <View
      accessible
      accessibilityLabel={`${label}: ${displayValue ?? `${Math.round(safeValue)} out of ${safeMaximum}`}`}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: safeMaximum, now: safeValue }}
      style={[{ gap: theme.spacing.sm }, style]}
    >
      <View
        accessibilityElementsHidden
        style={{
          flexDirection: 'row',
          alignItems: 'baseline',
          justifyContent: 'space-between',
        }}
      >
        <Text
          numberOfLines={1}
          style={{
            flex: 1,
            color: theme.colors.text,
            ...theme.typography.caption,
          }}
        >
          {label}
        </Text>
        <Text
          selectable
          style={{
            color: theme.colors.text,
            fontSize: 14,
            lineHeight: 18,
            fontWeight: '800',
            fontVariant: ['tabular-nums'],
          }}
        >
          {displayValue ?? Math.round(safeValue)}
        </Text>
      </View>
      <View
        accessibilityElementsHidden
        style={{
          height: 8,
          overflow: 'hidden',
          borderRadius: theme.radii.round,
          backgroundColor: theme.colors.surfaceMuted,
        }}
      >
        <View
          style={{
            width: `${percentage}%`,
            height: '100%',
            borderRadius: theme.radii.round,
            backgroundColor: toneMap[tone],
          }}
        />
      </View>
      {caption ? (
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          {caption}
        </Text>
      ) : null}
    </View>
  );
}
