// PDF-92 D1/D2. The frozen register of every top-level section that is a
// navigation destination and exists TODAY. `Navbar.astro` renders both the
// `sm`+ link row and the always-visible below-`sm` rail from this one array
// -- two hand-maintained link lists in one component is the drift surface
// this file exists to remove (D1).
//
// `tests/test_website_contract.py`'s `AR1` freezes the `id` sequence below
// in a tuple declared INDEPENDENTLY of this file, so a change here (e.g.
// `PDF-97` retiring `features` in favour of `safety`) reds by design unless
// the test's own tuple is edited in the same commit -- a deliberate edit,
// never a silent drift (D7).
//
// `safety` and `status` are RESERVED, not assigned: they are the
// information architecture's final section set and `PDF-97` creates both
// sections. Assigning either id now would put a safety contract's name on a
// Features grid that has not yet become one (D2).
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
}

export const SECTIONS: readonly SectionLink[] = [
  { id: 'features', label: 'Features', short: 'Features' },
  { id: 'architecture', label: 'Architecture', short: 'Architecture' },
  { id: 'verbs', label: 'Verbs', short: 'Verbs' },
  { id: 'quickstart', label: 'Quick Start', short: 'Install' },
  { id: 'contract', label: 'Exit Codes', short: 'Exit codes' },
  { id: 'licensing', label: 'Licensing', short: 'Licensing' },
] as const;
