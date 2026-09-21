// The 26-row verb roster, as a typed module. `status` is derived from
// `pdftooling --help` AND each verb's own `--help` (re-derived at
// implementation time, PDF-16 Phase B, 2026-08-31), NOT from PLAN.md §4.1
// or any spec's prose -- that is the whole point of honesty rule 7. All
// sixteen pdf-tooling specs have now landed: every one of the 25 top-level
// commands `pdftooling --help` prints resolves with a working `--help` of
// its own, so every entry below is `available` and `planned.length` is 0.
//
// `meta` is a grouping parent -- `pdftooling meta --help` prints `get` and
// `set` as its own two subcommands, both independently verified -- so the
// roster keeps `meta get` and `meta set` as two separate rows rather than
// collapsing them into one `meta` row: both are real, distinct invocations,
// and collapsing them would be a data-model change beyond this pass's
// remit that loses purpose granularity. 25 top-level commands, minus the
// `meta` parent, plus its two children, is 26 -- the array's row count.
//
// PDF-97 D1/D2 (ruling R3): the grouping field is renamed `port` -> `family`
// here -- and ONLY the field name changes. The nine values, their
// membership, the 26 purposes and the 26 statuses are carried byte-for-byte
// from the previous `Verbs.astro`-owned roster (`git show 5265850` is the
// comparison point `tests/test_website_contract.py`'s rename arm re-derives
// this against). `family` is right on its own merits -- it is a family and
// it is demonstrably not a port -- not because it agrees with any other
// taxonomy: the README's own family table (`README.md:87-96`) groups these
// same 26 verbs into a DIFFERENT eight-way partition under different names,
// and the diagrams proposal's chip-map sketch is a third, different again.
// Reconciling any of the three is explicitly out of scope (Finding 3) --
// this module ships a rename, not a re-taxonomisation. Deriving a REAL
// port per verb (a `ports: string[]` field backed by `src/pdf_tooling/ops/`)
// is ALSO out of scope, filed as `B-374` per ruling `R3`: it is the only
// item in the proposal whose cost cannot be bounded from outside the code.
//
// The claim that this roster is checked against the live command tree is
// made TRUE by `tests/test_website_contract.py`'s
// `test_the_website_verb_roster_is_the_live_command_tree`, which asserts
// `{v.name for v in discover_verbs()}` (the product's own CLI, walked
// recursively, no skip list) is set-equal to the 26 `name`s below -- on
// every pull request and every deploy, since `deploy-website.yml`'s gate
// calls `ci.yml` wholesale.

export type Verb = {
  name: string;
  family: string;
  purpose: string;
  status: 'available' | 'planned';
};

export const verbs: Verb[] = [
  { name: 'doctor', family: 'diagnostics', purpose: "Report each port's resolved adapter, version, and OS-aware install hint for what is missing.", status: 'available' },
  { name: 'info', family: 'diagnostics', purpose: 'Page count/sizes, encryption + permission bits, metadata, producer, font list, signature presence, per-page rotation.', status: 'available' },
  { name: 'version', family: 'diagnostics', purpose: 'Report the tool, runtime and engine versions.', status: 'available' },
  { name: 'merge', family: 'structure', purpose: 'Concatenate PDFs; per-input page selection via path:range; outline entry per source file.', status: 'available' },
  { name: 'split', family: 'structure', purpose: 'One PDF → many, by fixed chunk size, explicit ranges, per page, or at top-level bookmarks.', status: 'available' },
  { name: 'extract', family: 'structure', purpose: 'Write the selected pages to a new PDF, in the order given.', status: 'available' },
  { name: 'delete', family: 'structure', purpose: 'Write everything except the selected pages.', status: 'available' },
  { name: 'rotate', family: 'structure', purpose: 'Rotate the selected pages by a multiple of 90°, absolute or relative.', status: 'available' },
  { name: 'reorder', family: 'structure', purpose: 'Rewrite page order from an explicit sequence; duplicates allowed, order preserved.', status: 'available' },
  { name: 'repair', family: 'structure', purpose: "Structural recovery of a damaged/malformed PDF via libqpdf's recovery parser.", status: 'available' },
  { name: 'linearize', family: 'structure', purpose: 'Rewrite for byte-serving ("fast web view").', status: 'available' },
  { name: 'permissions', family: 'structure', purpose: 'Report the permission bits and encryption algorithm of an encrypted PDF.', status: 'available' },
  { name: 'meta get', family: 'structure', purpose: 'Read the document information dictionary + XMP.', status: 'available' },
  { name: 'meta set', family: 'structure', purpose: 'Write/clear document information fields and XMP.', status: 'available' },
  { name: 'rasterize', family: 'raster', purpose: 'PDF → PNG/JPEG/TIFF/WEBP at a chosen DPI or pixel width.', status: 'available' },
  { name: 'compose', family: 'compose', purpose: 'Images → PDF. JPEG inputs embed as DCTDecode streams (byte-preserving, no re-encode).', status: 'available' },
  { name: 'create', family: 'compose', purpose: 'Text (v1) → PDF. Markdown/HTML behind the [html] extra (Phase 2).', status: 'available' },
  { name: 'text', family: 'text', purpose: 'Extract text: fast path (pdfium) or layout-aware (pdfplumber) with per-block geometry.', status: 'available' },
  { name: 'tables', family: 'text', purpose: 'Detect and extract tables to CSV/JSON.', status: 'available' },
  { name: 'compress', family: 'optimize', purpose: 'Shrink: libqpdf object streams plus stream recompression (lossless), optional Pillow image downsample/recompress (lossy).', status: 'available' },
  { name: 'encrypt', family: 'crypto', purpose: 'Apply AES-256 (or RC4-128 with --legacy) with user/owner passwords and a permission set.', status: 'available' },
  { name: 'decrypt', family: 'crypto', purpose: 'Remove encryption given the correct password.', status: 'available' },
  { name: 'watermark', family: 'overlay', purpose: 'Overlay/underlay generated text across the selected pages.', status: 'available' },
  { name: 'stamp', family: 'overlay', purpose: 'Overlay/underlay an existing PDF page onto the selected pages.', status: 'available' },
  { name: 'ocr', family: 'overlay', purpose: 'Add a Tesseract text layer over untouched pixels — a text-only PDF generated per page and merged.', status: 'available' },
  { name: 'convert', family: 'external', purpose: 'Office → PDF via headless LibreOffice.', status: 'available' },
];

export const familyOrder = [
  'diagnostics',
  'structure',
  'raster',
  'compose',
  'text',
  'optimize',
  'crypto',
  'overlay',
  'external',
];
