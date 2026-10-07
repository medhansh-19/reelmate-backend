import type { PropsWithChildren } from 'react';
import { View, type ViewProps } from 'react-native';

import { useReelMateTheme } from '@/theme';

export type SurfaceProps = PropsWithChildren<
  ViewProps & {
    variant?: 'default' | 'raised' | 'muted' | 'accent';
    padding?: 'none' | 'compact' | 'regular' | 'generous';
  }
>;

export function Surface({
  children,
  variant = 'default',
  padding = 'regular',
  style,
  ...rest
}: SurfaceProps) {
  const theme = useReelMateTheme();
  const backgroundColor =
    variant === 'raised'
      ? theme.colors.surfaceRaised
      : variant === 'muted'
        ? theme.colors.surfaceMuted
        : variant === 'accent'
          ? theme.colors.accentSoft
          : theme.colors.surface;
  const paddingValue =
    padding === 'none'
      ? 0
      : padding === 'compact'
        ? theme.spacing.md
        : padding === 'generous'
          ? theme.spacing.xxl
          : theme.spacing.lg;

  return (
    <View
      style={[
        {
          backgroundColor,
          padding: paddingValue,
          borderRadius: theme.radii.lg,
          borderCurve: 'continuous',
        },
        style,
      ]}
      {...rest}
    >
      {children}
    </View>
  );
}

export function Card(props: SurfaceProps) {
  const theme = useReelMateTheme();
  return (
    <Surface
      {...props}
      variant={props.variant ?? 'raised'}
      style={[
        {
          borderWidth: 1,
          borderColor: theme.colors.separator,
          boxShadow: theme.shadows.card,
        },
        props.style,
      ]}
    />
  );
}
