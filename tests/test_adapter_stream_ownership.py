"""PDF-81 — an engine may borrow this process's diagnostic streams; it may not keep them.

``pikepdf.Pdf.check_linearization(stream)`` does not write *to* the stream it is
handed. It assigns ``sys.stderr = stream`` and never puts back what was there —
the parameter's own documented default **is** ``sys.stderr``, which is what an
API implemented that way looks like from outside, and the assignment lives in a
compiled extension, so no Python-level ``finally`` in the library can be waited
for. ``adapters/pikepdf_structure.py`` hands it a throwaway ``io.StringIO()``,
so before this spec every diagnostic the process wrote after any ``linearize``
run reached its verification step landed in a buffer discarded on return: the
product's own ``error:`` line, ``AtomicWriter``'s ``atomicity degraded``
warning, and the interpreter's unhandled-exception traceback alike. ``stdout``
and the raw file descriptor were untouched throughout, which is why this is a
**stream ownership** defect and not an output-contract one — the product never
stopped writing, it stopped being heard.

WHY THE ARMS LOOK LIKE THIS, AND NOT LIKE THE OBVIOUS ONE
---------------------------------------------------------
The obvious arm is ``assert sys.stderr is sys.__stderr__`` after driving the
adapter. **It is a broken instrument and this module does not contain one.**
pytest's capture machinery rebinds ``sys.stdout``/``sys.stderr`` itself for the
duration of every test: under default capture that assertion compares two
objects pytest chose, under ``-s`` it compares two objects pytest left alone,
so the same source line means different things depending on a flag — and on the
pre-fix binary it can be made to pass. It would be a test of the runner.
:func:`test_no_shipped_arm_asserts_stream_identity_inside_the_pytest_process`
holds that line against a future author rather than leaving it to this
paragraph.

What replaces it is two kinds of observation, both from OUTSIDE the parent:

* **Behavioural**, through ``tests/registry.py::run_cli`` — *does a post-engine
  diagnostic reach the user?* This is the defect as a user meets it, and it is
  immune to the trap because the parent asserts on the **child's captured
  stderr string**; what pytest did to the parent's streams cannot reach it.
* **Structural**, through a child process that installs **sentinel streams of
  its own** and reports the identity verdict on the stdout it saved first. The
  sentinels are what make it also catch the one wrong implementation an
  identity check written against ``sys.__stderr__`` would call green:
  ``sys.stderr = sys.__stderr__`` in the ``finally``, which does not restore a
  binding, it destroys a redirection.

THE CLASS IS DECIDABLE WITHOUT AN ALLOWLIST, AND THAT IS THE DESIGN
--------------------------------------------------------------------
A guard with an allowlist is not a guard: a list of blessed sites is a thing a
future engineer appends to. :func:`owned_stream_arguments` keys on the stream's
TYPE instead, because that is measurably the discriminator. Every call in
``adapters/`` handed a stream this product owns carries either BYTES or
DIAGNOSTICS, and an engine asked to print words looks for somewhere to print
them — ``sys.stderr`` — while a byte conduit is not a thing a C++ library will
mistake for one. So ``io.BytesIO`` is not in the rule's vocabulary at all: the
byte-carrying sites are **outside the rule's domain rather than exempted from
it**, and that difference is what makes the rule absolute.

Every population here is DERIVED at run time. No census figure from the spec is
retyped as a literal, because this product's most-filed defect class is a number
that was true when it was typed.
"""

from __future__ import annotations

import ast
import io
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from pdf_tooling.adapters import restore_standard_streams

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import REPO_ROOT, run_cli  # noqa: E402

SRC: Final[Path] = REPO_ROOT / "src"
ADAPTERS: Final[Path] = SRC / "pdf_tooling" / "adapters"
MALFORMED: Final[Path] = REPO_ROOT / "testdata" / "malformed.pdf"

#: The guard's own name, read off the imported symbol rather than typed. The
#: rule keys on a SYMBOL — that is the whole reason D2 refused an inline
#: `try`/`finally`, which would have left this walk keying on a syntax shape any
#: unrelated `finally` could satisfy. Renaming the guard without renaming it
#: here is impossible: this string is the guard.
GUARD_NAME: Final[str] = restore_standard_streams.__name__

#: Read off the stdlib types themselves, for the same reason.
TEXT_CONSTRUCTORS: Final[frozenset[str]] = frozenset({io.StringIO.__name__})
BYTE_CONSTRUCTORS: Final[frozenset[str]] = frozenset({io.BytesIO.__name__})

#: The three names an engine can steal. `sys.__stdin__` and friends are
#: deliberately NOT here: a call handed the ORIGINAL stream is handed something
#: this process may already have redirected away from, which is a different
#: (and rarer) mistake than handing it the live one.
STANDARD_STREAMS: Final[tuple[str, ...]] = ("stdin", "stdout", "stderr")

DIAGNOSTIC: Final[str] = "diagnostic"
BYTES: Final[str] = "bytes"


@dataclass(frozen=True)
class StreamArgument:
    """One call in ``adapters/`` handed a stream this product constructed."""

    module: str
    line: int
    kind: str
    call: str
    guarded: bool

    def describe(self) -> str:
        state = "inside the guard" if self.guarded else "UNGUARDED"
        return f"{self.module}:{self.line} [{self.kind}, {state}] {self.call}"


def _constructor_name(node: ast.AST) -> str | None:
    """``io.StringIO()`` and a bare ``StringIO()`` both answer ``"StringIO"``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id == io.__name__ else None
    if isinstance(func, ast.Name):
        return func.id
    return None


def _relative(path: Path) -> str:
    """A path a reader can open. A PLANTED tree lives outside the repository, and
    a walk that crashed on one would make every control below unrunnable."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _standard_stream(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == sys.__name__
        and node.attr in STANDARD_STREAMS
    )


def _kind_of(node: ast.AST, bindings: dict[str, str]) -> str | None:
    """``"diagnostic"``, ``"bytes"`` or ``None`` for an expression used as an argument."""
    constructor = _constructor_name(node)
    if constructor in TEXT_CONSTRUCTORS:
        return DIAGNOSTIC
    if constructor in BYTE_CONSTRUCTORS:
        return BYTES
    if _standard_stream(node):
        return DIAGNOSTIC
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    return None


def _scopes(tree: ast.Module) -> list[ast.AST]:
    """Every function body, plus the module body — the units a local name lives in.

    D3's rule resolves a name bound *in the same function*, so the binding map
    has to be rebuilt per scope: two functions may legitimately bind the same
    name to different kinds of stream, and one shared map would cross them.
    """
    found: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append(node)
    return found


def _local_stream_bindings(scope: ast.AST) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(scope):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, ast.NamedExpr):
            target, value = node.target, node.value
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            target, value = node.optional_vars, node.context_expr
        if not isinstance(target, ast.Name) or value is None:
            continue
        kind = _kind_of(value, {})
        if kind is not None:
            bindings[target.id] = kind
    return bindings


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _is_guarded(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """Is *call* lexically enclosed by a ``with`` on the named guard?"""
    node: ast.AST | None = call
    while node is not None:
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                name = _constructor_name(item.context_expr)
                if name == GUARD_NAME:
                    return True
        node = parents.get(node)
    return False


def owned_stream_arguments(adapters: Path = ADAPTERS) -> list[StreamArgument]:
    """Every call in *adapters* handed a stream this product constructed.

    The observable proxy for D3's class — *any call into an engine that rebinds a
    standard stream and does not restore it* — is *any call handed a stream the
    product owns*, which is what a static walk can decide. Both inline arguments
    (``engine.check(io.StringIO())``) and arguments bound to a local name earlier
    in the same function (``buffer = io.BytesIO(); pdf.save(buffer)``) are
    resolved, because looking only at the call site misses the second shape
    entirely and the second shape is the more common one in this package.

    The constructor call itself is never counted as its own argument: the
    ``data`` in ``io.BytesIO(data)`` is bytes, not a stream.
    """
    found: list[StreamArgument] = []
    for path in sorted(adapters.glob("*.py")):
        tree = ast.parse(path.read_text())
        parents = _parents(tree)
        module = _relative(path)
        seen: set[tuple[int, int, str]] = set()
        for scope in _scopes(tree):
            bindings = _local_stream_bindings(scope)
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                if _constructor_name(node) in TEXT_CONSTRUCTORS | BYTE_CONSTRUCTORS:
                    continue
                arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
                for index, argument in enumerate(arguments):
                    kind = _kind_of(argument, bindings)
                    if kind is None:
                        continue
                    fingerprint = (node.lineno, node.col_offset, f"{index}:{kind}")
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    found.append(
                        StreamArgument(
                            module=module,
                            line=node.lineno,
                            kind=kind,
                            call=ast.unparse(node)[:90],
                            guarded=_is_guarded(node, parents),
                        )
                    )
    return sorted(found, key=lambda site: (site.module, site.line, site.kind))


# --------------------------------------------------------------------------- #
# AC7 / AC8 — the class rule, over the whole package, with no allowlist
# --------------------------------------------------------------------------- #


@pytest.fixture
def census() -> list[StreamArgument]:
    return owned_stream_arguments()


def test_the_walk_resolves_both_populations_or_every_arm_below_is_vacuous(
    census: list[StreamArgument],
) -> None:
    """AC7 half (ii). A walk that matched nothing satisfies the rule perfectly.

    Both halves are required and they fail for different reasons. An empty
    DIAGNOSTIC population means the walk stopped seeing the one site the rule
    exists for; an empty BYTE-CARRYING population means it stopped seeing the
    21 sites that prove the rule has a domain it deliberately excludes — and an
    over-narrow walk that found neither would otherwise report the strongest
    possible green.
    """
    diagnostic = [site for site in census if site.kind == DIAGNOSTIC]
    byte_carrying = [site for site in census if site.kind == BYTES]
    assert diagnostic, (
        "the walk found NO product-owned diagnostic stream argument anywhere in "
        f"{ADAPTERS.relative_to(REPO_ROOT)}. The rule below would then pass over an empty "
        "set; a walk that sees nothing is not a package that does nothing"
    )
    assert byte_carrying, (
        "the walk found NO product-owned byte-carrying stream argument. Those sites "
        "are what prove the rule has a domain it EXCLUDES rather than an allowlist it "
        "consults, so their disappearance means the classifier stopped classifying"
    )


def test_every_product_owned_diagnostic_stream_argument_sits_inside_the_guard(
    census: list[StreamArgument],
) -> None:
    """AC7 — D3's rule, stated once and enforced over all of ``adapters/``.

    There is no allowlist and there is nowhere to add one: the byte-carrying
    sites are not listed as exceptions, they simply do not carry a diagnostic
    stream, so the rule never reaches them. Today its domain holds exactly one
    site and that site is guarded; a second unguarded one is red on arrival
    rather than silent for a cycle.
    """
    unguarded = [site for site in census if site.kind == DIAGNOSTIC and not site.guarded]
    listing = "\n  ".join(site.describe() for site in unguarded)
    assert not unguarded, (
        f"{len(unguarded)} call(s) in {ADAPTERS.relative_to(REPO_ROOT)} are handed one of "
        f"this process's own DIAGNOSTIC streams outside `{GUARD_NAME}`:\n  {listing}\n"
        "An engine handed a text stream may BIND it rather than write to it — "
        "`pikepdf.Pdf.check_linearization` assigns `sys.stderr` and never restores it — "
        f"and from that call onward every diagnostic this process writes is lost. Wrap "
        f"the call in `with {GUARD_NAME}():`; do not add an exception here."
    )


def test_the_shipped_diagnostic_site_is_the_one_the_spec_measured(
    census: list[StreamArgument],
) -> None:
    """The rule's domain is named, so a reader can check it against the product.

    Asserted as the SET of modules carrying a diagnostic argument rather than as
    a count, because a count is the thing this product keeps getting wrong and a
    set says which sites moved.
    """
    modules = {site.module for site in census if site.kind == DIAGNOSTIC}
    expected = {(ADAPTERS / "pikepdf_structure.py").relative_to(REPO_ROOT).as_posix()}
    assert modules == expected, (
        f"the diagnostic population lives in {sorted(modules)}, not {sorted(expected)}. "
        "A new module in the rule's domain is not a failure by itself — it is a site "
        "that must be read, guarded, and named here."
    )


# --------------------------------------------------------------------------- #
# AC7's controls — planted into a COPY of `src/`, never into the real tree
# --------------------------------------------------------------------------- #

_PLANT_INLINE = (
    "import io\n\n\ndef leak(engine: object) -> None:\n    engine.check(io.StringIO())\n"
)
_PLANT_LOCAL = (
    "import io\n\n\ndef leak(engine: object) -> None:\n"
    "    sink = io.StringIO()\n    engine.check(sink)\n"
)
_PLANT_SYS_STDERR = (
    "import sys\n\n\ndef leak(engine: object) -> None:\n    engine.check(sys.stderr)\n"
)
_PLANT_GUARDED = (
    "import io\n\nfrom pdf_tooling.adapters import restore_standard_streams\n\n\n"
    "def polite(engine: object) -> None:\n"
    "    with restore_standard_streams():\n        engine.check(io.StringIO())\n"
)
_PLANT_BYTES = (
    "import io\n\n\ndef carry(engine: object) -> None:\n    engine.read(io.BytesIO(b''))\n"
)


def _planted_adapters(tmp_path: Path, source: str) -> Path:
    """A copy of ``adapters/`` with one extra module in it. The real tree is read-only."""
    scratch = tmp_path / "adapters"
    shutil.copytree(ADAPTERS, scratch)
    (scratch / "sneaky.py").write_text(source)
    return scratch


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("plant-inline-stringio", _PLANT_INLINE),
        ("plant-stringio-bound-to-a-local", _PLANT_LOCAL),
        ("plant-sys-stderr", _PLANT_SYS_STDERR),
    ],
    ids=["plant-inline-stringio", "plant-stringio-bound-to-a-local", "plant-sys-stderr"],
)
def test_a_planted_unguarded_diagnostic_stream_reddens_the_walk(
    label: str, source: str, tmp_path: Path
) -> None:
    """AC7 half (i) — three shapes, because the rule claims to catch three.

    The inline shape is the one the product already has; the locally-bound shape
    is the one the product has only in its byte-carrying half, so without this
    plant the name-resolution half of the walk would be untested; and the
    ``sys.stderr`` shape is the one no adapter has ever written, which is
    exactly why nothing but a plant can prove it is seen.
    """
    planted = owned_stream_arguments(_planted_adapters(tmp_path, source))
    offenders = [
        site
        for site in planted
        if site.kind == DIAGNOSTIC and not site.guarded and site.module.endswith("sneaky.py")
    ]
    assert offenders, f"{label}: the walk did not notice the planted unguarded stream"
    described = offenders[0].describe()
    assert "sneaky.py" in described and ":" in described, (
        f"{label}: the finding does not name the file and line a reader would open: {described}"
    )


def test_a_planted_guarded_diagnostic_stream_does_not_redden_the_walk(tmp_path: Path) -> None:
    """The complement. A rule that reddened on a CORRECT new site would be
    unusable, and a rule that can only go red is not measuring guardedness."""
    planted = owned_stream_arguments(_planted_adapters(tmp_path, _PLANT_GUARDED))
    sneaky = [site for site in planted if site.module.endswith("sneaky.py")]
    assert sneaky, "the walk did not see the planted call at all, so it proves nothing here"
    assert all(site.guarded for site in sneaky), (
        f"a correctly guarded new site was reported unguarded: {[s.describe() for s in sneaky]}"
    )


def test_a_planted_unguarded_byte_stream_is_classified_and_not_demanded(tmp_path: Path) -> None:
    """AC7 half (ii), as a plant rather than as a claim.

    The 21 byte-carrying sites are not exempted from the rule, they are outside
    it. This proves the difference is real: a NEW unguarded ``io.BytesIO``
    argument is SEEN by the walk — so the classifier is not simply blind to it —
    and is still not demanded to be guarded.
    """
    planted = owned_stream_arguments(_planted_adapters(tmp_path, _PLANT_BYTES))
    sneaky = [site for site in planted if site.module.endswith("sneaky.py")]
    assert sneaky, "the walk did not see the planted byte-carrying argument at all"
    assert all(site.kind == BYTES for site in sneaky), [s.describe() for s in sneaky]
    # Scoped to the PLANTED module on purpose. Asserting over the whole planted
    # tree would fold in whatever the shipped sites are doing, so the arm would
    # red for a reason with nothing to do with the plant -- observed while
    # driving the guard-removed red control against the real tree.
    assert not [site for site in sneaky if site.kind == DIAGNOSTIC], (
        "a byte-carrying argument was pulled into the rule's domain, which would put an "
        f"allowlist-shaped hole in D3: {[site.describe() for site in sneaky]}"
    )


# --------------------------------------------------------------------------- #
# AC2 — restoration, observed from a child process that owns its own sentinels
# --------------------------------------------------------------------------- #

#: Runs in a CHILD, never here. It installs three sentinel streams of its own,
#: drives the adapter's `linearize`, and reports whether each name still points
#: at its sentinel afterwards. Sentinels rather than `sys.__std*__` is what makes
#: this catch D1's trap: a `finally` that assigns `sys.__stderr__` passes an
#: identity check written against `sys.__stderr__` and fails this one, because it
#: did not restore a binding — it destroyed one.
#:
#: The two WRONG implementations are reached by substituting the guard SYMBOL the
#: adapter calls, not by compiling a mutated copy of `src/`. A copy was written
#: first and is not what ships, for two measured reasons. It imports as a SECOND
#: `pdf_tooling` from a temp path, and `[tool.coverage.run] source =
#: ["pdf_tooling"]` measures anything importable under that name wherever it
#: lives — so `make cover` reported 20168 statements at 38% against an 85% floor,
#: from one extra copy of the package. The obvious remedy, scrubbing
#: `COVERAGE_PROCESS_*` out of the child, is pinned at exactly one site by
#: `tests/test_coverage_policy.py::test_exactly_one_test_module_scrubs_the_coverage_environment`
#: and that site is the startup-budget arm. Substitution is also STRICTLY
#: STRONGER than the copy it replaces: the substitute records that it was
#: entered, so "the mutation did not apply" reds instead of reading as "the
#: mutation applied and was harmless", which a text-diff check cannot tell apart.
#: The source-level mutations were still driven by hand against the real tree and
#: are recorded in this spec's report.
_IDENTITY_CHILD: Final[str] = '''\
import contextlib
import io
import json
import sys
from pathlib import Path


class Sentinel(io.StringIO):
    """Neither `sys.__std*__` nor any buffer an engine constructs for itself."""


MODE = sys.argv[1]
DOCUMENT = sys.argv[2]

from pdf_tooling.adapters import pikepdf_structure
from pdf_tooling.errors import PdfToolingError

entered = []

if MODE != "shipped":
    if not hasattr(pikepdf_structure, "restore_standard_streams"):
        raise SystemExit(
            "the adapter no longer holds the guard under that name, so this control "
            "would substitute nothing and report a green it did not earn"
        )

    @contextlib.contextmanager
    def substitute():
        entered.append(MODE)
        if MODE == "no-guard":
            yield                      # the pre-fix shape: nothing saved, nothing put back
        else:
            try:
                yield
            finally:                   # D1's trap, spelled out
                sys.stdin = sys.__stdin__
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__

    pikepdf_structure.restore_standard_streams = substitute

real_streams = (sys.stdin, sys.stdout, sys.stderr)
sentinels = {"stdin": Sentinel(), "stdout": Sentinel(), "stderr": Sentinel()}
for name, sentinel in sentinels.items():
    setattr(sys, name, sentinel)

raised = None
try:
    pikepdf_structure.ADAPTER.linearize(Path(DOCUMENT).read_bytes())
except PdfToolingError as error:
    raised = type(error).__name__

report = {
    "mode": MODE,
    "raised": raised,
    "substitute_entered": len(entered),
    "restored": {name: getattr(sys, name) is s for name, s in sentinels.items()},
    "took_the_original": {
        name: getattr(sys, name) is getattr(sys, "__%s__" % name) for name in sentinels
    },
}

# Put the REAL streams back before reporting. Printing to a saved handle while
# `sys.stdout` still points at a sentinel loses the verdict outright: the
# interpreter's shutdown flush drains whatever `sys.stdout` is bound to, and
# under `make cover` coverage's own shutdown hooks reorder teardown enough that
# the saved handle went unflushed and the parent read ZERO bytes. Measured, in
# `make engines-gate` arm 1 and nowhere else -- `make test` never showed it.
sys.stdin, sys.stdout, sys.stderr = real_streams
print(json.dumps(report))
sys.stdout.flush()
'''


def _identity_verdict(document: Path, *, mode: str = "shipped") -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", _IDENTITY_CHILD, mode, str(document)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120.0,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"the identity child ({mode}) exited {result.returncode}; it must always report a "
        f"verdict, because a crashed probe and a restored stream are not the same green.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip(), (
        f"the identity child ({mode}) exited 0 and printed NOTHING. A silent probe is the "
        f"one outcome this arm may never read as agreement. stderr: {result.stderr!r}"
    )
    verdict = json.loads(result.stdout)
    assert isinstance(verdict, dict)
    return verdict


@pytest.fixture
def linearizable(tmp_path: Path) -> Path:
    """A document `linearize` succeeds on, built by the product's own `create`."""
    source = tmp_path / "note.txt"
    source.write_text("PDF-81 payload\n")
    target = tmp_path / "linearizable.pdf"
    result = run_cli("create", str(source), "-O", str(target), "-o", "json", cwd=tmp_path)
    assert result.returncode == 0, f"could not build the fixture: {result.stdout}{result.stderr}"
    return target


@pytest.mark.parametrize("path_name", ["linearizable", "malformed"])
def test_the_guard_restores_the_binding_that_was_live_at_the_call(
    path_name: str, linearizable: Path
) -> None:
    """AC2 — on BOTH paths, and the failing one is the one that matters.

    The success path proves the ``finally`` runs on a normal return. The
    ``malformed.pdf`` path proves it runs while a ``FailureError`` is in flight,
    which is the path the defect actually lived on: the verdict this call
    produces is what raises the error, and the error is rendered to
    ``sys.stderr`` four lines later.
    """
    document = linearizable if path_name == "linearizable" else MALFORMED
    verdict = _identity_verdict(document)

    expected_raise = None if path_name == "linearizable" else "FailureError"
    assert verdict["raised"] == expected_raise, f"the child took an unexpected path: {verdict}"

    restored = verdict["restored"]
    assert isinstance(restored, dict)
    assert all(restored.values()), (
        f"after `linearize` over {document.name} the child's own sentinel streams were not "
        f"put back: {restored}. `took_the_original` was {verdict['took_the_original']} — "
        "True there means the guard assigned `sys.__std*__` instead of restoring what was "
        "live at the call, which is D1's trap and clobbers any legitimate redirection."
    )


@pytest.mark.parametrize(
    ("mode", "expect_original"),
    [("no-guard", False), ("dunder-restore", True)],
    ids=["no-guard", "dunder-restore"],
)
def test_the_restoration_arm_reddens_on_both_wrong_implementations(
    mode: str, expect_original: bool, linearizable: Path
) -> None:
    """AC2's two-halved control, SHIPPED rather than driven once by hand.

    Half (i) is the pre-fix binary: no restoring guard at all, so ``sys.stderr``
    is left pointing at the engine's throwaway buffer. Half (ii) is the
    implementation that looks right and is not — ``sys.stderr = sys.__stderr__``
    in the ``finally``. **The first alone would pass the second**, which is why
    both are here, and ``took_the_original`` is what tells them apart so a reader
    can see WHICH wrong answer was given rather than only that one was.

    Driven against the real tree while writing this item, the D1 trap left every
    behavioural arm in this module GREEN and reddened only these two cells. That
    is the whole argument for a structural arm existing at all.
    """
    verdict = _identity_verdict(linearizable, mode=mode)

    assert verdict["substitute_entered"], (
        f"{mode}: the substituted guard was never entered, so this control mutated nothing "
        f"and its red would be unearned. Verdict: {verdict}"
    )
    restored = verdict["restored"]
    took_original = verdict["took_the_original"]
    assert isinstance(restored, dict) and isinstance(took_original, dict)
    assert not restored["stderr"], (
        f"{mode}: the wrong implementation still restored the child's sentinel stderr, so "
        f"this control does not control anything. Verdict: {verdict}"
    )
    assert took_original["stderr"] is expect_original, (
        f"{mode}: expected took_the_original[stderr] to be {expect_original}, got "
        f"{took_original['stderr']} — the two wrong implementations are distinguishable "
        f"and this arm asserts WHICH one it saw. Verdict: {verdict}"
    )


# --------------------------------------------------------------------------- #
# AC3 / AC4 / AC6 / AC9 — the defect as a user meets it, through `run_cli`
# --------------------------------------------------------------------------- #

VERDICT_FAILURE: Final[str] = "linearization did not verify: the saved output is not linearized"


def test_a_failed_linearization_reaches_stderr_under_o_table(tmp_path: Path) -> None:
    """AC3 — one command, a fixture this repository ships, no second filesystem.

    Pre-fix this exited 1 with **zero bytes on both channels**, 3/3: the
    `error:` line was rendered into the buffer the engine had put in
    ``sys.stderr``'s place four lines earlier. Asserted on CONTENT and never on a
    byte count, because a byte count is a figure that goes stale and the point
    was never how many bytes arrived.
    """
    result = run_cli(
        "linearize",
        str(MALFORMED),
        "-O",
        str(tmp_path / "out.pdf"),
        "-f",
        "-o",
        "table",
        cwd=tmp_path,
    )
    assert result.returncode == 1, f"rc={result.returncode} {result.stdout}{result.stderr}"
    assert result.stdout == "", (
        f"`-o table` puts the payload on stdout and the error on stderr; stdout carried "
        f"{result.stdout!r}"
    )
    lines = [line for line in result.stderr.splitlines() if line.startswith("error:")]
    assert lines == [f"error: {VERDICT_FAILURE}"], (
        f"linearize said {result.stderr!r} on stderr. Before PDF-81 it said nothing at all, "
        "on a failure reachable in one command over a file this repository ships"
    )


def test_the_same_failure_class_on_compress_was_visible_all_along(tmp_path: Path) -> None:
    """AC3's counterpart control — the arm is not measuring the document.

    Same operand, same shape, same error class, a different verb, and it was
    green BEFORE the fix. A probe that reddened on both verbs would be measuring
    the input; a probe green on ``compress`` and red on ``linearize`` isolates
    the variable to the one call ``linearize`` makes and ``compress`` does not.
    """
    result = run_cli(
        "compress",
        str(MALFORMED),
        "-O",
        str(tmp_path / "out.pdf"),
        "-f",
        "-o",
        "table",
        cwd=tmp_path,
    )
    assert result.returncode == 1, f"rc={result.returncode} {result.stdout}{result.stderr}"
    assert [line for line in result.stderr.splitlines() if line.startswith("error:")], (
        f"compress reached its failure with nothing on stderr: {result.stderr!r}. This arm "
        "is the pre-fix control for the one above and it was never supposed to move"
    )


def test_the_json_limb_is_unchanged_and_the_fix_does_not_duplicate_onto_stderr(
    tmp_path: Path,
) -> None:
    """AC4 — the limb that was always intact must stay exactly as intact.

    ``emit_error``'s structured branch writes to ``sys.stdout``, which the engine
    never rebound, so a machine consumer reading stdout learned the run failed
    even on the pre-fix binary. The assertion that stderr stays EMPTY here is the
    control: a fix that "helpfully" routed the error to both channels would pass
    every other arm in this module and fail this one.
    """
    result = run_cli(
        "linearize",
        str(MALFORMED),
        "-O",
        str(tmp_path / "out.pdf"),
        "-f",
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert result.returncode == 1, f"rc={result.returncode} {result.stdout}{result.stderr}"
    error = json.loads(result.stdout)["error"]
    assert error["code"] == 1, error
    assert error["kind"] == "failure", error
    assert error["message"] == VERDICT_FAILURE, error
    assert result.stderr == "", (
        f"the structured error also reached stderr: {result.stderr!r}. `-o json` puts the "
        "envelope on stdout and nothing on stderr; duplicating it is a second defect"
    )


def test_a_post_engine_bug_path_on_linearize_is_not_silent(
    tmp_path: Path, linearizable: Path
) -> None:
    """AC6 — graded on NON-SILENCE only, never on the traceback's content.

    An existing directory as the destination, under ``-f`` so the clobber gate
    permits it, makes ``os.replace`` raise AFTER the engine has run. Every other
    producing verb has always printed its traceback here; ``linearize`` printed
    nothing, which is strictly worse than the traceback because it names no
    fault at all. Tidying that traceback into an envelope is the `PDF-50`
    bug-path class and explicitly not this item's — what is asserted is only
    that the user is told something.
    """
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    linearize = run_cli(
        "linearize", str(linearizable), "-O", str(occupied), "-f", "-o", "table", cwd=tmp_path
    )
    compress = run_cli(
        "compress", str(linearizable), "-O", str(occupied), "-f", "-o", "table", cwd=tmp_path
    )
    assert compress.stderr.strip(), (
        "the control verb went silent on the bug path too, so this arm is measuring the "
        f"destination shape rather than the verb: {compress.stdout!r} {compress.stderr!r}"
    )
    assert linearize.stderr.strip(), (
        f"linearize exited {linearize.returncode} with nothing on either channel "
        f"({linearize.stdout!r} / {linearize.stderr!r}). A process that fails silently "
        "cannot be debugged by the person it failed for"
    )


def test_linearize_still_verifies_and_still_refuses(tmp_path: Path, linearizable: Path) -> None:
    """AC9 — the verdict is produced by the very call the guard now wraps, so the
    ``finally`` must alter neither the ``bool(...)`` nor the inner
    ``except RuntimeError: verified = False``."""
    refused = run_cli(
        "linearize",
        str(MALFORMED),
        "-O",
        str(tmp_path / "refused.pdf"),
        "-f",
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert refused.returncode == 1, f"{refused.stdout}{refused.stderr}"
    assert json.loads(refused.stdout)["error"]["message"] == VERDICT_FAILURE, refused.stdout

    accepted = run_cli(
        "linearize",
        str(linearizable),
        "-O",
        str(tmp_path / "accepted.pdf"),
        "-f",
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert accepted.returncode == 0, f"{accepted.stdout}{accepted.stderr}"
    item = json.loads(accepted.stdout)["items"][0]
    assert item["message"] == "linearized", item
    assert item["bytes_after"], (
        f"a successful linearization published no output size: {item}. The guard must not "
        "change what the verification produced, only who owns the stream afterwards"
    )


# --------------------------------------------------------------------------- #
# AC14 — the broken instrument stays out, enforced rather than requested
# --------------------------------------------------------------------------- #


def _sys_attribute(node: ast.AST) -> str | None:
    """``sys.stderr`` -> ``"stderr"``, ``sys.__stderr__`` -> ``"__stderr__"``."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == sys.__name__
    ):
        return node.attr
    return None


def _stream_identity_assertions(root: Path) -> list[str]:
    """Every ``assert`` comparing a live stream name with its ``sys.__*__`` original."""
    originals = {f"__{name}__" for name in STANDARD_STREAMS}
    live = set(STANDARD_STREAMS)
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            for compare in ast.walk(node.test):
                if not isinstance(compare, ast.Compare):
                    continue
                if not any(isinstance(op, ast.Is | ast.IsNot) for op in compare.ops):
                    continue
                operands = (compare.left, *compare.comparators)
                attributes = {name for name in map(_sys_attribute, operands) if name is not None}
                if attributes & originals and attributes & live:
                    found.append(f"{_relative(path)}:{node.lineno}")
    return found


def test_no_shipped_arm_asserts_stream_identity_inside_the_pytest_process() -> None:
    """AC14 — ``assert sys.stderr is sys.__stderr__`` measures pytest, not the product.

    pytest's capture rebinds those names itself, so the assertion's meaning
    depends on whether ``-s`` was passed and it can be made to pass on the
    pre-fix binary. Identity is observed only from a child that installs
    sentinels of its own (:func:`_identity_verdict`). This arm exists because
    the reasoning above is a paragraph, and a paragraph does not survive the
    next author reaching for ``capsys``.
    """
    offenders = _stream_identity_assertions(TESTS_DIR)
    assert offenders == [], (
        f"in-process standard-stream identity assertions at: {offenders}. Under pytest's "
        "capture those compare two objects pytest chose; under `-s` two it left alone. "
        "Drive a child process and assert on ITS verdict instead"
    )


def test_the_identity_detector_is_shown_finding_its_needle_before_it_is_trusted(
    tmp_path: Path,
) -> None:
    """The arm above is a negative, and a negative over a broken detector is the
    strongest possible green. Both halves: the forbidden shape is found, and an
    ordinary stream assertion beside it is not."""
    (tmp_path / "planted.py").write_text(
        "import sys\n\n\ndef probe() -> None:\n"
        "    assert sys.stderr is sys.__stderr__\n"
        "    assert sys.stderr is not None\n"
        '    assert sys.stderr.write("x")\n'
    )
    found = _stream_identity_assertions(tmp_path)
    assert len(found) == 1, f"the detector reported {found} for one planted needle"
    assert found[0].endswith(":5"), f"the detector named the wrong line: {found}"
