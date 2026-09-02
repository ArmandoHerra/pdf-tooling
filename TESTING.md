# Testing

## Running the suites

```bash
uv sync
make test          # everything
make test-e2e      # only the subprocess-level CLI tests
make cover         # the suite under coverage, against the project's floor (also runs in `make ci`)
make samples-scratch  # copy $PDF_TOOLKIT_SAMPLES_DIR -> .scratch/samples/ + write the originals manifest
make samples-check    # re-hash the originals against that manifest -- never a CI job (see below)
```

Individual files and selections work as usual:

```bash
uv run pytest tests/test_cli_spine.py -q
uv run pytest -k renderer -q
uv run pytest -m e2e -q
uv run pytest -m samples -q
uv run pytest --update-golden -q          # regenerate tests/golden/ files; review the diff
```

## The generated fixture corpus

`tests/corpus.py` builds seven deterministic PDFs (`multipage_text`, `rotated`,
`jpeg_page`, `encrypted_aes256`, `metadata_rich`, `single_page`, `tabular`)
with `reportlab`, once per test session, into pytest's own scratch directory
— never into the repository tree. Each fixture's expected values (page count,
per-page text, rotation, metadata, encryption, cell grid) live in the same
file as its generator, so a fixture can never silently drift from what a test
asserts against it. Six of the seven are byte-identical across two
independent builds; `encrypted_aes256` is the one honest exemption (a fresh
AES-256 salt every build) and is instead proven semantically. See
`tests/corpus.py`'s module docstring and `tests/test_corpus.py`.

Access it in a test via the session-scoped `corpus` fixture:
`corpus.path("single_page")` / `corpus.spec("single_page")`.

## `testdata/` — the two committed binaries

`testdata/malformed.pdf` (a hand-authored PDF with its xref/trailer
destroyed, body objects intact) and `testdata/scanned-page.png` (a
synthesized raster tesseract can recover text from) are the only binary
artifacts committed to this repository — everything else is generated at
test time. See `testdata/README.md` for provenance, exact defect, and the
spec each one is pinned for. `tests/test_testdata.py` mechanizes the
contract.

## The CLI contract harness

`tests/registry.py::discover_verbs()` walks the **live** Typer command tree
with no skip list, no filter and no hard-coded verb name — a new verb is
covered automatically the next time the suite runs. `tests/test_cli_contract.py`
parameterizes thirteen checks (`--help`, exit codes, dry-run purity,
no-clobber, JSON-on-a-pipe, bulk non-TTY posture) over that discovery.

**The registration contract.** A verb that needs a specific argv shape (e.g.
`rotate --angle`) registers a `tests/registry.py::Invocation` — the harness
cannot invent one. `test_every_verb_is_registered` fails the suite, naming
the verb, the moment one is discovered but not registered
(`tests/registry.py::INVOCATIONS`).

**A named deviation from the literal `is_mutating` predicate.** The Design
intent was to derive "does this verb mutate anything" from whether its click
command declares `-O/--output`, `--out-dir` or `--in-place`. Those three are
part of the **global** flag block every verb inherits uniformly
(`pdf_toolkit.cli.common.global_options`), so that signal is universally true
today and cannot discriminate. `tests/registry.py` instead walks the verb's
own callback module (and every `pdf_toolkit.*` module it imports,
transitively) for a reference to `AtomicWriter`, the one write chokepoint —
still fully structural, still classifies a new verb automatically, and
correctly reports `version`/`doctor`/`info` as non-mutating today. See
`tests/registry.py`'s module docstring for the full account.

## The `samples` fixture — `PLAN.md` §10.1

```bash
export PDF_TOOLKIT_SAMPLES_DIR=/path/to/your/samples
uv run pytest -m samples -q
```

The operator's own real-document corpus, entirely outside the repository and
**never committed**. Six rules bind it, restated here because they are the
highest-consequence part of this test suite:

1. **Originals are never an operand.** No verb, test, or probe receives a
   path under `$PDF_TOOLKIT_SAMPLES_DIR`. The `samples` fixture exposes
   exactly `available`, `names()`, `copy(name)`, `copy_tree(name)` — **no
   member returns a path under the originals directory.**
2. **Copy-on-use, per test.** `samples.copy(name)` / `samples.copy_tree(name)`
   copy with `shutil.copy2` into the test's own `tmp_path`, then chmod the
   copy user-writable. Nothing is ever copied into `testdata/` or `tests/`.
3. **The originals-integrity guard** (`tests/samples_guard.py`) hashes every
   original at session start and re-hashes at session end; any difference at
   all **fails the session, naming the file** — never a warning. Controller-
   only under `pytest -n auto` (`if hasattr(config, "workerinput")`), proven
   by `tests/integration/test_samples_guard_fires.py` against a **synthetic**
   samples directory — the operator's real corpus is never used to prove the
   guard, and it never mutates a real original in doing so.
4. **Privacy.** Nothing from the corpus is committed, and nothing about it is
   quoted anywhere beyond **filename, page count, size, and hash** — not in
   this file, not in `changelog.md`, not in `testdata/README.md`, not in a
   spec's Implementation Log.
5. **Visible skip when absent.** `@pytest.mark.samples` tests skip with a
   reason (`"PDF_TOOLKIT_SAMPLES_DIR not set — real-document arm skipped
   (PLAN.md §10.1 rule 5)"`) both via the marker (collection-time) and via the
   fixture itself (`samples.copy()`/`copy_tree()`, so an unmarked test that
   reaches the fixture still skips instead of erroring). CI never sets the
   variable, so the suite is green without the corpus and *more thorough*
   with it.
6. **Scratch lives in `.scratch/`** (gitignored). `make samples-scratch`
   copies the tree there and writes a `sha256sum`-compatible originals
   manifest; `pdftoolkit … .scratch/samples/<file>` is the only sanctioned
   way to point a verb at a real document interactively. `make clean` removes
   it.

**`make samples-check` is never a CI job** (`decision.md` `B-R01`) — its
absence from `ci.yml` is a decision, not a gap: CI never has the corpus, so
running it there would be a permanent no-op that looks like coverage.

Later specs (`PDF-07`…`PDF-15`) append their own `@samples` arm to
`tests/test_samples.py` — an append-only shared file; see that file's own
module docstring for the rules every arm follows.

## Engine markers, and hiding an engine without touching the host

```bash
uv run pytest --markers            # the registered list
PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice uv run pytest -rs -q
```

`@pytest.mark.requires("tesseract")` (or `"soffice"`, or a bare port name
like `"OcrEngine"`) resolves through the **same** `ports.resolve()` the CLI
uses, never an independent `shutil.which`. A missing engine yields a visible
`pytest.skip`, never a pass and never a silent xfail.

`PDF_TOOLKIT_TEST_HIDE_ENGINES` builds a **PATH-shadowing symlink directory**
under `$TMPDIR` — every executable reachable on the real `PATH` is symlinked
into it except the named ones, and `PATH` is repointed there for the process.
**No system binary is ever renamed, moved, or `chmod`-ed.** Applied before
collection (`tests/conftest.py::pytest_configure`), so the `requires(engine)`
skip decision itself sees the hidden PATH.

| Marker | Selects |
|---|---|
| `e2e` | Tests that run the installed console script as a subprocess. Slower, and the only ones that measure real process startup. |
| `samples` | The `PLAN.md` §10.1 real-document arm. Skips visibly when `$PDF_TOOLKIT_SAMPLES_DIR` is unset. |
| `requires(engine)` | Skips visibly when the named engine/port does not resolve via `ports.resolve()`. |

## The golden primitive

`tests/conftest.py::Golden` compares a payload against
`tests/golden/<name>.json` as a **parsed dict**, never a raw string, so key
order is never a false failure. `uv run pytest --update-golden` regenerates —
review the diff before committing. An ordinary run never writes a golden file
into existence: a missing one fails loudly with that instruction rather than
being silently created, which is what keeps `tests/golden/` out of the
working-tree guard's way. Goldens are built from the generated corpus only,
never from a sample (`PLAN.md` §10.1 rule 4). Empty at PDF-06 landing — see
`tests/golden/README.md`.

## The working-tree guard

`tests/conftest.py` hashes every **tracked** file (`git ls-files`) before and
after the session and fails, naming the file, if any changed —
`.pytest_cache/`, coverage data and `.scratch/` are untracked and therefore
exempt by construction. Controller-only under `-n auto`, same reasoning as
the samples guard above.

## Expected skip counts

Measured against the landed suite at PDF-06's own commit (`uv run pytest -rs
-q`), on Linux, with `$PDF_TOOLKIT_SAMPLES_DIR` unset (CI's own posture):

| Configuration | Total skips | What they are |
|---|---|---|
| **Engines present** (`tesseract` + `soffice` on `PATH`) | non-zero, but **zero are engine-gated** — `scripts/assert_skips.py --expect-zero` asserts exactly that. The non-zero remainder is the pre-existing safety-spine skips (see below) plus four `test_cli_contract.py` parametrize sets that are empty until a mutating verb or a subcommand group exists (`C4`, `C9`, `C10`/`C11`/`C13`), plus the `samples`-marked arms (unset). **Every remaining skip is conditional.** PDF-15 originally shipped one that was not — `test_ac7_rotated_page_returns_the_expected_text` carried an unconditional `@pytest.mark.skip` because `adapters/pdfium_raster.py` double-applied `/Rotate`; **B-094 fixed the adapter and the test now runs**, gated only by the ordinary `requires("tesseract")` marker. |
| **Engines hidden** (`PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice`) | the engines-present count **plus at least 20 engine-gated skips** — `tests/test_doctor.py`'s existing arms (PDF-05) and `tests/test_testdata.py`'s tesseract-recovery arm (PDF-06, 7 together) **plus PDF-15's own 18** (13 in `tests/integration/test_ocr.py`, 5 in `tests/integration/test_office.py`; re-measured at B-099 by running the documented command verbatim, three times: `PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice uv run pytest tests/integration/test_ocr.py tests/integration/test_office.py -rs -q` reports `8 passed, 18 skipped` — **all 18 engine-gated**, none unconditional, since B-094 unskipped AC7 and added three rotated-page arms beside it. The pass count had read `7` since PDF-15 landed: B-094 corrected the skip half of this figure and carried the pass half across by transcription rather than re-running it, which is how a count stays one low through three sweeps. Re-run it; do not copy it). `scripts/assert_skips.py` (no `--expect-zero`) asserts this count is **non-zero**; a zero here is a regression, not vacuity, as of PDF-06. |

Both counts are read with `-rs` (`pytest`'s own reason-printing flag) — a
skip is information, not noise: it says which guarantee this particular run
did not check, and why.

## Safety-spine test arms (`PDF-04`)

The write chokepoint's guarantees are the ones a user acts on, so each of
them is *demonstrated* by a run rather than asserted in prose. Three of those
arms need something the ordinary suite does not, and all three are described
here so that a red — or a skip — can be read without opening the test.

### Fault injection: a real `SIGKILL`, at a named point

`tests/integration/test_atomic_crash.py` kills a child process that is provably parked in the middle of a write. Two environment variables drive it, and **both are unset in every real run**:

| Variable | Meaning |
|---|---|
| `PDF_TOOLKIT_FAULT_POINT` | The point to park at: `after_temp_create`, `after_fsync` or `after_backup`. |
| `PDF_TOOLKIT_FAULT_RENDEZVOUS` | `"<ready_fd>:<release_fd>"` — two pipe descriptors the test inherits to the child. |

The child announces its arrival on the ready descriptor and then blocks reading the release descriptor, so when the parent delivers signal 9 the process is at that exact point. No `sleep`, no polling. With neither variable set, `safety/_faults.checkpoint()` is one environment lookup and a return: no descriptor, no filesystem access, and no branch a user can reach. That inertness is itself asserted, under the purity snapshot.

There is deliberately no injection point "during the replace". `os.replace` is the atomic step; the absence of a point inside it is the guarantee rather than a gap in the coverage.

### Cross-filesystem: getting a second filesystem honestly

`tests/integration/test_cross_filesystem.py` needs two real mounts, because a monkeypatched device id proves the branch is reachable and not that the kernel does what the branch assumes. The acquisition ladder takes the first candidate on a different device than the test's temporary directory, and writable:

| Rung | Candidate | Note |
|---|---|---|
| `1 ($PDF_TOOLKIT_TEST_XDEV_DIR)` | the operator's explicit override | |
| `2 (/dev/shm)` | a tmpfs present on effectively every Linux, including GitHub's `ubuntu-*` runners | the rung this host resolves at |
| `3 ($HOME)` | | |
| `4 (/var/tmp)` | | |
| `5 (/run/user/$UID)` | | |

**Five rungs, enumerated discretely — corrected by `PDF-19` on 2026-09-02.**
This document collapsed rungs 3 to 5 onto one line from `PDF-04`'s landing
until then, while `_ladder()` (`tests/integration/test_cross_filesystem.py:53-60`)
always enumerated five. That matters because the fixture *prints* the rung it
resolved at — `[PDF-04] second filesystem from ladder rung 2 (/dev/shm): /dev/shm`
— and the skip reason names all five, so an operator reading a three-rung list
would not recognise the message they were handed.

```bash
PDF_TOOLKIT_TEST_XDEV_DIR=/dev/shm uv run pytest tests/integration/test_cross_filesystem.py -v
```

**If no rung succeeds, the behaviour is asymmetric on purpose.** On Linux the arm *fails*, naming the ladder — a Linux run that quietly skipped it would be a green run that proved nothing, which is the failure mode this whole document exists to prevent. On any other platform it skips, with that reason printed.

### The `--dry-run` purity primitive

`tests/fs_snapshot.py` photographs every root before and after a run — inode, mode, size, mtime, content hash and symlink target — and fails on any difference. `atime` is excluded (a dry run legitimately reads); directory mtime is included (it is the only thing that sees a create-then-delete inside the run). `$TMPDIR` and `$HOME` are redirected into the test's own temporary directory and both are snapshot roots, which is what turns "the temp directory gained nothing" into a whole-tree comparison instead of a glob racing every other process on the machine. `tests/test_cli_contract.py`'s `C9`/`C10` checks consume this primitive directly rather than re-deriving it.

**Nine** planted mutations prove the comparator can fail, and a non-dry-run control proves the guard is live: zero differences has to mean *the run wrote nothing*, never *the run never happened*. (Nine, not the six this section and both instrument docstrings claimed until `PDF-19` counted them on 2026-09-02: the six named `control_one`…`control_six`, plus create-then-delete caught only by directory `mtime`, symlink retarget, and `assert_unchanged` naming every difference.)

`PDF-19` additionally **ablated** each compared dimension and recorded which control goes blind, because re-running a passing control only proves it still passes. `Entry` carries seven fields and six are compared — `dev` is recorded and never compared. Removing `ino` blinds the identical-content-replacement control and nothing else; removing directory traversal, or `mtime_ns`, blinds the create-then-delete control; *adding* `atime` reds the exclusion control and five legitimate dry-run purity arms at once, which is the measurement that turns the exclusion from an omission into a decision.

### The write-chokepoint / import-boundary tests

`tests/test_import_boundaries.py` is shared and append-only, and it now carries **five** sections rather than the three it launched with: Section 1 (PDF-04) walks the AST of every file under `src/` and fails on any filesystem-mutating call outside `src/pdf_toolkit/safety/atomic.py`; Section 2 (PDF-05) does the same for engine imports outside `adapters/` and spawns outside the one subprocess chokepoint; Section 3 (PDF-06) does the same for `typer`/`click` imports below `cli/` (`PLAN.md` §10, D-03); Section 4 (B-093) forbids a `dry_run`-guarded confirmation-gate call; Section 5 (PDF-18) forbids a local filesystem-tier refusal construction under `ops/`. Every section's allowlists are empty, a test asserts they are empty, and a stale entry — one that no longer resolves to a real call site — fails the test. Planted violations prove each walk bites, and a negative-control test proves none of the walks is a text grep.

**All fourteen §D7 call groups now carry a planted violation** (`PDF-19`, 2026-09-02). `PDF-04` shipped five plants covering five groups; the other nine had never been observed to red. `D7_GROUP_PLANTS` maps each group to the plants that red it, and a test asserts the map has no empty group and names no plant `PLANTED` does not carry — so the coverage claim is executed rather than written down.

Two exemption registers live beside the two write allowlists, in the same `# reason:`-per-entry idiom with stale-entry detection: `SAFETY_INNER_ALLOW`/`ALLOWED_WRITE_SITES` (Section 1, both empty) and `GATE_EXEMPT` (Section 4). `GATE_EXEMPT` exists because Section 4's walk forbids a *guarded* confirmation call and structurally cannot see an *absent* one: every `cli/cmd_*.py` module must either call `require_confirmation` or carry an exemption naming its reason. Four of its twelve entries are the deferred question **B-022 ≡ B-045** — `extract`, `rasterize`, `tables` and `text` are `{PDF...}` multi-input producers consuming output-directory flags, so `bulk` is reachable for them and nothing gates it. That is recorded here, not decided here.

### Expected visible skips (safety-spine arms only)

| Configuration | Skips from these arms |
|---|---|
| Linux, engines installed or absent | **0.** Re-measured by `PDF-19` on 2026-09-02 over the eight safety-spine files (`tests/unit/test_atomic_writer.py`, `test_safety_paths.py`, `test_confirm.py`, `test_tempnames.py`, `tests/integration/test_atomic_crash.py`, `test_cross_filesystem.py`, `test_purity_primitive.py`, `tests/test_import_boundaries.py`): **259 passed, 0 skipped, 1 xfailed** with `-rs`. The one `xfail` is not a skip — it is the strict marker on `test_a_positional_mode_on_path_open_is_a_violation`, which turns RED the day the §D7 row-2 blind spot is closed. The cross-filesystem ladder resolved at rung `2 (/dev/shm)`, device 27 against `/tmp`'s 66308. |
| macOS | **5** — the cross-filesystem arms that need a second mount skip together, with the ladder printed. The sixth arm in that file asserts the *absence* of a warning on one filesystem and always runs. Inherited from `PDF-04`'s landing and **not** re-measured: no macOS host is available to this cycle (`decision.md` X-153). |
| Any platform, `uid 0` | **1** — the unwritable-destination arm, since directory permissions cannot cause a write to fail for root. |
| Filesystem without hard links | **1** — the sidecar-keeps-the-inode arm. |

## What the other suites cover

- **`tests/test_cli_spine.py`** — the command surface and its exit codes, the exit-code constants themselves, the three renderers and their stream discipline, the structured error shape, global-flag precedence across both declaration levels, the mutually exclusive flag pairs, and the startup budget (`PLAN.md` §12 R-13 — `tests/test_cli_contract.py` deliberately does not duplicate this; see its module docstring).
- **`tests/test_docs_antirot.py`** — that the documentation cannot silently rot: one phase line per prime document, no specification identifiers or counts embedded in them, and every `make` target mentioned in the documentation actually existing in the `Makefile`.
- **`tests/test_license_policy.py`** — the `PLAN.md` §7.2 forbidden-name AST walk (imports, dynamic imports, subprocess `argv[0]`, `shutil.which`).

## Skips are visible, never silent

Two classes of test cannot always run:

- **Engine-absent tests.** Some engines are system binaries rather than Python wheels, so they can legitimately be missing on a given machine or CI leg.
- **Real-document tests.** The generated fixtures prove the *contract*; they cannot prove the tool survives documents produced by other software. Those arms read an operator-provided corpus that lives outside the repository and is never committed.

In both cases the rule is the same and it is not negotiable: **a test that cannot run reports as a skip, with a reason.** It never passes silently. A green run that proved nothing is worse than a red one, because it is believed.

Deleting or weakening a failing test so the suite turns green is never an acceptable fix. If a test cannot pass for a reason outside the change, say so explicitly in the change's description and leave the test in place.

## Determinism

Every test writes into pytest's own temporary directory and never into the repository tree (enforced, not just intended — see the working-tree guard above). Nothing that a test asserts depends on wall-clock timing, on the order tests run in, or on which machine runs them — with one deliberate exception: the startup-budget test measures real elapsed time. It takes the **fastest** of several runs rather than the mean, so scheduler noise cannot turn it red while a genuine regression still will.

## The coverage floor — status after the PDF-06 fix-forward commit

`--cov-fail-under=85` (`make cover`, part of `make ci`) is measured on
`src/pdf_toolkit`. **At PDF-06's original landing commit this floor read
71.29%, not 85%.** That number was a measurement artifact, not a real gap:
`tests/registry.py::run_cli`, `tests/test_doctor.py`, `tests/test_info.py`
and `tests/test_cli_spine.py` drive the CLI exclusively through
`subprocess.run`, and `[tool.coverage.run]` carried no `patch = ["subprocess"]`
— so coverage.py measured the parent pytest process only, and every
CLI-reached line executed in an unmeasured child. Twelve hand invocations run
in-process moved `cli/cmd_doctor.py` 32%→82%, `cli/cmd_info.py` 26%→76%,
`ops/inspect.py` 30%→90%, `output/json.py` 43%→90%, `cli/main.py` 70%→88% —
the code was already exercised; the instrument could not see it.

The fix-forward commit turns on `[tool.coverage.run] patch = ["subprocess"]`
(rides the `coverage`-installed `a1_coverage.pth` hook, which is inert until
`COVERAGE_PROCESS_CONFIG`/`COVERAGE_PROCESS_START` is set — `patch =
["subprocess"]` is what sets it) and `parallel = true` (so a spawned child
gets its own `.coverage.<host>.<pid>.<rand>` instead of every child
clobbering the same data file; pytest-cov's own `combine()` step, which runs
unconditionally at session end, merges them back into one report). Every
subprocess call site in this suite already inherits the full parent
environment by default (`env=None` → `subprocess.run` inherits `os.environ`),
so the propagation needed no test-helper changes — the one exception,
`tests/unit/test_subprocess_util.py`, deliberately builds a scrubbed
from-scratch `env=` because it is testing `subprocess_util`'s own env
handling, not the CLI, and stays scrubbed on purpose. `make cover`'s
`COVERAGE_FILE` is pinned to an absolute path (`$(CURDIR)/.coverage`) so a
subprocess-measured child's data file — several tests spawn the CLI with
`cwd` inside a temp directory — always lands next to the parent's, never
inside a purity-snapshot root.

**Re-measured total: 91.29%, engines present — the floor is met.** `ci.yml`'s
`engines-present` job now enforces `--cov-fail-under=85` as well (the
`without-engines` job does not, matching Design §6's "adapters/ get a lower
bar where an engine is absent" via configuration, not via `omit`). `fail_under`
was never touched — it was 85 before this fix and stays 85 after it — and no
`omit` of anything under `src/pdf_toolkit/` was ever added.

## The coverage floor — status after the B-034 fix-forward commit

PDF-06's `patch = ["subprocess"]` made the floor honest; it also made the
local `make cover`/`make ci` unrunnable in practice. On this project's dev
host, `[tool.coverage.run] branch = true` forces coverage.py's classic
ctrace tracer (Python's `sys.monitoring` core, `COVERAGE_CORE=sysmon`,
cannot measure branches on the Python/coverage.py combination this project
runs), and ctrace tracing `adapters/pypdf_structure.py` — a pure-Python PDF
parser and the primary `StructureEngine` — is catastrophically slow: a
single isolated `info` subprocess call measured 0.245s uninstrumented vs
15.8s instrumented (~65x); the `info`/`doctor`/`cli_contract` band (84
tests) measured 14.49s vs 544.59s (~37.6x). CI was never affected — the
same suite ran in ~86s on Python 3.13 in the `engines-present` job — which
is itself part of the evidence: this is not a fixed per-subprocess coverage
tax (`version`/`doctor` calls, which never reach the parser, stay near
baseline) and not the `.coverage.*` combine step (the single-call isolation
reproduces the full multiplier with no combine involved).

The fix: `[tool.coverage.run] branch = true` → `branch = false` + `core =
"sysmon"`. Turning off branch tracking alone does **not** fix it (still
15.8s for the isolated call under the default ctrace core) — the win is
specifically `core = "sysmon"` becoming reachable once branch tracking is
off: the same isolated call drops to 0.34s (~46x faster) and the same
84-test band drops to 21.51s end-to-end (~25x faster). This is a single
shared `pyproject.toml` section read by both pytest-cov's parent-process
measurement and every subprocess-patched child, on both local and CI, so
there is no local/CI divergence to document — both apply the identical
config.

**This is line coverage, not branch coverage**, and that is a real,
intentional trade-off, not an oversight: line coverage credits a branch's
line as covered the moment either arm of it executes once, so it reads
higher for the same code — the 84-test band alone moved from 66.24%
(branch) to 71.49% (line) under identical tests. `--cov-fail-under=85` is
unchanged. **Re-measured total: 93.79%, engines present — the floor is
met**, comfortably above the unchanged 85% threshold. `make cover` (full
suite, instrumented) now completes in ~77s (was ~571s); `make ci` end to
end completes in ~80s. Re-enabling branch coverage is a legitimate future
follow-up once coverage.py/CPython ship a version combination whose
`sys.monitoring` core supports branch measurement — see the comment above
`[tool.coverage.run]` in `pyproject.toml`.
