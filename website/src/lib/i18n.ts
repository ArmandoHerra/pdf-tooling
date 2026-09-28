// The two-locale machinery. ONE set of components renders both pages.
//
// The obvious alternative -- a parallel `components/es/` tree -- was
// rejected for a measured reason, not a stylistic one: eight of the
// thirteen components are pinned BY PATH from the Python suite
// (`tests/test_website_contract.py` reads `Verbs.astro`, `Hero.astro`,
// `Terminal.astro`, `ClosingCta.astro`, `Posture.astro`;
// `tests/test_website_diagrams.py` reads `Architecture.astro`,
// `ExitCodes.astro`, `AtomicWrite.astro`). A duplicated tree would leave
// those arms guarding the English copy only, and the Spanish page would
// ship with no contract at all -- the exact "second copy that silently
// rots" failure this project keeps writing censuses to prevent.
//
// So: markup stays in one place, and only the WORDS fork. Each component
// declares its English strings as a local `EN` object -- the sentences
// remain literally present in the file the suite pins, byte-for-byte --
// and hands them to `pick()` with the Spanish slice. On `/es/` the two are
// merged; everywhere else `EN` is returned untouched.
//
// What never enters a copy table: identifiers. Flag names, paths, module
// names, exit-code NAMES and command lines are the product's own surface
// and are the same word in every language, so prose that contains one is
// split into fragments AROUND it rather than embedding markup in a string.
// That also keeps `set:html` out of the build entirely.

export type Lang = 'en' | 'es';

/** The locale a page belongs to, derived from its own URL.
 *
 *  Components read this from `Astro.url` rather than taking a prop, so
 *  `pages/es/index.astro` can stay a near-copy of `pages/index.astro`
 *  instead of threading a `lang` through thirteen call sites -- a thread
 *  that only has to be dropped once to ship an English paragraph on the
 *  Spanish page.
 *
 *  Matching is on a whole path SEGMENT: `/pdf-tooling/es/` is Spanish and
 *  so is `/pdf-tooling/es/licensing/`, while a hypothetical `/estimates/`
 *  is not. `base` itself can never collide -- it is `/pdf-tooling`. */
export function langOf(url: URL): Lang {
  return url.pathname.split('/').includes('es') ? 'es' : 'en';
}

/** Merge a component's English strings with its Spanish overrides.
 *
 *  The Spanish slice is `Partial<T>` on purpose: a key that has no
 *  translation yet falls back to English and renders, rather than
 *  rendering `undefined`. Missing keys are caught by
 *  `tests/test_website_i18n.py`, which compares the two tables key by key
 *  -- a silent English leak on the Spanish page is a defect the suite
 *  names, not something a reader has to notice. */
export function pick<T extends object>(url: URL, en: T, es: Partial<T>): T {
  return langOf(url) === 'es' ? { ...en, ...es } : en;
}

/** Route a same-site page path into the current locale.
 *
 *  `licensing/` resolves to `/pdf-tooling/licensing/` on the English page
 *  and `/pdf-tooling/es/licensing/` on the Spanish one. Anchors (`#verbs`)
 *  are deliberately NOT localized -- the section ids are one published
 *  register shared by both pages (`sections.ts`), so a link to `#verbs`
 *  means the same place in either language. */
export function langPath(url: URL, path: string): string {
  const clean = path.replace(/^\/+/, '');
  return langOf(url) === 'es' ? `es/${clean}` : clean;
}

/** The other locale's equivalent of the current page, for the switch in
 *  the navbar. Strictly a path transform: `/pdf-tooling/es/licensing/`
 *  and `/pdf-tooling/licensing/` are each other's counterpart, which only
 *  holds because every Spanish route is the English route under `es/`. */
export function alternatePath(url: URL, base: string): string {
  const rest = url.pathname.slice(base.length).replace(/^\/+/, '');
  return langOf(url) === 'es' ? `${base}${rest.replace(/^es\/?/, '')}` : `${base}es/${rest}`;
}

/** The `hreflang` pair every page in either locale declares. */
export const LOCALES: readonly Lang[] = ['en', 'es'] as const;
