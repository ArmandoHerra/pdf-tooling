# Testing

## Running the suites

```bash
uv sync
make test          # everything
make test-e2e      # only the subprocess-level CLI tests
make cover         # the suite under coverage, against the project's floor
```

`make cover` is deliberately **not** part of `make ci`. The coverage floor becomes a gate once the fixture corpus and the per-verb contract harness exist; enforcing it against a spine with one placeholder verb would measure nothing and block everything.

Individual files and selections work as usual:

```bash
uv run pytest tests/test_cli_spine.py -q
uv run pytest -k renderer -q
uv run pytest -m e2e -q
```

## What the current suites cover

- **`tests/test_cli_spine.py`** — the command surface and its exit codes, the exit-code constants themselves, the three renderers and their stream discipline, the structured error shape, global-flag precedence across both declaration levels, the mutually exclusive flag pairs, and the startup budget.
- **`tests/test_docs_antirot.py`** — that the documentation cannot silently rot: one phase line per prime document, no specification identifiers or counts embedded in them, and every `make` target mentioned in the documentation actually existing in the `Makefile`.

## Safety-spine test arms

The write chokepoint's guarantees are the ones a user acts on, so each of them is *demonstrated* by a run rather than asserted in prose. Three of those arms need something the ordinary suite does not, and all three are described here so that a red — or a skip — can be read without opening the test.

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

1. `$PDF_TOOLKIT_TEST_XDEV_DIR` — the operator's explicit override.
2. `/dev/shm`
3. `$HOME`, then `/var/tmp`, then `/run/user/$UID`

```bash
PDF_TOOLKIT_TEST_XDEV_DIR=/dev/shm uv run pytest tests/integration/test_cross_filesystem.py -v
```

**If no rung succeeds, the behaviour is asymmetric on purpose.** On Linux the arm *fails*, naming the ladder — a Linux run that quietly skipped it would be a green run that proved nothing, which is the failure mode this whole document exists to prevent. On any other platform it skips, with that reason printed.

### The `--dry-run` purity primitive

`tests/fs_snapshot.py` photographs every root before and after a run — inode, mode, size, mtime, content hash and symlink target — and fails on any difference. `atime` is excluded (a dry run legitimately reads); directory mtime is included (it is the only thing that sees a create-then-delete inside the run). `$TMPDIR` and `$HOME` are redirected into the test's own temporary directory and both are snapshot roots, which is what turns "the temp directory gained nothing" into a whole-tree comparison instead of a glob racing every other process on the machine.

Six planted mutations prove the comparator can fail, and a non-dry-run control proves the guard is live: zero differences has to mean *the run wrote nothing*, never *the run never happened*.

### The write-chokepoint import-boundary test

`tests/test_import_boundaries.py` walks the AST of every file under `src/` and fails on any filesystem-mutating call outside `src/pdf_toolkit/safety/atomic.py`. Its two allowlists are empty, a test asserts they are empty, and a stale entry — one that no longer resolves to a real call site — fails the test. Planted violations prove the walk bites. The file is shared and append-only: later specs add their own section and reuse its machinery.

### Expected visible skips

| Configuration | Skips from these arms |
|---|---|
| Linux, engines installed or absent | **0.** Every arm above runs; the cross-filesystem ladder reaches `/dev/shm`. |
| macOS | **5** — the cross-filesystem arms that need a second mount skip together, with the ladder printed. The sixth arm in that file asserts the *absence* of a warning on one filesystem and always runs. |
| Any platform, `uid 0` | **1** — the unwritable-destination arm, since directory permissions cannot cause a write to fail for root. |
| Filesystem without hard links | **1** — the sidecar-keeps-the-inode arm. |

Read them with `-rs`. A skip here is information, not noise: it says which guarantee this run did *not* check.

## Markers

| Marker | Selects |
|---|---|
| `e2e` | Tests that run the installed console script as a subprocess. Slower, and the only ones that measure real process startup. |

Run `uv run pytest --markers` for the registered list.

## Skips are visible, never silent

Two classes of test cannot always run:

- **Engine-absent tests.** Some engines are system binaries rather than Python wheels, so they can legitimately be missing on a given machine or CI leg.
- **Real-document tests.** The generated fixtures prove the *contract*; they cannot prove the tool survives documents produced by other software. Those arms read an operator-provided corpus that lives outside the repository and is never committed.

In both cases the rule is the same and it is not negotiable: **a test that cannot run reports as a skip, with a reason.** It never passes silently. A green run that proved nothing is worse than a red one, because it is believed.

Deleting or weakening a failing test so the suite turns green is never an acceptable fix. If a test cannot pass for a reason outside the change, say so explicitly in the change's description and leave the test in place.

## Determinism

Every test writes into pytest's own temporary directory and never into the repository tree. Nothing that a test asserts depends on wall-clock timing, on the order tests run in, or on which machine runs them — with one deliberate exception: the startup-budget test measures real elapsed time. It takes the **fastest** of several runs rather than the mean, so scheduler noise cannot turn it red while a genuine regression still will.
