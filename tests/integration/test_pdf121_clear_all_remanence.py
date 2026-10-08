"""PDF-121 -- ``meta set --clear-all`` drops the XMP packet; nothing it removed is recoverable.

Ledger ``350c89b83c`` (critical): ``--clear-all`` unlinked ``/Metadata`` from the
catalogue and then wrote the input's packet anyway, byte-identical, as an
unreferenced ``/Type /Metadata`` stream. The run exited ``0``, ``ok``,
``warnings: []``, and ``meta get`` called the file clean. Ledger ``23659a085e``
(R-04, folded): eight page verbs wrote a duplicate unreferenced ``/Info``.

THE ORACLE IS INDEPENDENT. ``tests/remanence.py`` imports nothing from
``pdf_tooling``; the CLI runs as a subprocess. The search is a raw byte search
over every encoded string form AND a decoded scan of every object the xref lists,
with the unreachable set computed twice (pikepdf, pypdf) -- see that module.

ARMS. PC (the positive control, which every other arm depends on), S (the
sentinel matrix), V (the verifier shape matrix incl. encryption and the README
chain), P (the page-verb ``/Info`` census), R (no prior revision), plus the
AC9 census of pypdf write sites.

Every guard here was driven red before landing; the commit body records each
``mutation -> failing node -> assertion``.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import remanence as R  # noqa: E402
from registry import PDF_08_VERBS, expectation, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"

#: The positive control's literal expectations, with provenance: measured on
#: 2026-10-08 at `e2a980e` (pypdf 6.19.0, pikepdf 10.16.0) by scanning the
#: UN-cleared inputs. ``raw`` = locations found in the file bytes; ``reachable``
#: / ``unreachable`` = locations found in a decoded xref object that the trailer
#: does / does not reach; ``revisions`` = (startxref, %%EOF, trailer /Prev).
#: Nothing here is derived from ``src/``.
PC_EXPECT: Final[dict[str, dict[str, Any]]] = {
    "A": {
        "raw": {"info", "xmp", "content"},
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    # A2: the Flate packet is raw-ABSENT and decoded-PRESENT; the pypdf-written
    # /Info is raw-present only through the octal-escape form (`SENT\055INFO`).
    "A2": {
        "raw": {"info"},
        "reachable": {"info", "xmp"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "E": {
        "raw": {"info", "xmp"},
        "reachable": {"info", "xmp"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "D": {
        "raw": {"info", "xmp", "page_xmp", "content"},
        "reachable": {"info", "xmp", "page_xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "U": {
        "raw": {"info", "content"},
        "reachable": {"info", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "U_pypdf": {
        "raw": {"info"},
        "reachable": {"info"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "U16": {
        "raw": {"info", "content"},
        "reachable": {"info", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "U16_pypdf": {
        "raw": {"info"},
        "reachable": {"info"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    # B: the old revision is raw-visible (`SENT-OLDREV`) and the old packet is an
    # unreachable listed object (`SENT-OLDXMP`); the trailer carries /Prev.
    "B": {
        "raw": {"old_info", "info", "old_xmp", "xmp", "content"},
        "reachable": {"info", "xmp", "content"},
        "unreachable": {"old_xmp"},
        "revisions": (2, 2, True),
    },
    "B2": {
        "raw": {"old_info", "info", "content"},
        "reachable": {"info", "content"},
        "unreachable": {"old_info"},
        "revisions": (2, 2, True),
    },
    "C": {
        "raw": {"info", "xmp", "chain", "content"},
        "reachable": {"info", "xmp", "chain", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "C2": {
        "raw": {"info", "xmp", "content"},
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "O": {
        "raw": {"info", "xmp", "preorphan", "content"},
        "reachable": {"info", "xmp", "content"},
        "unreachable": {"preorphan"},
        "revisions": (1, 1, False),
    },
    # Encrypted: strings are ciphertext on the wire. pikepdf builds RC4 (R3) only
    # with /EncryptMetadata false and (measured) the packet is not raw-visible
    # there either; AES256-NOMETA leaves the packet plaintext.
    "A-RC4-UO": {
        "raw": set(),
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "A-AES128-UO": {
        "raw": set(),
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "A-AES256-UO": {
        "raw": set(),
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "A-AES256-O": {
        "raw": set(),
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
    "A-AES256-NOMETA-UO": {
        "raw": {"xmp"},
        "reachable": {"info", "xmp", "content"},
        "unreachable": set(),
        "revisions": (1, 1, False),
    },
}


#: Doc-level sentinel LOCATIONS a `--clear-all` run removes (everything but the
#: false-removal controls).
def _removed(fixture: str) -> dict[str, str]:
    return {k: v for k, v in R.SENTINELS[fixture].items() if k not in R.KEPT_LOCATIONS}


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pdf121")


@pytest.fixture(scope="module")
def fx(work: Path) -> dict[str, Path]:
    """The un-cleared inputs (built once per worker)."""
    return R.build_fixtures(work / "fx")


@pytest.fixture(scope="module")
def env(work: Path) -> dict[str, str]:
    home = work / "home"
    tmp = work / "tmp"
    home.mkdir()
    tmp.mkdir()
    return {**os.environ, "HOME": str(home), "TMPDIR": str(tmp)}


def assert_positive_control(fx: dict[str, Path], work: Path) -> None:
    for name, expected in PC_EXPECT.items():
        sentinels = R.SENTINELS[name]
        password, _ = R.passwords_for(name, work / "fx")
        result = R.scan(fx[name], list(sentinels.values()), password)
        where = {
            "raw": {loc for loc, s in sentinels.items() if s in result.raw_hits},
            "reachable": {
                loc
                for loc, s in sentinels.items()
                if s in result.decoded_hits and any(r for _, r in result.decoded_hits[s])
            },
            "unreachable": {
                loc
                for loc, s in sentinels.items()
                if s in result.decoded_hits and any(not r for _, r in result.decoded_hits[s])
            },
        }
        for channel, found in where.items():
            assert found == expected[channel], (
                f"POSITIVE CONTROL {name}/{channel}: found {sorted(found)}, "
                f"expected {sorted(expected[channel])} (a scan that cannot find a "
                f"planted sentinel proves nothing about its absence)"
            )
        assert result.revisions == expected["revisions"], (
            f"POSITIVE CONTROL {name}: revisions {result.revisions} != {expected['revisions']}"
        )
        assert len(result.unreachable) == len(expected["unreachable"]), (
            f"POSITIVE CONTROL {name}: {len(result.unreachable)} unreachable objects"
        )


def test_positive_control_finds_every_sentinel_in_the_inputs(
    fx: dict[str, Path], work: Path
) -> None:
    """PC: the instrument finds every planted sentinel on every channel it should."""
    assert_positive_control(fx, work)


@pytest.fixture(scope="module")
def control(fx: dict[str, Path], work: Path) -> None:
    """Every other arm depends on the control: if it is red they are meaningless."""
    assert_positive_control(fx, work)


def cli(env: dict[str, str], work: Path, verb: str, *args: str) -> tuple[int, dict[str, Any]]:
    proc = run_cli(verb, *args, "-o", "json", env=env, cwd=work)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"unparsed_stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, payload


def clear_all(
    env: dict[str, str], work: Path, source: Path, out: Path, *extra: str
) -> dict[str, Any]:
    rc, payload = cli(env, work, "meta set", str(source), "--clear-all", "-O", str(out), *extra)
    assert rc == 0, f"meta set --clear-all rc {rc}: {payload}"
    assert payload["items"][0]["message"] == "ok", payload
    if "--allow-decrypted-output" in extra:
        assert [w for w in payload["warnings"] if "input is encrypted" not in w] == [], payload
    else:
        assert payload["warnings"] == [], payload
    return payload


def in_place_copy(fx: dict[str, Path], env: dict[str, str], work: Path, tag: str) -> Path:
    target = work / f"{tag}-in-place.pdf"
    shutil.copy(fx["A"], target)
    rc, payload = cli(
        env, work, "meta set", str(target), "--clear-all", "--in-place", "--no-backup", "-y"
    )
    assert rc == 0, payload
    assert payload["items"][0]["message"] == "ok", payload
    return target


def assert_nothing_removed_survives(path: Path, fixture: str, password: str = "") -> None:
    sentinels = R.SENTINELS[fixture]
    removed = _removed(fixture)
    result = R.scan(path, list(sentinels.values()), password)
    for location, sentinel in removed.items():
        assert sentinel not in result.raw_hits, (
            f"RAW: {sentinel!r} ({location}) is still in the bytes of {path.name}"
        )
        assert sentinel not in result.decoded_hits, (
            f"DECODED: {sentinel!r} ({location}) is still in xref object(s) "
            f"{result.decoded_hits.get(sentinel)} of {path.name}"
        )
    assert result.unreachable == (), (
        f"UNREACHABLE: {path.name} lists objects the trailer does not reach: {result.unreachable}"
    )
    assert result.revisions == (1, 1, False), f"REVISIONS: {result.revisions} in {path.name}"
    for location, sentinel in sentinels.items():
        if location in R.KEPT_LOCATIONS:
            hits = result.decoded_hits.get(sentinel)
            assert hits and all(reachable for _, reachable in hits), (
                f"FALSE REMOVAL: {sentinel!r} ({location}) must survive --clear-all, got {hits}"
            )


# --------------------------------------------------------------------------- #
# S -- the sentinel matrix
# --------------------------------------------------------------------------- #

S_CASES: Final[tuple[str, ...]] = (
    "A",
    "A2",
    "E",
    "D",
    "U",
    "U_pypdf",
    "U16",
    "U16_pypdf",
    "B",
    "B2",
    "C",
    "C2",
    "O",
    "A-in-place",
)


@pytest.mark.parametrize("case", S_CASES)
def test_clear_all_leaves_no_removed_sentinel(
    case: str, control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    """S: nothing `--clear-all` removed is in the output on ANY channel; the page-2 packet stays."""
    if case == "A-in-place":
        out, fixture = in_place_copy(fx, env, work, "s"), "A"
    else:
        out, fixture = work / f"s-{case}.pdf", case
        clear_all(env, work, fx[case], out)
    assert_nothing_removed_survives(out, fixture)
    if case == "D":
        rc, payload = cli(env, work, "meta get", str(out))
        assert rc == 0, payload
        assert payload["residual_surfaces"]["page_xmp_pages"] == [2], payload["residual_surfaces"]


# --------------------------------------------------------------------------- #
# V -- the independent verifier shape matrix (the PDF-107 rule)
# --------------------------------------------------------------------------- #

V_ENCRYPTED: Final[tuple[str, ...]] = (
    "RC4-UO",
    "AES128-UO",
    "AES256-UO",
    "AES256-O",
    "AES256-NOMETA-UO",
)
V_CASES: Final[tuple[str, ...]] = (
    *V_ENCRYPTED,
    "readme-chain-rotate",
    "readme-chain-extract",
    "A",
    "A2",
    "E",
    "D",
    "A-in-place",
)

#: Provenance: `e2a980e`, 2026-10-08. At that commit `meta set --clear-all` over
#: `A-AES256-NOMETA-UO` left exactly ONE unreferenced /Type /Metadata stream (it
#: holds pypdf's mis-decrypted bytes, the `17add7b3e9` class, so no sentinel
#: matches it). After the fix the expected population is empty.
NOMETA_ORPHAN_METADATA_AT_BASE: Final[int] = 1
NOMETA_ORPHAN_METADATA_AFTER_FIX: Final[list[tuple[int, int]]] = []


@pytest.mark.parametrize("case", V_CASES)
def test_verifier_shape_matrix(
    case: str, control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    """V: rc 0, no unreachable object, no unreferenced /Metadata stream, 0 sentinel hits."""
    out = work / f"v-{case}.pdf"
    fixture = "A"
    if case in V_ENCRYPTED:
        fixture = f"A-{case}"
        _, pw_args = R.passwords_for(fixture, work / "fx")
        clear_all(env, work, fx[fixture], out, "--allow-decrypted-output", *pw_args)
    elif case.startswith("readme-chain-"):
        verb = case.removeprefix("readme-chain-")
        mid = work / f"v-{case}-mid.pdf"
        args = ["--pages", "1", "--angle", "90"] if verb == "rotate" else ["--pages", "1"]
        rc, payload = cli(env, work, verb, str(fx["A"]), *args, "-O", str(mid))
        assert rc == 0, payload
        clear_all(env, work, mid, out)
    elif case == "A-in-place":
        out = in_place_copy(fx, env, work, "v")
    else:
        fixture = case
        clear_all(env, work, fx[case], out)
    result = R.scan(out, list(R.SENTINELS[fixture].values()))
    assert result.unreachable == (), f"UNREACHABLE in {case}: {result.unreachable}"
    leftovers = R.metadata_streams_outside_pages(out)
    assert leftovers == [], (
        f"/Type /Metadata stream(s) outside page dictionaries in {case}: {leftovers}"
    )
    if case == "AES256-NOMETA-UO":
        assert leftovers == NOMETA_ORPHAN_METADATA_AFTER_FIX, (
            f"base left {NOMETA_ORPHAN_METADATA_AT_BASE} orphan /Metadata stream(s)"
        )
    for location, sentinel in _removed(fixture).items():
        assert sentinel not in result.raw_hits, f"RAW {sentinel!r} ({location}) in {case}"
        assert sentinel not in result.decoded_hits, f"DECODED {sentinel!r} ({location}) in {case}"


# --------------------------------------------------------------------------- #
# P -- the page-verb /Info census (R-04, ledger 23659a085e)
# --------------------------------------------------------------------------- #

#: ``verb -> fixtures`` -- per-verb DATA as a mapping (never a hand-typed verb list;
#: `test_derived_dimensions` governs the four PDF-08 verbs), tied to the live
#: registry by `test_the_p_arm_declares_every_pdf08_verb`. ``merge``'s "fixture" is
#: its operand order; its donor (the first operand) is the carry control.
P_FIXTURES: Final[dict[str, tuple[str, ...]]] = {
    "delete": ("D",),  # A has one page: nothing to delete
    "extract": ("A", "D"),
    "split": ("A", "D"),
    "rotate": ("A", "D"),
    "reorder": ("A", "D"),
    "merge": ("AD", "DA"),
    "stamp": ("A", "D"),
    "watermark": ("A", "D"),
}
P_CASES: Final[tuple[tuple[str, str], ...]] = tuple(
    (verb, fixture) for verb, fixtures in P_FIXTURES.items() for fixture in fixtures
)


def test_the_p_arm_declares_every_pdf08_verb() -> None:
    """The totality tie: a page verb joining the registry without a P cell fails by name."""
    for verb in PDF_08_VERBS:
        expectation(dict(P_FIXTURES), verb, label="PDF-121 arm P")


def page_verb_outputs(
    verb: str, fixture: str, fx: dict[str, Path], env: dict[str, str], work: Path
) -> tuple[list[Path], Path]:
    """Run one page verb; return ``(outputs, the input whose /Info is carried)``."""
    tag = f"p-{verb}-{fixture}"
    out = work / f"{tag}.pdf"
    donor = fx[fixture[0]]
    if verb == "delete":
        cli_args = ["delete", str(fx[fixture]), "--pages", "2", "-O", str(out)]
    elif verb == "extract":
        cli_args = ["extract", str(fx[fixture]), "--pages", "1", "-O", str(out)]
    elif verb == "rotate":
        cli_args = ["rotate", str(fx[fixture]), "--pages", "1", "--angle", "90", "-O", str(out)]
    elif verb == "reorder":
        order = "1" if fixture == "A" else "2,1"
        cli_args = ["reorder", str(fx[fixture]), "--pages", order, "-O", str(out)]
    elif verb == "merge":
        cli_args = ["merge", str(fx[fixture[0]]), str(fx[fixture[1]]), "-O", str(out)]
    elif verb == "stamp":
        cli_args = ["stamp", str(fx[fixture]), "--from", str(fx["N"]), "-O", str(out)]
    elif verb == "watermark":
        cli_args = ["watermark", str(fx[fixture]), "--text", "WM", "-O", str(out)]
    else:
        assert verb == "split", verb
        directory = work / tag
        cli_args = [
            "split", str(fx[fixture]), "--each-page", "--out-dir", str(directory),
            "--name", "p{page:03}.pdf",
        ]  # fmt: skip
        out = directory
    rc, payload = cli(env, work, cli_args[0], *cli_args[1:])
    assert rc == 0, f"{verb} {fixture}: rc {rc}: {payload}"
    outputs = sorted(out.glob("*.pdf")) if out.is_dir() else [out]
    assert outputs, f"{verb} {fixture} wrote nothing"
    return outputs, donor


def docinfo(path: Path) -> dict[str, str]:
    with pikepdf.open(path) as pdf:
        return {str(k): v.unparse().decode("latin-1") for k, v in pdf.docinfo.items()}


@pytest.mark.parametrize(("verb", "fixture"), P_CASES, ids=[f"{v}-{f}" for v, f in P_CASES])
def test_page_verbs_write_no_unreferenced_info(
    verb: str, fixture: str, control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    """P: one carried /Info, reachable and equal to the donor's; no duplicate behind it."""
    outputs, donor = page_verb_outputs(verb, fixture, fx, env, work)
    expected = docinfo(donor)
    assert expected, "the carry control needs a donor /Info"
    for output in outputs:
        count = R.unreferenced_info_count(output)
        assert count == 0, (
            f"{verb} {fixture}: {output.name} holds {count} unreferenced /Info dict(s)"
        )
        unreachable = R.scan(output, []).unreachable
        assert unreachable == (), f"{verb} {fixture}: {output.name} unreachable {unreachable}"
        assert docinfo(output) == expected, (
            f"{verb} {fixture}: the carried /Info moved ({output.name})"
        )


OTHER_WRITERS: Final[tuple[str, ...]] = ("compress", "repair", "linearize", "meta-set-author")


@pytest.mark.parametrize("verb", OTHER_WRITERS)
def test_other_writers_stay_at_zero(
    verb: str, control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    """P: the qpdf-backed verbs and `meta set --author` never had a duplicate /Info."""
    out = work / f"o-{verb}.pdf"
    if verb == "meta-set-author":
        rc, payload = cli(env, work, "meta set", str(fx["A"]), "--author", "X", "-O", str(out))
    else:
        rc, payload = cli(env, work, verb, str(fx["A"]), "-O", str(out))
    assert rc == 0, payload
    assert R.unreferenced_info_count(out) == 0, f"{verb}: unreferenced /Info"
    assert R.scan(out, []).unreachable == (), f"{verb}: unreachable objects"


# PDF-121 E2: `ocr` was unmeasured on the spec host (no tesseract). It writes through the
# same PypdfStructureWriter seam as the eight page verbs, so its arm runs only where the
# engine exists. `requires` (not a bare skipif) is what the engine-gating census demands.
@pytest.mark.requires("tesseract")
def test_ocr_writes_no_unreferenced_info(
    control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    out = work / "p-ocr-A.pdf"
    rc, payload = cli(env, work, "ocr", str(fx["A"]), "--skip-text-pages", "-O", str(out))
    assert rc == 0, payload
    assert R.unreferenced_info_count(out) == 0
    assert R.scan(out, []).unreachable == ()


# --------------------------------------------------------------------------- #
# R -- no prior revision survives
# --------------------------------------------------------------------------- #

R_FIXTURES: Final[dict[str, tuple[str, ...]]] = {
    "clear-all": ("B", "B2"),
    "rotate": ("B", "B2"),
}
R_CASES: Final[tuple[tuple[str, str], ...]] = tuple(
    (verb, fixture) for verb, fixtures in R_FIXTURES.items() for fixture in fixtures
)


@pytest.mark.parametrize(("verb", "fixture"), R_CASES, ids=[f"{v}-{f}" for v, f in R_CASES])
def test_no_prior_revision_survives(
    verb: str, fixture: str, control: None, fx: dict[str, Path], env: dict[str, str], work: Path
) -> None:
    """R: one revision, no trailer /Prev, and the old-revision sentinels are in no channel."""
    out = work / f"r-{verb}-{fixture}.pdf"
    if verb == "clear-all":
        clear_all(env, work, fx[fixture], out)
    else:
        rc, payload = cli(
            env, work, "rotate", str(fx[fixture]), "--pages", "1", "--angle", "90", "-O", str(out)
        )
        assert rc == 0, payload
    old = {loc: s for loc, s in R.SENTINELS[fixture].items() if loc.startswith("old_")}
    assert old, "the fixture must plant an old-revision sentinel"
    result = R.scan(out, list(old.values()))
    assert result.revisions == (1, 1, False), (
        f"REVISIONS {result.revisions}: a prior revision survived"
    )
    for location, sentinel in old.items():
        assert sentinel not in result.raw_hits, f"RAW {sentinel!r} ({location}) survived"
        assert sentinel not in result.decoded_hits, f"DECODED {sentinel!r} ({location}) survived"


# --------------------------------------------------------------------------- #
# AC9 -- the census of pypdf write sites (the X-732 class)
# --------------------------------------------------------------------------- #

#: Provenance: `e2a980e`, PDF-121 E7. The `PdfWriter(` construction sites in src/.
PDFWRITER_SITES: Final[frozenset[str]] = frozenset(
    {
        "pypdf_structure.PypdfStructureAdapter.write_metadata",
        "pypdf_structure.PypdfStructureWriter.__init__",
        "pypdf_structure.PypdfStructureAdapter.downsample_images",
        "tesseract_ocr._normalize_layer_geometry",
    }
)
SWEEP_SITES: Final[frozenset[str]] = frozenset(
    {
        "pypdf_structure.PypdfStructureAdapter.write_metadata",
        "pypdf_structure.PypdfStructureWriter.write",
    }
)


def _call_sites(name: str) -> list[str]:
    """Enclosing ``module.Class.func`` of every call to ``name`` in ``src/pdf_tooling``."""
    found: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self, module: str) -> None:
            self.module = module
            self.scope: list[str] = []

        def _enter(self, node: ast.AST, label: str) -> None:
            self.scope.append(label)
            self.generic_visit(node)
            self.scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._enter(node, node.name)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter(node, node.name)

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                found.append(".".join([self.module, *self.scope]))
            self.generic_visit(node)

    for path in sorted(SRC_ROOT.rglob("*.py")):
        Visitor(path.stem).visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


def test_every_pypdf_writer_site_is_censused() -> None:
    """AC9: a new `PdfWriter(` site reds here until censused; the sweep has exactly two calls."""
    writers = _call_sites("PdfWriter")
    assert set(writers) == PDFWRITER_SITES and len(writers) == len(PDFWRITER_SITES), (
        f"uncensused PdfWriter( construction site(s): {sorted(set(writers) ^ PDFWRITER_SITES)} "
        f"(all: {sorted(writers)})"
    )
    sweeps = _call_sites("_drop_unreachable")
    assert sorted(sweeps) == sorted(SWEEP_SITES), (
        f"_drop_unreachable( must be called in exactly {sorted(SWEEP_SITES)}, "
        f"found {sorted(sweeps)}"
    )
