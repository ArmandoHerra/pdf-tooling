// astro.config.mjs
//
// GitHub Pages project-site configuration.
//
// `site` + `base` are what make asset/link paths resolve correctly when the
// app is served from https://armandoherra.github.io/pdf-tooling/ instead of the
// domain root. When a custom domain is registered later (PLAN.md §12 R-17),
// both of these change -- see website/README.md "Switching to a custom
// domain" for the exact diff.
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://armandoherra.github.io',
  base: '/pdf-tooling',
  integrations: [sitemap()],
  vite: {
    plugins: [tailwindcss()],
  },
  build: {
    assets: 'assets',
  },
});
