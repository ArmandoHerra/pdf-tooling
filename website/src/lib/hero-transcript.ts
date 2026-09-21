// PDF-95 D1. The hero's transcript, CAPTURED never composed (ruling R8/R4's
// refinement). This module is the one sanctioned place a version string may
// be written (AC20) -- it is a record of a drive, never a claim -- and it is
// filed under `lib/`, not `data/`: `scripts/licenses.py` owns `src/data/`,
// writes into it, and silently skips when it is absent (`website/README.md`'s
// "Regenerating `src/data/licenses.json`" section); a hand-captured artifact
// whose entire value is that a human ran a command and pasted the bytes is
// the opposite of a regenerable one, and filing it in the regenerable
// directory would mislabel it in the one dimension this product cares about
// most (D1). `lib/site.ts` already holds hand-authored TypeScript consumed by
// components, written by no generator, diffed by nothing -- the same shelf.
//
// PROVENANCE -- re-derive this block, never transcribe it, the next time this
// file is touched (the discipline `QuickStart.astro` and `Verbs.astro` carry
// forward from PDF-16).
//
//   Captured:            2026-09-20, against `apps/pdf-tooling` @ 4dffc4c
//                         (git status --porcelain empty before and after).
//   pdftooling --version: pdftooling 1.0.0 (Python 3.12.13 (CPython) on
//                         linux); engines: pypdf 6.16.2, pypdfium2 5.13.0,
//                         reportlab 5.0.1, pikepdf 10.12.0, pdfplumber
//                         0.11.10, pytesseract 0.3.13, pillow 12.3.0
//                         (182 characters, measured -- the dossier's 178 is
//                         stale by four waves of engine bumps; only the
//                         `pdftooling 1.0.0` fragment is quoted in the UI,
//                         per the operator's own instruction).
//   Fixtures:             one one-page PDF via `pdftooling create`, then
//                         `pdftooling merge` of repeated `path:range`
//                         operands on that single page to reach the target
//                         page counts -- never hand-built. jul.pdf 12 pages
//                         / 9,983 bytes, aug.pdf 9 pages / 7,578 bytes,
//                         sep.pdf 11 pages / 9,182 bytes. Built and merged
//                         in a `mktemp -d` outside every repository.
//   Invocation CAPTURED:  `pdftooling merge jul.pdf aug.pdf sep.pdf -O
//                         q3.pdf --dry-run -o table  </dev/null  >A.txt`
//                         (non-TTY pipe, `-o table` explicit, since a pipe
//                         defaults to `json`).
//   Invocation SHOWN:     `pdftooling merge jul.pdf aug.pdf sep.pdf -O
//                         q3.pdf --dry-run` (no `-o table`) -- the panel
//                         depicts a terminal, not a pipe, and a terminal
//                         defaults to `table`. Verified identical: driving
//                         the same command through `script -qec "..."
//                         /dev/null` (a real pty) and diffing against the
//                         piped `-o table` capture is byte-identical once
//                         the pty's own CRLF line endings are stripped.
//                         `merge --help`, re-read at capture time: "Defaults
//                         to table on a TTY and json otherwise."
//   Widest line:          72 columns (the header row and its rule, lines 1
//                         and 2 below); the three data rows are 62. `bytes
//                         before` values are fixture-dependent and are NOT
//                         expected to reproduce byte-for-byte on a future
//                         re-run against freshly built fixtures -- the
//                         geometry (5 lines, 72-column widest line, the
//                         message text) is what AC1's re-run diff is
//                         re-deriving, not a frozen number.
//   `ls` verdict:         `ls q3.pdf` after the dry run: exit 2, "ls: cannot
//                         access 'q3.pdf': No such file or directory"
//                         (GNU coreutils phrasing) -- q3.pdf was never
//                         created, which is the entire point (`--dry-run`
//                         itself announces nothing about being a dry run in
//                         `merge`'s `-o table` output; ruling R8's own
//                         finding, filed as `B-375` and not fixed here).
//
// The shape is structured, never a padded string (the root cause `D2`
// names): the alignment INSIDE a captured table line is the product's own
// and is preserved byte-for-byte; the alignment of a comment to a command
// moves out of characters and into CSS (`Terminal.astro` renders `comment`
// outside the scroll container). This session ships no `comment` field --
// PDF-95's own `AC19` throwaway control exercises that path without
// committing a permanent example.
export interface TerminalSessionLine {
  readonly kind: 'command' | 'output' | 'blank';
  readonly text: string;
  readonly comment?: string;
}

export const HERO_TRANSCRIPT_SESSION: readonly TerminalSessionLine[] = [
  { kind: 'command', text: 'pdftooling merge jul.pdf aug.pdf sep.pdf -O q3.pdf --dry-run' },
  { kind: 'output', text: 'input    output  exit code  message            bytes before  duration ms' },
  { kind: 'output', text: '-------  ------  ---------  -----------------  ------------  -----------' },
  { kind: 'output', text: 'jul.pdf  q3.pdf  0          12 pages selected  9983          0' },
  { kind: 'output', text: 'aug.pdf  q3.pdf  0          9 pages selected   7578          0' },
  { kind: 'output', text: 'sep.pdf  q3.pdf  0          11 pages selected  9182          0' },
  { kind: 'blank', text: '' },
  { kind: 'command', text: 'ls q3.pdf' },
  { kind: 'output', text: "ls: cannot access 'q3.pdf': No such file or directory" },
] as const;

// AC6(c). The caption's two-fragment signature, DECLARED here so a test
// asserts against a signature this file owns rather than a substring chosen
// at the test site. `merge --dry-run` announces nothing about being a dry
// run in its own `-o table` output (ruling R8) -- the `ls` line is doing ALL
// of the proof, and the caption is what tells a visitor that is what they
// are looking at.
export const CAPTION_FRAGMENTS = {
  dryRun: 'dry run',
  nothingWritten: 'nothing was written',
} as const;

export const HERO_CAPTION =
  `A ${CAPTION_FRAGMENTS.dryRun} plans the whole merge across three files — ` +
  `then ls is the check, and ${CAPTION_FRAGMENTS.nothingWritten}.`;
