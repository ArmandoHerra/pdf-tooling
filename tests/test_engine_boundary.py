"""PDF-36 half one — the pikepdf engine boundary, by DERIVATION.

`6f5911ef9d`: ``compress testdata/malformed.pdf`` exited 1 with **zero bytes of
stdout and 3644 bytes of raw traceback**, because
``adapters/pikepdf_structure.py``'s post-save re-open sat *outside* the ``try``
its own function closes three lines above. `cli/main.py:10-13` calls a traceback
"a signal, not a UX" and that policy is CORRECT — a ``pikepdf.PdfError`` raised
by opening a malformed document is simply not a bug, so the fix belongs at the
engine boundary and never at the terminal seam.

**WHY THIS IS A WALK AND NOT THREE ASSERTIONS.** Belting exactly the sites a
human happened to read is the point-belt pattern that produced `02096f4422`
(*incomplete inside the very file the engineer identified*) and then
`09b8511ee8` behind it. The population is derived FROM THE MODULE, so a
pikepdf call added next year is a RED rather than a discovery.

**THE FOURTH SITE.** `PDF-36`'s spec predicted three unbelted sites — the
``compress``/``repair``/``linearize`` re-opens. The walk found **four**:
``pikepdf.Permissions(...)`` in ``encrypt`` was also outside its function's
handler. It is FILED here rather than exempted, per the spec's own anti-gaming
rule ("*a fourth unbelted site ... is FILED with its measurement, never
exempted*"), and it is closed by BELTING it — moving it inside the ``try`` that
already sits one line below — never by narrowing the population to hide it.

Measured at `ae723bc`, immediately before the fix:

===========================  =====
population (pikepdf-rooted)     12
residue (unbelted)               4
===========================  =====

The residue was lines 178 (``compress``), 217 (``repair``), 254
(``linearize``) and 368 (``encrypt``).

**LINE NUMBERS ARE NOT PINNED, AND THAT IS THE POINT.** Adding a belt MOVES
every line below it, so a guard that hard-coded 178/217/254 would fail for a
CORRECT reason on the very commit that fixes the defect — the exact way
`test_cli_contract.py`'s ``POPULATIONS`` docstring says an instrument gets
weakened back into a claim. What is pinned instead is the STRUCTURE those line
numbers were instances of: each of ``compress``/``repair``/``linearize``
opens the document once and re-opens its own saved output afterwards, and the
walk must resolve BOTH opens in each.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

#: The one module this walk is scoped to. `PDF-36` is deliberately NOT a
#: repo-wide read-seam instrument — that is `PDF-43`, by name, with its own
#: sizing. One module, one exception class, closable.
ADAPTER: Final[Path] = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "pdf_toolkit"
    / "adapters"
    / "pikepdf_structure.py"
)

#: The engine root whose calls this boundary is about.
ENGINE_ROOT: Final[str] = "pikepdf"

#: A handler naming any of these converts a ``pikepdf.PdfError`` into a
#: ``PdfToolkitError`` (or is broad enough to). ``pikepdf.PdfError``'s own base
#: is ``Exception``, so a bare ``except:`` and ``except Exception`` are belts
#: too — they are listed for completeness, NOT because either is acceptable
#: style here; every real belt in this adapter names ``pikepdf.PdfError``.
BELT_TYPES: Final[frozenset[str]] = frozenset({"pikepdf.PdfError", "Exception", "<bare>"})

#: The three methods whose post-save re-open was the defect. Each opens its
#: input once and re-opens its OWN OUTPUT afterwards, so each must contribute
#: at least two ``pikepdf.Pdf.open`` calls to the population.
REOPENING_METHODS: Final[tuple[str, ...]] = ("compress", "repair", "linearize")

#: The residue this walk measured at `ae723bc`, the commit immediately before
#: the fix, recorded so AC2(iii)'s "reported as a number" survives in the tree
#: rather than only in a report. NOT asserted against the live module — it is
#: history, and the live assertion below is that the residue is now ZERO.
PRE_FIX_RESIDUE_AT_AE723BC: Final[int] = 4
PRE_FIX_POPULATION_AT_AE723BC: Final[int] = 12


@dataclass(frozen=True)
class EngineCall:
    """One ``pikepdf``-rooted call site, with the handlers enclosing it."""

    function: str
    target: str
    line: int
    handlers: tuple[str, ...]

    @property
    def belted(self) -> bool:
        return bool(BELT_TYPES & set(self.handlers))

    def __str__(self) -> str:
        return f"{ADAPTER.name}:{self.line}: {self.function}() calls {self.target}"


def dotted(func: ast.expr) -> str:
    """``a.b.c`` for an Attribute/Name chain, ``""`` for anything else.

    Modelled on `tests/test_import_boundaries.py:129`'s helper of the same
    name — the landed, *write*-shaped walker this call-shaped one copies.
    Kept local rather than imported so that importing one test module does not
    execute another's collection-time constants.
    """
    parts: list[str] = []
    node: ast.expr | None = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _handler_types(handler: ast.ExceptHandler) -> list[str]:
    """Every exception name one ``except`` clause catches."""
    caught = handler.type
    if caught is None:
        return ["<bare>"]
    if isinstance(caught, ast.Tuple):
        return [dotted(element) for element in caught.elts]
    return [dotted(caught)]


class _EngineCallVisitor(ast.NodeVisitor):
    """Collects every engine-rooted call, with its enclosing function and belts.

    Scope tracking mirrors ``_WriteCallVisitor``
    (`tests/test_import_boundaries.py:281`); the belt half is this walk's own,
    because a write-shaped walker has no notion of a handler.
    """

    def __init__(self, root: str) -> None:
        self.root = root
        self.scope: list[str] = ["<module>"]
        self.belts: list[list[str]] = []
        self.found: list[EngineCall] = []

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        """Only the ``try`` BODY is belted.

        A call in an ``except``/``else``/``finally`` clause is NOT protected by
        that statement's own handlers — ``repair``'s ``finally: pdf.close()``
        is the live example — so the belt is pushed for the body alone and the
        other clauses are visited outside it.
        """
        caught = [name for handler in node.handlers for name in _handler_types(handler)]
        self.belts.append(caught)
        for statement in node.body:
            self.visit(statement)
        self.belts.pop()
        for clause in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(clause)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = dotted(node.func)
        if target.startswith(f"{self.root}."):
            enclosing = tuple(name for frame in self.belts for name in frame)
            self.found.append(EngineCall(self.scope[-1], target, node.lineno, enclosing))
        self.generic_visit(node)


def scan_engine_calls(source: str, *, root: str = ENGINE_ROOT) -> list[EngineCall]:
    """Every *root*-rooted call in one module's source, belted or not."""
    visitor = _EngineCallVisitor(root)
    visitor.visit(ast.parse(source, filename=ADAPTER.name))
    return visitor.found


def residue(calls: list[EngineCall]) -> list[EngineCall]:
    """The failure list: engine calls no handler converts."""
    return [call for call in calls if not call.belted]


@pytest.fixture(scope="module")
def adapter_source() -> str:
    return ADAPTER.read_text()


@pytest.fixture(scope="module")
def engine_calls(adapter_source: str) -> list[EngineCall]:
    return scan_engine_calls(adapter_source)


# --------------------------------------------------------------------------- #
# AC2 -- the invariant, and the three anti-vacuity assertions beneath it.
# --------------------------------------------------------------------------- #


def test_ac2_the_engine_boundary_has_zero_residue(
    engine_calls: list[EngineCall],
) -> None:
    """AC2: residue ZERO.

    Every ``pikepdf``-rooted call in this adapter executes inside a handler
    that converts ``pikepdf.PdfError`` into a ``PdfToolkitError``. Red at
    `ae723bc` with a residue of 4.
    """
    leaking = residue(engine_calls)
    assert leaking == [], (
        f"{len(leaking)} pikepdf call(s) can raise `pikepdf.PdfError` straight past this "
        f"adapter and out through `cli/main.py`'s bug path, where it prints a raw "
        f"traceback (`6f5911ef9d`: 3644 bytes of it). Belt each at the engine boundary "
        f"-- never with a catch-all at the terminal seam:\n  "
        + "\n  ".join(str(call) for call in leaking)
    )


def test_ac2i_the_walk_resolves_a_non_empty_population(engine_calls: list[EngineCall]) -> None:
    """AC2(i): a walk that resolves nothing passes vacuously.

    This product's second headline failure mode and the exact shape of `B-080`.
    `git grep -cE 'pikepdf\\.' -- src/pdf_toolkit/adapters/pikepdf_structure.py`
    returned **36** references at `ae723bc`; the call population is a subset of
    those and is MEASURED, never assumed.
    """
    assert engine_calls, (
        "the engine-boundary walk resolved ZERO pikepdf calls in "
        f"{ADAPTER.name}. Either the adapter stopped calling the engine (in which case "
        "this whole module is obsolete and should be deleted deliberately) or `dotted()` "
        "stopped resolving the call shape the adapter uses -- and a residue of zero over "
        "an empty population is not a guarantee, it is an absence of measurement"
    )


@pytest.mark.parametrize("method", REOPENING_METHODS)
def test_ac2ii_the_walk_resolves_both_opens_in_each_reopening_method(
    engine_calls: list[EngineCall], method: str
) -> None:
    """AC2(ii): the three known sites, pinned STRUCTURALLY rather than by line.

    At `ae723bc` these were lines 178, 217 and 254 — the second
    ``pikepdf.Pdf.open`` in each method, the post-save re-open of the method's
    own output. Adding the belt moves those numbers by construction, so what is
    asserted is the shape they were instances of: each method opens its input
    AND re-opens its output, and the walk sees both.
    """
    opens = [
        call
        for call in engine_calls
        if call.function == method and call.target == "pikepdf.Pdf.open"
    ]
    assert len(opens) >= 2, (
        f"the walk resolved {len(opens)} `pikepdf.Pdf.open` call(s) in {method}(), expected "
        f"at least 2 -- the input open and the post-save re-open of its own output, which is "
        f"the site `6f5911ef9d` escaped through. Resolving fewer means either the method was "
        f"restructured (re-derive this pin deliberately) or the walk stopped seeing the call "
        f"shape. Resolved: {[str(call) for call in opens]}"
    )


def test_ac2iii_every_reopen_site_is_belted_by_name(engine_calls: list[EngineCall]) -> None:
    """AC2: the re-opens specifically — the sites the ledger row escaped through.

    Distinct from the residue assertion above: that one would still pass if the
    re-opens were DELETED. This one fails if they are unbelted, and the
    structural pin above fails if they vanish.
    """
    for method in REOPENING_METHODS:
        opens = [
            call
            for call in engine_calls
            if call.function == method and call.target == "pikepdf.Pdf.open"
        ]
        unbelted = [call for call in opens if not call.belted]
        assert not unbelted, (
            f"{method}(): the post-save re-open is outside its own handler -- "
            f"{[str(call) for call in unbelted]}"
        )


# --------------------------------------------------------------------------- #
# The walk must be able to FAIL. Two reds, both standing rather than one-off.
# --------------------------------------------------------------------------- #


def test_red_the_walk_reports_a_residue_when_a_belt_is_removed(adapter_source: str) -> None:
    """AC2 RED: unbelt one site on a COPY and the walk names it.

    The mutation is textual and applied to a string — the working tree is never
    touched (HC-4). ``compress``'s ``except pikepdf.PdfError`` clause is
    rewritten to catch an unrelated type, which is exactly what "the belt was
    removed" looks like to the walk.
    """
    belt = "        except pikepdf.PdfError as error:\n"
    assert adapter_source.count(belt) >= 1, (
        "the adapter no longer contains the belt this red mutates; re-derive the "
        "mutation against the live source rather than deleting this control"
    )
    mutated = adapter_source.replace(belt, "        except KeyboardInterrupt as error:\n", 1)
    assert mutated != adapter_source

    leaking = residue(scan_engine_calls(mutated))
    assert leaking, (
        "removing a `pikepdf.PdfError` belt produced NO residue -- the walk cannot fail, "
        "so its green says nothing about the code"
    )
    assert any(call.function == "compress" for call in leaking), (
        f"the walk found a residue but did not attribute it to compress(): "
        f"{[str(call) for call in leaking]}"
    )


def test_red_a_call_in_an_except_clause_is_not_belted_by_its_own_try() -> None:
    """The belt is the ``try`` BODY, never the whole statement.

    A ``pikepdf`` call in an ``except`` or ``finally`` clause is not protected
    by that statement's handlers. If the walk credited them, `repair`'s
    ``finally: pdf.close()`` shape would let a genuinely unbelted call read as
    belted — a false green in the exact place this module exists to watch.
    """
    source = (
        "import pikepdf\n"
        "def f(data):\n"
        "    try:\n"
        "        pikepdf.Pdf.open(data)\n"
        "    except pikepdf.PdfError:\n"
        "        pikepdf.Pdf.open(data)\n"
    )
    calls = scan_engine_calls(source)
    assert len(calls) == 2, f"expected both opens to resolve, got {calls}"
    by_line = {call.line: call for call in calls}
    assert by_line[4].belted, "the call in the try BODY is belted"
    assert not by_line[6].belted, (
        "the call in the except CLAUSE was credited with its own statement's handler -- "
        "that is a false green"
    )


def test_red_an_empty_population_is_not_a_guarantee() -> None:
    """AC2(i) RED: stub the population empty and the non-empty assertion must bite.

    Driven rather than argued: a module with no engine calls yields an empty
    population AND a zero residue, and it is the emptiness — not the zero —
    that has to fail.
    """
    calls = scan_engine_calls("import pikepdf\ndef f():\n    return 1\n")
    assert calls == [], "a module with no pikepdf calls must resolve an empty population"
    assert residue(calls) == [], "an empty population trivially has a zero residue"
    with pytest.raises(AssertionError):
        assert calls, "this is the assertion AC2(i) makes; it must fail on an empty population"
