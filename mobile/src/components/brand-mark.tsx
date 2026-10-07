import { Text, View, type ViewStyle } from 'react-native';

import { brandColors, useReelMateTheme } from '@/theme';

export type ReelMateMarkProps = {
  size?: number;
  decorative?: boolean;
  style?: ViewStyle;
};

export function ReelMateMark({
  size = 44,
  decorative = false,
  style,
}: ReelMateMarkProps) {
  const theme = useReelMateTheme();
  const dotSize = Math.max(3, size * 0.105);

  return (
    <View
      accessibilityElementsHidden={decorative}
      accessibilityLabel={decorative ? undefined : 'ReelMate'}
      accessibilityRole={decorative ? undefined : 'image'}
      importantForAccessibility={decorative ? 'no-hide-descendants' : 'yes'}
      style={[
        {
          width: size,
          height: size,
          borderRadius: size * 0.31,
          borderCurve: 'continuous',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: theme.colors.accent,
          transform: [{ rotate: '-4deg' }],
        },
        style,
      ]}
    >
      <View
        style={{
          width: size * 0.64,
          height: size * 0.64,
          borderRadius: size,
          backgroundColor: brandColors.ink,
          alignItems: 'center',
          justifyContent: 'center',
          transform: [{ rotate: '4deg' }],
        }}
      >
        {[-135, -45, 45, 135].map((rotation) => (
          <View
            key={rotation}
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              alignItems: 'center',
              transform: [{ rotate: `${rotation}deg` }],
            }}
          >
            <View
              style={{
                width: dotSize,
                height: dotSize,
                borderRadius: dotSize,
                backgroundColor: brandColors.lime,
                top: size * 0.075,
              }}
            />
          </View>
        ))}
        <View
          style={{
            width: size * 0.16,
            height: size * 0.16,
            borderRadius: size,
            backgroundColor: brandColors.paper,
          }}
        />
      </View>
    </View>
  );
}

export type ReelMateWordmarkProps = {
  size?: 'compact' | 'regular' | 'large';
  showMark?: boolean;
  style?: ViewStyle;
};

export function ReelMateWordmark({
  size = 'regular',
  showMark = true,
  style,
}: ReelMateWordmarkProps) {
  const theme = useReelMateTheme();
  const fontSize = size === 'large' ? 34 : size === 'compact' ? 20 : 26;
  const markSize = size === 'large' ? 48 : size === 'compact' ? 30 : 38;

  return (
    <View
      accessible
      accessibilityLabel="ReelMate"
      style={[
        { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm },
        style,
      ]}
    >
      {showMark && <ReelMateMark decorative size={markSize} />}
      <View accessibilityElementsHidden style={{ flexDirection: 'row' }}>
        <Text
          style={{
            color: theme.colors.text,
            fontSize,
            lineHeight: fontSize + 4,
            fontWeight: '800',
            letterSpacing: -0.9,
          }}
        >
          Reel
        </Text>
        <Text
          style={{
            color: theme.colors.accent,
            fontSize,
            lineHeight: fontSize + 4,
            fontWeight: '800',
            letterSpacing: -0.9,
          }}
        >
          Mate
        </Text>
      </View>
    </View>
  );
}
