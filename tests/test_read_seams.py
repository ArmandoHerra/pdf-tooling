"""`PDF-43` -- the runtime `open()` completeness instrument, and the three seams it names.

WHAT THIS MODULE IS FOR, AND WHY IT IS NOT A FOURTH BELT
--------------------------------------------------------
`PDF-26`'s §D3 read-seam belt landed and its charter deliverable is proven. What
did not land is §D3's **completeness**, and the reason is not that somebody
missed a file: the measurement *"0 tracebacking seams"* was produced by an
instrument that could not have reported anything else. It was blind twice, and
both blindnesses landed on the same seam --

* **(a) statically**, because the AST walk looks for read-*shaped* calls and
  ``drawImage(path)`` is not one;
* **(b) dynamically**, because the drive used a mode-000-**from-the-start**
  operand, which fails at each verb's **first** read seam and shadows every
  later one.

Three point-fixes have been spent on this seam, each individually correct and
each followed by a new defect -- one of them (`48766ee6f2`) introduced by
`PDF-26` itself. So what ships here is the **instrument**, in ``tests/seams.py``,
and these arms are what hold it honest.

**`PDF-26` remains `Implemented` with its verification WITHHELD AND ACCEPTED.
Nothing in this module re-grants it.** A future re-verify is *unblocked* by this
work and is not *performed* by it.

THE NUMBERS IN THIS FILE ARE CEILINGS, NOT TARGETS
--------------------------------------------------
The residue and population ceilings below are frozen at their **measured** size,
following `PDF-30`'s ``RESIDUE_CEILING`` precedent: legacy population stays
visible at its exact size, and the ceiling **forbids growth**. A newly-honest
instrument revealing more red is this module working, not failing -- the correct
response is to FILE it, never to widen a ceiling or weaken the drive.
"""

from __future__ import annotations

import ast
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, NamedTuple

import pytest
from PIL import Image

import seams
from test_cli_contract import _skip_as_root

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SRC_ROOT: Final = REPO_ROOT / "src"
SEAMS_MODULE: Final = REPO_ROOT / "tests" / "seams.py"

# --------------------------------------------------------------------------- #
# FROZEN CEILINGS. Measured at the working commit; recorded, not invented.
# --------------------------------------------------------------------------- #


#: Static read seams the drive never reaches, per module -- **undriven, therefore
#: unproven**. Not a build failure on sight: the drive covers `compose` and
#: `compress`, and pretending it covers every branch of every verb would make the
#: instrument lie. It is COUNTED, and the count MAY NOT GROW (X-421).
class _ReadSeamRatification(NamedTuple):
    """One recorded movement of the undriven-read-seam residue ceiling.

    Immutable, and `ceilings` is a read-only view rather than a mutable dict
    shared with the live ceiling (PDF-70 D1).
    """

    date: str
    spec: str
    #: "genesis" | "down" | "up"
    direction: str
    ceilings: Mapping[str, int]
    reason: str
    #: The PM ruling id (X-NNN) authorising an UPWARD key movement. X-715 is the
    #: only one this constant has ever been granted.
    ruling: str = ""


_RATIFICATION_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RATIFICATION_DIRECTIONS: Final = ("genesis", "down", "up")


def read_seam_ratification_complaints(ledger: Sequence[_ReadSeamRatification]) -> list[str]:
    """Every rule violation in *ledger*, per key. Empty means ACCEPTED.

    PURE OVER ITS PARAMETER (PDF-70 D4), so synthetic ledgers drive it in-process
    on every run and the real ledger is never mutated to prove a point. It
    RETURNS complaints rather than raising so the refusing direction is as
    ordinary to assert as the accepting one.

    **This is the arm that finally delivers what `:629-630` claimed.** The
    `sum(...) == 44` literal it replaced was an anti-lapse guard on the
    constant's TOTAL, and its own comment said the total existed "so a shrink in
    one module cannot silently pay for a growth in another" — which is precisely
    the act a frozen total cannot see. A COMPENSATING SWAP (`crypto.py` 4 -> 3,
    `optimize.py` 3 -> 4) leaves the total at 44 and the old guard accepted it;
    that was driven against the pre-PDF-70 constant and recorded in PDF-70's
    Implementation Log. The residual strength of the old guard was that such a
    swap had to be funded out of genuine SLACK, because shrinking a ceiling below
    its measured count reds that module's own arm — so the guard was exactly as
    strong as the absence of slack, and slack is precisely what accumulates as
    the product improves. This walk is per key and needs no slack argument.

    DUPLICATED, KNOWINGLY, as `docs_ratification_complaints` in
    `tests/test_docs_antirot.py` (D5). It is deliberately NOT imported across
    test modules: cross-test-module coupling is already a filed defect on this
    product (I-12 piece 3, carrier `B-308`), and adding a fresh instance of a
    defect while deferring its fix would be indefensible. Consolidating is a
    two-line follow-up once `B-308` decides the shared home.
    """
    complaints: list[str] = []
    if not ledger:
        return ["the ratification ledger is EMPTY: the live ceiling has no record behind it"]

    for index, record in enumerate(ledger):
        where = f"[{index}] {record.spec} ({record.date})"
        if not _RATIFICATION_DATE.fullmatch(record.date):
            complaints.append(f"{where}: date is not YYYY-MM-DD")
        if not record.spec.strip():
            complaints.append(f"{where}: no allocating spec id")
        if not record.reason.strip():
            complaints.append(
                f"{where}: no reason — a ratification carrying no evidence is an edit "
                f"wearing a record's clothes"
            )
        if record.direction not in _RATIFICATION_DIRECTIONS:
            complaints.append(
                f"{where}: direction {record.direction!r} is not one of "
                f"{list(_RATIFICATION_DIRECTIONS)}"
            )
        if (record.direction == "genesis") != (index == 0):
            complaints.append(f"{where}: direction 'genesis' belongs to record 0 and to no other")
        if index and record.date < ledger[index - 1].date:
            complaints.append(f"{where}: dated before its predecessor {ledger[index - 1].date}")

    for index in range(1, len(ledger)):
        previous, current = ledger[index - 1], ledger[index]
        where = f"[{index}] {current.spec} ({current.date})"
        for key in sorted(set(previous.ceilings) | set(current.ceilings)):
            before = previous.ceilings.get(key)
            after = current.ceilings.get(key)
            if before == after:
                continue
            if after is not None and (before is None or after > before):
                # An ADDED key is this case with `before` absent -- exactly the act
                # X-715 licensed once, for `soffice_office.py`, and no other.
                shown = "absent" if before is None else before
                if current.direction != "up":
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} in a record declaring "
                        f"direction={current.direction!r}; an upward movement must declare "
                        f"direction='up'"
                    )
                if not current.ruling.strip():
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} with NO ruling. X-715's "
                        f"fourth condition — the PM rules it explicitly, on the record — is "
                        f"not satisfiable without a ruling id in the diff. Raising a ceiling "
                        f"is anti-gaming; drive the seam or FILE it"
                    )
                if key not in current.reason:
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} but the reason does not "
                        f"name the key; a raise is justified per key or not at all"
                    )
            else:
                # PDF-70 D2 row 2 -- ORDINARY, and no ruling is required. A
                # fabricated tightening is caught by the measured `grew` arm, not
                # here: the ledger RECORDS, the arm MEASURES, and a second oracle
                # that could disagree with the first would be worse than none.
                shown = "removed" if after is None else after
                if current.direction != "down":
                    complaints.append(
                        f"{where}: {key} LOWERED {before} -> {shown} in a record declaring "
                        f"direction={current.direction!r}; a tightening must declare "
                        f"direction='down' so it is recorded rather than furtive"
                    )
    return complaints


#: PDF-70 D1 -- THE RATIFICATION LEDGER, append-only. The live ceiling below is
#: the NEWEST record's mapping, never a separately-writable literal, so a ceiling
#: cannot move without a record moving with it (AC3 asserts that structurally, by
#: `ast`). Values here are byte-identical to the pre-PDF-70 constant: PDF-70 pays
#: no debt down, it only builds the path by which debt CAN be paid down.
READ_SEAM_RESIDUE_LEDGER: Final[tuple[_ReadSeamRatification, ...]] = (
    _ReadSeamRatification(
        date="2026-09-12",
        spec="PDF-63",
        direction="genesis",
        ceilings=MappingProxyType(
            {
                "pdf_tooling/adapters/pdfplumber_text.py": 1,
                "pdf_tooling/adapters/pikepdf_structure.py": 10,
                "pdf_tooling/adapters/pypdf_structure.py": 7,
                #: X-715 -- the ONE entry this constant is licensed to gain, and no other.
                #: (a) THE CLASS: `:120` is `handle.read(...)` on an ALREADY-OPEN handle, a
                #: read-shaped call that cannot raise the `open` audit event this observer
                #: hooks -- structurally unobservable, not undriven, under any verb, race
                #: or depth. (b) THE CONTROL: `ops/compose.py:538` is observed and `:539`
                #: is residual under the identical two-line idiom, in a module the drive
                #: DOES reach, absorbed by that module's own frozen ceiling of `2` (E3) --
                #: the same concession, at the same size, for the same structural reason.
                #: (c) FORWARD-LOOKING BY ONE COMMIT: at `PDF-63`'s own commit the adapter
                #: carries no read-shaped site at all, so this key is inert here and
                #: registers a site arriving in the next commit of the same push (X-715.1).
                #: `1`, not `2`: `:119` IS observable and IS driven by the `convert/
                #: office-dry` cell below, and the value must not cover it -- a `2` would
                #: let a future engineer delete that cell and stay green, which is the act
                #: this constant exists to forbid (X-715, decision.md §11).
                "pdf_tooling/adapters/soffice_office.py": 1,
                "pdf_tooling/adapters/tesseract_ocr.py": 2,
                "pdf_tooling/cli/cmd_create.py": 2,
                "pdf_tooling/cli/common.py": 1,
                "pdf_tooling/cli/password.py": 1,
                "pdf_tooling/ops/compose.py": 2,
                "pdf_tooling/ops/crypto.py": 4,
                "pdf_tooling/ops/document_password.py": 3,
                "pdf_tooling/ops/metadata.py": 1,
                "pdf_tooling/ops/office.py": 1,
                "pdf_tooling/ops/optimize.py": 3,
                "pdf_tooling/safety/_faults.py": 1,
                "pdf_tooling/safety/atomic.py": 4,
            }
        ),
        ruling="X-715",
        reason=(
            "GENESIS. The undriven read-seam residue as measured by this module's "
            "own sweep, 16 modules totalling 44. Every entry is legacy population "
            "recorded at its exact size; the one entry the constant was ever "
            "LICENSED to gain is pdf_tooling/adapters/soffice_office.py, granted by "
            "X-715 (decision.md §11) under all four of its conditions, whose class, "
            "control (ops/compose.py:538 observed / :539 residual) and "
            "forward-looking-by-one-commit reasoning are carried verbatim on that "
            "entry above. PDF-70 transcribes this record without moving a value."
        ),
    ),
)

#: The LIVE ceiling: the newest record's mapping, and nothing else. No
#: separately-writable literal survives, which is the load-bearing property --
#: a ceiling cannot move unless a record moves with it.
RESIDUE_CEILING: Final[Mapping[str, int]] = READ_SEAM_RESIDUE_LEDGER[-1].ceilings

#: The scoped METADATA population -- `ops/**` plus `safety/paths.py`, the two
#: layers that hold an operand path. The UNSCOPED census over `src/` is published
#: beside it so the scoping can be audited rather than trusted.
#:
#: **73 -> 75 (PDF-38), and the disposition this guard asks for is COUNTED AND
#: INERT rather than belted.** `safety/paths.py::ensure_backup_sidecar_free` adds
#: two zero-argument `.exists()` probes -- one on the DESTINATION, one on the
#: `.bak` SIDECAR beside it -- mirroring `AtomicWriter._make_backup`'s own guard
#: clauses so a prediction and an outcome are the same answer. Neither is an
#: OPERAND probe: they are the write-target class this census's own recipe says
#: it deliberately over-reads, and `Path.exists()` returns `False` on `OSError`
#: rather than raising, so neither can produce the traceback §D3 is about. They
#: are counted here because the scoping rule is structural (module + call shape)
#: and must stay auditable, NOT because a ceiling may be widened to clear a red:
#: the two figures are named, and the growth is exactly the two calls the diff
#: adds. Raising this for a seam that CAN raise would be a different act.
METADATA_POPULATION_CEILING: Final = 75

#: `ops/` calls into an engine whose port signature hands it a path (D5's rule,
#: enumerated). Frozen so a new unbelted one is a red on the day it is written.
BOUNDARY_SITE_CEILING: Final = 12

#: The static walk's two word lists. Frozen with an asserted size, because **a
#: vocabulary that can be widened quietly is how blindness (a) survived three
#: fixes.**
READ_ATTRS_SIZE: Final = 5
READ_FUNCS_SIZE: Final = 5

_TRACEBACK: Final = "Traceback (most recent call last)"


# --------------------------------------------------------------------------- #
# Operands. Built with Pillow in a temp dir -- NO acceptance criterion in this
# module reads the real-document corpus (HC-2).
# --------------------------------------------------------------------------- #


def _image_operand(fmt: str, ext: str):
    def build(directory: Path) -> Path:
        target = directory / f"operand{ext}"
        extra = {"quality": 85} if fmt == "JPEG" else {}
        Image.new("RGB", (64, 48), (200, 30, 30)).save(target, format=fmt, **extra)
        return target

    return build


def _pdf_operand(directory: Path) -> Path:
    from reportlab.pdfgen.canvas import Canvas

    target = directory / "operand.pdf"
    canvas = Canvas(str(target))
    canvas.drawString(72, 720, "seam drive")
    canvas.showPage()
    canvas.save()
    return target


def _compose_argv(operand: Path, workdir: Path) -> list[str]:
    return ["-o", "json", "compose", str(operand), "-O", str(workdir / "out.pdf")]


def _compress_argv(operand: Path, workdir: Path) -> list[str]:
    return ["-o", "json", "compress", str(operand), "-O", str(workdir / "out.pdf")]


#: PDF-63 D2 -- an ASCII payload behind a `.docx` name. Reaches BOTH residue
#: sites (`ensure_source_loadable` opens and reads the head before the
#: `head != _ZIP_MAGIC` early return) and stops there: a non-`PK` operand never
#: reaches `zipfile.is_zipfile`/`zipfile.ZipFile`, which are invisible to the
#: static walk and unregistered, so this shape keeps AC4's rogue list empty
#: (E5) -- a `PK`-prefixed operand does not (driven separately, D3, outside
#: this population). This is the MINIMAL drive of the two residue sites, not
#: an operand chosen to dodge a red.
def _office_dry_operand(directory: Path) -> Path:
    target = directory / "operand.docx"
    target.write_bytes(b"an ASCII operand behind a .docx name\n")
    return target


def _convert_dry_argv(operand: Path, workdir: Path) -> list[str]:
    return ["-o", "json", "convert", str(operand), "--out-dir", str(workdir / "out"), "--dry-run"]


_SWEEP_SPECS: Final = {
    "compose/JPEG": (_image_operand("JPEG", ".jpg"), _compose_argv, seams.RACE_UNREADABLE),
    # A JPEG whose NAME says nothing. The suffix-derived default noun answers
    # "the input file" here, so this cell is the only one that can tell the
    # explicit `noun=IMAGE_NOUN` at the frame-header read apart from the default
    # -- without it, that belt has no arm of its own and AC15 is not N/N.
    "compose/JPEG-as-bin": (_image_operand("JPEG", ".bin"), _compose_argv, seams.RACE_DIRECTORY),
    "compose/PNG": (_image_operand("PNG", ".png"), _compose_argv, seams.RACE_UNREADABLE),
    "compose/JPEG-dir": (_image_operand("JPEG", ".jpg"), _compose_argv, seams.RACE_DIRECTORY),
    "compress/PDF-delete": (_pdf_operand, _compress_argv, seams.RACE_DELETE),
    # PDF-63 -- the third driven verb of twenty-six. Spawn-free (`--dry-run`,
    # no `soffice` spawn, no LibreOffice profile dir), so this is the cheapest
    # cell in the drive (E7). Drives `soffice_office.py:119` out of AC5's
    # residue; `:120` (`handle.read` on an already-open handle) raises no
    # `open` audit event and is structurally unobservable under any verb, race
    # or depth (E2) -- covered instead by the X-715 `RESIDUE_CEILING` entry
    # above, not by widening this cell.
    "convert/office-dry": (_office_dry_operand, _convert_dry_argv, seams.RACE_UNREADABLE),
}

_CACHE: dict[str, seams.Sweep] = {}


@pytest.fixture(scope="session")
def sweeps(tmp_path_factory: pytest.TempPathFactory) -> dict[str, seams.Sweep]:
    """Every drive this module needs, run once per worker.

    Session-scoped because each cell is a subprocess and the sweeps are the
    expensive part of this module by an order of magnitude.
    """
    if not _CACHE:
        root = tmp_path_factory.mktemp("seam-sweeps")
        for label, (operand_for, argv_for, race) in _SWEEP_SPECS.items():
            _CACHE[label] = seams.sweep_cell(
                label=label,
                argv_for=argv_for,
                operand_for=operand_for,
                root=root / label.replace("/", "-"),
                race=race,
            )
    return _CACHE


def _assert_installed(sweep: seams.Sweep) -> None:
    """No cell may carry an `install-error`, and the ledger may not be empty.

    **An observer that failed to install produces an empty ledger, and an empty
    ledger reads exactly like "this verb performed no reads."** That is a silent
    invisibility, which is the defect class this whole spec is about. It is not
    hypothetical: the first draft of the child installer swallowed a real
    `AttributeError` and reported a clean, entirely fictional zero.
    """
    for cell in (sweep.control, *sweep.cells):
        broken = [row for row in cell.records if row.get("channel") == "install-error"]
        assert not broken, (
            f"{sweep.label}: the observer FAILED TO INSTALL in the driven child, so every "
            f"figure this sweep reports is fiction -- {broken[0].get('detail')}"
        )
    assert sweep.control.records, (
        f"{sweep.label}: the un-raced control observed NOTHING. Either the observer is not "
        f"installed or the operand never matched; both make this sweep's zero meaningless"
    )


# --------------------------------------------------------------------------- #
# THE OBSERVER -- AC1, AC2, AC3, AC16.
# --------------------------------------------------------------------------- #


def test_ac1_the_observer_records_ordinal_and_both_frames_in_the_driven_child(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC1: per open of the driven operand -- ordinal, non-product frame, product frame.

    RED: point the drive at a verb that takes no operand (`version`) -> **0**
    records, asserted below in its own arm; remove the hook installation from
    `sitecustomize.py` -> AC2 fails and `_assert_installed` fails first.
    """
    _skip_as_root()
    sweep = sweeps["compose/JPEG"]
    _assert_installed(sweep)

    reads = sweep.control.channel(seams.CHANNEL_READ)
    assert reads, "the clean control observed no reads of a JPEG that compose demonstrably opens"

    assert [row["ordinal"] for row in reads] == list(
        range(seams.FIRST_ORDINAL, seams.FIRST_ORDINAL + len(reads))
    ), f"ordinals must be dense and 1-based, got {[r['ordinal'] for r in reads]}"

    for row in reads:
        assert row["first_party"], f"a read with no pdf_tooling frame is unattributable: {row}"
        assert row["origin"], f"a read with no originating frame cannot name its opener: {row}"
        assert re.match(r"^pdf_tooling/.+\.py:\d+$", str(row["first_party"])), row


def test_ac1_a_verb_with_no_operand_observes_nothing(tmp_path: Path) -> None:
    """AC1's RED, run as an arm: `version` takes no operand, so the ledger is empty.

    This is the control that stops the observer from being a thing that records
    *any* open -- it records opens **of the driven operand**, and a drive pointed
    at a verb that never touches it must produce exactly zero.
    """
    operand = _image_operand("JPEG", ".jpg")(tmp_path)
    result = seams.drive_cell(
        argv=["-o", "json", "version"],
        operand=operand,
        workdir=tmp_path,
        depth=None,
        race=seams.RACE_NONE,
    )
    assert result.exit_code == 0, f"version should succeed: {result.stderr[:300]}"
    assert result.channel(seams.CHANNEL_READ) == (), (
        f"`version` never touches the operand, so the read channel must be EMPTY; "
        f"a non-empty one means the observer is matching something else: {result.records}"
    )


def test_ac2_the_runtime_observer_sees_the_seam_the_static_walk_cannot(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC2 -- THE BLINDNESS-(a) CONTROL, and it is free.

    For `compose` with a `.jpg` operand the observer records **at least one** open
    attributed to a frame inside **reportlab**, while the static enumerator
    returns **zero** rows in `adapters/reportlab_compose.py`. Both figures are
    recorded in the Implementation Log.

    RED: restrict the observer to the static walk's call shapes
    (`READ_ATTRS`/`READ_FUNCS`) -> the reportlab seam disappears and this arm
    fails. That is the wave-7 instrument reproduced and shown blind.
    """
    _skip_as_root()
    sweep = sweeps["compose/JPEG"]
    _assert_installed(sweep)

    static = seams.static_read_sites(SRC_ROOT)
    reportlab_rows = [site for site in static if "reportlab_compose" in site.module]
    assert reportlab_rows == [], (
        f"the static walk is supposed to be BLIND here -- that is the whole control. "
        f"If it now sees {reportlab_rows}, the vocabulary was widened and AC2 measures nothing"
    )

    reportlab_opens = [
        row
        for row in sweep.control.channel(seams.CHANNEL_READ)
        if "reportlab" in str(row.get("origin", ""))
    ]
    assert reportlab_opens, (
        f"the observer saw NO reportlab-performed open of the operand, so blindness (a) is "
        f"not closed and this instrument is no better than the one it replaces. "
        f"Observed origins: {[r.get('origin') for r in sweep.control.channel(seams.CHANNEL_READ)]}"
    )
    assert any("reportlab_compose" in str(row.get("first_party", "")) for row in reportlab_opens), (
        f"the reportlab open must be attributed to the adapter that handed it the path: "
        f"{reportlab_opens}"
    )


def test_ac3_every_resolvable_engine_is_registered_with_its_visibility(tmp_path: Path) -> None:
    """AC3 -- the blind spot is DECLARED and ASSERTED, not assumed.

    Pins the observer's coverage across the resolved engines: `pypdf.PdfReader`
    **visible**, `pikepdf.Pdf.open` **visible**, `pypdfium2.PdfDocument`
    **invisible**, `os.stat` **invisible on the read channel**. Every invisible
    member carries its exception class and its §D3 disposition.

    **A SILENT INVISIBILITY IS THE DEFECT THIS WHOLE SPEC IS ABOUT, and it must be
    the one thing that cannot happen quietly.**

    RED: remove `pypdfium2` from the register while it is still resolvable -> the
    companion arm below fails, naming an unregistered invisible engine.
    """
    for entry in seams.ENGINE_REGISTER:
        assert entry.exception, f"{entry.dotted} carries no exception class"
        assert entry.disposition, f"{entry.dotted} carries no §D3 disposition"
        assert "§D3" in entry.disposition, (
            f"{entry.dotted}'s disposition must say whether it is INSIDE or OUTSIDE §D3; "
            f"a register entry that does not is a declaration of nothing"
        )

    ledger = tmp_path / "coverage.jsonl"
    probe = tmp_path / "probe.pdf"
    _pdf_operand_at(probe)
    measured = _measure_engine_visibility(probe, ledger, tmp_path)

    for entry in seams.ENGINE_REGISTER:
        # A register entry with no probe recipe is a BROKEN ENTRY, not an absent
        # engine, and it must fail rather than skip. Skipping on an unrecognised
        # name would let a renamed or fabricated entry pass silently -- which is
        # the same walk-past this criterion exists to forbid.
        assert entry.dotted in measured, (
            f"{entry.dotted} is in the register and the probe has no recipe for it, so its "
            f"visibility claim is UNMEASURED. Add a recipe to `_ENGINE_PROBE` or remove the "
            f"entry; an unmeasured claim is worse than no claim"
        )
        verdict = measured[entry.dotted]
        if isinstance(verdict, str):
            if "ModuleNotFound" in verdict or "ImportError" in verdict:
                pytest.skip(f"{entry.dotted} is not installed in this environment ({verdict})")
            pytest.fail(f"{entry.dotted} could not be measured: {verdict}")
        assert verdict == entry.visible, (
            f"{entry.dotted}: the register says visible={entry.visible} and the observer "
            f"measured visible={verdict}. The register is a CLAIM about what "
            f"this instrument can see, and a false claim there is worse than no register"
        )


def test_ac3_no_resolvable_engine_is_invisible_without_being_registered(tmp_path: Path) -> None:
    """AC3's companion, and the arm that stops the class recurring.

    A future engine that opens below the Python layer must not be able to join the
    blind spot **silently** -- which is precisely how this class of defect arrived
    the first time.

    RED: drop `pypdfium2` from `INVISIBLE_ENGINES` while it is still importable ->
    this arm fails naming it.
    """
    ledger = tmp_path / "coverage.jsonl"
    probe = tmp_path / "probe.pdf"
    _pdf_operand_at(probe)
    measured = _measure_engine_visibility(probe, ledger, tmp_path)

    registered = {entry.dotted for entry in seams.ENGINE_REGISTER}
    unregistered_invisible = sorted(
        dotted for dotted, visible in measured.items() if not visible and dotted not in registered
    )
    assert unregistered_invisible == [], (
        f"these engines resolve, open the operand, and are INVISIBLE to the observer, and "
        f"nothing declares them: {unregistered_invisible}. Add each to "
        f"`seams.INVISIBLE_ENGINES` with its exception class and its §D3 disposition -- "
        f"a silent invisibility is exactly the defect PDF-43 exists to make impossible"
    )


def test_ac6_the_static_walks_vocabulary_is_frozen_with_an_asserted_size() -> None:
    """AC6: `READ_ATTRS` / `READ_FUNCS` are frozen constants with an asserted size.

    RED: silently widen either set -> the size assertion fails.

    *A vocabulary that can be widened quietly is how blindness (a) survived three
    fixes.* Widening it is also not a repair: the next third-party API handed a
    path will not be in the widened list either, which is why the runtime observer
    exists at all.
    """
    assert len(seams.READ_ATTRS) == READ_ATTRS_SIZE, (
        f"READ_ATTRS moved to {sorted(seams.READ_ATTRS)}. This set is deliberately kept as "
        f"blind as the wave-7 walk it reproduces; changing it changes what AC2 measures"
    )
    assert len(seams.READ_FUNCS) == READ_FUNCS_SIZE, (
        f"READ_FUNCS moved to {sorted(seams.READ_FUNCS)}"
    )
    assert isinstance(seams.READ_ATTRS, frozenset) and isinstance(seams.READ_FUNCS, frozenset)


# --------------------------------------------------------------------------- #
# The engine-visibility probe. Runs in a CHILD, like every other use of the
# observer, and reports per engine whether its open reached the READ channel.
# --------------------------------------------------------------------------- #

_ENGINE_PROBE: Final = r"""
import json, os, sys

RECIPES = {
    "pypdf.PdfReader":                 lambda p: __import__("pypdf").PdfReader(p),
    "pikepdf.Pdf.open":                lambda p: __import__("pikepdf").Pdf.open(p).close(),
    "pypdfium2.PdfDocument":           lambda p: __import__("pypdfium2").PdfDocument(p).close(),
    "reportlab.lib.utils.ImageReader": lambda p: __import__(
        "reportlab.lib.utils", fromlist=["ImageReader"]).ImageReader(p),
    "PIL.Image.open": lambda p: __import__("PIL.Image", fromlist=["open"]).open(p).load(),
    "os.stat":                         lambda p: os.stat(p),
}

probe   = os.environ["PDF_SEAM_TARGET"]
ledger  = os.environ["PDF_SEAM_LEDGER"]
image   = os.environ["PDF_SEAM_PROBE_IMAGE"]

def reads():
    if not os.path.exists(ledger):
        return 0
    with open(ledger, encoding="utf-8") as handle:
        return sum(1 for line in handle if '"channel": "read"' in line)

out = {}
for dotted, call in RECIPES.items():
    subject = image if dotted in ("reportlab.lib.utils.ImageReader", "PIL.Image.open") else probe
    if subject != probe:
        out[dotted] = None            # driven operand is the PDF; skip mismatched subjects
        continue
    before = reads()
    try:
        call(subject)
    except Exception as error:
        out[dotted] = f"ERROR:{type(error).__name__}"
        continue
    out[dotted] = reads() > before

# NOT stderr. pypdf and pikepdf write their own diagnostics there ("invalid pdf
# header", "EOF marker not found"), and a payload sharing a channel with the
# subject under test is a payload that gets silently dropped -- which is how this
# probe first reported "engine not resolvable" for an engine it had measured.
with open(os.environ["PDF_SEAM_PROBE_OUT"], "w", encoding="utf-8") as handle:
    json.dump(out, handle)
"""


def _pdf_operand_at(target: Path) -> Path:
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(target))
    canvas.drawString(72, 720, "engine probe")
    canvas.showPage()
    canvas.save()
    return target


def _measure_engine_visibility(probe: Path, ledger: Path, workdir: Path) -> dict[str, object]:
    """Per registered engine: did its open of *probe* reach the READ channel?

    Engines whose natural subject is an image rather than a PDF are measured in a
    second pass against an image operand, so no engine is reported ``ERROR`` for
    the trivial reason that it was handed the wrong file type.
    """
    measured: dict[str, bool] = {}
    for subject, suffix in ((probe, ".pdf"), (_image_operand("JPEG", ".jpg")(workdir), ".jpg")):
        own_ledger = ledger.with_suffix(f"{suffix}.jsonl")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT / "tests" / "seam_sitecustomize"), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        env[seams.ENV_MODULE] = str(SEAMS_MODULE)
        env[seams.ENV_TARGET] = str(subject)
        env[seams.ENV_LEDGER] = str(own_ledger)
        env[seams.ENV_DEPTH] = ""
        env[seams.ENV_RACE] = seams.RACE_NONE
        env["PDF_SEAM_PROBE_IMAGE"] = str(subject)
        payload_path = own_ledger.with_suffix(".probe.json")
        env["PDF_SEAM_PROBE_OUT"] = str(payload_path)
        subprocess.run(
            [sys.executable, "-c", _ENGINE_PROBE],
            capture_output=True,
            text=True,
            cwd=workdir,
            env=env,
            timeout=180,
        )
        if not payload_path.exists():
            continue
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        for dotted, value in payload.items():
            if isinstance(value, bool):
                measured[dotted] = value
            elif dotted not in measured:
                measured[dotted] = value
    return measured


# --------------------------------------------------------------------------- #
# THE DEFENDED POPULATION -- AC4, AC5.
# --------------------------------------------------------------------------- #


def test_ac4_no_observed_seam_escapes_all_three_enumerators(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC4: the union of the buckets is asserted TOTAL.

    A seam observed at runtime that appears in **neither** the static enumerator
    **nor** the register is blindness (a) live -- something read the operand and
    no enumerator predicted it -- and it **fails, naming the frame**.

    **This is the arm that would have caught `09b8511ee8` on the day it was
    introduced**, and the red is mechanical: drop the
    `reportlab.lib.utils.ImageReader` entry from `seams.ENGINE_REGISTER` (the
    reportlab seam is in no static row, so nothing else covers it) and this arm
    fails naming `reportlab/lib/utils.py`.
    """
    _skip_as_root()
    static = seams.static_read_sites(SRC_ROOT)
    observed: list[dict[str, object]] = []
    for sweep in sweeps.values():
        _assert_installed(sweep)
        for cell in (sweep.control, *sweep.cells):
            observed.extend(cell.records)

    # The register is what keeps the reportlab seam out of `rogue`; assert it is
    # doing that job, or a register that silently stopped matching would show up
    # as a GREEN here rather than as the failure it is.
    assert seams.registered_engine_for("reportlab/lib/utils.py:463") is not None, (
        "no register entry matches a reportlab frame, so bucket 3 no longer covers the seam "
        "this instrument was built for -- AC4 would go green by covering nothing"
    )
    rogue = seams.unregistered_runtime_seams(observed, static)
    formatted = sorted({f"{r.get('first_party')} <- {r.get('origin')}" for r in rogue})
    assert formatted == [], (
        f"these opens of the driven operand were OBSERVED and no enumerator predicts them -- "
        f"not the static walk (their call shape is not read-shaped) and not the register "
        f"(nothing declares the engine): {formatted}. This is blindness (a), live. Either "
        f"belt the seam or DECLARE the engine; do not widen the static vocabulary, which "
        f"cannot fix the class"
    )


#: The `error.kind` the product returns when a verb's engine does not resolve --
#: `README.md`'s exit-code table's code `3`, and `PDF-67`/`OR-19`'s contract.
_ENGINE_MISSING_KIND: Final = "engine_missing"


def _skip_if_a_cell_never_drove(sweeps: dict[str, seams.Sweep]) -> None:
    """PDF-82 D3 -- the AC5 residue's PREMISE, read off the OBSERVED sweep.

    The arm below measures UNDRIVEN read seams against a ceiling that encodes
    *the drive happened*. Its premise is therefore not "soffice exists on this
    host" -- it is "every cell in `sweeps` actually drove", which is a fact about
    the drive and is read here from the cell's own un-raced control rather than
    from the host. A cell whose control refused with `engine_missing` never
    reached the adapter at all, so its module's residue is not a smaller number
    that a narrowed assertion could absorb: it is an **unanswerable question**,
    and the honest answer to one is a VISIBLE skip.

    Deliberately NOT `@pytest.mark.requires("soffice")` (`X-757`, `PDF-82` D3).
    Two reasons, the second load-bearing: the marker would state a fact about the
    host where this arm needs a fact about the drive; and the arm reaches its
    drive through the `sweeps` FIXTURE, spelling no verb of its own, so it is not
    in `tests/test_engine_gating_census.py`'s population and a marker here would
    red that module's own fitness assertion.

    The reason text names the engine, so `scripts/assert_skips.py` counts the
    skip in its `engine-gated` class rather than in the unclassified remainder.
    """
    for label, sweep in sorted(sweeps.items()):
        envelope = sweep.control.envelope or {}
        error = envelope.get("error")
        kind = error.get("kind") if isinstance(error, dict) else None
        if kind == _ENGINE_MISSING_KIND:
            pytest.skip(
                f"soffice unavailable: the {label!r} cell's un-raced control refused with "
                f"exit {sweep.control.exit_code} ({kind}), so that drive never reached the "
                f"adapter and this module's undriven residue is an unanswerable question "
                f"rather than a smaller number. tests/test_read_seams.py's RESIDUE_CEILING "
                f"(not tests/test_docs_antirot.py's) encodes a configuration in which every "
                f"cell drove, and X-757 rules that it stays where it is"
            )


def test_ac5_the_undriven_residue_is_counted_against_a_ceiling_that_may_not_grow(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC5: static seams never observed at runtime, per module, against a frozen ceiling.

    Residue is **undriven, therefore unproven**. It does not fail on sight -- the
    drive covers `compose` and `compress`, and a ceiling that pretended otherwise
    would make the instrument lie -- but it is counted, and it **may not grow**
    (`PDF-30`'s `RESIDUE_CEILING` precedent, X-373/X-421).

    **THE PREMISE, made explicit (`PDF-82` D3).** This count is taken against a
    configuration in which every cell in `sweeps` actually drove. A configuration
    where one could not -- `convert`'s cell with `soffice` absent, which refuses
    at the engine gate before the adapter is ever opened -- does not produce a
    smaller residue; it produces an unanswerable question, and
    `_skip_if_a_cell_never_drove` above skips visibly rather than counting it.

    RED: add an unreached `open(path)` in `ops/` -> residue +1 -> over ceiling ->
    red naming the module and the site.

    **Escalation, not tuning.** If a future engineer finds itself widening the
    drive in order to shrink this number, that is the moment to stop and escalate
    the list to the PM. The ratchet ships; the number stays visible at its size.
    """
    _skip_as_root()
    _skip_if_a_cell_never_drove(sweeps)
    static = seams.static_read_sites(SRC_ROOT)
    observed: list[str] = []
    for sweep in sweeps.values():
        _assert_installed(sweep)
        observed.extend(sweep.observed_first_party)

    remaining = seams.residue(static, sorted(set(observed)))
    counts = collections.Counter(site.module for site in remaining)

    grew = {
        module: (count, RESIDUE_CEILING.get(module, 0))
        for module, count in counts.items()
        if count > RESIDUE_CEILING.get(module, 0)
    }
    assert grew == {}, (
        f"undriven read seams grew past their frozen ceiling {{module: (now, ceiling)}}: {grew}. "
        f"The sites: "
        f"{[s.key for s in remaining if s.module in grew]}. "
        f"Raising the ceiling is anti-gaming; drive the seam or FILE it"
    )
    assert set(counts) <= set(RESIDUE_CEILING), (
        f"a module joined the residue with no ceiling entry: "
        f"{sorted(set(counts) - set(RESIDUE_CEILING))}"
    )
    assert read_seam_ratification_complaints(READ_SEAM_RESIDUE_LEDGER) == [], (
        "the read-seam ratification ledger does not verify. PDF-70 replaced the frozen "
        "`sum(...) == 44` literal with a PER-KEY walk, which is what this guard's own "
        "comment always claimed to be: a frozen TOTAL catches NET movement and is "
        "structurally blind to COMPENSATING movement, so a shrink in one module COULD "
        "silently pay for a growth in another whenever the shrinking module had slack. "
        "Lowering a ceiling is now ORDINARY -- append a record with direction='down' "
        "and a reason, no ruling needed. RAISING one still needs everything X-715 "
        "required; raising it to reach green is anti-gaming -- drive the seam or FILE it"
    )


# --------------------------------------------------------------------------- #
# PDF-70 -- the ratification verifier, self-tested in BOTH directions
# --------------------------------------------------------------------------- #
#
# The arm above asserts the verifier ACCEPTS the real, landed ledger. The arms
# below assert it REFUSES the movements X-715 forbids. Neither half establishes
# anything alone -- a verifier that accepts everything passes the arm above, a
# verifier that rejects everything passes every arm below -- and this product has
# already paid once for trusting a one-sided control (`PDF-44`).


def _rs_synthetic(
    direction: str, ceilings: dict[str, int], *, ruling: str = "", reason: str = "synthetic"
) -> _ReadSeamRatification:
    return _ReadSeamRatification(
        date="2026-09-15",
        spec="PDF-70",
        direction=direction,
        ceilings=MappingProxyType(dict(ceilings)),
        reason=reason,
        ruling=ruling,
    )


def _rs_genesis(ceilings: dict[str, int]) -> _ReadSeamRatification:
    return _ReadSeamRatification(
        date="2026-09-14",
        spec="PDF-70",
        direction="genesis",
        ceilings=MappingProxyType(dict(ceilings)),
        reason="synthetic genesis",
    )


def test_a_downward_read_seam_ratification_is_accepted_with_no_ruling() -> None:
    """PDF-70 AC4 -- the deliverable, on this instrument.

    An engineer who DRIVES a seam has made the product better and must be able
    to record the tightening without a PM ruling. Before PDF-70 the only way to
    re-tighten was to edit a constant frozen by an equality, so the reward for
    driving a seam was an act the instrument culture forbids -- and the ceiling
    silently kept the headroom instead.

    RED: require a ruling for a downward movement and this arm fires.
    """
    ledger = (
        _rs_genesis({"pdf_tooling/ops/crypto.py": 4}),
        _rs_synthetic("down", {"pdf_tooling/ops/crypto.py": 3}),
    )
    assert read_seam_ratification_complaints(ledger) == []


def test_an_unruled_read_seam_raise_is_refused_naming_the_module_and_both_values() -> None:
    """PDF-70 AC5. X-715's fourth condition, mechanized: an upward movement is
    structurally impossible without a ruling id in the diff.

    RED: drop the ruling requirement and this arm fires. Its other half is the
    test below."""
    ledger = (
        _rs_genesis({"pdf_tooling/ops/optimize.py": 3}),
        _rs_synthetic("up", {"pdf_tooling/ops/optimize.py": 4}),
    )
    complaints = read_seam_ratification_complaints(ledger)
    assert complaints, "an unruled raise must be REFUSED"
    joined = " ".join(complaints)
    assert "pdf_tooling/ops/optimize.py" in joined, joined
    assert "3" in joined and "4" in joined, joined
    assert "ruling" in joined, f"the missing field must be named: {joined}"


def test_a_ruled_read_seam_raise_is_accepted_so_x715s_own_path_still_works() -> None:
    """PDF-70 AC5 case (b'). X-715 is APPLIED here, never amended: the path it
    opened for `soffice_office.py` is exactly as available after PDF-70 as
    before, and an arm that refused every raise would have swapped one broken
    ratchet for another."""
    ledger = (
        _rs_genesis({"pdf_tooling/ops/optimize.py": 3}),
        _rs_synthetic(
            "up",
            {"pdf_tooling/ops/optimize.py": 4},
            ruling="X-999",
            reason=(
                "synthetic: pdf_tooling/ops/optimize.py gains one structurally "
                "unobservable site, with a control"
            ),
        ),
    )
    assert read_seam_ratification_complaints(ledger) == []


def test_the_compensating_swap_is_refused_per_module_regardless_of_the_total() -> None:
    """PDF-70 AC7 -- THE act this instrument's own comment claimed to catch.

    `crypto.py` 4 -> 3 and `optimize.py` 3 -> 4 leaves the total at 44. Driven
    against the pre-PDF-70 constant, `sum(RESIDUE_CEILING.values()) == 44`
    evaluated TRUE and the old guard accepted the swap -- recorded in PDF-70's
    Implementation Log. The old guard's only residual strength was that the swap
    had to be funded out of genuine slack in the shrinking module, because
    shrinking a ceiling below its measured count reds that module's own `grew`
    arm; so it was exactly as strong as the ABSENCE of slack, and slack is
    precisely what accumulates every time the product improves.

    RED: collapse this walk back onto a total and this arm goes green again.
    """
    ledger = (
        _rs_genesis({"pdf_tooling/ops/crypto.py": 4, "pdf_tooling/ops/optimize.py": 3}),
        _rs_synthetic("down", {"pdf_tooling/ops/crypto.py": 3, "pdf_tooling/ops/optimize.py": 4}),
    )
    assert sum(ledger[0].ceilings.values()) == sum(ledger[1].ceilings.values()), (
        "the fixture is only meaningful while the two totals agree"
    )
    complaints = read_seam_ratification_complaints(ledger)
    assert complaints, "a compensating swap must be REFUSED even though the total is unchanged"
    joined = " ".join(complaints)
    assert "pdf_tooling/ops/optimize.py" in joined, f"the RAISED module must be named: {joined}"


def test_a_read_seam_record_whose_direction_disagrees_with_its_movement_is_refused() -> None:
    """PDF-70 D4 case (e)."""
    ledger = (
        _rs_genesis({"pdf_tooling/ops/crypto.py": 4}),
        _rs_synthetic("down", {"pdf_tooling/ops/crypto.py": 5}),
    )
    joined = " ".join(read_seam_ratification_complaints(ledger))
    assert "direction='down'" in joined, joined


@pytest.mark.parametrize(
    ("label", "ledger"),
    (
        ("empty", ()),
        ("no genesis", (_rs_synthetic("down", {"m.py": 1}),)),
        ("genesis twice", (_rs_genesis({"m.py": 1}), _rs_genesis({"m.py": 1}))),
        ("reasonless", (_rs_genesis({"m.py": 1}), _rs_synthetic("down", {"m.py": 0}, reason=" "))),
        ("bad direction", (_rs_genesis({"m.py": 1}), _rs_synthetic("sideways", {"m.py": 0}))),
    ),
)
def test_a_malformed_read_seam_ledger_is_refused(label: str, ledger: object) -> None:
    assert read_seam_ratification_complaints(ledger), label  # type: ignore[arg-type]


def test_a_newly_added_module_key_is_held_to_the_upward_rules() -> None:
    """The act X-715 licensed ONCE. A key appearing is an upward movement from
    absent, not a free new mapping -- otherwise the one concession X-715 granted
    could be repeated silently by anyone."""
    ledger = (
        _rs_genesis({"pdf_tooling/ops/crypto.py": 4}),
        _rs_synthetic("up", {"pdf_tooling/ops/crypto.py": 4, "pdf_tooling/ops/office.py": 2}),
    )
    joined = " ".join(read_seam_ratification_complaints(ledger))
    assert "pdf_tooling/ops/office.py" in joined and "ruling" in joined, joined


def test_the_read_seam_ceiling_is_the_newest_ledger_record_not_a_writable_literal() -> None:
    """PDF-70 AC3, on this module. Without it the ledger is documentation and the
    constant is still freely editable.

    RED: re-introduce a hand-written `dict` literal beside the ledger -- the
    exact shape this constant had before PDF-70 -- and this arm fires.
    """
    module_path = Path(__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    bindings: list[ast.expr] = []
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", None) == "RESIDUE_CEILING"
        ):
            if node.value is not None:
                bindings.append(node.value)
        elif isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "RESIDUE_CEILING" for target in node.targets
        ):
            bindings.append(node.value)
    assert len(bindings) == 1, (
        f"{module_path.name} binds RESIDUE_CEILING {len(bindings)} times at module level"
    )
    value = bindings[0]
    assert not isinstance(value, ast.Dict), (
        "RESIDUE_CEILING is bound to a literal `dict` display again. The live ceiling "
        "must BE the newest ratification record's mapping, so moving it is impossible "
        "without appending a record"
    )
    assert isinstance(value, ast.Attribute) and value.attr == "ceilings", ast.dump(value)
    subscript = value.value
    assert isinstance(subscript, ast.Subscript), ast.dump(value)
    assert getattr(subscript.value, "id", None) == "READ_SEAM_RESIDUE_LEDGER", ast.dump(value)


def test_x715s_reasoning_survives_the_refactor_onto_the_genesis_record() -> None:
    """PDF-70 AC9. X-715.4's lesson, applied to X-715 itself: *an amendment
    scoped by location loses what was not enumerated.* PDF-70 moved this
    constant into a ledger record, and the danger of any such move is that the
    surrounding justification is dropped as incidental.

    What must survive is not the number -- the number is asserted elsewhere --
    but the four conditions, the CLASS, and above all the CONTROL: that
    `ops/compose.py:538` is observed while `:539` is residual under the identical
    idiom, which is the evidence that the concession is structural rather than a
    ceiling raised to reach green.

    RED, mechanical: delete the comment block from the genesis entry, or blank
    the record's reason, and this arm fires.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    entry = source.index('"pdf_tooling/adapters/soffice_office.py"')
    preceding = source[:entry].rsplit('"pdf_tooling/adapters/pypdf_structure.py"', 1)[-1]
    for needle in (
        "X-715",
        "THE CLASS",
        "THE CONTROL",
        "ops/compose.py:538",
        ":539",
        "FORWARD-LOOKING BY ONE COMMIT",
        "decision.md",
    ):
        assert needle in preceding, (
            f"X-715's justification for the soffice_office.py entry lost {needle!r} in "
            "the PDF-70 refactor; an amendment scoped by location loses what was not "
            "enumerated (X-715.4)"
        )

    genesis = READ_SEAM_RESIDUE_LEDGER[0]
    assert genesis.ruling == "X-715", genesis.ruling
    assert "X-715" in genesis.reason and "compose.py:538" in genesis.reason, genesis.reason


# --------------------------------------------------------------------------- #
# PDF-63 D3/D4 -- the `PK`-claiming branch, driven OUTSIDE `_SWEEP_SPECS`, and
# the `OSError`-catch reachability answer (E6).
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_convert_zip_claim_branch_and_the_oserror_catch_reachability(tmp_path: Path) -> None:
    """The `PK`-claiming branch of `ensure_source_loadable`, driven directly.

    **Kept OUT of `_SWEEP_SPECS` on purpose (D3).** A `PK\\x03\\x04`-prefixed
    operand routes past the early return into `zipfile.is_zipfile`/
    `zipfile.ZipFile` -- neither call is read-shaped (invisible to the static
    walk) and `zipfile` is registered nowhere (invisible to bucket 3), so
    driving it INSIDE the `sweeps` population would redden
    `test_ac4_no_observed_seam_escapes_all_three_enumerators` naming the frame
    (E5) -- a strictly worse trade than the AC5 red this spec exists to clear.
    Driven here, standalone, it informs this criterion without enlarging that
    population.

    **What it answers (D4, E6): is `soffice_office.py`'s `except OSError:
    return` reachable, and does it mispredict?** The catch's own ground is
    that an unreadable operand is "`ops/batch.py` rung 4 ... reached before
    this ever runs" -- true of a STATICALLY unreadable operand, untested
    against a RACING one. Driven at `depth=None` (control) and
    `depth=FIRST_ORDINAL` (the operand becomes unreadable at its own first
    open), the two hypotheses give different exit codes, so the answer is
    decisive rather than assumed.

    **Measured answer: reachable, and silent.** Filed as F-1 (§D6) -- not
    fixed here, since fixing it means editing `soffice_office.py`, which is
    both `src/**` and one of `PDF-53`'s seven files.

    RED (the zip branch, D3): change the operand's leading bytes away from
    `PK\\x03\\x04` -> the control no longer reaches `zipfile.is_zipfile` and
    the message assertion below fails.
    RED (the `OSError` answer, D4): delete `soffice_office.py`'s
    `except OSError: return` in a scratch worktree -> the depth-1 cell stops
    exiting 0 (it raises instead, or a caller further up turns it into a
    traceback -- either is a `PDF-53` defect to REPORT, never to fix here).

    **§Sequencing note.** `PDF-63` lands FIRST, `PDF-53` second, one push
    (drive-first, X-715.1). At `PDF-63`'s own commit `soffice_office.py`
    carries no container triage at all -- there is nothing for this arm to
    drive yet -- so it SKIPS, visibly and by name, rather than asserting a
    behaviour that does not exist on that tree (the `test_ac16_…` interpreter-
    availability precedent: "skips visibly with a reason and never passes
    silently"). It runs, and asserts in full, once `PDF-53`'s diff lands.
    """
    _skip_as_root()
    adapter_source = (SRC_ROOT / "pdf_tooling" / "adapters" / "soffice_office.py").read_text()
    if "ensure_source_loadable" not in adapter_source:
        pytest.skip(
            "PDF-63 lands before PDF-53 in this push (drive-first, decision.md §11.5, "
            "X-715.1); soffice_office.py's container triage does not exist at this commit, "
            "so there is nothing for this arm to drive yet"
        )

    def _pk_claim_operand(directory: Path) -> Path:
        target = directory / "operand.docx"
        # `PK\x03\x04` claims a ZIP container; the trailing bytes are not one,
        # so `zipfile.is_zipfile` returns False -- E5's "malformed zip" shape.
        target.write_bytes(b"PK\x03\x04" + b"not a real zip container, only its magic bytes\n")
        return target

    site_pattern = re.compile(r"^pdf_tooling/adapters/soffice_office\.py:\d+$")

    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control_operand = _pk_claim_operand(control_dir)
    control = seams.drive_cell(
        argv=_convert_dry_argv(control_operand, control_dir),
        operand=control_operand,
        workdir=control_dir,
        depth=None,
        race=seams.RACE_UNREADABLE,
    )
    assert control.exit_code == 1, (
        f"the un-raced control should refuse the malformed zip container: "
        f"exit={control.exit_code} stdout={control.stdout[:300]} stderr={control.stderr[:300]}"
    )
    assert "not a loadable office document (malformed zip container)" in (
        control.stdout + control.stderr
    ), f"the container-refusal message drifted: {control.stdout[:300]} {control.stderr[:300]}"
    control_sites = [str(row.get("first_party", "")) for row in control.channel(seams.CHANNEL_READ)]
    in_module = [site for site in control_sites if site_pattern.match(site)]
    assert len(set(in_module)) == 2, (
        f"the control must open the operand at exactly two DISTINCT sites inside this adapter "
        f"-- the head-read site and `zipfile.is_zipfile`'s own open -- got {control_sites}"
    )

    raced_dir = tmp_path / "depth-1"
    raced_dir.mkdir()
    raced_operand = _pk_claim_operand(raced_dir)
    raced = seams.drive_cell(
        argv=_convert_dry_argv(raced_operand, raced_dir),
        operand=raced_operand,
        workdir=raced_dir,
        depth=seams.FIRST_ORDINAL,
        race=seams.RACE_UNREADABLE,
    )
    reads = raced.channel(seams.CHANNEL_READ)
    flipped = [row for row in reads if row.get("flipped")]
    assert flipped, f"the depth-1 cell never raced the operand: {reads}"
    assert flipped[0]["ordinal"] == seams.FIRST_ORDINAL, flipped
    assert site_pattern.match(str(flipped[0]["first_party"])), flipped
    assert raced.exit_code == 0, (
        f"depth {seams.FIRST_ORDINAL}: the `OSError` catch answer flipped -- expected exit 0 "
        f"(silent, reachable) but got exit {raced.exit_code}: "
        f"stdout={raced.stdout[:300]} stderr={raced.stderr[:300]}"
    )
    envelope = raced.envelope
    assert envelope is not None, f"depth {seams.FIRST_ORDINAL}: no parsable `-o json` envelope"
    items = envelope.get("items")
    assert items and all(item.get("ok") is True for item in items), (
        f"depth {seams.FIRST_ORDINAL}: expected every item ok=True (the catch's silent return), "
        f"got {items}"
    )


# --------------------------------------------------------------------------- #
# THE MULTI-SEAM DRIVE -- AC7, AC8, AC9.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label", sorted(_SWEEP_SPECS))
def test_ac7_the_sweep_ceiling_is_derived_and_exhaustion_is_proven(
    label: str, sweeps: dict[str, seams.Sweep]
) -> None:
    """AC7: `K = M + 1`, and at `depth = K` the flip never fires.

    **This is the criterion that proves the sweep ran past the last seam rather
    than stopping where somebody guessed.** At `K` there is no `K`-th open, so the
    cell must be indistinguishable from the un-raced control -- same exit code,
    same envelope shape, no traceback. A sweep whose top cell matches its control
    has *provably* exhausted the operand's seams.

    RED: pin the ceiling to the wave-7 literal `range(1, 9)`. The
    `compress/PDF-delete` cell derives `M = 14`, so a literal ceiling of 9 stops
    at depth 8 -- a depth at which the flip DOES fire, so the exhaustion cell no
    longer matches the control **and** the seam this spec closes at depth 12 is
    never reached at all. (On `compose/JPEG`, `M = 4`, so a literal 9 would *not*
    fail this assertion -- which is exactly why the drive is not single-celled.)
    """
    _skip_as_root()
    sweep = sweeps[label]
    _assert_installed(sweep)

    assert sweep.ceiling == sweep.clean_opens + 1, "the ceiling must be DERIVED from M"
    assert len(sweep.cells) == sweep.ceiling, (
        f"{label}: the sweep must cover {seams.FIRST_ORDINAL}..K inclusive, "
        f"got {len(sweep.cells)} cells"
    )
    assert sweep.exhaustion.depth == sweep.ceiling
    assert not sweep.exhaustion.flipped, (
        f"{label}: the flip FIRED at depth K={sweep.ceiling}, so there was a K-th touch and the "
        f"ceiling is not exhaustive -- M was measured wrong"
    )
    assert sweep.exhaustion_matches_control, (
        f"{label}: the exhaustion cell does not match the un-raced control "
        f"(exhaustion={sweep.exhaustion.shape} control={sweep.control.shape}); the sweep has NOT "
        f"provably run past the last seam and every 'no seam here' below it is unproven"
    )


def test_ac8_the_shadowing_is_reported_as_two_separate_figures(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC8 -- THE BLINDNESS-(b) CONTROL, and both numbers are reported.

    The drive reports *tracebacking seams at the first ordinal* and *tracebacking
    seams across the whole sweep* as **two separate figures**, so the shadowing is
    a number in every run rather than a fact somebody has to remember.

    At the pre-fix working commit these were `0` and `1` for both `compose/JPEG`
    (the reportlab seam, depth 4) and `compress/PDF-delete` (the `stat` seam,
    depth 12) -- i.e. *"0 tracebacking seams"* under the wave-7 condition, and a
    live defect one seam further in. **Both are now 0 and 0**, and the arm asserts
    the pair rather than the first figure alone.

    RED: pin the drive to the first ordinal -> the second figure collapses onto
    the first and both seams disappear, which is the wave-7 measurement
    reproduced and shown shadowed.
    """
    _skip_as_root()
    for label in ("compose/JPEG", "compress/PDF-delete"):
        sweep = sweeps[label]
        _assert_installed(sweep)
        assert sweep.tracebacks_at_first_ordinal == 0, f"{label}: first-ordinal traceback"
        assert sweep.tracebacks_across_sweep == 0, (
            f"{label}: {sweep.tracebacks_across_sweep} tracebacking seam(s) at depths "
            f"{sweep.tracebacking_depths}. The first-ordinal figure is "
            f"{sweep.tracebacks_at_first_ordinal}, which is precisely the shadowing this arm "
            f"exists to expose: a drive that only reported the first figure would call this GREEN"
        )
        assert sweep.ceiling > seams.FIRST_ORDINAL, (
            f"{label}: a sweep of one cell cannot distinguish the two figures at all"
        )


def test_ac9_the_format_dimension_is_derived_and_non_singleton(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC9: for a verb accepting more than one input class, the drive covers more than one.

    The classes come from **the product's own verdict** -- `inspect_image`'s
    `passthrough` -- never from a file extension, which is the pattern
    `test_the_compose_decode_arm_reaches_the_seam_it_names` already uses.

    This exists because of the sharpest lesson on this product's record: the
    `:518` decode arm's PNG fixture was **not vacuous** and still routed the arm
    around a live defect, because PNG takes the re-encode path and JPEG takes the
    passthrough path -- and the passthrough path held the unbelted seam. *A
    control that entrenches a blind spot is a new failure mode, and no vacuity
    check detects it.*

    RED: drive `compose` with PNG only -> the `09b8511ee8` seam is not reached at
    any depth and this arm fails.
    """
    _skip_as_root()
    from pdf_tooling.ops.compose import inspect_image

    with tempfile.TemporaryDirectory() as raw:
        scratch = Path(raw)
        jpeg_dir = scratch / "jpeg"
        png_dir = scratch / "png"
        jpeg_dir.mkdir()
        png_dir.mkdir()
        jpeg_facts = inspect_image(_image_operand("JPEG", ".jpg")(jpeg_dir), dpi_flag=None)
        png_facts = inspect_image(_image_operand("PNG", ".png")(png_dir), dpi_flag=None)

    assert jpeg_facts.passthrough != png_facts.passthrough, (
        "the two operands must land on DIFFERENT compose paths by the product's own verdict, "
        f"or the format dimension is a singleton wearing two extensions "
        f"(jpeg.passthrough={jpeg_facts.passthrough} png.passthrough={png_facts.passthrough})"
    )

    driven = {label for label in sweeps if label.startswith("compose/")}
    assert len(driven) > 1, f"compose accepts more than one input class; the drive covers {driven}"

    jpeg_frames = set(sweeps["compose/JPEG"].observed_first_party)
    png_frames = set(sweeps["compose/PNG"].observed_first_party)
    only_via_jpeg = jpeg_frames - png_frames
    assert any("reportlab_compose" in frame for frame in only_via_jpeg), (
        f"the passthrough-only seam is not reached by the JPEG drive, so the format dimension "
        f"is not buying what it is here to buy. JPEG-only frames: {sorted(only_via_jpeg)}"
    )
    assert not any("reportlab_compose" in frame for frame in png_frames), (
        "PNG reached the reportlab passthrough seam, which contradicts the re-encode routing "
        "this arm's asymmetry rests on -- re-derive before trusting either figure"
    )


# --------------------------------------------------------------------------- #
# THE THREE SEAMS -- AC10, AC11, AC12, AC13, AC14.
# --------------------------------------------------------------------------- #


def test_ac10_the_reportlab_boundary_seam_is_coded_at_every_derived_depth(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC10 -- `09b8511ee8` closed, at EVERY depth in the derived sweep.

    `compose <toctou-unreadable .jpg> -o json` exits 1, writes a parseable
    envelope on stdout (**non-empty**), writes no traceback on stderr, and the
    envelope **names the failing operand**.

    *Pre-fix at this working commit, depth 4 (the reportlab seam):* exit 1,
    **0 bytes of stdout**, and a traceback of **5836-5848 bytes** on stderr --
    the size varies with the temp path's length, which is why the recorded figure
    is a measurement and not a pinned literal.

    RED: remove `_engine_boundary_error`'s handler at
    `ops/compose.py::compose_images` -> the traceback returns at the depths AC9
    identifies, and at those depths only.
    """
    _skip_as_root()
    sweep = sweeps["compose/JPEG"]
    _assert_installed(sweep)

    for cell in sweep.cells[:-1]:
        assert cell.exit_code == 1, (
            f"depth {cell.depth}: an operand that EXISTS and cannot be READ is an operation "
            f"that ran and failed (exit 1), got {cell.exit_code}"
        )
        assert _TRACEBACK not in (cell.stdout + cell.stderr), (
            f"depth {cell.depth}: a traceback of {cell.stderr_bytes} bytes reached the user. "
            f"stderr tail: {cell.stderr.strip().splitlines()[-1:]}"
        )
        assert cell.stdout_bytes > 0, f"depth {cell.depth}: ZERO bytes of stdout under -o json"
        envelope = cell.envelope
        assert envelope is not None, f"depth {cell.depth}: stdout is not a parseable envelope"
        error = envelope.get("error")
        assert isinstance(error, dict) and error.get("path"), (
            f"depth {cell.depth}: the envelope does not name the failing operand -- {envelope}. "
            f"Attribution comes from the placement list the caller already holds, never from "
            f"parsing the engine's message"
        )


def test_ac10_the_boundary_seam_is_coded_under_the_directory_race_too(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC10, second condition: the mode race is not the only way an operand goes bad.

    The mode-000 race can never reach `source_read_error`'s bottom rung, because
    that ladder asks the accessibility question FIRST and answers "exists but
    cannot be read". Replacing the operand with a **directory** is the condition
    the `48766ee6f2` row actually recorded (`[Errno 21] Is a directory`), and it
    reaches both the noun rung and the engine boundary.
    """
    _skip_as_root()
    sweep = sweeps["compose/JPEG-dir"]
    _assert_installed(sweep)

    for cell in sweep.cells[:-1]:
        assert _TRACEBACK not in (cell.stdout + cell.stderr), (
            f"depth {cell.depth}: traceback under the directory race ({cell.stderr_bytes} bytes)"
        )
        envelope = cell.envelope
        assert envelope is not None and isinstance(envelope.get("error"), dict), (
            f"depth {cell.depth}: no coded envelope -- {cell.stdout[:200]!r}"
        )
        assert envelope["error"].get("path"), (
            f"depth {cell.depth}: the envelope names no operand -- {envelope}"
        )


def test_ac11_every_ops_to_engine_path_handoff_is_enumerated_and_bounded() -> None:
    """AC11 -- THE RULE IS ENFORCED, not just the instance.

    **This is the criterion that distinguishes this spec from a fourth belt.** A
    static arm enumerates every call from `ops/**` into an engine whose port
    signature hands it an operand-derived path, and freezes the population. A new
    such call is a red **on the day it is written**, not a traceback a verifier
    finds eight weeks later.

    The enumerated population and its recipe are published in the Implementation
    Log. RED: add a thirteenth `engine.open_document(<path>)` in `ops/` -> over
    ceiling -> red naming the file and line.

    **A DELIBERATE LIMIT, STATED RATHER THAN DISCOVERED.** This arm does not
    assert that every enumerated site carries an `ops/`-side handler. Eleven of
    the twelve do not: their reads are mapped by the **adapter**, which is
    allowed to do so -- `pypdf_structure.py` and `pdfplumber_text.py` both import
    `source_read_error` and both use it. Asserting an ops-side belt at all twelve
    would demand eleven redundant belts across nine modules, far outside this
    spec's scope, and would say nothing true. What is asserted instead is that
    the population **cannot grow unnoticed**, and that every site the drive
    actually reaches produces a coded failure rather than a traceback.
    """
    sites = seams.engine_boundary_sites(SRC_ROOT)
    assert len(sites) <= BOUNDARY_SITE_CEILING, (
        f"the ops->engine path-handoff population grew to {len(sites)} (ceiling "
        f"{BOUNDARY_SITE_CEILING}); new sites: {[s.key for s in sites]}. When `ops/` hands an "
        f"operand path across an engine boundary, that read failure is OWNED -- by the "
        f"adapter, or by the `ops/` caller that supplied the path. Belt it or declare it"
    )
    assert sites, "the enumerator found nothing, so this arm is vacuous"

    belted = [site for site in sites if site.ops_belted]
    assert any("compose.py" in site.module for site in belted), (
        f"`ops/compose.py`'s `compose_images` boundary must carry the D5 handler -- it is the "
        f"one site whose adapter provably cannot map the read (reportlab performs it inside "
        f"`drawImage`, and a belt there would be the FOURTH point-fix). Belted: "
        f"{[s.key for s in belted]}"
    )

    can_self_belt = seams.adapters_importing_safety(SRC_ROOT)
    assert can_self_belt, (
        "no adapter imports `safety/`, which would make the adapter-side coverage bucket empty "
        "and every unbelted enumerated site an unmapped seam. Re-derive before trusting AC11"
    )


def test_ac12_a_non_pdf_operand_never_gets_a_pdf_noun(sweeps: dict[str, seams.Sweep]) -> None:
    """AC12 -- `48766ee6f2` closed as a PROPOSITION, not as a string.

    For every seam the observer attributes to a **non-PDF** operand, the resulting
    envelope's message does not name PDF.

    This is deliberately **not an exact-phrase grep**: `B-101` proved a grep
    answers *"is this STRING gone"*, not *"is this CLAIM gone"*, and `B-106`
    survived one because a fourth copy stated the same proposition in different
    words. The check here is a property over **observed** seams, which the
    instrument can only express because the observer exists -- a small
    demonstration that the instrument pays for itself.

    *Pre-fix at this working commit*, the directory race at depth 3 yielded
    `{"code":1,"kind":"failure","message":"could not read PDF: [Errno 21] Is a
    directory: '.../photo.jpg'"}` against a `.jpg`. RED: restore the
    unconditional fallback noun in `safety/paths.py::source_read_error` -> red.
    """
    _skip_as_root()
    for label in ("compose/JPEG", "compose/JPEG-dir"):
        sweep = sweeps[label]
        _assert_installed(sweep)
        for cell in sweep.cells:
            envelope = cell.envelope
            if envelope is None or not isinstance(envelope.get("error"), dict):
                continue
            message = str(envelope["error"].get("message", ""))
            assert "PDF" not in message, (
                f"{label} depth {cell.depth}: the operand is an IMAGE and the failure names PDF "
                f"-- {message!r}. The noun is a property of the OPERAND, not a fallback string; "
                f"this is the exact falsehood `PDF-26` removed at `create` and reinstated at "
                f"`compose`"
            )

    # The other half of the proposition, and the half a suffix cannot carry. The
    # operand below is a JPEG *named* `.bin`, so the derived default answers with
    # the generic noun; only the explicit `noun=IMAGE_NOUN` at the frame-header
    # read -- which takes its class from `inspect_image`'s own verdict, never
    # from the extension -- can name it an image.
    from pdf_tooling.safety.paths import GENERIC_NOUN, IMAGE_NOUN

    unnamed = sweeps["compose/JPEG-as-bin"]
    _assert_installed(unnamed)
    nouns = {
        str((cell.envelope or {}).get("error", {}).get("message", ""))
        for cell in unnamed.cells
        if isinstance((cell.envelope or {}).get("error"), dict)
    }
    read_seam_messages = [message for message in nouns if message.startswith("could not read ")]
    assert read_seam_messages, f"no read-seam message observed for the .bin cell: {nouns}"
    assert not any(GENERIC_NOUN in message for message in read_seam_messages), (
        f"the operand is a JPEG by the PRODUCT'S OWN VERDICT and the failure fell back to the "
        f"generic noun {GENERIC_NOUN!r} because the file happens to be named `.bin`: "
        f"{read_seam_messages}. The class comes from `inspect_image`, never from a suffix"
    )
    assert any(IMAGE_NOUN in message for message in read_seam_messages), (
        f"no read-seam failure named the image class: {read_seam_messages}"
    )


def test_ac13_the_metadata_seam_is_coded_and_the_two_populations_are_disjoint(
    sweeps: dict[str, seams.Sweep],
) -> None:
    """AC13 -- `37b355b19a` closed as a METADATA seam, with §D3 left exactly as wide.

    Under the **delete** race, `compress` with an operand removed between
    `classify_operand` and `ops/optimize.py`'s size probe exits with a **coded
    envelope and no traceback**.

    **On the exit code, and this is a correction to the criterion as drafted.**
    The spec says "exits 1". The product's own vocabulary for an operand that no
    longer exists is `NoInputError` -> **exit 4** ("no such file"), which is what
    `classify_operand`'s rung 1 already returns for the identical condition at six
    other depths of this very sweep, and what `source_read_error`'s own
    `FileNotFoundError` rung returns. Exit 1 here would make the `stat` seam
    disagree with the classifier that governs it. This arm therefore asserts the
    seam is CODED and agrees with the classifier, and the divergence from the
    drafted "1" is reported rather than silently satisfied.

    *Pre-fix at this working commit*: depth 12 exited 1 with **0 bytes of stdout**
    and a **4289-byte** `FileNotFoundError` traceback.

    RED: remove the `metadata_probe_error` handler at `ops/optimize.py` -> the
    traceback returns at depth 12 and only there.
    """
    _skip_as_root()
    sweep = sweeps["compress/PDF-delete"]
    _assert_installed(sweep)

    from pdf_tooling.errors import NoInputError

    coded_codes = {1, NoInputError.exit_code, 2}
    for cell in sweep.cells[:-1]:
        assert _TRACEBACK not in (cell.stdout + cell.stderr), (
            f"depth {cell.depth}: a {cell.stderr_bytes}-byte traceback at a METADATA seam. "
            f"stderr tail: {cell.stderr.strip().splitlines()[-1:]}"
        )
        assert cell.stdout_bytes > 0, f"depth {cell.depth}: zero bytes of stdout under -o json"
        assert cell.exit_code in coded_codes, (
            f"depth {cell.depth}: exit {cell.exit_code} is outside the product's coded set"
        )

    # THE CLASS BOUNDARY, mechanised. §D3 is a READ-seam class and this spec does
    # not widen it to swallow whatever the instrument happened to find.
    read_frames: set[str] = set()
    meta_frames: set[str] = set()
    for other in sweeps.values():
        for cell in (other.control, *other.cells):
            for row in cell.channel(seams.CHANNEL_READ):
                read_frames.add(str(row.get("first_party", "")))
            for row in cell.channel(seams.CHANNEL_META):
                meta_frames.add(str(row.get("first_party", "")))
    overlap = sorted(read_frames & meta_frames)
    assert overlap == [], (
        f"these seams are counted on BOTH channels: {overlap}. The read population and the "
        f"metadata population must be disjoint -- a `stat` site inside §D3's read ledger would "
        f"enlarge a WITHHELD verification's scope using this spec's own findings"
    )
    assert meta_frames, "the metadata channel observed nothing, so the disjointness is vacuous"


def test_ac14_the_metadata_population_is_scoped_published_and_frozen() -> None:
    """AC14: the operand-reachable metadata population, with its recipe and a ceiling.

    The unscoped census over `src/` deliberately OVER-READS -- it counts
    write-target and temp-name probes that are not operand metadata seams at all,
    and `git grep -c` counts *lines*, so a line with two calls counts once. The
    scoping rule is stated in `seams.metadata_sites` and both figures are
    published, so the scoping can be **audited rather than trusted**.

    **Where the scoping is incomplete, this says so with a number**: a metadata
    seam on a code path the drive does not reach is residue, exactly as in AC5.
    An unstated limit is what produced this whole item.

    RED: add an unbelted operand `stat()` in `ops/` -> population +1 -> over
    ceiling -> red.
    """
    scoped = seams.metadata_sites(SRC_ROOT)
    assert len(scoped) <= METADATA_POPULATION_CEILING, (
        f"the scoped metadata population grew to {len(scoped)} (ceiling "
        f"{METADATA_POPULATION_CEILING}). Every metadata seam that can see an operand is either "
        f"belted or counted; a new one is neither until someone says which"
    )
    assert scoped, "the metadata enumerator found nothing, so this arm is vacuous"
    assert any(site.module.endswith("ops/optimize.py") for site in scoped), (
        "`ops/optimize.py` holds the seam this criterion is named for; its absence means the "
        "scoping rule stopped covering the site it was written for"
    )


# --------------------------------------------------------------------------- #
# MECHANISM PORTABILITY AND HYGIENE -- AC16, AC19.
# --------------------------------------------------------------------------- #

#: A self-contained mechanism probe. It uses NO third-party package, so it runs
#: on any supported interpreter without the product being installed there --
#: `shutil.copyfile` is the stdlib's own "hand a callee a path and let it open
#: the file" shape, which is structurally the same thing `drawImage` does and is
#: equally invisible to a walk that greps for `read_bytes` / `open` / `Image`.
_MECHANISM_PROBE: Final = r"""
import json, os, pathlib, shutil, sys

target = os.environ["PDF_SEAM_TARGET"]
ledger = os.environ["PDF_SEAM_LEDGER"]

shutil.copyfile(target, target + ".copy")
pathlib.Path(target).stat()

rows = []
if os.path.exists(ledger):
    with open(ledger, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

sys.stderr.write(json.dumps({
    "install_errors": [r for r in rows if r.get("channel") == "install-error"],
    "read":  [r for r in rows if r.get("channel") == "read"],
    "meta":  [r for r in rows if r.get("channel") == "meta"],
    "version": "%d.%d" % sys.version_info[:2],
}))
"""


def _supported_interpreter_series() -> list[str]:
    """Every interpreter series the product supports, DERIVED not listed.

    `requires-python` gives the floor; the CI matrix gives the roster that
    actually runs. Parsed with a regex rather than a YAML dependency, because
    AC18 forbids adding one.
    """
    floor = re.search(
        r'requires-python\s*=\s*"[^0-9]*(\d+)\.(\d+)"', (REPO_ROOT / "pyproject.toml").read_text()
    )
    assert floor is not None, "requires-python is unreadable; AC16's roster cannot be derived"
    series = {f"{floor.group(1)}.{floor.group(2)}"}
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if workflow.exists():
        for line in workflow.read_text().splitlines():
            if "python-version:" in line and "[" in line:
                series.update(re.findall(r'"(\d+\.\d+)"', line))
    return sorted(series, key=lambda item: tuple(int(part) for part in item.split(".")))


def _resolve_interpreter(series: str) -> str | None:
    """Locate `python<series>`, including interpreters uv manages off `PATH`.

    `shutil.which` alone reported "3.13 is not installed" on a host where uv had
    3.13.14 sitting in its own store. **A skip that could have run is a walk-past**
    -- it turns a leg this criterion is supposed to measure into a silent pass,
    which is the same shape of defect as the blindness this whole module exists
    to close.
    """
    found = shutil.which(f"python{series}")
    if found:
        return found
    if shutil.which("uv") is None:
        return None
    probe = subprocess.run(
        ["uv", "python", "find", series], capture_output=True, text=True, timeout=60
    )
    candidate = probe.stdout.strip()
    return candidate if probe.returncode == 0 and Path(candidate).exists() else None


@pytest.mark.parametrize("series", _supported_interpreter_series())
def test_ac16_the_observers_mechanism_holds_on_every_supported_interpreter(
    series: str, tmp_path: Path
) -> None:
    """AC16: the mechanism is pinned on every interpreter the product supports.

    The `open` audit event has existed since 3.8, but **the number of opens a
    library performs per seam is a property of the installed versions**, and
    `pathlib`'s internals have been rewritten more than once across
    `>=3.11`. So what is pinned here is the MECHANISM, never a count:

    * a callee handed a path raises an `open` audit event the caller's call shape
      cannot reveal -- blindness (a) is closed on this interpreter;
    * `os.stat` is the bottom of `pathlib.Path.stat()`, so the metadata channel
      has a real single interception point on this interpreter;
    * the observer installs without error.

    An interpreter that is not installed here **skips visibly with a reason** and
    never passes silently.

    RED: introduce a hard-coded expected open count into `tests/seams.py` -> the
    companion no-literals arm fails; break the `os.stat` wrapper -> the metadata
    assertion fails on every leg.
    """
    interpreter = _resolve_interpreter(series)
    if interpreter is None:
        pytest.skip(f"python{series} is not installed on this host; AC16's leg cannot be measured")

    operand = tmp_path / "operand.bin"
    operand.write_bytes(b"seam mechanism probe\n")
    ledger = tmp_path / f"mech-{series}.jsonl"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "tests" / "seam_sitecustomize")
    env[seams.ENV_MODULE] = str(SEAMS_MODULE)
    env[seams.ENV_TARGET] = str(operand)
    env[seams.ENV_LEDGER] = str(ledger)
    env[seams.ENV_DEPTH] = ""
    env[seams.ENV_RACE] = seams.RACE_NONE
    completed = subprocess.run(
        [interpreter, "-c", _MECHANISM_PROBE],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, f"python{series} probe failed: {completed.stderr[-600:]}"
    payload = json.loads(completed.stderr)

    assert payload["install_errors"] == [], (
        f"python{series}: the observer failed to install -- {payload['install_errors']}"
    )
    assert payload["version"] == series, f"resolved python{series} reports {payload['version']}"

    assert payload["read"], (
        f"python{series}: `shutil.copyfile` was handed the operand PATH and opened it, and the "
        f"observer saw NOTHING. Blindness (a) is not closed on this interpreter"
    )
    origins = {row["origin"] for row in payload["read"]}
    assert any("shutil" in origin for origin in origins), (
        f"python{series}: the open was not attributed to the callee that performed it -- "
        f"origins {sorted(origins)}. Attribution is what names `reportlab` rather than `ops/`"
    )
    assert payload["meta"], (
        f"python{series}: `Path.stat()` raised no METADATA record, so `os.stat` is not the "
        f"bottom of `Path.stat()` here and the metadata channel would silently return zero -- "
        f"which is the exact failure shape this instrument exists to prevent"
    )


def test_ac16_no_open_count_depth_or_ordinal_is_a_literal_in_the_instrument() -> None:
    """AC16's other half: `tests/seams.py` hard-codes no measured quantity.

    RED: add `assert opens == 4` (or any such comparison) to `tests/seams.py` ->
    this arm fails. Recipe, published so it can be re-run by hand:
    `git grep -nE '(depth|ordinal|opens)\\s*==\\s*[0-9]' -- tests/seams.py`
    """
    pattern = re.compile(r"(depth|ordinal|opens)\s*==\s*[0-9]")
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(SEAMS_MODULE.read_text().splitlines(), start=1)
        if pattern.search(line)
    ]
    assert offenders == [], (
        f"the instrument hard-codes a measured quantity: {offenders}. `M`, `K` and every depth "
        f"are DERIVED per run, because the number of opens a library performs per seam is a "
        f"property of the installed versions and of the interpreter"
    )


def test_ac19_the_coverage_floor_is_untouched_at_its_single_site() -> None:
    """AC19: `--cov-fail-under=85` remains, at its single real site, unmoved.

    `pyproject.toml` mentions the flag **in a comment** and is not a second
    setting. Checked BY VALUE rather than by line number, because line numbers rot
    and this guard must not.

    RED: any change to that token -- in either direction. `PDF-06`'s rule stands:
    if the floor is unreachable the answer is more tests, never a lower
    `fail_under`.
    """
    makefile = (REPO_ROOT / "Makefile").read_text()
    settings = re.findall(r"--cov-fail-under=(\d+)", makefile)
    assert settings == ["85"], (
        f"the coverage floor in the Makefile is now {settings}. It is not raised, not lowered, "
        f"and not moved by PDF-43"
    )
    commented = [
        line
        for line in (REPO_ROOT / "pyproject.toml").read_text().splitlines()
        if "cov-fail-under" in line
    ]
    assert all(line.lstrip().startswith("#") for line in commented), (
        f"`pyproject.toml` acquired a REAL second `cov-fail-under` setting: {commented}. One "
        f"floor, one site"
    )
