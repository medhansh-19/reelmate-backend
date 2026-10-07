import { Text, View, type ViewStyle } from 'react-native';

import { useReelMateTheme, type ReelMateColors } from '@/theme';

export type AnalysisStatus =
  | 'awaiting_upload'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'expired';

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const STATUS_META: Record<AnalysisStatus, { label: string; tone: StatusTone }> =
  {
    awaiting_upload: { label: 'Ready to upload', tone: 'neutral' },
    queued: { label: 'In queue', tone: 'warning' },
    processing: { label: 'Analyzing', tone: 'info' },
    completed: { label: 'Complete', tone: 'success' },
    failed: { label: 'Needs attention', tone: 'danger' },
    cancelled: { label: 'Cancelled', tone: 'neutral' },
    expired: { label: 'Upload expired', tone: 'neutral' },
  };

function toneColors(tone: StatusTone, colors: ReelMateColors) {
  if (tone === 'info')
    return { foreground: colors.info, background: colors.infoSoft };
  if (tone === 'success')
    return { foreground: colors.success, background: colors.successSoft };
  if (tone === 'warning')
    return { foreground: colors.warning, background: colors.warningSoft };
  if (tone === 'danger')
    return { foreground: colors.danger, background: colors.dangerSoft };
  return { foreground: colors.textMuted, background: colors.surfaceMuted };
}

export type StatusBadgeProps = {
  status?: AnalysisStatus;
  label?: string;
  tone?: StatusTone;
  showDot?: boolean;
  style?: ViewStyle;
};

export function StatusBadge({
  status,
  label,
  tone,
  showDot = true,
  style,
}: StatusBadgeProps) {
  const theme = useReelMateTheme();
  const metadata = status ? STATUS_META[status] : undefined;
  const resolvedLabel = label ?? metadata?.label ?? 'Unknown';
  const resolvedTone = tone ?? metadata?.tone ?? 'neutral';
  const palette = toneColors(resolvedTone, theme.colors);

  return (
    <View
      accessible
      accessibilityLabel={`Status: ${resolvedLabel}`}
      accessibilityLiveRegion={status === 'processing' ? 'polite' : 'none'}
      style={[
        {
          alignSelf: 'flex-start',
          minHeight: 28,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 6,
          paddingHorizontal: theme.spacing.md,
          paddingVertical: 5,
          borderRadius: theme.radii.round,
          backgroundColor: palette.background,
        },
        style,
      ]}
    >
      {showDot && (
        <View
          accessibilityElementsHidden
          style={{
            width: 7,
            height: 7,
            borderRadius: 7,
            backgroundColor: palette.foreground,
          }}
        />
      )}
      <Text
        accessibilityElementsHidden
        numberOfLines={1}
        style={{
          color: palette.foreground,
          fontSize: 12,
          lineHeight: 16,
          fontWeight: '800',
        }}
      >
        {resolvedLabel}
      </Text>
    </View>
  );
}
