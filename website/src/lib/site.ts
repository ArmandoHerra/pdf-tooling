// Astro's `import.meta.env.BASE_URL` reflects whatever `base` is set to in
// astro.config.mjs verbatim -- with base: '/pdf-tooling' (no trailing slash),
// BASE_URL is "/pdf-tooling", NOT "/pdf-tooling/". Naively concatenating a filename
// onto that ("${base}og-image.png") silently produces the broken path
// "/pdf-toolingog-image.png". Normalize once here and reuse everywhere a public/
// asset is referenced by string path (built-in Astro helpers like the
// stylesheet link already do this correctly on their own).
const rawBase = import.meta.env.BASE_URL;
export const base = rawBase.endsWith('/') ? rawBase : `${rawBase}/`;

/** Prefix a root-relative public/ asset or page path with the configured base. */
export function withBase(path: string): string {
  return `${base}${path.replace(/^\/+/, '')}`;
}
