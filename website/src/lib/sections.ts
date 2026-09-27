// PDF-92 D1/D2. The frozen register of every top-level section that is a
// navigation destination and exists TODAY. `Navbar.astro` renders both the
// `sm`+ link row and the always-visible below-`sm` rail from this one array
// -- two hand-maintained link lists in one component is the drift surface
// this file exists to remove (D1).
//
// `tests/test_website_contract.py`'s `AR1` freezes the `id` sequence below
// in a tuple declared INDEPENDENTLY of this file, so a change here reds by
// design unless the test's own tuple is edited in the same commit -- a
// deliberate edit, never a silent drift (D7).
//
// PDF-97 D10: `features` retires in favour of `safety` -- `Features.astro`
// is retitled to the safety contract and keeps `#features` resolving via
// an empty, `aria-hidden` anchor of its own, so the published link is not
// broken by this rename. `status` is newly assigned to the production-
// posture section (`Posture.astro`, NEW). Both were RESERVED, not assigned,
// until this item created the sections they name.
export interface SectionLink {
  /** The section's `id` -- e.g. `features` renders as a `<section>` whose
   *  id attribute is that same word. Deliberately not spelled here as a
   *  literal `id=` example: `tests/test_website_contract.py`'s `AR2`/`AR4`
   *  scan `website/src` for exactly that attribute shape, and a worked
   *  example in this comment would double-count as one of its own targets. */
  readonly id: string;
  /** Full label, used in the `sm`+ row. */
  readonly label: string;
  /** Short label, used in the below-`sm` rail, where a 44px-tall chip at
   *  320px has far less width to spend than a `sm`+ text link does. */
  readonly short: string;
  /** The Spanish pair. The `id` is deliberately NOT translated: it is the
   *  published anchor, shared by both pages, and `#verbs` has to keep
   *  meaning the same place in a link somebody sent last year. Only the
   *  words a reader sees change.
   *
   *  English moved too: `Verbs` -> `Commands` (one word for a subcommand
   *  across the whole site) added 38px to a row with 33px of slack and
   *  wrapped it, so `Quick Start` became `Install` -- which is both
   *  shorter and a plainer name for the section it points at, and which
   *  the `short` column was already using.
   *
   *  Spanish runs longer than English almost everywhere here, and the
   *  `sm`+ row is already the width-critical surface this file's own D4
   *  note describes. Measured at 1,152-1,440px, where the row has 735px:
   *  the English labels need 718px and fit on one line, while the first
   *  Spanish draft ("Instalación", "Códigos de salida", "Todos los
   *  paquetes") needed 889px and wrapped to two rows at EVERY desktop
   *  width. D4's wrap escape hatch means that renders correctly rather
   *  than overflowing -- it is not a defect -- but the English row does
   *  not wrap, so the Spanish one should not either. Three labels were
   *  shortened to the word that already carries the meaning; the section
   *  headings they point at still spell it out in full. */
  readonly es: { readonly label: string; readonly short: string };
}

export const SECTIONS: readonly SectionLink[] = [
  { id: 'safety', label: 'Safety', short: 'Safety', es: { label: 'Seguridad', short: 'Seguridad' } },
  { id: 'architecture', label: 'Architecture', short: 'Architecture', es: { label: 'Arquitectura', short: 'Arquitectura' } },
  { id: 'verbs', label: 'Commands', short: 'Commands', es: { label: 'Comandos', short: 'Comandos' } },
  { id: 'examples', label: 'Examples', short: 'Examples', es: { label: 'Ejemplos', short: 'Ejemplos' } },
  { id: 'quickstart', label: 'Install', short: 'Install', es: { label: 'Instalar', short: 'Instalar' } },
  { id: 'contract', label: 'Exit Codes', short: 'Exit codes', es: { label: 'Códigos', short: 'Códigos' } },
  { id: 'status', label: 'Status', short: 'Status', es: { label: 'Garantías', short: 'Garantías' } },
  { id: 'licensing', label: 'Licensing', short: 'Licensing', es: { label: 'Licencias', short: 'Licencias' } },
] as const;
