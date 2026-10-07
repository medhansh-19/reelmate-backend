export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 40,
  hero: 56,
} as const;

export const radii = {
  sm: 10,
  md: 16,
  lg: 22,
  xl: 28,
  round: 999,
} as const;

export const typography = {
  eyebrow: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '700' as const,
    letterSpacing: 1.1,
    textTransform: 'uppercase' as const,
  },
  caption: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '500' as const,
  },
  body: {
    fontSize: 16,
    lineHeight: 23,
    fontWeight: '500' as const,
  },
  bodyStrong: {
    fontSize: 16,
    lineHeight: 22,
    fontWeight: '700' as const,
  },
  title: {
    fontSize: 22,
    lineHeight: 27,
    fontWeight: '800' as const,
    letterSpacing: -0.35,
  },
  display: {
    fontSize: 38,
    lineHeight: 42,
    fontWeight: '800' as const,
    letterSpacing: -1.2,
  },
  score: {
    fontSize: 36,
    lineHeight: 40,
    fontWeight: '800' as const,
    letterSpacing: -1,
    fontVariant: ['tabular-nums'] as const,
  },
} as const;

export const layout = {
  contentMaxWidth: 720,
  readingMaxWidth: 560,
  tapTarget: 48,
  compactBreakpoint: 380,
} as const;

export const shadows = {
  subtle: '0 1px 2px rgba(0, 0, 0, 0.10)',
  card: '0 10px 30px rgba(0, 0, 0, 0.12)',
  floating: '0 18px 48px rgba(0, 0, 0, 0.22)',
} as const;
