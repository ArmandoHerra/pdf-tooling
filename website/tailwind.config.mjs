// tailwind.config.mjs
//
// Tailwind CSS v4 is CSS-first: the actual theme tokens that drive the build
// live in `@theme` inside src/styles/global.css, loaded via the
// `@tailwindcss/vite` plugin in astro.config.mjs (no `tailwind.config.*` file
// is read by the build). This file is kept for editor/IDE tooling that still
// looks for a config file, and as a single readable reference for the theme
// below -- keep the two in sync if you change one.
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        // Plate M -- the ink. 400/500 frozen byte-for-byte (PDF-93 D1/AC2).
        primary: {
          50: '#fff1f2',
          100: '#ffe4e6',
          200: '#fecdd3',
          300: '#fda4af',
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          900: '#881337',
        },
        // Plate K -- warm near-neutral ink-black. Replaces the slate ramp.
        surface: {
          950: '#0b0709',
          900: '#120c10',
          850: '#181116',
          800: '#1f171d',
          750: '#271e25',
          700: '#33282f',
          600: '#4e434b',
          500: '#756a71',
          400: '#a1979d',
          300: '#c6bfc4',
          200: '#e0dbde',
          100: '#efecee',
          50: '#fbf9fa',
        },
        // The single inverted band (closing CTA); PDF-95 builds the band.
        paper: {
          50: '#f7f3f5',
          100: '#eae3e7',
        },
      },
      fontFamily: {
        // Pure system stacks -- no font file ships. No phantom name is
        // named (PDF-93 D6): the three sans/mono display names this file
        // used to carry never resolved to a fetched face and are removed --
        // not spelled out here so this comment does not itself become a
        // ninth occurrence of what it is describing the removal of.
        sans: [
          'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI Variable Text',
          'Segoe UI', 'Roboto', 'Noto Sans', 'Liberation Sans', 'Arial', 'sans-serif',
        ],
        mono: [
          'ui-monospace', 'SF Mono', 'SFMono-Regular', 'Menlo', 'Cascadia Mono',
          'Segoe UI Mono', 'Roboto Mono', 'DejaVu Sans Mono', 'Liberation Mono',
          'Consolas', 'monospace',
        ],
      },
      borderRadius: {
        xs: '3px',
        sm: '5px',
        md: '8px',
        lg: '10px',
      },
      boxShadow: {
        card: 'inset 0 1px 0 0 rgb(255 255 255 / 0.05), 0 1px 2px 0 rgb(0 0 0 / 0.40)',
        lift: 'inset 0 1px 0 0 rgb(255 255 255 / 0.09), 0 10px 30px -12px rgb(244 63 94 / 0.10), 0 0 0 1px rgb(251 113 133 / 0.35)',
        well: 'inset 0 1px 2px 0 rgb(0 0 0 / 0.60), inset 0 0 0 1px rgb(255 255 255 / 0.04)',
        float: '0 24px 60px -24px rgb(0 0 0 / 0.85), 0 0 0 1px rgb(255 255 255 / 0.06)',
      },
    },
  },
};
