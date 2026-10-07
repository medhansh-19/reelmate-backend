import { Pressable, Text, View, type ViewStyle } from 'react-native';

import { useReelMateTheme } from '@/theme';

export type PreviewModeBannerProps = {
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
  style?: ViewStyle;
};

export function PreviewModeBanner({
  message = 'You are viewing sample results. Connect the app to analyze your own reels.',
  actionLabel = 'Setup',
  onAction,
  style,
}: PreviewModeBannerProps) {
  const theme = useReelMateTheme();

  return (
    <View
      accessible={!onAction}
      accessibilityLabel={!onAction ? `Preview mode. ${message}` : undefined}
      accessibilityRole={!onAction ? 'summary' : undefined}
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: theme.spacing.md,
          paddingHorizontal: theme.spacing.lg,
          paddingVertical: theme.spacing.md,
          borderRadius: theme.radii.md,
          borderCurve: 'continuous',
          backgroundColor: theme.colors.highlightSoft,
          borderWidth: 1,
          borderColor: theme.colors.highlight,
        },
        style,
      ]}
    >
      <View
        accessibilityElementsHidden
        style={{
          width: 9,
          height: 9,
          borderRadius: 9,
          backgroundColor: theme.colors.highlight,
        }}
      />
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={{ color: theme.colors.text, ...theme.typography.eyebrow }}>
          Preview mode
        </Text>
        <Text
          selectable
          style={{ color: theme.colors.textMuted, ...theme.typography.caption }}
        >
          {message}
        </Text>
      </View>
      {onAction ? (
        <Pressable
          accessibilityLabel={`${actionLabel} preview mode`}
          accessibilityRole="button"
          hitSlop={8}
          onPress={onAction}
          style={({ pressed }) => ({
            opacity: pressed ? 0.6 : 1,
            paddingVertical: 4,
          })}
        >
          <Text
            style={{
              color: theme.colors.text,
              fontSize: 13,
              fontWeight: '800',
            }}
          >
            {actionLabel}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
