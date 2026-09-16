"""PDF-74 — the argument VALUE-SHAPE dimension, at the CLI tier.

**The finding this module exists to make impossible.** `PDF-64` measured a
`--dry-run` with a relative, not-yet-existing `--out-dir` crashing with a raw
`ValueError`, exit 1, zero bytes on stdout, on **all eleven** verbs that take
one, while the identical argv without `--dry-run` succeeded on all eleven —
and 4,450 tests were green over it, including the contract row added three
specs earlier *specifically* to assert that a dry run predicts the real run's
exit code. Nothing saw it because every matrix in this suite is built over
dimensions enumerable from the command tree, and **there is no dimension for
the shape of the value a user types**: 245 of 249 argument values in the suite
are `str(tmp_path / …)`, always absolute, and pytest makes `tmp_path`
absolute.

So the load-bearing quantity is not "how many spellings exist" but **the
maximum, over all `(verb, flag)` cells, of the number of distinct spellings
driven at that cell**. It was **one** everywhere before `PDF-64`, **two** on
eleven cells after it, and this module moves it to **eight** — measured by
`tests/test_derived_dimensions.py`'s collapse tie rather than re-grepped.

**The cross.** `registry.path_spellings()` × `registry.destination_flag_cases()`
× {dry, real}: 8 × 30 = 240 cells, 480 subprocess runs. The population is
DERIVED off each leaf's own `consumes` declaration and is **eleven at
`--out-dir` including `split`** — `out_dir_batch_verbs()` is a TEN-verb answer
for this property and is unfit, because its step-2 operand-arity filter is a
filter value shape does not license. That is not prose here: it is asserted, by
name, below.

**Why the cells drive dry and real SEPARATELY** rather than through
`dryreal.dry_and_real`. The purity oracle has to observe the filesystem after
the dry run **alone**, never after a pair whose second half would legitimately
create the destination, and a helper that returns only once both have run
cannot express that. `tests/integration/test_out_dir_planning.py`'s own C cell
makes the same separation for the same reason and says so in a comment; this
module consumes `prediction()` and `real_envelope()` from the same helper
module, which is where the value of `tests/dryreal.py` actually is (a legible
failure when a dry run prints nothing, instead of a bare `JSONDecodeError`).

**What this module FOUND, and what became of it.** Driving H1/H2 before
writing a line of matrix surfaced a real product defect on both destination
flags: the product did not agree with itself about whether a destination's `~`
is expanded. `PDF-74` filed it rather than fixing it — `src/` is byte-untouched
by that spec, deliberately, because a spec whose new matrix reds and whose same
commit fixes the product cannot show which change moved the needle — and pinned
it with twenty-eight `strict=True` xfails so it could not go quiet.

**`PDF-80` fixed it and those pins are gone** (ledger `1e824f5f74`, ruled
`X-732`). The thirty tilde cells are now ordinary parametrizations that must
PASS, which is strictly stronger than the pin was: `strict=True` proved only
that *something* changed, while a passing cell proves the contract. Two oracles
this matrix was blind to arrived with the retirement and are asserted at every
cell — **disclosure** and **real-run purity** — because a crash-only fix would
have left `bytes_after: null` beside a real file, and every one of the five
original oracles passed on that.

**If `PDF-76` consolidates the `POPULATIONS` roster, this is the module to
consume.** Its floors are carried here, in the same three-field shape, rather
than added to `tests/test_cli_contract.py`'s roster — that control reads only
its own module's source (`module_level_tuple_names(Path(__file__).read_text())`),
so a row naming a population declared here would be a roster entry guarding
nothing, which is precisely the hand-maintained-list-beside-a-live-module shape
the roster exists to end.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import prediction, real_envelope  # noqa: E402
from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from registry import (  # noqa: E402
    DESTINATION_VALUE_FLAGS,
    FILTER_MEANINGS,
    LICENSED_POPULATION_FIELDS,
    OUTPUT_FLAG_INVOCATIONS,
    TILDE_SPELLING,
    PathSpelling,
    destination_flag_cases,
    discover_verbs,
    out_dir_batch_verbs,
    path_spellings,
    population_fields,
    rerun_hint,
    run_cli,
    spelled_destination,
)

# --------------------------------------------------------------------------- #
# The two axes, CONSUMED. Neither is re-listed here, and an AST scan over the
# whole `tests/` tree enforces that for the spelling axis
# (`tests/test_derived_dimensions.py`).
# --------------------------------------------------------------------------- #

SPELLINGS: Final[tuple[PathSpelling, ...]] = path_spellings()

VERB_FLAG_CASES: Final[tuple[tuple[str, str], ...]] = destination_flag_cases()

#: The full cross, one entry per CELL. One test node per cell, covering both
#: modes, is deliberate: the red control's predicted red set is derived as
#: `{(verb, "--out-dir", spelling) : spelling.anchoring == "relative"}` and is
#: compared for SET EQUALITY against observed leaves, which only works when a
#: cell is a leaf.
CASES: Final[tuple[tuple[str, str, PathSpelling], ...]] = tuple(
    (verb, flag, spelling) for verb, flag in VERB_FLAG_CASES for spelling in SPELLINGS
)


def _cell_id(verb: str, flag: str, spelling: PathSpelling) -> str:
    return f"{verb.replace(' ', '-')}-{flag.lstrip('-')}-{spelling.id}"


# --------------------------------------------------------------------------- #
# The defect this matrix found on its first run, and the shape of its repair.
#
# MEASURED at PDF-74, both commands, from a scratch directory:
#
#   $ cd "$SCRATCH" && HOME="$SCRATCH/home" pdftooling extract in.pdf \
#       --out-dir '~/out' --dry-run -o json        ->  rc 0, would_exit 0
#   $ cd "$SCRATCH" && HOME="$SCRATCH/home" pdftooling extract in.pdf \
#       --out-dir '~/out' -o json                  ->  rc 1, and a literal '~'
#                                                      DIRECTORY in the cwd
#
# RE-MEASURED at PDF-80 against the same binary, and it was WORSE than filed in
# two ways nothing upstream had named. (1) A FOURTH SEAM: `plan_output_set`'s
# own `out_dir.exists()` read the raw spelling, so a dry run over a `~`
# `--out-dir` whose EXPANDED form exists skipped the writability tier entirely
# and predicted 0 for a real run that exits 1 -- while the ABSOLUTE spelling of
# that same directory mirrored exactly. (2) A FOURTH SHAPE: when the expanded
# `--out-dir` already exists, the eleven `--out-dir` cells stopped returning a
# clean error envelope and started returning a raw traceback with 0 bytes of
# stdout AND the artefact written to `$HOME` undisclosed.
#
# THE ROOT CAUSE, and it is not what the pin text said. `canonical()` was
# always the single correct expansion point; the defect was twenty-three sites
# asking the filesystem about a path `canonical()` was never given -- two in
# `safety/atomic.py` (`_ensure_out_dir`'s `mkdir`, `plan_output_set`'s
# existence test) and twenty-one in `ops/`, each one stat()-ing the spelling
# handed to an `AtomicWriter` whose `.destination` was the canonical path
# `os.replace` had just written to. So the fix ADDS NO EXPANSION: the two
# `safety/` seams consume one `canonical()` call made at `plan_output_set`'s
# boundary, and the twenty-one readbacks consume `AtomicWriter.bytes_written`.
# `tests/test_destination_canonicalization_boundary.py` is the rule that keeps
# `ops/` at ZERO destination filesystem calls.
#
# WHAT THE RETIREMENT HAD TO BE, and it was not the marks. `PDF-74` derived pin
# membership from the DECLARATION (`set(consumes[verb]) != {"--output"}`), not
# from behaviour, so after the fix that derivation still returned twenty-seven
# and a GREEN test named "the pinned tilde membership is tied to the
# measurement" would have asserted that twenty-seven cells are defective when
# none is. The population and its two guards were the retirement; the marks
# were the easy half. What replaces the pin is below, asserting the properties
# of the PRODUCT (30 / 11 / 19) that must outlive the defect.
#
# ONE THING THIS ITEM DID NOT FIX, recorded so a reader does not read its
# absence as a failure. `linearize` was silent on BOTH channels, not just
# stdout, because `adapters/pikepdf_structure.py`'s `check_linearization(
# io.StringIO())` assigns `sys.stderr = <that buffer>` and never restores it.
# That is a different root cause in a different layer, filed as PDF-80 E6 and
# allocated `PDF-81` (ledger `333f0b182f`). PDF-80 removed the TRIGGER, not the
# silence: `linearize` now exits 0 and prints its payload on stdout, which was
# never stolen -- but any OTHER post-engine failure on that verb is still
# silent on stderr, and that is PDF-81's, not evidence against this matrix.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# The builder. Constraint 2 of this item, and the assertion IS the item in
# miniature: an absolute value smuggled into a relative row PASSES -- on the
# pre-fix binary, forever. It is not a test that fails loudly; it is a test
# that silently stops testing, which is the failure `AUDIT.md` 5.1 found
# across 245 values.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Cell:
    """One built `(verb, flag, spelling)` invocation and everything it denotes."""

    verb: str
    flag: str
    spelling: PathSpelling
    argv: list[str]
    value: str
    cwd: Path
    env: dict[str, str]
    anchor: Path
    roots: tuple[Path, ...]
    denoted: Path


def destination_index(argv: list[str], flag: str) -> int:
    """Where *flag*'s VALUE sits in *argv*.

    Both spellings of the short flag are accepted because the registered
    invocations use the one a user would type: `OUTPUT_FLAG_INVOCATIONS`'
    `--output` rows all spell it `-O`. Reading the position out of the built
    argv is what keeps the per-verb file EXTENSION correct (`.csv` for
    `tables`, `.txt` for `text`) without a table of them here.
    """
    tokens = ("--output", "-O") if flag == "--output" else (flag,)
    for index, token in enumerate(argv):
        if token in tokens:
            return index
    raise AssertionError(f"{flag} is not present in the registered invocation {argv!r}")


def assert_anchoring(cell: Cell) -> None:
    """The guard that makes every relative cell in this matrix real.

    Four conditions, because the smuggle takes four shapes and the third is the
    one that actually happens (a `str(anchor / leaf)` sliding into a relative
    row through a copy-paste).
    """
    spelling = cell.spelling
    label = f"{cell.verb} {cell.flag} [{spelling.id}]"
    if spelling.anchoring == "relative":
        assert not os.path.isabs(cell.value), (
            f"{label}: the row declares anchoring={spelling.anchoring!r} and rendered an "
            f"ABSOLUTE value {cell.value!r} -- an absolute value in a relative row passes on "
            "the buggy binary, forever, which is the failure this matrix exists to remove"
        )
        assert not cell.value.startswith(os.sep), (
            f"{label}: rendered {cell.value!r}, which begins with {os.sep!r}"
        )
        assert str(cell.anchor) not in cell.value, (
            f"{label}: rendered {cell.value!r}, which carries the anchor's absolute prefix "
            f"{str(cell.anchor)!r} as a substring -- this is the shape the smuggle takes"
        )
    else:
        assert os.path.isabs(cell.value), (
            f"{label}: the row declares anchoring={spelling.anchoring!r} and rendered a "
            f"RELATIVE value {cell.value!r}"
        )
    if spelling.id == TILDE_SPELLING:
        assert cell.value.startswith("~"), f"{label}: rendered {cell.value!r}, not a ~ spelling"
        home = Path(cell.env["HOME"])
        assert home.is_relative_to(cell.anchor), (
            f"{label}: $HOME is {home}, which is not under the test's own root {cell.anchor} "
            "-- a tilde cell that expanded into the real home directory would write there"
        )
    assert cell.cwd == spelling.cwd(cell.anchor), (
        f"{label}: the cell would run from {cell.cwd}, not the row's own declared anchor "
        f"{spelling.cwd(cell.anchor)} -- a relative value driven from the wrong directory "
        "measures nothing"
    )


def build_cell(verb: str, flag: str, spelling: PathSpelling, corpus: Any, anchor: Path) -> Cell:
    """The one place a cell is built, asserting its own anchoring before it returns."""
    anchor.mkdir(parents=True, exist_ok=True)
    env, roots = redirected_environment(anchor)
    spelling.prepare(anchor)
    registered = OUTPUT_FLAG_INVOCATIONS[(verb, flag)](corpus, anchor)
    index = destination_index(registered, flag)
    leaf = Path(registered[index + 1]).name
    value = spelling.render(anchor, leaf)
    cell = Cell(
        verb=verb,
        flag=flag,
        spelling=spelling,
        argv=[*registered[: index + 1], value, *registered[index + 2 :]],
        value=value,
        cwd=spelling.cwd(anchor),
        env=env,
        anchor=anchor,
        roots=roots,
        denoted=spelled_destination(spelling, anchor, leaf, home=Path(env["HOME"])),
    )
    assert_anchoring(cell)
    return cell


# --------------------------------------------------------------------------- #
# The oracles, derived from the contract rather than chosen.
# --------------------------------------------------------------------------- #


def path_prefixes(value: str) -> tuple[str, ...]:
    """*value* normalized, and its immediate parent -- at most two entries.

    A refusal legitimately names the DIRECTORY component rather than the whole
    destination: `--output` with an absent intermediate directory refuses with
    ``destination directory does not exist: missing``, naming the directory that
    does not exist. Accepting that one step up is correct; accepting further
    would eventually accept ``/`` or ``..`` and stop discriminating, which is
    why the walk is capped at one component rather than run to the root.
    """
    normalized = os.path.normpath(value)
    parent = str(Path(normalized).parent)
    if parent in (".", os.sep, normalized):
        return (normalized,)
    return (normalized, parent)


def assert_no_traceback(completed: Any, cell: Cell, mode: str) -> None:
    combined = (completed.stdout or "") + (completed.stderr or "")
    assert "Traceback (most recent call last)" not in combined, (
        f"{cell.verb} {cell.flag} [{cell.spelling.id}] {mode}: a raw traceback reached the "
        f"user. Repro: {rerun_hint([cell.verb, *cell.argv])} (cwd={cell.cwd})\n{completed.stderr}"
    )


def destination_strings(completed: Any) -> tuple[str, ...]:
    """Every string in *completed*'s payload that names the DESTINATION.

    DELIBERATELY NOT THE WHOLE PAYLOAD, and the narrowing was forced by a
    measurement rather than chosen: several registered invocations build their
    own operand inside the same directory this matrix anchors on (`compose`'s
    JPEG, `create`'s text file, `convert`'s source, `decrypt`/`encrypt`'s
    password file), so the `input` field legitimately carries the anchor's
    absolute prefix. A whole-payload scan reported 38 of those operands as
    absolutized destinations -- a false positive that would have been "fixed"
    by weakening the assertion that matters.
    """
    text = completed.stdout or ""
    if not text.strip():
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    found: list[str] = []
    error = payload.get("error")
    if isinstance(error, dict):
        found.extend(str(error.get(key) or "") for key in ("path", "message"))
    for item in payload.get("items") or ():
        if isinstance(item, dict) and item.get("output") is not None:
            found.append(str(item["output"]))
    return tuple(entry for entry in found if entry)


def assert_echo(completed: Any, cell: Cell, mode: str, *, whole: bool) -> None:
    """The payload renders the spelling the user typed, never an absolutized one.

    Two halves, and the first is the one the parameter-swap mutant reds:

    * a relative cell's destination fields must NEVER carry the anchor's
      absolute prefix;
    * the spelling itself must be there, normalized by nothing more than
      `os.path.normpath`. AC8 states that `./out` renders unchanged; MEASURED,
      it renders as `out`, because `Path("./out")` collapses the leading `./`
      at construction and every echo in this product goes through `Path`. The
      same is true of a trailing separator. Recorded here rather than asserted
      away: `normpath` is the exact and only normalization observed, at all
      eight spellings.
    """
    label = f"{cell.verb} {cell.flag} [{cell.spelling.id}] {mode}"
    fields = destination_strings(completed)
    assert fields, (
        f"{label}: the payload named no destination at all, so there is nothing for the echo "
        f"oracle to read:\n{(completed.stdout or '')[:800]}"
    )
    if cell.spelling.anchoring == "relative":
        for field in fields:
            assert str(cell.anchor) not in field, (
                f"{label}: a destination field carries the absolutized form -- "
                f"{field!r} contains {str(cell.anchor)!r}, while the user typed "
                f"{cell.value!r}. The destination is echoed as the user spelled it; only "
                "the internal geometry may use the absolutized value"
            )
    candidates = path_prefixes(cell.value)
    wanted = candidates[:1] if whole else candidates
    assert any(candidate in field for field in fields for candidate in wanted), (
        f"{label}: the payload's destination field(s) {list(fields)} render none of "
        f"{list(wanted)} -- the user's own spelling {cell.value!r} did not survive"
    )


def landed_at(named: str, cell: Cell) -> Path:
    """Where *named* -- a destination string the payload echoed -- actually is.

    Built by SUBSTITUTION against the cell's own two values rather than by a
    second copy of the expansion rule: `cell.value` is what the user typed and
    `cell.denoted` is what `registry.spelled_destination` says that denotes, so
    an echoed string beginning with the former is rebased onto the latter.
    Re-implementing `~`-expansion here would put a second definition of the
    rule beside the one in `tests/registry.py`, and two definitions of one
    expansion rule that can disagree is the entire subject of this item.
    """
    spelled = str(Path(cell.value))
    if named == spelled:
        return cell.denoted
    if named.startswith(spelled + os.sep):
        return cell.denoted / named[len(spelled) + 1 :]
    if os.path.isabs(named):
        return Path(named)
    return Path(cell.cwd) / named


def undisclosed_items(payload: Any, cell: Cell) -> tuple[str, ...]:
    """Items that SUCCEEDED, named a destination that exists, and reported no size.

    **The oracle the existing five are blind to, and the blindness was
    measured.** `create`, `compose` and `merge` guarded their readback with
    ``output.stat().st_size if output.exists() else None``, which converted the
    crash the other sixteen verbs had into a FALSE FIELD: at a `~` spelling
    they exited 0 and published ``bytes_after: null`` for a file that exists and
    is non-empty, while the identical argv at an absolute spelling published
    the real byte count for a byte-identical file. Mirror held, echo held,
    effect held (the bytes really did land at `$HOME`), purity held, and there
    was no traceback -- so all three cells were UNPINNED and green, and a
    crash-only fix would have left this limb of the defect shipping.
    ``ItemResult.bytes_after`` is part of the structured shapes `README.md:161`
    freezes as public API from v1.0.0; its value may not depend on the SPELLING
    of the destination.

    Deliberately narrow, in three ways that are each a "does not fire" half:
    a DRY item reports ``null`` by design and is skipped via the envelope's own
    ``dry_run``; a REFUSED or failed item reports ``null`` by design
    (`ops/raster.py`'s per-page failure path is exactly that shape) and is
    skipped on ``ok``/``exit_code``; and an item whose destination is not on
    disk has nothing to disclose.
    """
    if not isinstance(payload, dict) or payload.get("dry_run"):
        return ()
    found: list[str] = []
    for item in payload.get("items") or ():
        if not isinstance(item, dict):
            continue
        if item.get("ok") is not True or item.get("exit_code") not in (0, None):
            continue
        if item.get("bytes_after") is not None:
            continue
        named = item.get("output")
        if named is None:
            continue
        landed = landed_at(str(named), cell)
        if landed.is_file() and landed.stat().st_size > 0:
            found.append(f"{named} -> {landed} ({landed.stat().st_size} bytes on disk)")
    return tuple(found)


def assert_disclosure(completed: Any, cell: Cell) -> None:
    """A real run that wrote bytes says how many."""
    text = completed.stdout or ""
    if not text.strip():
        return
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return
    undisclosed = undisclosed_items(payload, cell)
    assert undisclosed == (), (
        f"{cell.verb} {cell.flag} [{cell.spelling.id}] real: exited 0 and reported "
        f"bytes_after: null for {list(undisclosed)} -- file(s) that exist and are "
        "non-empty. bytes_after is part of the structured shapes README.md freezes as "
        "public API; a published field whose value depends on the SPELLING of the "
        "destination is the half of this defect a crash-only fix leaves behind"
    )


def literal_tilde_entries(root: Path) -> tuple[str, ...]:
    """Every directory entry literally NAMED `~` anywhere under *root*.

    Matched on `Path.name` rather than through a glob pattern so the character
    is compared as data, never interpreted. The real run used to create one of
    these -- `_ensure_out_dir`'s `mkdir` ran on the raw spelling -- moments
    before printing a message asserting that path does not exist, and the
    shipped purity oracle could not see it because it snapshots after the DRY
    run alone.
    """
    return tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.name == "~")
    )


def assert_real_run_purity(cell: Cell) -> None:
    """The sharpest single sentence of the `--out-dir` shape, as an assertion."""
    strays = literal_tilde_entries(cell.anchor)
    assert strays == (), (
        f"{cell.verb} {cell.flag} [{cell.spelling.id}] real: the run created "
        f"{list(strays)} -- a directory entry literally named '~', at a path the user "
        f"never named, under {cell.anchor}. A destination is expanded by exactly one "
        "vocabulary (safety/paths.py::canonical) or by none; a mkdir on the raw "
        "spelling is the product disagreeing with the writer standing beside it"
    )


# --------------------------------------------------------------------------- #
# The matrix. 240 cells, 480 runs, dry and real driven separately so the purity
# oracle can land BETWEEN them.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("verb", "flag", "spelling"),
    [pytest.param(*case, id=_cell_id(*case)) for case in CASES],
)
def test_the_value_shape_cell_holds(
    verb: str, flag: str, spelling: PathSpelling, corpus: Any, tmp_path: Path
) -> None:
    """Five oracles at one `(verb, flag, spelling)` cell, in both modes.

    * **mirror** — `dry.returncode == real.returncode`, and the dry item's own
      `detail.would_exit` agrees with it. `README.md`'s exit-code table, a row
      of the section that document declares *"public API from v1.0.0"*, reads
      *"A `--dry-run` mirrors the code the real run would return"*. At the
      crashing cell `PDF-64` fixed, dry was 1 and real was 0.
    * **echo** — the payload renders the spelling as typed, in BOTH modes.
    * **effect** — the real run's bytes land at the path the spelling DENOTES,
      resolved by the rule a shell would use, and a refusing real run lands
      nothing there. This is the oracle mirror and echo cannot cover: a binary
      that echoes `~/out` and writes `./~/out` satisfies both and is wrong.
    * **purity** — after the dry run ALONE, the destination does not exist and
      the redirected `$HOME`/`$TMPDIR` roots are byte-unchanged; and after the
      REAL run, no directory entry literally named `~` exists under the cell's
      anchor (`PDF-80` D10.2 — the shipped oracle snapshots only after the dry
      run, so *"the real run created a directory the user never named"* was
      asserted by nothing).
    * **disclosure** — a real run that exits 0 over a destination that exists on
      disk reports its size rather than `bytes_after: null` (`PDF-80` D10.1 —
      the limb all five oracles above pass on, measured).
    * **engine gating** — `convert`'s and `ocr`'s cells assert a DERIVED
      relation (dry agrees with real) rather than a hard-coded code, so an
      engine-absent leg answers the same question without a skip. No cell here
      is skipped; `scripts/assert_skips.py --expect-zero` stays true.
    """
    cell = build_cell(verb, flag, spelling, corpus, tmp_path / "cell")
    label = _cell_id(verb, flag, spelling)

    before = snapshot(cell.anchor, *cell.roots)
    dry = run_cli(verb, "--dry-run", *cell.argv, "-o", "json", cwd=cell.cwd, env=cell.env)

    # -- purity, measured after the DRY RUN ALONE ------------------------- #
    assert not os.path.lexists(cell.denoted), (
        f"{label}: --dry-run created {cell.denoted} -- a prediction that performed the "
        "operation in order to measure it satisfies every exit-code oracle and is not a "
        "prediction"
    )
    assert_unchanged(before, snapshot(cell.anchor, *cell.roots))

    # -- the dry run said something at all (non-vacuity) ------------------ #
    assert_no_traceback(dry, cell, "dry")
    assert dry.returncode != 2, (
        f"{label}: the dry run exited 2 (usage), so this cell never reached the planner and "
        f"measures nothing -- {dry.stdout}{dry.stderr}"
    )
    detail = prediction(dry, context=label)

    real = run_cli(verb, *cell.argv, "-o", "json", cwd=cell.cwd, env=cell.env)
    assert_no_traceback(real, cell, "real")

    # -- purity, measured after the REAL run (PDF-80 D10.2) ---------------- #
    assert_real_run_purity(cell)

    # -- disclosure (PDF-80 D10.1) ----------------------------------------- #
    assert_disclosure(real, cell)

    # -- mirror ------------------------------------------------------------ #
    assert dry.returncode == real.returncode, (
        f"{label}: dry exited {dry.returncode} and real exited {real.returncode} over the "
        f"IDENTICAL argv. README.md's exit-code table is public API from v1.0.0 and says a "
        f"--dry-run mirrors the code the real run would return. Repro: "
        f"{rerun_hint([verb, *cell.argv])} (cwd={cell.cwd})\ndry: {dry.stdout}{dry.stderr}\n"
        f"real: {real.stdout}{real.stderr}"
    )
    if "would_exit" in detail:
        assert detail["would_exit"] == dry.returncode, (
            f"{label}: the item predicted would_exit={detail['would_exit']!r} while the "
            f"process exited {dry.returncode}"
        )

    # -- echo, both modes -------------------------------------------------- #
    assert_echo(dry, cell, "dry", whole=True)
    assert_echo(real, cell, "real", whole=False)

    # -- effect ------------------------------------------------------------ #
    if real.returncode == 0:
        assert os.path.lexists(cell.denoted), (
            f"{label}: the real run exited 0 and echoed the user's spelling, but nothing "
            f"landed at {cell.denoted} -- the path that spelling DENOTES by the rule a shell "
            "would use. An exit code and an echo can both agree and still be wrong"
        )
    else:
        assert not os.path.lexists(cell.denoted), (
            f"{label}: the real run REFUSED with {real.returncode} and still left "
            f"{cell.denoted} behind"
        )
        envelope = real_envelope(real.stdout)
        assert envelope is not None, (
            f"{label}: the real run refused with {real.returncode} and printed NOTHING under "
            f"-o json -- {real.stderr}"
        )


# --------------------------------------------------------------------------- #
# AC2 -- the FITNESS statement, MECHANIZED. `X-157` says consume the dimension
# rather than re-derive it, and is SILENT about whether the reused thing is the
# RIGHT thing for this property. That silence produced a ten-verb answer for an
# eleven-verb defect twice, in this item's own brief. Prose would have been
# satisfied by both.
# --------------------------------------------------------------------------- #


def unlicensed_filters(population: Any) -> tuple[str, ...]:
    """Every `VerbSpec` field *population* filters on that value shape does not
    license, in the terms of what filtering on it MEANS."""
    return tuple(
        sorted(
            f"{field} ({FILTER_MEANINGS.get(field, 'an undeclared narrowing')})"
            for field in population_fields(population) - LICENSED_POPULATION_FIELDS
        )
    )


def test_the_consumed_population_applies_no_filter_but_flag_declaration() -> None:
    """The load-bearing half of AC2, and the arm that would have reddened on
    `out_dir_batch_verbs()`."""
    offending = unlicensed_filters(destination_flag_cases)
    assert offending == (), (
        "the population this value-shape matrix consumes narrows on "
        f"{list(offending)}, and the property under test is *does the SHAPE of the value "
        "the user typed change the answer?* -- the only filter that question licenses is "
        "flag declaration. Every other filter drops cells the defect reaches"
    )


def test_the_fitness_assertion_names_the_arity_filter_on_the_unfit_population() -> None:
    """AC2's red, driven rather than argued: point the same assertion at
    `out_dir_batch_verbs()` and it must fail NAMING the filter and what it
    means, not merely fail. An assertion that fires without naming why is the
    provenance-only shape this criterion exists to replace."""
    offending = unlicensed_filters(out_dir_batch_verbs)
    assert offending == ("variadic_operands (operand arity)",), offending
    dropped = set(dict.fromkeys(verb for verb, flag in VERB_FLAG_CASES if flag == "--out-dir"))
    assert dropped - set(out_dir_batch_verbs()) != set(), (
        "out_dir_batch_verbs() no longer drops any --out-dir consumer, so the population "
        "this matrix refused is no longer distinguishable from the one it uses -- re-derive "
        "before trusting either"
    )


# --------------------------------------------------------------------------- #
# The population floors, in `test_cli_contract.py`'s own three-field shape, and
# this module's own roster scan. E10: that module's roster reads ONLY its own
# source, so a row there naming a population declared here would guard nothing.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Population:
    """One derived population, the checks it feeds, and its floor."""

    name: str
    members: tuple
    checks: str
    minimum: int
    why: str
    """Why *minimum* is what it is. Argued per row, never defaulted."""


POPULATIONS: Final[tuple[Population, ...]] = (
    Population(
        "SPELLINGS",
        SPELLINGS,
        "the value-shape axis of every cell below",
        2,
        "TWO, not one, and the argument is the whole item: a one-member axis is what the "
        "suite already had (absolute, everywhere), and it is what let 4,450 tests stay "
        "green over a two-command reproduction. One spelling cannot disagree with another, "
        "so at one member every cell here still asserts something and the DIMENSION asserts "
        "nothing. The real non-vacuity guard is the collapse tie in "
        "tests/test_derived_dimensions.py, which is a live check against the product",
    ),
    Population(
        "DESTINATION_VALUE_FLAGS",
        DESTINATION_VALUE_FLAGS,
        "destination_flag_cases(); the flag half of every cell below",
        2,
        "TWO, and the floor IS the argument this time rather than a concession to it. The "
        "item's central finding is that --out-dir and --output do not normalize a path "
        "alike, so a one-flag axis cannot state the finding at all: it would drive a "
        "perfectly green matrix over whichever flag survived. Not pinned at 2 by equality "
        "because a third destination flag is a legitimate future addition, and the exact "
        "membership is tied in test_the_population_is_derived_and_split_is_in_it",
    ),
    Population(
        "VERB_FLAG_CASES",
        VERB_FLAG_CASES,
        "the (verb, flag) axis; test_the_value_shape_cell_holds",
        2,
        "TWO, because the population spans two flags that do NOT share a code path "
        "(--out-dir reaches _ensure_out_dir/_predict_out_dir_creation, --output reaches "
        "AtomicWriter/ensure_no_clobber) and the item's whole finding is that they do not "
        "normalize alike. A floor of one would pass with an entire flag missing. It is not "
        "pinned at 30: a verb legitimately retired must not weaken this instrument, and the "
        "real guarantee is destination_flag_cases()'s derivation plus the exact-count tie "
        "in tests/test_derived_dimensions.py",
    ),
    Population(
        "CASES",
        CASES,
        "test_the_value_shape_cell_holds (the whole matrix)",
        4,
        "the product of the two floors above, and it is the cross rather than either axis "
        "that this module drives. Below four, the matrix has stopped being a cross of two "
        "axes and is a list of examples again",
    ),
)

_ROSTERED: Final[frozenset[str]] = frozenset(row.name for row in POPULATIONS)


@pytest.mark.parametrize("population", POPULATIONS, ids=[row.name for row in POPULATIONS])
def test_every_population_is_non_empty(population: Population) -> None:
    assert len(population.members) >= population.minimum, (
        f"{population.name} has {len(population.members)} member(s), below its floor of "
        f"{population.minimum} -- the check(s) it feeds ({population.checks}) would then "
        f"collect too few parametrized cases to discriminate. Why this floor: "
        f"{population.why}"
    )


def module_level_tuple_names(source: str, namespace: Mapping[str, object]) -> frozenset[str]:
    """Every module-level name in *source* whose live value in *namespace* is a tuple."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return frozenset(name for name in names if isinstance(namespace.get(name), tuple))


def unrostered_populations(
    source: str, namespace: Mapping[str, object], rostered: frozenset[str]
) -> list[str]:
    return sorted(module_level_tuple_names(source, namespace) - rostered - {"POPULATIONS"})


def test_every_population_here_is_rostered() -> None:
    """Without this, POPULATIONS is a hand-maintained list beside a live module."""
    missing = unrostered_populations(
        Path(__file__).read_text(encoding="utf-8"), dict(globals()), _ROSTERED
    )
    assert missing == [], (
        f"module-level tuple population(s) {missing} have no row in this module's "
        "POPULATIONS -- add one naming the check(s) it feeds and a `minimum` with a stated "
        "argument, or the new population is exempt from the only emptiness pin here"
    )


def test_the_roster_check_here_fires_on_an_unrostered_population() -> None:
    """AC5's red, synthetic rather than a real edit for the same reason
    `tests/test_acceptance_audit.py`'s proofs are synthetic: a red proof that
    vandalises the thing it proves is not a proof."""
    source = "SPELLINGS = path_spellings()\nSMUGGLED = tuple(s for s in SPELLINGS)\n"
    namespace = {"SPELLINGS": SPELLINGS, "SMUGGLED": SPELLINGS}
    assert unrostered_populations(source, namespace, frozenset({"SPELLINGS"})) == ["SMUGGLED"]
    # ...and the same scan is quiet once the row exists, so it is not always red.
    assert unrostered_populations(source, namespace, frozenset({"SPELLINGS", "SMUGGLED"})) == []


def test_the_roster_scan_here_sees_this_module_at_all() -> None:
    """The non-vacuity guard for the guard."""
    found = module_level_tuple_names(Path(__file__).read_text(encoding="utf-8"), dict(globals()))
    assert len(found) >= len(POPULATIONS), (
        f"the AST scan found {len(found)} module-level tuple(s) but POPULATIONS declares "
        f"{len(POPULATIONS)} -- the scan itself has stopped seeing this module"
    )
    assert "CASES" in found and "SPELLINGS" in found, sorted(found)


# --------------------------------------------------------------------------- #
# The population, the cross, and the pin, each tied to what was MEASURED.
# --------------------------------------------------------------------------- #


def test_the_population_is_derived_and_split_is_in_it() -> None:
    """AC1. The exact-count tie the floors above deliberately do not carry.

    A future destination-flag verb joins with zero author action and trips this,
    which is the prompt to extend the matrix rather than a failure to route
    around. `split` is named as a MEMBERSHIP question, never as a literal
    population member: it is the single verb `out_dir_batch_verbs()`' arity
    filter drops, and a population of ten here IS that population.
    """
    out_dir = tuple(verb for verb, flag in VERB_FLAG_CASES if flag == "--out-dir")
    output = tuple(verb for verb, flag in VERB_FLAG_CASES if flag == "--output")
    assert (len(out_dir), len(output), len(VERB_FLAG_CASES)) == (11, 19, 30), (
        f"the live destination-flag population is {len(out_dir)} --out-dir / {len(output)} "
        f"--output / {len(VERB_FLAG_CASES)} pairs, not 11/19/30 -- extend this matrix rather "
        "than silently accepting the new count"
    )
    dropped = sorted(set(out_dir) - set(out_dir_batch_verbs()))
    assert len(dropped) == 1, (
        f"out_dir_batch_verbs() drops {dropped} from the --out-dir population; exactly one "
        "verb (the single-operand consumer) was dropped when this was measured"
    )
    assert len(set(CASES)) == len(VERB_FLAG_CASES) * len(SPELLINGS) == 240, len(CASES)
    assert {flag for _verb, flag in VERB_FLAG_CASES} == set(DESTINATION_VALUE_FLAGS), (
        "the cross no longer spans both destination flags declared by the dimension -- a "
        "whole flag dropping out would leave every floor above satisfied"
    )


def test_no_verb_name_is_written_down_anywhere_in_this_module() -> None:
    """AC1's other half. Every verb this module drives arrives from the live
    registry; a literal would make the matrix stale-but-passing the day a verb
    is renamed, which is the failure `e138934a60` already cost this suite."""
    source = Path(__file__).read_text(encoding="utf-8")
    live = {verb.name for verb in discover_verbs() if not verb.is_group}
    offenders = sorted(
        {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in live
        }
    )
    assert offenders == [], (
        f"verb name literal(s) {offenders} appear as string constants in this module -- the "
        "population is derived precisely so it cannot be tempted"
    )


def test_the_destination_population_outlives_the_defect_that_shaped_it() -> None:
    """What REPLACES the retired pin membership (`PDF-80` D9).

    `PDF-74`'s pin membership derived from each verb's `consumes` DECLARATION
    rather than from behaviour, so it would have kept returning twenty-seven
    after the fix and kept this node green while asserting that twenty-seven
    cells are defective when none is. Deleting it outright would have thrown
    away three guarantees that were never about the defect at all: **the
    population is thirty, the `--out-dir` limb is eleven, the `--output` limb
    is nineteen.** Those are properties of the PRODUCT, so they are asserted
    here against the live registry with the defect vocabulary gone -- gone to
    the letter, including from this docstring, because `PDF-80` AC12 mechanises
    the retirement as a grep for the retired name over the whole `tests/` tree
    and a prose mention is a hit. The name is preserved where naming a dead
    symbol belongs: this item's `changelog.md` entry.

    Red: drop a destination flag from any verb's `consumes` and this names the
    flag whose count moved. The `--out-dir` limb being ELEVEN is the one worth
    reading twice -- `_ensure_out_dir` is verb-independent, so every one of the
    eleven reaches the same planner and a count that falls means a verb stopped
    reaching it, not that a verb got simpler.
    """
    cases = destination_flag_cases()
    by_flag = {
        flag: tuple(verb for verb, row_flag in cases if row_flag == flag)
        for flag in DESTINATION_VALUE_FLAGS
    }
    measured = {flag: len(verbs) for flag, verbs in by_flag.items()}
    assert (len(cases), measured) == (30, {"--out-dir": 11, "--output": 19}), (
        f"the live destination population is {len(cases)} cell(s) {measured}, not 30 "
        "(11 --out-dir / 19 --output) -- extend this matrix rather than silently "
        f"accepting the new shape: {sorted(cases)}"
    )
    for flag, verbs in by_flag.items():
        assert verbs, f"no verb declares {flag} any more -- a whole limb of the cross is gone"
        assert len(set(verbs)) == len(verbs), f"{flag} names a verb twice: {sorted(verbs)}"


def test_the_builder_catches_a_smuggled_absolute_value(corpus: Any, tmp_path: Path) -> None:
    """AC6's red, planted and OBSERVED. A relative row rendering an absolute
    value is not a test that fails loudly -- it is a test that silently stops
    testing, so the guard is asserted rather than documented."""
    relative = next(row for row in SPELLINGS if row.anchoring == "relative")
    smuggler = PathSpelling(
        relative.id,
        relative.anchoring,
        lambda anchor, leaf: str(anchor / leaf),  # the copy-paste that does it
        relative.prepare,
        relative.cwd,
        relative.redirect_home,
    )
    verb, flag = VERB_FLAG_CASES[0]
    with pytest.raises(AssertionError) as caught:
        build_cell(verb, flag, smuggler, corpus, tmp_path / "smuggled")
    message = str(caught.value)
    assert relative.id in message, message
    assert "ABSOLUTE value" in message, message
    assert str(tmp_path / "smuggled") in message, message


def test_the_builder_is_not_simply_always_red(corpus: Any, tmp_path: Path) -> None:
    """The other half: every shipped row builds cleanly, so the guard above is
    a guard rather than a wall."""
    verb, flag = VERB_FLAG_CASES[0]
    for index, row in enumerate(SPELLINGS):
        cell = build_cell(verb, flag, row, corpus, tmp_path / f"clean-{index}")
        assert cell.value, row.id


# --------------------------------------------------------------------------- #
# The two new oracles' own controls (`PDF-80` AC15/AC16). Each has a half that
# FIRES and a half that does NOT over-fire, because an oracle proven in one
# direction only is the shape three engineers hit this cycle.
# --------------------------------------------------------------------------- #


def synthetic_cell(tmp_path: Path, value: str) -> Cell:
    """A `Cell` built by hand, so the controls below need no subprocess.

    The oracles are pure functions of a payload plus a cell's two destination
    values, which is deliberate: it is what lets them be driven to red without
    vandalising the product or the matrix to do it.
    """
    anchor = tmp_path / "anchor"
    home = anchor / "home"
    home.mkdir(parents=True, exist_ok=True)
    spelling = next(row for row in SPELLINGS if row.id == TILDE_SPELLING)
    return Cell(
        verb="",
        flag="--output",
        spelling=spelling,
        argv=[],
        value=value,
        cwd=anchor,
        env={"HOME": str(home)},
        anchor=anchor,
        roots=(),
        denoted=home / Path(value).name,
    )


@pytest.mark.parametrize(
    ("label", "item", "expect_reported"),
    [
        ("succeeded-with-a-null-size", {"ok": True, "exit_code": 0, "bytes_after": None}, True),
        ("succeeded-and-disclosed", {"ok": True, "exit_code": 0, "bytes_after": 1395}, False),
        ("refused", {"ok": False, "exit_code": 5, "bytes_after": None}, False),
        ("failed-per-item", {"ok": False, "exit_code": 4, "bytes_after": None}, False),
    ],
)
def test_the_disclosure_oracle_fires_on_a_null_size_beside_a_real_file(
    label: str, item: dict[str, object], expect_reported: bool, tmp_path: Path
) -> None:
    """AC15, both halves.

    FIRES on the exact shape `create`/`compose`/`merge` shipped -- exit 0, a
    real non-empty artefact on disk, `bytes_after: null`. DOES NOT fire on a
    refused or per-item-failed row, which is `ops/raster.py`'s own legitimate
    `None` and must stay legitimate.
    """
    cell = synthetic_cell(tmp_path, "~/til.pdf")
    cell.denoted.write_bytes(b"%PDF-1.7\n" * 40)
    payload = {"dry_run": False, "items": [{**item, "output": cell.value}]}
    reported = undisclosed_items(payload, cell)
    assert bool(reported) is expect_reported, f"{label}: {reported}"


def test_the_disclosure_oracle_is_silent_on_a_dry_item(tmp_path: Path) -> None:
    """The other "does not fire" half, and the one most likely to be got wrong:
    a DRY item reports `bytes_after: null` by design, at every spelling, and an
    oracle that flagged it would be red on all 240 cells on arrival."""
    cell = synthetic_cell(tmp_path, "~/til.pdf")
    cell.denoted.write_bytes(b"%PDF-1.7\n" * 40)
    dry = {
        "dry_run": True,
        "items": [{"ok": True, "exit_code": 0, "bytes_after": None, "output": cell.value}],
    }
    assert undisclosed_items(dry, cell) == ()


def test_the_disclosure_oracle_needs_the_file_to_exist(tmp_path: Path) -> None:
    """And the narrowing is real rather than accidental: an item naming a
    destination that is NOT on disk has nothing to disclose, so a refusal that
    wrote nothing is not reported as an undisclosed write."""
    cell = synthetic_cell(tmp_path, "~/absent.pdf")
    payload = {
        "dry_run": False,
        "items": [{"ok": True, "exit_code": 0, "bytes_after": None, "output": cell.value}],
    }
    assert undisclosed_items(payload, cell) == ()


def test_the_real_run_purity_scan_sees_a_literal_tilde_directory(tmp_path: Path) -> None:
    """AC16 half 1, synthetic: the entry `_ensure_out_dir`'s raw-spelling
    `mkdir` used to create IS detected, at any depth, and is reported by name.

    The nested arm is not decoration. `--out-dir '~/out'` creates `./~/out`, so
    the entry to find is the `~` at the TOP of that pair and `out` beneath it is
    an ordinary directory name -- and the run that reaches the anchor's own
    subdirectories (the parent-relative spelling drives from `anchor/sub`)
    would leave its stray one level down. A scan that only looked at the root's
    immediate children would be green on that cell, forever.
    """
    (tmp_path / "~" / "out").mkdir(parents=True)
    (tmp_path / "sub" / "~").mkdir(parents=True)
    assert literal_tilde_entries(tmp_path) == ("sub/~", "~")


def test_the_real_run_purity_scan_does_not_cry_wolf(tmp_path: Path) -> None:
    """AC16 half 2: a tree with no literal `~` entry is quiet -- including one
    holding files whose names merely CONTAIN the character, which the other
    seven spellings legitimately produce and which must not be flagged."""
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "out.pdf").write_bytes(b"x")
    (tmp_path / "~draft.pdf").write_bytes(b"x")
    (tmp_path / "a~b").mkdir()
    assert literal_tilde_entries(tmp_path) == ()
