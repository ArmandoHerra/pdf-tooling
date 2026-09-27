// Worked examples for the `examples` section.
//
// CAPTURED, NEVER COMPOSED -- the same rule `hero-transcript.ts` states and
// for the same reason: a transcript nobody ran is a screenshot of a wish.
// Every line below is the real stdout of the command above it.
//
// Captured 2026-09-27 against `pdftooling 1.0.0` (pypdf 6.16.2, pypdfium2
// 5.13.0, reportlab 5.0.1, pikepdf 10.12.0, pdfplumber 0.11.10, tesseract
// 5.5.0, LibreOffice 26.2.5.2), in a scratch directory outside every
// repository. `report.pdf` and `appendix.pdf` were built there with
// `pdftooling create` from plain-text sources of 12 and 4 pages.
//
// Re-capture with the commands exactly as written. Byte counts depend on
// the fixture instance and are expected to move if the fixtures are
// rebuilt; the SHAPE is what this section shows.

export interface ExampleLine {
  readonly kind: 'command' | 'output' | 'blank';
  readonly text: string;
  readonly comment?: string;
}

export interface WorkedExample {
  readonly id: string;
  readonly title: string;
  /** What the reader should take from it -- never a restatement of the command. */
  readonly point: string;
  /** The status the session's SUBJECT command ended on -- the one the
   *  capture is about, not necessarily the last line typed. Omitted means
   *  0. `refuse` is the reason this field exists: it exits 5 on purpose,
   *  and the terminal chrome used to print `exit 0` over it. */
  readonly exit?: number;
  readonly session: ReadonlyArray<ExampleLine>;
}

export const EXAMPLES: readonly WorkedExample[] = [
  {
    id: 'doctor',
    title: 'Find out what is actually installed',
    point:
      'Engines are optional and are found when you run the tool. This reports what it found, which version, and what is missing, so a machine can decide whether a job is even possible before starting it.',
    session: [
      { kind: 'command', text: 'pdftooling doctor -o table' },
      { kind: 'output', text: 'port             adapter     available  version   kind' },
      { kind: 'output', text: '---------------  ----------  ---------  --------  --------------' },
      { kind: 'output', text: 'StructureEngine  pypdf       yes        6.16.2    python-package' },
      { kind: 'output', text: 'RasterEngine     pypdfium2   yes        5.13.0    python-package' },
      { kind: 'output', text: 'ComposeEngine    reportlab   yes        5.0.1     python-package' },
      { kind: 'output', text: 'TextEngine       pdfplumber  yes        0.11.10   python-package' },
      { kind: 'output', text: 'OcrEngine        tesseract   yes        5.5.0     system-binary' },
      { kind: 'output', text: 'OfficeConverter  soffice     yes        26.2.5.2  system-binary' },
    ],
  },
  {
    id: 'inspect',
    title: 'Inspect a document, machine-first',
    point:
      'No flag was passed. Output is JSON because stdout is not a terminal; the same command is human-readable when you run it yourself and parseable when a script runs it.',
    session: [
      { kind: 'command', text: 'pdftooling info report.pdf | jq .documents[0]' },
      { kind: 'output', text: '{' },
      { kind: 'output', text: '  "path": "report.pdf",' },
      { kind: 'output', text: '  "size_bytes": 6695,' },
      { kind: 'output', text: '  "page_count": 12,' },
      { kind: 'output', text: '  "pdf_version": "1.3",' },
      { kind: 'output', text: '  "encrypted": false,' },
      { kind: 'output', text: '  "permissions": [],' },
      { kind: 'output', text: '  "linearized": false,' },
      { kind: 'output', text: '  "has_signature": false' },
      { kind: 'output', text: '}' },
    ],
  },
  {
    id: 'merge',
    title: 'Do the work',
    point:
      'One row per input, each with its own exit code and byte counts. Nothing is written until every input has been read and the destination has been checked.',
    session: [
      { kind: 'command', text: 'pdftooling merge report.pdf appendix.pdf -O book.pdf -o table' },
      { kind: 'output', text: 'input         output    exit code  message            bytes after' },
      { kind: 'output', text: '------------  --------  ---------  -----------------  -----------' },
      { kind: 'output', text: 'report.pdf    book.pdf  0          12 pages selected  8777' },
      { kind: 'output', text: 'appendix.pdf  book.pdf  0          4 pages selected   8777' },
    ],
  },
  {
    id: 'refuse',
    title: 'Fail in a way a script can act on',
    point:
      'Run it again and it refuses rather than overwriting. The refusal is a structured object with a stable code, not a message you have to parse, and not a silent overwrite.',
    exit: 5,
    session: [
      { kind: 'command', text: 'pdftooling merge report.pdf appendix.pdf -O book.pdf' },
      { kind: 'output', text: '{' },
      { kind: 'output', text: '  "schema_version": 1,' },
      { kind: 'output', text: '  "error": {' },
      { kind: 'output', text: '    "code": 5,' },
      { kind: 'output', text: '    "kind": "refused",' },
      { kind: 'output', text: '    "message": "book.pdf exists; pass --force to overwrite it",' },
      { kind: 'output', text: '    "path": "book.pdf"' },
      { kind: 'output', text: '  }' },
      { kind: 'output', text: '}' },
      { kind: 'blank', text: '' },
      { kind: 'command', text: 'echo $?', comment: 'the exit code matches the payload' },
      { kind: 'output', text: '5' },
    ],
  },
] as const;
