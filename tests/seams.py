"""Runtime read/metadata seam instrument for `PDF-26` §D3 completeness (`PDF-43`).

WHY THIS MODULE EXISTS, STATED BEFORE ANYTHING IT DOES
------------------------------------------------------
`PDF-26`'s §D3 completeness claim -- *"0 tracebacking seams"* -- was produced by
an instrument that was blind **twice**, and both blindnesses landed on the same
seam:

**(a) STATIC.** The AST walk looks for read-*shaped* calls. ``drawImage(path)``
is not one: reportlab is handed the operand *path* and performs the open itself,
so the seam appears **0** times in the walk. No widening of the walk's word list
fixes the class -- the next third-party API handed a path will not be in it
either. That is a property of the *technique*, not of the vocabulary.

**(b) DYNAMIC.** The live drive used a mode-000-**from-the-start** operand, which
fails at each verb's **first** read seam and shadows every later one. So *"0
tracebacking seams"* actually measured *"0 verbs traceback at their FIRST
seam"*, which records nothing about completeness.

A count of zero produced by an instrument that cannot see the thing it is
counting is not evidence of absence; it is the absence of evidence wearing a
number.

**This module is deliberately an instrument rather than a fourth belt.** Three
point-fixes have been spent on this seam, each individually correct and each
followed by a new defect -- `48766ee6f2` was introduced by `PDF-26` *itself*,
when the fix that belted the read seams made a **PDF** noun fire at a **JPEG**
read site. The ruling on that record is explicit: a fourth belt at ``drawImage``
repeats the error. So what ships is the thing that would have caught all three.

THE FOUR BUCKETS
----------------
Every candidate seam lands in exactly one of four buckets, and a fifth is a test
failure:

1. **Runtime** (:func:`install_observer`) -- any Python-level open, *regardless of
   call shape*, including opens performed inside a third-party library that was
   handed a path. Cannot see opens below the Python layer (pdfium) or seams on
   code paths the drive never reaches.
2. **Static** (:func:`static_read_sites`) -- first-party read-shaped call sites,
   including ones the drive never executes. Cannot see third-party-performed
   opens; that is blindness (a) itself, preserved here on purpose so the
   instrument can be shown blind next to the one that is not.
3. **Register** (:data:`INVISIBLE_ENGINES`) -- a frozen, named set of engine entry
   points that open *below* the Python layer, each pinned to the exception class
   it raises and to its §D3 disposition. It sees nothing it does not name, which
   is exactly why it is asserted rather than scanned.
4. **Residue** -- static seams never observed at runtime during the drive. Not a
   build failure on sight (the drive cannot reach every branch of every verb, and
   pretending otherwise would make the instrument lie) but **counted**, against a
   frozen ceiling that may not grow.

A seam in (1) but in neither (2) nor (3) is **blindness (a) live** and fails,
naming the frame. That is the arm that would have caught `09b8511ee8` on the day
it was introduced.

NO COUNT IN THIS MODULE IS A LITERAL
------------------------------------
The number of opens a library performs per seam is a property of the installed
Pillow / reportlab / pypdf versions and of the interpreter, and ``pathlib``'s
internals have been rewritten more than once across the supported range
(``requires-python = ">=3.11"``). Every depth ceiling, open count and ordinal in
this module is **derived at drive time**. The one integer written down,
:data:`FIRST_ORDINAL`, is definitional -- it names *the first open*, not a
measured quantity.

This module is framework-free on purpose: it is imported by the arms in
``tests/test_read_seams.py``, by ``tests/seam_sitecustomize/sitecustomize.py``
inside the driven child, and it is runnable by a ``qa-sentinel`` re-verifying
§D3 without this engineer's context.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# The child's environment contract.
#
# The observer runs in the DRIVEN CHILD, never in the pytest process, and three
# reasons make that non-negotiable -- the first alone is decisive:
#
#   1. `sys.addaudithook` CANNOT BE REMOVED once installed. A hook added in the
#      pytest process would persist for every subsequent test in that worker,
#      under `-n auto`, for the rest of the session.
#   2. It would observe pytest's own imports and coverage writes.
#   3. It would slow every unrelated arm.
# --------------------------------------------------------------------------- #

ENV_MODULE: Final = "PDF_SEAM_MODULE"
ENV_TARGET: Final = "PDF_SEAM_TARGET"
ENV_LEDGER: Final = "PDF_SEAM_LEDGER"
ENV_DEPTH: Final = "PDF_SEAM_DEPTH"
ENV_RACE: Final = "PDF_SEAM_RACE"

CHANNEL_READ: Final = "read"
CHANNEL_META: Final = "meta"

RACE_NONE: Final = ""
RACE_UNREADABLE: Final = "unreadable"
RACE_DELETE: Final = "delete"
#: Replace the operand with a DIRECTORY at the raced ordinal.
#:
#: A third race kind is not decoration. `safety/paths.py::source_read_error` asks
#: the ACCESSIBILITY question first, so under the mode-000 race its first rung
#: always fires and the run reports "exists but cannot be read" -- the PDF-noun
#: fallback at the bottom of that ladder is **unreachable by the unreadable
#: race**. The row that recorded `48766ee6f2` measured `[Errno 21] Is a
#: directory`, which is exactly this condition: an `OSError` that is neither
#: EACCES-on-a-file nor ENOENT, so the ladder falls through to its noun. The
#: mutation is still one piece of state about the operand and the failure is
#: still real kernel enforcement.
RACE_DIRECTORY: Final = "directory"

#: The ordinal of the **first** open of the operand. Definitional, not measured:
#: it names where counting starts, and it is the one integer in this module that
#: is not derived (see the module docstring).
FIRST_ORDINAL: Final = 1

_PRODUCT_PACKAGE: Final = "pdf_tooling"
_PRODUCT_MARKER: Final = os.sep + _PRODUCT_PACKAGE + os.sep
_TRACEBACK_MARKER: Final = "Traceback (most recent call last)"

#: What the child runs. The product's real entry point, so the drive measures the
#: product's real behaviour under real kernel enforcement -- only the MOMENT the
#: operand becomes unreadable is synthetic.
CHILD_PROGRAM: Final = "from pdf_tooling.cli.main import main; main()"


def _display_path(filename: str) -> str:
    """A stable, short name for *filename* in a seam record.

    Product frames keep their ``pdf_tooling/...`` prefix because the population
    ledger keys on them; third-party frames are shown from ``site-packages/``
    onward, which is what makes ``reportlab/lib/utils.py`` legible as *the
    opener* rather than as an absolute path nobody can diff.
    """
    marker = os.sep + "site-packages" + os.sep
    if marker in filename:
        return filename.split(marker, 1)[1]
    head = os.sep + _PRODUCT_PACKAGE + os.sep
    if head in filename:
        return _PRODUCT_PACKAGE + os.sep + filename.split(head, 1)[1]
    return filename


def _is_product(filename: str) -> bool:
    return _PRODUCT_MARKER in filename


class _Observer:
    """One mechanism, two jobs: it counts the opens **and** it fires the race.

    The wave-7 harness split those two jobs -- it patched four call shapes and
    counted only those -- and a split of that kind is how a drive silently stops
    one seam short. Here the observer and the racer cannot disagree about what an
    open *is*, because they are the same code path.
    """

    __slots__ = (
        "_targets",
        "_resolved",
        "_fd",
        "_depth",
        "_race",
        "_counts",
        "_fired",
        "_busy",
        "_harness",
    )

    def __init__(self, target: str, ledger: str, *, depth_text: str, race: str) -> None:
        # Resolved ONCE, at install time, while no hook is live. Resolving inside
        # a hook would route through the patched `os.stat` and recurse.
        self._resolved = os.path.realpath(target)
        self._targets = frozenset({target, os.path.abspath(target), self._resolved})
        self._depth = int(depth_text) if depth_text.strip() else None
        self._race = race
        self._counts = {CHANNEL_READ: 0, CHANNEL_META: 0}
        self._fired = False
        self._busy = False
        self._harness = os.path.realpath(__file__)
        # Opened before the hooks go live, so the sink's own open is not an event
        # this observer can see. Raw fd + `os.write`: a buffered file object would
        # need flushing on a path that may end in a traceback.
        self._fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

    # -- matching ----------------------------------------------------------- #

    def _matches(self, raw: object) -> bool:
        """Whether *raw* names the driven operand.

        Deliberately does **not** call ``os.path.realpath``: that routes through
        ``os.stat``, which this observer patches for the metadata channel, and
        the reentrancy would be silent. ``os.path.abspath`` is pure string work
        plus ``getcwd`` and stats nothing.
        """
        try:
            candidate = os.fspath(raw)  # type: ignore[arg-type]
        except TypeError:
            return False
        if isinstance(candidate, bytes):
            try:
                candidate = candidate.decode()
            except UnicodeDecodeError:
                return False
        if candidate in self._targets:
            return True
        return os.path.abspath(candidate) in self._targets

    # -- frames ------------------------------------------------------------- #

    def _frames(self) -> tuple[str, str]:
        """``(originating frame, first-party frame)`` for the open in flight.

        The *originating* frame is the innermost frame outside ``pdf_tooling``
        and outside this harness -- it is what names ``reportlab`` as the opener
        rather than ``ops/compose.py``, and it is the whole of how blindness (a)
        is closed. The *first-party* frame is the innermost ``pdf_tooling/**``
        frame: the seam's own ``file:line``, which the population ledger keys on.
        """
        origin = ""
        first_party = ""
        frame = sys._getframe()
        while frame is not None:
            filename = frame.f_code.co_filename
            if filename != self._harness:
                if _is_product(filename):
                    if not first_party:
                        first_party = f"{_display_path(filename)}:{frame.f_lineno}"
                elif not origin:
                    origin = f"{_display_path(filename)}:{frame.f_lineno}"
                if origin and first_party:
                    break
            frame = frame.f_back
        return origin, first_party

    # -- the race ----------------------------------------------------------- #

    def _race_channel(self) -> str:
        """Which channel's ordinals the flip counts.

        A ``stat`` seam is not reachable by a mode flip, so the delete race counts
        **metadata** touches; the unreadable race counts **opens**.
        """
        return CHANNEL_META if self._race == RACE_DELETE else CHANNEL_READ

    def _maybe_fire(self, channel: str, ordinal: int) -> bool:
        if self._fired or self._depth is None or self._race == RACE_NONE:
            return False
        if channel != self._race_channel() or ordinal < self._depth:
            return False
        self._fired = True
        try:
            if self._race == RACE_DELETE:
                os.unlink(self._resolved)
            elif self._race == RACE_DIRECTORY:
                os.unlink(self._resolved)
                os.mkdir(self._resolved)
            else:
                os.chmod(self._resolved, 0o000)
        except OSError:
            # A flip that cannot happen is recorded as not-fired rather than
            # raised: an exception here would replace the product's behaviour
            # with the harness's, which is the one thing a drive may not do.
            self._fired = False
            return False
        return True

    # -- recording ---------------------------------------------------------- #

    def _record(self, channel: str, raw: object) -> None:
        if self._busy:
            # Re-entry is harness-induced (our own bookkeeping stats and writes),
            # never product-induced. Dropping it is correct, not lossy.
            return
        self._busy = True
        try:
            if not self._matches(raw):
                return
            self._counts[channel] += 1
            ordinal = self._counts[channel]
            origin, first_party = self._frames()
            fired = self._maybe_fire(channel, ordinal)
            line = json.dumps(
                {
                    "channel": channel,
                    "ordinal": ordinal,
                    "origin": origin,
                    "first_party": first_party,
                    "flipped": fired,
                },
                sort_keys=True,
            )
            os.write(self._fd, (line + "\n").encode("utf-8"))
        except Exception:
            # An audit hook that raises replaces the program's behaviour with the
            # harness's. Never.
            pass
        finally:
            self._busy = False

    # -- installation ------------------------------------------------------- #

    def install(self) -> None:
        def audit(event: str, args: tuple[object, ...]) -> None:
            if event != "open":
                return
            self._record(CHANNEL_READ, args[0])

        # The METADATA channel is explicitly separate, with its own ledger and its
        # own ceiling, because `stat()` raises NO audit event at all -- measured,
        # not assumed (E7). Had that not been measured, a metadata census here
        # would have silently returned zero, which is precisely the defect this
        # whole module exists to make impossible.
        real_stat = os.stat
        real_lstat = os.lstat

        def stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_stat(path, *args, **kwargs)
            self._record(CHANNEL_META, path)
            return result

        def lstat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_lstat(path, *args, **kwargs)
            self._record(CHANNEL_META, path)
            return result

        os.stat = stat  # type: ignore[assignment]
        os.lstat = lstat  # type: ignore[assignment]
        sys.addaudithook(audit)


def install_observer() -> None:
    """Install the observer in **this** process from the environment contract.

    Called by ``tests/seam_sitecustomize/sitecustomize.py`` at child startup. A
    no-op when the contract is absent, so putting the directory on ``PYTHONPATH``
    is harmless for anything that is not being driven.
    """
    target = os.environ.get(ENV_TARGET, "")
    ledger = os.environ.get(ENV_LEDGER, "")
    if not target or not ledger:
        return
    _Observer(
        target,
        ledger,
        depth_text=os.environ.get(ENV_DEPTH, ""),
        race=os.environ.get(ENV_RACE, RACE_UNREADABLE),
    ).install()


# --------------------------------------------------------------------------- #
# ENUMERATOR 2 -- the static walk, promoted from probe to shipped instrument.
#
# This is `ast_sweep.py` from the wave-7 sweep, with its two word lists frozen as
# ASSERTED constants. It is kept EXACTLY as blind as it was: its purpose here is
# to be the thing the runtime observer is shown to beat. A vocabulary that can be
# widened quietly is how blindness (a) survived three fixes, so the arms pin its
# size rather than trusting a reviewer to notice a new word.
# --------------------------------------------------------------------------- #

READ_ATTRS: Final[frozenset[str]] = frozenset(
    {"read_bytes", "read_text", "open", "open_binary", "read"}
)
READ_FUNCS: Final[frozenset[str]] = frozenset(
    {"open", "PdfReader", "PdfDocument", "Image", "read_source_bytes"}
)


@dataclass(frozen=True)
class StaticSite:
    """One read-shaped call site under ``src/``."""

    module: str
    line: int
    function: str
    label: str

    @property
    def key(self) -> str:
        return f"{self.module}:{self.line}"


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    functions: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if hasattr(inner, "lineno"):
                    functions.setdefault(inner.lineno, node.name)
    return functions


def static_read_sites(src_root: Path) -> tuple[StaticSite, ...]:
    """Every ``OSError``-capable read-shaped call site beneath *src_root*.

    Reproduces the wave-7 walk exactly, so its figure is comparable across
    commits rather than merely similar. **It returns zero rows for
    ``adapters/reportlab_compose.py``, and that is the point**: the operand is
    opened there, by reportlab, on a call shape no word list contains.
    """
    rows: list[StaticSite] = []
    for path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            label: str | None = None
            if isinstance(node.func, ast.Attribute) and node.func.attr in READ_ATTRS:
                label = f"{ast.unparse(node.func.value)}.{node.func.attr}"
            elif isinstance(node.func, ast.Name) and node.func.id in READ_FUNCS:
                label = node.func.id
            if label is None:
                continue
            rows.append(
                StaticSite(
                    module=str(path.relative_to(src_root)),
                    line=node.lineno,
                    function=functions.get(node.lineno, "<module>"),
                    label=label,
                )
            )
    return tuple(rows)


# --------------------------------------------------------------------------- #
# ENUMERATOR 3 -- the register of engines that open BELOW the Python layer.
#
# The instrument's blind spot and the class §D3 is ruled out of are THE SAME SET,
# and that is the strongest available defence of the population boundary rather
# than a coincidence to hide: `pypdfium2` does not raise `OSError`, so the §D3
# belt cannot map it by exception type, AND pdfium is the one engine whose opens
# the observer cannot see, because they happen in C.
#
# The register is ASSERTED, not assumed. An arm resolves every member and fails
# if one no longer exists, and a companion arm fails if the product resolves an
# engine that is invisible to the observer and is NOT named here. A SILENT
# INVISIBILITY IS THE DEFECT THIS WHOLE MODULE IS ABOUT, and it is the one thing
# that must not be able to happen quietly.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EngineEntry:
    """One engine entry point, pinned to what the observer can see of it."""

    dotted: str
    module: str
    attribute: str
    visible: bool
    exception: str
    disposition: str


INVISIBLE_ENGINES: Final[tuple[EngineEntry, ...]] = (
    EngineEntry(
        dotted="pypdfium2.PdfDocument",
        module="pypdfium2",
        attribute="PdfDocument",
        visible=False,
        exception="pypdfium2.PdfiumError",
        disposition=(
            "OUTSIDE §D3. pdfium opens below the Python layer, so it raises no "
            "`open` audit event and does not raise `OSError`; the §D3 belt maps "
            "by exception type and therefore cannot map it. PDF-26 reported this "
            "and did not fix it; PDF-43 inherits the exclusion UNCHANGED and "
            "declares it here rather than closing it with an out-of-tree oracle."
        ),
    ),
    EngineEntry(
        dotted="os.stat",
        module="os",
        attribute="stat",
        visible=False,
        exception="OSError (FileNotFoundError at the operand seams)",
        disposition=(
            "OUTSIDE §D3, and deliberately so. `stat()` raises NO audit event at "
            "all, so it is invisible on the READ channel; it is covered by the "
            "separate METADATA channel, which has its own ledger and its own "
            "ceiling. §D3's class is a READ-seam class and is NOT widened to "
            "swallow metadata seams -- a class that absorbs whatever the "
            "instrument happens to find stops being a claim."
        ),
    ),
)

VISIBLE_ENGINES: Final[tuple[EngineEntry, ...]] = (
    EngineEntry(
        dotted="pypdf.PdfReader",
        module="pypdf",
        attribute="PdfReader",
        visible=True,
        exception="OSError",
        disposition="INSIDE §D3. Opens through a Python-level file object.",
    ),
    EngineEntry(
        dotted="pikepdf.Pdf.open",
        module="pikepdf",
        attribute="Pdf",
        visible=True,
        exception="OSError",
        disposition=(
            "INSIDE §D3. QPDF is C++, but pikepdf opens through a Python-level "
            "file object, so the observer sees it. This was a premise held and "
            "FALSIFIED by measurement before the design was written."
        ),
    ),
    EngineEntry(
        dotted="reportlab.lib.utils.ImageReader",
        module="reportlab.lib.utils",
        attribute="ImageReader",
        visible=True,
        exception="OSError",
        disposition=(
            "INSIDE §D3, and it is the seam this module exists for. reportlab is "
            "handed the operand PATH and opens it itself, so it is invisible to "
            "the static walk and visible to the observer."
        ),
    ),
    EngineEntry(
        dotted="PIL.Image.open",
        module="PIL.Image",
        attribute="open",
        visible=True,
        exception="OSError / UnidentifiedImageError",
        disposition="INSIDE §D3, belted by `ops/compose.py::_image_read_error`.",
    ),
)

ENGINE_REGISTER: Final[tuple[EngineEntry, ...]] = VISIBLE_ENGINES + INVISIBLE_ENGINES


# --------------------------------------------------------------------------- #
# THE `ops/` -> ENGINE BOUNDARY RULE (D5), enumerated so it is a RULE and not an
# instance.
#
#   When `ops/` hands an operand path across an engine boundary, the read failure
#   at that boundary is owned -- either by the adapter, which may map it, or by
#   the `ops/` caller that supplied the path.
#
# A NOTE ON WHY THE BELT IS `ops/`-SIDE FOR compose, MEASURED RATHER THAN
# ASSUMED. The inherited justification was "adapters/ cannot import safety/, so
# an adapter CANNOT raise a coded error for a read it did not perform". That
# premise is FALSE at this commit and the measurement is
# `git grep -nE 'from pdf_tooling\.safety' -- src/pdf_tooling/adapters`, which
# returns TWO rows: `pypdf_structure.py` and `pdfplumber_text.py` both import
# `source_read_error` and both use it. Adapters demonstrably CAN belt.
#
# The placement is unchanged, but the reason is different and narrower: a belt at
# `made.drawImage(...)` is the FOURTH point-fix at the same seam and is the error
# the withheld verification exists to stop, and converting the path passthrough
# to an `ImageReader` would decode the JPEG and destroy the byte-identity
# guarantee. So compose's boundary is owned `ops/`-side BY DECISION. The
# enumerator below therefore models the codebase as it IS -- two coverage
# buckets, adapter-side and ops-side -- rather than as the inherited premise
# described it.
# --------------------------------------------------------------------------- #

SAFETY_IMPORT_MARKER: Final = "pdf_tooling.safety"


@dataclass(frozen=True)
class BoundarySite:
    """One ``ops/`` call into an engine that is handed an operand-derived path."""

    module: str
    line: int
    method: str
    ops_belted: bool

    @property
    def key(self) -> str:
        return f"{self.module}:{self.line}"


def port_methods_handing_a_path(ports_root: Path) -> frozenset[str]:
    """Port protocol methods whose signature hands the engine a path.

    Derived from the product's own port declarations rather than from a list this
    module invents: a parameter annotated ``Path``, or annotated with a payload
    dataclass declared in ``ports/`` that carries a ``Path`` field (which is how
    ``compose_images`` hands paths -- through ``ImagePlacement.source``).
    """
    payloads: set[str] = set()
    trees: list[ast.AST] = []
    for path in sorted(ports_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees.append(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and ast.unparse(item.annotation) == "Path":
                    payloads.add(node.name)
                    break

    methods: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for argument in node.args.args + node.args.kwonlyargs:
                if argument.annotation is None:
                    continue
                annotation = ast.unparse(argument.annotation)
                if "Path" in annotation or any(name in annotation for name in payloads):
                    methods.add(node.name)
                    break
    return frozenset(methods)


def _handler_maps_oserror(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    return "OSError" in ast.unparse(handler.type)


def engine_boundary_sites(src_root: Path) -> tuple[BoundarySite, ...]:
    """Every ``engine.<method>(...)`` call in ``ops/`` that is handed a path.

    ``ops_belted`` is whether the call is lexically inside a ``try`` whose handler
    names ``OSError``. It is deliberately *not* the whole coverage question: a
    site whose adapter belts it is covered too, and the arm that consumes this
    enumerator asserts the union is total rather than demanding a redundant
    second belt at every site.
    """
    ports_root = src_root / _PRODUCT_PACKAGE / "ports"
    path_methods = port_methods_handing_a_path(ports_root)
    ops_root = src_root / _PRODUCT_PACKAGE / "ops"
    rows: list[BoundarySite] = []
    for path in sorted(ops_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        guarded: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and any(
                _handler_maps_oserror(handler) for handler in node.handlers
            ):
                body_lines = [
                    inner.lineno
                    for statement in node.body
                    for inner in ast.walk(statement)
                    if hasattr(inner, "lineno")
                ]
                if body_lines:
                    guarded.append((min(body_lines), max(body_lines)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "engine":
                continue
            if func.attr not in path_methods:
                continue
            rows.append(
                BoundarySite(
                    module=str(path.relative_to(src_root)),
                    line=node.lineno,
                    method=func.attr,
                    ops_belted=any(lo <= node.lineno <= hi for lo, hi in guarded),
                )
            )
    return tuple(rows)


def adapters_importing_safety(src_root: Path) -> tuple[str, ...]:
    """Adapter modules that import ``safety/`` -- i.e. that CAN belt their own reads.

    Measured, not assumed. The inherited premise said this set was empty.
    """
    adapters_root = src_root / _PRODUCT_PACKAGE / "adapters"
    found: list[str] = []
    for path in sorted(adapters_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if SAFETY_IMPORT_MARKER in text:
            found.append(str(path.relative_to(src_root)))
    return tuple(found)


# --------------------------------------------------------------------------- #
# THE DRIVE (D3) -- depth is DERIVED, and exhaustion is PROVEN.
#
# The wave-7 driver swept `after` over a literal `range(1, 9)`. A literal ceiling
# cannot prove it ran past the last seam: it can only report what it happened to
# reach. This drive derives the ceiling per cell and then proves it.
#
#   1. OBSERVE FIRST, RACE SECOND. Run the cell once with the observer installed
#      and NO flip. That yields M -- the opens of the operand on a clean run --
#      and the seam ledger for the cell.
#   2. DERIVE THE CEILING. K = M + 1. Sweep depth over FIRST_ORDINAL .. K.
#   3. THE EXHAUSTION PROOF. At depth K the flip NEVER fires, because there is no
#      K-th open. The cell must then behave exactly as the un-raced control. A
#      sweep whose top cell is indistinguishable from the control has PROVABLY
#      run past the last seam.
#
# Depth FIRST_ORDINAL is retained as a NAMED cell rather than discarded: it is
# the wave-7 condition, and reporting "tracebacking seams at the first ordinal"
# beside "tracebacking seams across the whole sweep" makes the shadowing visible
# as a number in every run instead of a fact somebody has to remember.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CellResult:
    """One `(verb, format, depth)` cell of the drive."""

    depth: int | None
    exit_code: int
    stdout: str
    stderr: str
    records: tuple[dict[str, object], ...]

    @property
    def traceback(self) -> bool:
        return _TRACEBACK_MARKER in (self.stdout + self.stderr)

    @property
    def stderr_bytes(self) -> int:
        return len(self.stderr.encode("utf-8"))

    @property
    def stdout_bytes(self) -> int:
        return len(self.stdout.encode("utf-8"))

    @property
    def envelope(self) -> dict[str, object] | None:
        """The parsed ``-o json`` envelope, or ``None`` when stdout carries none."""
        text = self.stdout.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def channel(self, channel: str) -> tuple[dict[str, object], ...]:
        return tuple(row for row in self.records if row.get("channel") == channel)

    @property
    def flipped(self) -> bool:
        return any(row.get("flipped") for row in self.records)

    @property
    def shape(self) -> tuple[int, bool, bool]:
        """What the exhaustion proof compares: exit code, envelope-ness, traceback."""
        return (self.exit_code, self.envelope is not None, self.traceback)


def drive_cell(
    *,
    argv: Sequence[str],
    operand: Path,
    workdir: Path,
    depth: int | None = None,
    race: str = RACE_UNREADABLE,
    timeout: float = 180.0,
) -> CellResult:
    """Run one cell of the drive in a child with the observer installed.

    The operand's mode is restored afterwards unconditionally, so a failed cell
    never leaves an unreadable file behind for ``tmp_path`` teardown to trip over.
    """
    here = Path(__file__).resolve()
    ledger = workdir / "seam-ledger.jsonl"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(here.parent / "seam_sitecustomize"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env[ENV_MODULE] = str(here)
    env[ENV_TARGET] = str(operand)
    env[ENV_LEDGER] = str(ledger)
    env[ENV_DEPTH] = "" if depth is None else str(depth)
    env[ENV_RACE] = race
    try:
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_PROGRAM, *argv],
            capture_output=True,
            text=True,
            cwd=workdir,
            env=env,
            timeout=timeout,
        )
    finally:
        try:
            operand.chmod(0o600)
        except OSError:
            pass
    records: list[dict[str, object]] = []
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return CellResult(
        depth=depth,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        records=tuple(records),
    )


@dataclass(frozen=True)
class Sweep:
    """A whole `(verb, format)` cell: the control, the derived ceiling, the sweep."""

    label: str
    control: CellResult
    cells: tuple[CellResult, ...]
    race: str

    @property
    def clean_opens(self) -> int:
        """``M`` -- opens of the operand on the un-raced run, on the raced channel."""
        channel = CHANNEL_META if self.race == RACE_DELETE else CHANNEL_READ
        return len(self.control.channel(channel))

    @property
    def ceiling(self) -> int:
        """``K = M + 1`` -- the depth at which the flip provably cannot fire."""
        return self.clean_opens + 1

    @property
    def exhaustion(self) -> CellResult:
        return self.cells[-1]

    @property
    def exhaustion_matches_control(self) -> bool:
        return self.exhaustion.shape == self.control.shape and not self.exhaustion.flipped

    @property
    def tracebacking_depths(self) -> tuple[int, ...]:
        return tuple(cell.depth for cell in self.cells if cell.traceback and cell.depth is not None)

    @property
    def tracebacks_at_first_ordinal(self) -> int:
        """The wave-7 figure: does the verb traceback at its FIRST seam only."""
        return sum(1 for cell in self.cells if cell.depth == FIRST_ORDINAL and cell.traceback)

    @property
    def tracebacks_across_sweep(self) -> int:
        """The honest figure: does the verb traceback at ANY seam."""
        return len(self.tracebacking_depths)

    @property
    def observed_origins(self) -> tuple[str, ...]:
        seen: list[str] = []
        for cell in (self.control, *self.cells):
            for row in cell.channel(CHANNEL_READ):
                origin = str(row.get("origin", ""))
                if origin and origin not in seen:
                    seen.append(origin)
        return tuple(seen)

    @property
    def observed_first_party(self) -> tuple[str, ...]:
        seen: list[str] = []
        for cell in (self.control, *self.cells):
            for row in cell.channel(CHANNEL_READ):
                site = str(row.get("first_party", ""))
                if site and site not in seen:
                    seen.append(site)
        return tuple(seen)


def sweep_cell(
    *,
    label: str,
    argv_for: Callable[[Path, Path], Sequence[str]],
    operand_for: Callable[[Path], Path],
    root: Path,
    race: str = RACE_UNREADABLE,
) -> Sweep:
    """Observe, derive the ceiling, sweep, and carry the exhaustion cell.

    *operand_for* builds a FRESH operand per cell -- the race destroys it -- and
    *argv_for* receives ``(operand, cell workdir)`` so a verb that needs an output
    path can name one inside the cell.
    """

    def run(depth: int | None, name: str) -> CellResult:
        workdir = root / name
        workdir.mkdir(parents=True, exist_ok=True)
        operand = operand_for(workdir)
        return drive_cell(
            argv=argv_for(operand, workdir),
            operand=operand,
            workdir=workdir,
            depth=depth,
            race=race,
        )

    control = run(None, "control")
    channel = CHANNEL_META if race == RACE_DELETE else CHANNEL_READ
    ceiling = len(control.channel(channel)) + 1
    cells = tuple(run(depth, f"depth-{depth}") for depth in range(FIRST_ORDINAL, ceiling + 1))
    return Sweep(label=label, control=control, cells=cells, race=race)


def residue(
    static: Sequence[StaticSite], observed_first_party: Sequence[str]
) -> tuple[StaticSite, ...]:
    """Static seams the drive never reached -- undriven, therefore unproven.

    Counted, never silently dropped. It is not a build failure on sight, because
    the drive cannot reach every branch of every verb and pretending otherwise
    would make the instrument lie; it is held by a frozen per-module ceiling that
    MAY NOT GROW.
    """
    reached = set(observed_first_party)
    out: list[StaticSite] = []
    for site in static:
        # Reach is asserted at SEAM level, never at module level: a module the
        # drive entered is not a module every seam in it ran.
        # `StaticSite.module` is already relative to `src/`, so it is ALREADY
        # `pdf_tooling/...` -- exactly the shape `_display_path` emits for a
        # first-party frame. Re-prefixing it produced `pdf_tooling/pdf_tooling/`
        # and a residue of 47/47, i.e. an instrument reporting that its own
        # drive reached nothing. Keyed identity is asserted by a test.
        if site.key in reached:
            continue
        out.append(site)
    return tuple(out)


def registered_engine_for(origin: str) -> EngineEntry | None:
    """The :data:`ENGINE_REGISTER` entry whose module produced *origin*, if any.

    *origin* is a seam record's originating frame, e.g.
    ``reportlab/lib/utils.py:463``. This is bucket 3 of the four-bucket
    population: an open the static walk cannot predict, performed by a
    third-party module the register NAMES.

    Stdlib frames deliberately do not match. A seam whose opener is ``pathlib``
    is a first-party read-shaped call the static walk already sees, so it belongs
    to bucket 2 and counting it here would let one seam sit in two buckets.
    """
    head = origin.rsplit(":", 1)[0]
    for entry in ENGINE_REGISTER:
        prefix = entry.module.replace(".", "/")
        if head == f"{prefix}.py" or head.startswith(f"{prefix}/"):
            return entry
    return None


def unregistered_runtime_seams(
    observed: Sequence[dict[str, object]], static: Sequence[StaticSite]
) -> tuple[dict[str, object], ...]:
    """Observed read seams in bucket 1 and in NEITHER bucket 2 nor bucket 3.

    **This is the arm that would have caught `09b8511ee8` on the day it was
    introduced.** Something read the operand and no enumerator predicted it: not
    the static walk, because the call shape is not read-shaped; not the register,
    because nobody declared the engine. Both directions of the population are
    failures and they fail differently -- this one fails LOUDLY, naming the
    frame, because a seam nobody predicted is the defect class itself.
    """
    known = {site.key for site in static}
    rogue: list[dict[str, object]] = []
    for row in observed:
        if row.get("channel") != CHANNEL_READ:
            continue
        if str(row.get("first_party", "")) in known:
            continue
        if registered_engine_for(str(row.get("origin", ""))) is not None:
            continue
        rogue.append(row)
    return tuple(rogue)


def metadata_sites(src_root: Path) -> tuple[StaticSite, ...]:
    """Operand-reachable METADATA (``stat``-family) call sites.

    The unscoped census over ``src/`` deliberately OVER-READS: it counts
    write-target probes and temp-name probes that are not operand metadata seams
    at all. The scoping rule, stated so it can be audited rather than trusted:
    **``ops/**`` and ``safety/paths.py`` only** -- the two layers that hold an
    operand path -- and the unscoped figure is published beside it so the
    difference is visible.

    Recipe for the unscoped figure:
    ``git grep -n -E '[.](stat|exists|is_file|is_dir|lstat)[(][)]' -- src | wc -l``
    """
    attrs = {"stat", "exists", "is_file", "is_dir", "lstat"}
    scoped: list[StaticSite] = []
    roots = [
        src_root / _PRODUCT_PACKAGE / "ops",
        src_root / _PRODUCT_PACKAGE / "safety" / "paths.py",
    ]
    files: list[Path] = []
    for candidate in roots:
        files.extend(sorted(candidate.rglob("*.py")) if candidate.is_dir() else [candidate])
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr not in attrs:
                continue
            if node.args or node.keywords:
                continue
            scoped.append(
                StaticSite(
                    module=str(path.relative_to(src_root)),
                    line=node.lineno,
                    function=functions.get(node.lineno, "<module>"),
                    label=f"{ast.unparse(node.func.value)}.{node.func.attr}",
                )
            )
    return tuple(scoped)
