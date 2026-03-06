// Auto-generated design tokens — re-generated on every Figma export.
// Edit the Figma file, not this file.

export const tokens = {
  colors: {
    background: '#000000',
    surface: '#0f0f0f',
    overlay: '#121212',
    primary: '#f58220',
    secondary: '#1a73e8',
    tertiary: '#3c4852',
    accent: '#7d7d7d',
    highlight: '#4b4b4b',
    link: '#737373',
    text: {
      primary: '#ffffff',
      secondary: '#d9d9d9',
      muted: '#edf5ff',
    },
  },
  spacing: {
    xs: 3,
    sm: 8,
    md: 11,
    lg: 12,
    xl: 16,
    sz2xl: 18,
    sz3xl: 32,
  },
  typography: {
    display: { size: 96, weight: 400, lineHeight: 116 },
    h1: { size: 88, weight: 400, lineHeight: 116 },
    h2: { size: 40, weight: 400, lineHeight: 48 },
    h3: { size: 36, weight: 400, lineHeight: 46 },
    h4: { size: 32, weight: 400, lineHeight: 41 },
    body: { size: 28, weight: 400, lineHeight: 36 },
    sm: { size: 27, weight: 400, lineHeight: 36 },
    xs: { size: 25, weight: 400, lineHeight: 30 },
    caption: { size: 22, weight: 400, lineHeight: 28 },
  },
  radii: {
    sm: 3,
    md: 6,
    lg: 7,
    xl: 8,
    sz2xl: 11,
    full: 9999,
  },
  shadows: {
    sm: '0px 4px 65px 1px rgba(0,6,43,0.21)',
    md: '0px 4px 29px rgba(60,60,60,0.15)',
    lg: '0px 1px 24px 1px rgba(0,0,0,0.16)',
    xl: '0px 2px 26px rgba(0,0,0,0.18)',
  },
} as const

export type Tokens = typeof tokens
