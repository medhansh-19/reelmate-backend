import { useColorScheme, type ColorSchemeName } from 'react-native';

import { createReelMateColors } from './colors';
import { layout, radii, shadows, spacing, typography } from './tokens';

function createTheme(resolvedScheme: 'light' | 'dark') {
  return {
    scheme: resolvedScheme,
    isDark: resolvedScheme === 'dark',
    colors: createReelMateColors(resolvedScheme),
    spacing,
    radii,
    typography,
    layout,
    shadows,
  } as const;
}

const themes = {
  light: createTheme('light'),
  dark: createTheme('dark'),
} as const;

export type ReelMateTheme = (typeof themes)[keyof typeof themes];

export function getReelMateTheme(
  scheme: ColorSchemeName = 'dark',
): ReelMateTheme {
  return themes[scheme === 'light' ? 'light' : 'dark'];
}

export function useReelMateTheme(): ReelMateTheme {
  const scheme = useColorScheme();
  return getReelMateTheme(scheme);
}
