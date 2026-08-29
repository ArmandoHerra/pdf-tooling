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
        primary: {
          50: '#fff1f2',
          100: '#ffe4e6',
          400: '#fb7185',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          900: '#881337',
        },
        surface: {
          50: '#f8fafc',
          100: '#f1f5f9',
          800: '#1e293b',
          900: '#0f172a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
};
