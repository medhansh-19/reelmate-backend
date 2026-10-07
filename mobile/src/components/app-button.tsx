import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  Text,
  type GestureResponderEvent,
  type PressableProps,
  type ViewStyle,
} from 'react-native';

import { useReelMateTheme } from '@/theme';

export type AppButtonProps = Omit<PressableProps, 'children' | 'style'> & {
  label: string;
  variant?: 'primary' | 'secondary';
  size?: 'compact' | 'regular';
  leading?: ReactNode;
  trailing?: ReactNode;
  loading?: boolean;
  fullWidth?: boolean;
  style?: ViewStyle;
};

export function AppButton({
  label,
  variant = 'primary',
  size = 'regular',
  leading,
  trailing,
  loading = false,
  fullWidth = false,
  disabled = false,
  onPress,
  accessibilityLabel,
  style,
  ...rest
}: AppButtonProps) {
  const theme = useReelMateTheme();
  const isDisabled = disabled || loading;
  const isPrimary = variant === 'primary';
  const foreground = isPrimary ? theme.colors.onAccent : theme.colors.text;

  function handlePress(event: GestureResponderEvent) {
    if (process.env.EXPO_OS === 'ios') {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }
    onPress?.(event);
  }

  return (
    <Pressable
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      onPress={handlePress}
      style={({ pressed }) => [
        {
          minHeight: size === 'compact' ? 42 : theme.layout.tapTarget,
          alignSelf: fullWidth ? 'stretch' : 'flex-start',
          paddingHorizontal:
            size === 'compact' ? theme.spacing.lg : theme.spacing.xl,
          paddingVertical:
            size === 'compact' ? theme.spacing.sm : theme.spacing.md,
          borderRadius: theme.radii.round,
          borderCurve: 'continuous',
          backgroundColor: isPrimary
            ? pressed
              ? theme.colors.accentPressed
              : theme.colors.accent
            : pressed
              ? theme.colors.surfaceMuted
              : theme.colors.surfaceRaised,
          borderWidth: isPrimary ? 0 : 1,
          borderColor: theme.colors.separator,
          boxShadow: isPrimary ? theme.shadows.subtle : undefined,
          opacity: isDisabled ? 0.48 : 1,
          transform: [{ scale: pressed ? 0.985 : 1 }],
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: theme.spacing.sm,
        },
        style,
      ]}
      {...rest}
    >
      {loading ? (
        <ActivityIndicator color={foreground} size="small" />
      ) : (
        leading
      )}
      <Text
        numberOfLines={1}
        style={{
          color: foreground,
          fontSize: size === 'compact' ? 14 : 16,
          lineHeight: size === 'compact' ? 18 : 21,
          fontWeight: '800',
          letterSpacing: -0.15,
        }}
      >
        {label}
      </Text>
      {!loading && trailing}
    </Pressable>
  );
}

export function PrimaryButton(props: Omit<AppButtonProps, 'variant'>) {
  return <AppButton {...props} variant="primary" />;
}

export function SecondaryButton(props: Omit<AppButtonProps, 'variant'>) {
  return <AppButton {...props} variant="secondary" />;
}
