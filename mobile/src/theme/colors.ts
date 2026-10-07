import { Color } from 'expo-router';
import { Platform, type ColorSchemeName, type ColorValue } from 'react-native';

export const brandColors = {
  ink: '#11100F',
  paper: '#F6F4EE',
  coral: '#FF6A55',
  coralPressed: '#E95743',
  lime: '#D9FF57',
  cyan: '#60DFFF',
  violet: '#A792FF',
} as const;

export type ReelMateColors = {
  background: ColorValue;
  backgroundElevated: ColorValue;
  surface: ColorValue;
  surfaceRaised: ColorValue;
  surfaceMuted: ColorValue;
  text: ColorValue;
  textMuted: ColorValue;
  textSubtle: ColorValue;
  separator: ColorValue;
  outline: ColorValue;
  accent: ColorValue;
  accentPressed: ColorValue;
  onAccent: ColorValue;
  accentSoft: ColorValue;
  highlight: ColorValue;
  highlightSoft: ColorValue;
  info: ColorValue;
  infoSoft: ColorValue;
  success: ColorValue;
  successSoft: ColorValue;
  warning: ColorValue;
  warningSoft: ColorValue;
  danger: ColorValue;
  dangerSoft: ColorValue;
  scrim: ColorValue;
  skeleton: ColorValue;
};

export function createReelMateColors(scheme: ColorSchemeName): ReelMateColors {
  const isDark = scheme !== 'light';

  return {
    background: Platform.select({
      ios: Color.ios.systemGroupedBackground,
      android: Color.android.dynamic.surface,
      default: isDark ? '#0D0D0C' : '#F6F4EE',
    })!,
    backgroundElevated: Platform.select({
      ios: Color.ios.systemBackground,
      android: Color.android.dynamic.surfaceContainerLow,
      default: isDark ? '#121210' : '#FFFEFA',
    })!,
    surface: Platform.select({
      ios: Color.ios.secondarySystemGroupedBackground,
      android: Color.android.dynamic.surfaceContainer,
      default: isDark ? '#181816' : '#FFFEFA',
    })!,
    surfaceRaised: Platform.select({
      ios: Color.ios.tertiarySystemGroupedBackground,
      android: Color.android.dynamic.surfaceContainerHigh,
      default: isDark ? '#22221F' : '#FFFFFF',
    })!,
    surfaceMuted: Platform.select({
      ios: Color.ios.secondarySystemFill,
      android: Color.android.dynamic.surfaceContainerHighest,
      default: isDark ? '#2B2B27' : '#EAE7DE',
    })!,
    text: Platform.select({
      ios: Color.ios.label,
      android: Color.android.dynamic.onSurface,
      default: isDark ? '#F7F5EF' : '#181714',
    })!,
    textMuted: Platform.select({
      ios: Color.ios.secondaryLabel,
      android: Color.android.dynamic.onSurfaceVariant,
      default: isDark ? '#B4B1A9' : '#625F58',
    })!,
    textSubtle: Platform.select({
      ios: Color.ios.tertiaryLabel,
      android: Color.android.dynamic.outline,
      default: isDark ? '#7F7D76' : '#88847B',
    })!,
    separator: Platform.select({
      ios: Color.ios.separator,
      android: Color.android.dynamic.outlineVariant,
      default: isDark ? '#34332F' : '#D9D5CB',
    })!,
    outline: Platform.select({
      ios: Color.ios.opaqueSeparator,
      android: Color.android.dynamic.outline,
      default: isDark ? '#4A4841' : '#B9B4A8',
    })!,
    accent: brandColors.coral,
    accentPressed: brandColors.coralPressed,
    onAccent: brandColors.ink,
    accentSoft: isDark ? '#3A1E19' : '#FFE3DD',
    highlight: brandColors.lime,
    highlightSoft: isDark ? '#2C3517' : '#EDF8C9',
    info: Platform.select({
      ios: Color.ios.systemCyan,
      android: Color.android.dynamic.tertiary,
      default: isDark ? brandColors.cyan : '#087E9A',
    })!,
    infoSoft: Platform.select({
      android: Color.android.dynamic.tertiaryContainer,
      default: isDark ? '#163239' : '#D9F5FB',
    })!,
    success: Platform.select({
      ios: Color.ios.systemGreen,
      android: isDark ? '#55D98A' : '#147A41',
      default: isDark ? '#55D98A' : '#147A41',
    })!,
    successSoft: isDark ? '#183324' : '#DDF3E5',
    warning: Platform.select({
      ios: Color.ios.systemOrange,
      android: '#F3B33E',
      default: isDark ? '#FFC35C' : '#9A5C00',
    })!,
    warningSoft: isDark ? '#3A2C16' : '#FFF0D0',
    danger: Platform.select({
      ios: Color.ios.systemRed,
      android: Color.android.dynamic.error,
      default: isDark ? '#FF716E' : '#BB2929',
    })!,
    dangerSoft: Platform.select({
      android: Color.android.dynamic.errorContainer,
      default: isDark ? '#3B1D1D' : '#FCE1DF',
    })!,
    scrim: isDark ? 'rgba(0, 0, 0, 0.72)' : 'rgba(17, 16, 15, 0.42)',
    skeleton: isDark ? '#302F2B' : '#E4E0D7',
  };
}
