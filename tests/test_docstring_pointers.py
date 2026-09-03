"""PDF-30 D8 / `b408baff4a` — a pointer from `src/` to `tests/` must resolve.

``safety/confirm.py:42`` said *"``tests/test_cli_spine.py`` asserts, against the
AST rather than a comment, that no ``cli/cmd_*.py`` module re-introduces such a
guard."* The file exists. It holds **zero** references to
``require_confirmation``. The walk it describes is
``tests/test_import_boundaries.py`` Section 4. **The fix's own explanation of
itself pointed at the wrong file**, and an existence-only check would have
passed it — which is why the identifier half is what makes this guard bite.

WHAT IS MECHANIZED, AND WHAT DELIBERATELY IS NOT
-------------------------------------------------
Three properties, in increasing strength:

1. **Existence.** Every ``tests/…py`` path named anywhere under
   ``src/pdf_toolkit`` resolves to a real file.
2. **Resolution.** A pointer that names an explicit target — ``::<identifier>``
   or a following ``Section <N>`` — must find that target IN the file it names.
   This is the half ``confirm.py:42`` failed.
3. **Closure.** The set of pointers naming NO explicit target is frozen at its
   measured size, so a new unresolvable pointer is a failure. The closure rule
   of this spec, applied to pointers instead of to cardinals.

**Deriving an untargeted pointer's subject automatically is NOT mechanized, and
that is reported rather than faked.** The obvious heuristic — take the pointing
module's own name as the subject — was measured against the real tree and
produced **seven false positives** out of twenty-eight (e.g.
``cmd_compress.py``'s pointer at ``tests/registry.py``, whose claim is about
*registry.py's own docstring* and not about ``cmd_compress``). *The worst
control is not one that cannot fail; it is one that reports the WRONG ANSWER.*
So the heuristic is not shipped, the measurement is on the record, and property
3 closes the class going forward instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "pdf_toolkit"

POINTER = re.compile(r"tests/[A-Za-z0-9_/]+\.py(?:::(?P<identifier>[A-Za-z_][A-Za-z0-9_]*))?")
FOLLOWING_SECTION = re.compile(r"\A(?:``|`|\s)*Section\s+(?P<section>\d+)")


@dataclass(frozen=True)
class Pointer:
    source: str
    line: int
    path: str
    target: str | None

    def describe(self) -> str:
        named = f" -> {self.target!r}" if self.target else " (no explicit target)"
        return f"{self.source}:{self.line} names {self.path}{named}"


def pointers() -> list[Pointer]:
    """Every `tests/…py` path named in a `src/pdf_toolkit/**` docstring or comment."""
    found: list[Pointer] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text()
        relative = path.relative_to(REPO_ROOT).as_posix()
        for match in POINTER.finditer(text):
            target = match.group("identifier")
            if target is None:
                section = FOLLOWING_SECTION.match(text[match.end() : match.end() + 40])
                if section:
                    target = f"Section {section.group('section')}"
            found.append(
                Pointer(
                    source=relative,
                    line=text[: match.start()].count("\n") + 1,
                    path=match.group(0).split("::")[0],
                    target=target,
                )
            )
    return found


def resolves(pointer: Pointer) -> tuple[bool, bool]:
    """`(the file exists, the named target is in it)` for *pointer*.

    Returned as a PAIR on purpose: `confirm.py:42` is the case where the first
    half is True and the second False, and AC27 asks for both recorded so it is
    visible that existence alone would not have caught it.
    """
    target_file = REPO_ROOT / pointer.path
    if not target_file.is_file():
        return False, False
    if pointer.target is None:
        return True, True
    return True, pointer.target in target_file.read_text()


#: Pointers that name no `::identifier` and no following `Section <N>`. A reader
#: cannot check an untargeted pointer, so the set is frozen: a NEW one is a test
#: failure. It was **36** of 50 at `7afdb1a`; correcting `confirm.py:42` onto
#: ``tests/test_import_boundaries.py`` Section 4 makes it **35** of 51.
UNTARGETED_CEILING = 35


def test_at_least_one_pointer_exists_or_this_module_proves_nothing() -> None:
    """The anti-lapse assertion. A resolver over an empty population is green."""
    assert len(pointers()) >= 40, (
        "the pointer walk found almost nothing; a resolver that resolves no "
        "pointers passes every assertion below vacuously"
    )


@pytest.mark.parametrize("pointer", pointers(), ids=lambda p: f"{Path(p.source).name}:{p.line}")
def test_every_docstring_pointer_names_a_file_that_exists(pointer: Pointer) -> None:
    """Property 1."""
    exists, _ = resolves(pointer)
    assert exists, f"{pointer.describe()}, which is not a file in this repository"


@pytest.mark.parametrize(
    "pointer",
    [p for p in pointers() if p.target],
    ids=lambda p: f"{Path(p.source).name}:{p.line}",
)
def test_every_targeted_pointer_finds_its_target_in_the_file_it_names(pointer: Pointer) -> None:
    """Property 2 — the half `confirm.py:42` failed."""
    exists, resolved = resolves(pointer)
    assert exists, f"{pointer.describe()}, which is not a file in this repository"
    assert resolved, (
        f"{pointer.describe()}, and that file does not contain it. A pointer that "
        "sends the next reader somewhere nothing is wrong is worse than no pointer."
    )


def test_the_untargeted_pointer_population_does_not_grow() -> None:
    """Property 3 — the closure rule, applied to pointers."""
    untargeted = [p for p in pointers() if p.target is None]
    listing = "\n  ".join(p.describe() for p in untargeted)
    assert len(untargeted) <= UNTARGETED_CEILING, (
        f"{len(untargeted)} pointers name no checkable target, above the frozen "
        f"ceiling of {UNTARGETED_CEILING} measured at 7afdb1a. A new pointer names "
        f"`::<identifier>` or a `Section <N>`, or it names nothing a reader can "
        f"check:\n  {listing}"
    )


def test_the_resolver_is_red_on_the_pre_fix_confirm_pointer() -> None:
    """AC27's RED, free, and BOTH halves recorded.

    `confirm.py:42` claimed `tests/test_cli_spine.py` asserts the B-093 AST walk.
    Existence passes — the file is right there. The identifier fails: the file
    holds **zero** `require_confirmation` references. The walk is
    `tests/test_import_boundaries.py` Section 4, which holds both.
    """
    pre_fix = Pointer(
        source="src/pdf_toolkit/safety/confirm.py",
        line=42,
        path="tests/test_cli_spine.py",
        target="require_confirmation",
    )
    exists, resolved = resolves(pre_fix)
    assert exists, "the existence half must PASS, or this control proves the wrong thing"
    assert not resolved, (
        "the identifier half must FAIL on the pre-fix pointer; if "
        "tests/test_cli_spine.py has grown a require_confirmation reference this "
        "control no longer controls"
    )

    corrected = Pointer(
        source="src/pdf_toolkit/safety/confirm.py",
        line=42,
        path="tests/test_import_boundaries.py",
        target="Section 4",
    )
    assert resolves(corrected) == (True, True)
    identifier = Pointer(**{**corrected.__dict__, "target": "require_confirmation"})
    assert resolves(identifier) == (True, True), (
        "the corrected file must hold the identifier too, or the correction moved "
        "the pointer without making it resolvable"
    )


def test_the_resolver_reports_a_missing_file_rather_than_passing_it() -> None:
    """The other red: a path that does not exist fails BOTH halves."""
    ghost = Pointer(
        source="<synthetic>", line=0, path="tests/test_does_not_exist.py", target="anything"
    )
    assert resolves(ghost) == (False, False)
