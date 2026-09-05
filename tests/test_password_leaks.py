"""PDF-13's real deliverable — the adversarial no-leak proofs.

Top level, mirroring `tests/test_license_policy.py` and
`tests/test_import_boundaries.py`, because these are properties of the whole
product rather than of one module.

Every other verb in this cycle fails by producing a wrong PDF. This one fails
by producing a **security incident**, and disclosure is not undoable by a
later fix — so the criteria here are negative, adversarial, and each one
carries a positive control proving it is capable of going red. This cycle has
already found four controls that could not fail (X-68, X-92, X-102, X-108);
a green control is worthless until it has been seen red.

Contents
--------
* **AC1**  a literal password value is refused, and the refusal does not echo it.
* **AC18** ruling OR-4 / X-114 — `--password`, `--user-password` and
  `--owner-password` do not exist, on any verb, in any shape.
* **AC3**  ``reveal()`` is confined to exactly one file, by AST walk.
* **AC4**  the password is absent from captured ``-vv`` stderr.
* **AC5**  the password is absent from the ``-o json`` payload.
* **AC6**  the password is absent from a deliberately forced traceback,
  including the locals-capturing form.
* **AC7**  the password is never in ``/proc/<pid>/cmdline`` — read while the
  process is provably blocked, so there is no race.
* **AC12** the advisory truth is documented, and over-claiming language is
  absent, both mechanized.
* **AC20(e)** every grep above re-run with ``--dry-run``, because *"we never
  read it"* is a claim about code and these are claims about output.

**No production fault-injection hook exists for AC6.** A debug backdoor in
the crypto path would be worse than the bug it helps find; the injection is a
test-time monkeypatch and nothing else.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    INVOCATIONS,
    console_script,
    derive_password_file_pairs,
    output_shape_states,
    run_cli,
    run_cli_with_pty,
    tty_modes,
)

REPO_ROOT: Final[Path] = TESTS_DIR.parent
SRC: Final[Path] = REPO_ROOT / "src" / "pdf_toolkit"

#: Fixed so a grep can be written once and re-run by anyone.
PW_SENTINEL: Final[str] = "Sentinel-PW-7f3a91c4e85b4d02"
#: The Unicode variant exists because a JSON encoder may emit ``\\uXXXX``
#: escapes, so a raw-byte grep for the ASCII sentinel alone would miss an
#: escape-encoded leak.
PW_SENTINEL_UNICODE: Final[str] = "Señal-PW-Ünïcøde-7f3a91c4"

SENTINELS: Final[dict[str, str]] = {
    "ascii": PW_SENTINEL,
    "unicode": PW_SENTINEL_UNICODE,
}

VERBS: Final[tuple[str, ...]] = ("encrypt", "decrypt", "permissions")

#: The files permitted to call ``Secret.reveal()`` (`PLAN.md` §5.7).
#:
#: PDF-37 widens this from one file to four, each for a DIFFERENT, necessary
#: reason -- not a general loosening:
#:
#: * ``adapters/pypdf_structure.py`` -- the primary structure adapter gains
#:   the password-bearing read seam (``open_document``/``read_document_info``
#:   /``read_metadata``/``write_metadata``); this is the one other place
#:   pypdf demands a plain ``str``, exactly like pikepdf already does.
#: * ``ops/raster.py`` -- `rasterize`'s per-page render crosses a REAL
#:   ``ProcessPoolExecutor`` boundary (module docstring), and a ``Secret``
#:   refuses to pickle by design; the plaintext is revealed exactly once per
#:   source, in the main process, immediately before building the picklable
#:   work-item tuple, and travels no further than that.
#: * ``ops/ocr.py`` -- `ocr`'s own per-page render calls the SAME
#:   ``RasterEngine.render_page`` (shared with `rasterize`, so its
#:   ``password`` parameter is uniformly a plain ``str``), sequentially, in
#:   this process -- never a worker.
#: * ``ops/textract.py`` -- `text`/`tables` extraction runs entirely
#:   in-process, sequentially (module docstring: no worker pool at all), but
#:   ``TextEngine``'s own ``extract_text``/``extract_lines``/
#:   ``extract_tables`` (``pdfium_text``/``pdfplumber_text``) take a plain
#:   ``str`` for the SAME reason ``RasterEngine.render_page`` does: both
#:   operate on a bare path, never an already-open document.
#:
#: Each site is revealed at most once per source and the value is never
#: bound to a name that outlives the call/tuple it was built for.
REVEAL_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "adapters/pikepdf_structure.py",
        "adapters/pypdf_structure.py",
        "ops/raster.py",
        "ops/ocr.py",
        "ops/textract.py",
    }
)


# --------------------------------------------------------------------------- #
# Shared apparatus
# --------------------------------------------------------------------------- #


def _write_password(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


class Bed:
    """One module-scoped fixture bed: a plain PDF, two password files, and two
    documents encrypted with each sentinel as BOTH the owner and the user
    password, so `decrypt` and `permissions` each need the credential too."""

    def __init__(self, root: Path, plain: Path) -> None:
        self.root = root
        self.plain = plain
        self.password_file: dict[str, Path] = {}
        self.encrypted: dict[str, Path] = {}

    def out(self, name: str) -> Path:
        return self.root / name


@pytest.fixture(scope="module")
def bed(tmp_path_factory: pytest.TempPathFactory, corpus: Any) -> Bed:
    from pdf_toolkit.ports.structure import require_encryption
    from pdf_toolkit.secret import Secret

    root = tmp_path_factory.mktemp("password-leaks")
    plain = root / "plain.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    made = Bed(root, plain)
    engine = require_encryption()
    for label, value in SENTINELS.items():
        made.password_file[label] = _write_password(root / f"pw-{label}.txt", value)
        target = root / f"encrypted-{label}.pdf"
        target.write_bytes(
            engine.encrypt(
                plain.read_bytes(),
                owner=Secret(value, source="test"),
                user=Secret(value, source="test"),
                allow=frozenset({"print"}),
                legacy=False,
            )
        )
        made.encrypted[label] = target
    return made


def _argv(verb: str, bed: Bed, label: str, tag: str) -> list[str]:
    """A complete, succeeding invocation of *verb* carrying the *label* sentinel."""
    password = str(bed.password_file[label])
    if verb == "encrypt":
        return [
            str(bed.plain),
            "--owner-password-file",
            password,
            "--user-password-file",
            password,
            "--allow",
            "print",
            "-O",
            str(bed.out(f"{tag}-{label}.pdf")),
        ]
    if verb == "decrypt":
        return [
            str(bed.encrypted[label]),
            "--password-file",
            password,
            "-O",
            str(bed.out(f"{tag}-{label}-dec.pdf")),
        ]
    return [str(bed.encrypted[label]), "--password-file", password]


def _clean_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PDF_TOOLKIT_PASSWORD", None)
    env.pop("PDF_TOOLKIT_OWNER_PASSWORD", None)
    env.update(extra)
    return env


def _assert_no_sentinel(haystack: str, *, where: str) -> None:
    for label, value in SENTINELS.items():
        assert value not in haystack, f"{where} leaked the {label} sentinel"


# --------------------------------------------------------------------------- #
# AC1 / AC18 -- a password-shaped flag does not exist, and refusing one never
# echoes what it was given.
# --------------------------------------------------------------------------- #

_REFUSED_SPELLINGS: Final[tuple[str, ...]] = (
    "--password",
    "--user-password",
    "--owner-password",
)

#: `info` is in the matrix deliberately: the global block is SHARED, so the
#: removal has to hold on a verb PDF-13 never touched, or it was a per-verb
#: patch wearing a shared-layer costume.
_REFUSAL_VERBS: Final[tuple[str, ...]] = ("encrypt", "decrypt", "permissions", "info")


def _refusal_shapes(bed: Bed) -> dict[str, list[str]]:
    """The three shapes AC18 requires, and the reason there are three.

    ``literal`` is the leak the ruling exists to prevent. ``valid-path``
    proves the flag is GONE rather than merely validating differently — the
    old alias accepted a real path and exited 1 on a malformed file. ``bare``
    is the shape Click would otherwise answer with its own un-enveloped
    "requires an argument".
    """
    return {
        "literal": [PW_SENTINEL],
        "valid-path": [str(bed.password_file["ascii"])],
        "bare": [],
    }


@pytest.mark.e2e
@pytest.mark.parametrize("verb", _REFUSAL_VERBS)
@pytest.mark.parametrize("spelling", _REFUSED_SPELLINGS)
@pytest.mark.parametrize("shape", ["literal", "valid-path", "bare"])
def test_ac1_ac18_a_password_shaped_flag_is_refused_and_never_echoed(
    verb: str, spelling: str, shape: str, bed: Bed
) -> None:
    tail = _refusal_shapes(bed)[shape]
    result = run_cli(verb, str(bed.plain), spelling, *tail, env=_clean_env())
    combined = result.stdout + result.stderr

    assert result.returncode == 2, f"{verb} {spelling} ({shape}) -> {result.returncode}: {combined}"
    # (e) -- neither the literal nor the path is echoed. At the moment of
    # refusal we cannot know which it was, so neither may be printed.
    _assert_no_sentinel(combined, where=f"{verb} {spelling} ({shape})")
    for value in tail:
        assert value not in combined, f"{verb} {spelling} ({shape}) echoed its value"
    # (d) -- the message names all three supported paths.
    assert "--password-file" in combined
    assert "PDF_TOOLKIT_PASSWORD" in combined
    assert "prompt" in combined.lower()
    # The envelope, not Click's generic path (`4772bfd8fc`).
    assert '"kind": "usage"' in result.stdout or "error:" in result.stderr


@pytest.mark.e2e
@pytest.mark.parametrize("verb", _REFUSAL_VERBS)
def test_ac18_the_canonical_flag_still_works_on_every_verb(verb: str, bed: Bed) -> None:
    """The regression control: the removal must not take `--password-file`
    with it. A run that reaches exit 0/4/6 has PARSED the flag; only exit 2
    would mean it was rejected as unknown.

    PDF-37 (X-417/X-435, a RULED contract change): `encrypt` is the one
    exception, carved out explicitly rather than silently exempted.
    `encrypt` never consumed the GLOBAL `--password-file` slot (it declares
    its own `--owner-/--user-password-file` instead) and D2/D4's central
    consumption check now REFUSES it there -- exit 2, but the "does not
    accept" shape (`common.py`'s `_check_password_file_consumption`), never
    Click's own "no such option" -- which is exactly what distinguishes
    "rejected as unknown" (a real regression this test still catches) from
    "recognized and refused" (this spec's own, deliberate change). `decrypt`/
    `permissions`/`info` are UNCHANGED: `--password-file` still resolves
    to a real plan for all three, so exit 2 there would still mean the flag
    itself broke.
    """
    source = bed.plain if verb in {"encrypt", "info"} else bed.encrypted["ascii"]
    args = [verb, str(source), "--password-file", str(bed.password_file["ascii"])]
    if verb in {"encrypt", "decrypt"}:
        args += ["-O", str(bed.out(f"regression-{verb}.pdf"))]
    if verb == "encrypt":
        args += ["--owner-password-file", str(bed.password_file["ascii"])]
    result = run_cli(*args, env=_clean_env())
    if verb == "encrypt":
        assert result.returncode == 2, (
            f"encrypt should REFUSE --password-file (X-417/X-435): got {result.returncode}: "
            f"{result.stderr}"
        )
        assert "does not accept" in (result.stdout + result.stderr), (
            "encrypt's refusal should name what it does not accept, not Click's "
            f"generic unknown-option shape: {result.stdout}{result.stderr}"
        )
        return
    assert result.returncode != 2, f"{verb} rejected --password-file: {result.stderr}"


@pytest.mark.e2e
@pytest.mark.parametrize("verb", [*VERBS, "info"])
def test_ac18_rendered_help_names_no_password_flag_other_than_password_file(verb: str) -> None:
    """An OBSERVABLE-BEHAVIOUR grep, over rendered ``--help`` and never over
    source: B-052's lesson is that grepping *source* for an absent string
    asserts intent and can fail a correct implementation."""
    result = run_cli(verb, "--help")
    assert result.returncode == 0
    # De-wrap first. Click hard-wraps help text, and it wraps INSIDE a hyphenated
    # flag name: `--password-\n  file`. Grepping the raw output for
    # `--password(?!-file)` therefore fires on a correct implementation --
    # measured, not hypothetical, and exactly X-121's class of harness defect
    # (a check that fails the code it was written to pass).
    normalized = re.sub(r"-[ \t]*\n[ \t]*", "-", result.stdout)
    offenders = re.findall(r"--password(?!-file)[a-z-]*", normalized)
    assert offenders == [], f"`{verb} --help` still names {offenders}"
    assert "--password-file" in normalized


def test_ac18_the_help_dewrapper_can_still_catch_a_real_offender() -> None:
    """The positive control for the de-wrapping above: normalization must not
    have blunted the grep into one that cannot fire."""
    normalized = re.sub(r"-[ \t]*\n[ \t]*", "-", "  --owner-\n  password TEXT\n")
    assert re.findall(r"--password(?!-file)[a-z-]*", normalized) == []
    assert re.findall(r"--owner-password(?!-file)", normalized) == ["--owner-password"]
    plain = "  --password TEXT   the old alias\n"
    assert re.findall(r"--password(?!-file)[a-z-]*", plain) == ["--password"]


def test_ac18_the_refused_spellings_are_not_in_the_global_block() -> None:
    """Structural half: ``GLOBAL_OPTIONS`` is what the §4.2 verb-block-vs-root
    diff test iterates, and it must not grow. ``OUTPUT_FLAGS`` must not either
    (PDF-07's Scope > Out)."""
    from pdf_toolkit.cli.common import GLOBAL_OPTIONS, OUTPUT_FLAGS, REFUSED_PASSWORD_FLAGS

    assert set(REFUSED_PASSWORD_FLAGS) & set(GLOBAL_OPTIONS) == set()
    assert "--password-file" in GLOBAL_OPTIONS
    assert OUTPUT_FLAGS == ("--output", "--out-dir", "--name", "--in-place")


# --------------------------------------------------------------------------- #
# AC3 -- `reveal()` is confined to one file, by AST walk
# --------------------------------------------------------------------------- #


def _reveal_call_sites(root: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reveal"
            ):
                found.add(path.relative_to(root).as_posix())
    return found


def test_ac3_reveal_is_called_in_exactly_one_file() -> None:
    assert _reveal_call_sites(SRC) == REVEAL_ALLOWLIST


def test_ac3_the_reveal_walk_is_not_vacuous(tmp_path: Path) -> None:
    """Non-vacuity plus a positive control: the allowlisted file really does
    call it (otherwise the check proves nothing), and a planted call in a
    second file is detected."""
    assert REVEAL_ALLOWLIST <= _reveal_call_sites(SRC)
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "leak.py").write_text("def go(s):\n    return s.reveal()\n")
    assert _reveal_call_sites(planted) == {"leak.py"}


# --------------------------------------------------------------------------- #
# AC4 / AC5 -- the captured-stream proofs.
#
# ONE subprocess per (verb, sentinel), reused by both criteria: the run is
# `-vv -o json`, so stderr carries the debug records AC4 greps and stdout
# carries the payload AC5 greps. Six runs, cached module-wide (B-061 -- a
# subprocess is bought only where a real process is the only observer).
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def captures(bed: Bed) -> dict[tuple[str, str], subprocess.CompletedProcess[str]]:
    results: dict[tuple[str, str], subprocess.CompletedProcess[str]] = {}
    for verb in VERBS:
        for label in SENTINELS:
            results[(verb, label)] = run_cli(
                verb,
                *_argv(verb, bed, label, "capture"),
                "-vv",
                "-o",
                "json",
                env=_clean_env(),
            )
    return results


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("label", sorted(SENTINELS))
def test_ac4_the_password_is_absent_from_vv_stderr(
    verb: str, label: str, captures: dict[tuple[str, str], subprocess.CompletedProcess[str]]
) -> None:
    result = captures[(verb, label)]
    assert result.returncode == 0, f"{verb}/{label} did not run: {result.stderr}"

    # The positive control FIRST: without it the grep below could pass simply
    # because logging was silently off.
    assert result.stderr.strip(), f"{verb} -vv produced no stderr at all"
    assert "password resolved from" in result.stderr, (
        f"{verb} -vv carried no password-resolution debug record; the grep below "
        "would then be vacuous"
    )

    _assert_no_sentinel(result.stderr, where=f"{verb} -vv stderr")
    # The LENGTH is a smaller leak, and still a leak.
    for value in SENTINELS.values():
        assert not re.search(rf"\b{len(value)}\b", result.stderr), (
            f"{verb} -vv stderr carries the password's length"
        )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("label", sorted(SENTINELS))
def test_ac5_the_password_is_absent_from_the_json_payload(
    verb: str, label: str, captures: dict[tuple[str, str], subprocess.CompletedProcess[str]]
) -> None:
    result = captures[(verb, label)]
    assert result.returncode == 0, result.stderr

    # Raw bytes, re-serialized text, and every string leaf of a recursive walk.
    # The Unicode sentinel is what makes the second and third non-redundant: a
    # `\uXXXX`-escaped leak is invisible to a raw-byte grep for the decoded form.
    payload = json.loads(result.stdout)
    _assert_no_sentinel(result.stdout, where=f"{verb} -o json raw stdout")
    _assert_no_sentinel(json.dumps(payload, ensure_ascii=False), where=f"{verb} payload re-dumped")
    _assert_no_sentinel(json.dumps(payload, ensure_ascii=True), where=f"{verb} payload escaped")
    for leaf in _string_leaves(payload):
        _assert_no_sentinel(leaf, where=f"{verb} payload leaf")

    # The positive control: the payload DID render, and it carries the source
    # label -- so the greps are not passing because the run failed early.
    detail = payload["items"][0]["detail"]
    key = "owner_password_source" if verb == "encrypt" else "password_source"
    assert detail[key].startswith("file:"), detail
    assert detail[key].endswith(f"pw-{label}.txt"), detail


def _string_leaves(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [
            leaf
            for key, value in node.items()
            for leaf in [*_string_leaves(key), *_string_leaves(value)]
        ]
    if isinstance(node, list):
        return [leaf for item in node for leaf in _string_leaves(item)]
    return []


# --------------------------------------------------------------------------- #
# AC20(e) -- the same greps with `--dry-run`, over BOTH channels at once.
#
# "We never read it" is a claim about code; these are claims about output. The
# environment variable is exported AND the flag is given in the same run, so a
# leak from either channel is caught by one process rather than two.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("label", sorted(SENTINELS))
def test_ac20e_the_dry_run_leaks_nothing_through_either_channel(
    verb: str, label: str, bed: Bed
) -> None:
    env = _clean_env(
        PDF_TOOLKIT_PASSWORD=SENTINELS[label],
        PDF_TOOLKIT_OWNER_PASSWORD=SENTINELS[label],
    )
    result = run_cli(
        verb, *_argv(verb, bed, label, "dry"), "--dry-run", "-vv", "-o", "json", env=env
    )
    assert result.returncode == 0, f"{verb} --dry-run: {result.stdout}{result.stderr}"
    _assert_no_sentinel(result.stdout, where=f"{verb} --dry-run stdout")
    _assert_no_sentinel(result.stderr, where=f"{verb} --dry-run stderr")
    for leaf in _string_leaves(json.loads(result.stdout)):
        _assert_no_sentinel(leaf, where=f"{verb} --dry-run payload leaf")


# --------------------------------------------------------------------------- #
# AC6 -- a deliberately forced traceback, including the locals-capturing form
# --------------------------------------------------------------------------- #


def _formatted(exc: BaseException) -> tuple[str, str]:
    plain = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    with_locals = "".join(
        traceback.TracebackException.from_exception(exc, capture_locals=True).format()
    )
    return plain, with_locals


def test_ac6_a_forced_traceback_carries_no_password(
    tmp_path: Path, corpus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Injected at a point where the password is a live local AND a call
    argument, which is the only place a locals-capturing formatter could
    surface it. No production hook exists for this; it is a monkeypatch.
    """
    from typer.testing import CliRunner

    from pdf_toolkit.adapters.pikepdf_structure import PikepdfStructureAdapter
    from pdf_toolkit.cli.main import app

    def boom(self: Any, data: bytes, *, owner: Any, user: Any, allow: Any, legacy: bool) -> bytes:
        raise RuntimeError("injected")

    monkeypatch.setattr(PikepdfStructureAdapter, "encrypt", boom)

    plain = tmp_path / "plain.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    password = _write_password(tmp_path / "pw.txt", PW_SENTINEL)

    result = CliRunner().invoke(
        app,
        [
            "encrypt",
            str(plain),
            "--owner-password-file",
            str(password),
            "-O",
            str(tmp_path / "out.pdf"),
        ],
    )
    assert result.exception is not None, "the injection did not fire"
    plain_text, with_locals = _formatted(result.exception)

    assert "injected" in plain_text, "the wrong exception was captured"
    assert PW_SENTINEL not in plain_text
    assert PW_SENTINEL not in with_locals
    assert "<redacted>" in with_locals, (
        "the locals-capturing formatter did not even reach the injected frame's "
        "locals; this assertion is what keeps the two above from being vacuous"
    )
    assert PW_SENTINEL not in result.output


def _locals_form(password: object) -> str:
    """One raise with *password* as a live local, formatted with locals captured.

    A HELPER rather than an inline try/except, and the reason is a real trap
    this test hit: ``capture_locals`` walks every frame in the traceback,
    including the caller's. With both halves inline, the second call's
    traceback captured the FIRST call's formatted text -- which contains the
    sentinel -- as a local of the test function, and the negative assertion
    failed against its own scratch variable rather than against anything the
    product did. Isolating the raise keeps the compared frames to
    ``_locals_form`` and ``inner``.
    """

    def inner(secret_argument: object) -> None:
        raise RuntimeError("injected")

    try:
        inner(password)
    except RuntimeError as error:
        return _formatted(error)[1]
    raise AssertionError("the injection did not fire")  # pragma: no cover


def test_ac6_a_raw_str_password_WOULD_surface_in_the_locals_form() -> None:
    """The positive control, and the reason AC6 is not vacuous: the
    locals-capturing formatter really does ``repr()`` frame locals in this
    interpreter. A plain ``str`` in the same position leaks; a ``Secret``
    does not.
    """
    from pdf_toolkit.secret import Secret

    leaked = _locals_form(PW_SENTINEL)
    assert PW_SENTINEL in leaked, (
        "capture_locals did not surface a raw str; AC6's negative assertions "
        "would then prove nothing"
    )

    redacted = _locals_form(Secret(PW_SENTINEL, source="test"))
    assert PW_SENTINEL not in redacted
    assert "<redacted>" in redacted


# --------------------------------------------------------------------------- #
# AC7 -- /proc/<pid>/cmdline, read while the process is PROVABLY blocked
# --------------------------------------------------------------------------- #

_PROC_SKIP = pytest.mark.skipif(
    not Path("/proc").is_dir() or sys.platform != "linux",
    reason="/proc is Linux-only; this arm skips visibly rather than passing silently "
    "(PLAN.md §10 posture)",
)


@pytest.mark.e2e
@_PROC_SKIP
def test_ac7_the_password_is_never_in_argv_and_the_env_channel_is_documented_not_hidden(
    bed: Bed,
) -> None:
    """Deterministic, without a race.

    The process is launched with ``--owner-password-file -`` and **nothing is
    written to its stdin**, so it blocks inside the read. While it is blocked
    -- proven by ``poll() is None`` at the moment of the read -- ``/proc/<pid>``
    is inspected. Only then is the password written.

    ``/proc/<pid>/environ`` is asserted to CONTAIN the value on the
    environment path. That is not a defect being hidden: the environment
    channel is readable by any same-uid process, and this product documents it
    as weaker than a file rather than implying it is safe.
    """
    target = bed.out("ac7-out.pdf")
    argv = [
        *console_script(),
        "encrypt",
        str(bed.plain),
        "--owner-password-file",
        "-",
        "-O",
        str(target),
    ]
    env = _clean_env(PDF_TOOLKIT_PASSWORD=PW_SENTINEL)
    process = subprocess.Popen(  # noqa: S603 - argv is built here, never shell
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        proc_dir = Path("/proc") / str(process.pid)
        deadline = time.monotonic() + 60.0
        cmdline = b""
        environ = b""
        # POLL UNTIL POPULATED, not until merely readable. The kernel exposes
        # /proc/<pid> the moment the child is forked, BEFORE `execve` has
        # installed the new argv and environment, so a read that succeeds can
        # still return b"" -- and an empty buffer trivially "does not contain
        # the password", which is a green assertion proving nothing. CI caught
        # this on `test (3.11, ubuntu-latest)`: it is a genuine race and the
        # fix is to wait for the argv we passed to be visible.
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"the process exited before blocking on stdin: {stdout}{stderr}")
            try:
                cmdline = (proc_dir / "cmdline").read_bytes()
                environ = (proc_dir / "environ").read_bytes()
            except OSError:  # pragma: no cover - the process is alive; retry
                cmdline = b""
                environ = b""
            if b"--owner-password-file" in cmdline and environ:
                break
            time.sleep(0.05)
        else:  # pragma: no cover - only on a pathologically slow host
            pytest.fail(
                "/proc never showed the child's own argv within 60s; the read below "
                "would have been against an empty buffer"
            )
        # Still blocked at the moment the buffers above were read -- which is
        # what makes this a measurement of a LIVE process rather than of a
        # corpse's leftovers.
        assert process.poll() is None

        assert cmdline, "read an empty /proc/<pid>/cmdline"
        assert PW_SENTINEL.encode() not in cmdline, "the password reached argv"
        # Non-vacuity: the argv we DID pass is visible, so the grep above is
        # looking at a populated cmdline rather than an empty buffer.
        assert b"encrypt" in cmdline
        assert b"--owner-password-file" in cmdline
        # The env channel, documented rather than hidden.
        assert PW_SENTINEL.encode() in environ, (
            "the environment channel is expected to be readable here; this "
            "assertion is what keeps README's caveat honest"
        )

        stdout, stderr = process.communicate(input=PW_SENTINEL + "\n", timeout=120)
    finally:
        if process.poll() is None:  # pragma: no cover - only on a failed assertion
            process.kill()
            process.communicate()

    assert process.returncode == 0, f"{stdout}{stderr}"
    assert target.is_file()
    _assert_no_sentinel(stdout + stderr, where="the stdin-fed run's own output")

    import pikepdf

    with pikepdf.Pdf.open(target, password=PW_SENTINEL) as reopened:
        assert reopened.is_encrypted is True


# --------------------------------------------------------------------------- #
# AC12 -- the advisory truth, mechanized in BOTH directions
# --------------------------------------------------------------------------- #

#: The negative half, and the half that matters. Verbatim from the spec.
OVER_CLAIMING = re.compile(r"\bprevents\b|\benforces\b|\bbyte-identical file\b", re.IGNORECASE)


def _crypto_readme_section() -> str:
    text = (REPO_ROOT / "README.md").read_text()
    start = text.index("## Encryption, passwords and permissions")
    end = text.index("\n## ", start + 1)
    return text[start:end]


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["encrypt", "permissions"])
def test_ac12_help_states_the_advisory_truth(verb: str) -> None:
    text = run_cli(verb, "--help").stdout
    assert re.search(r"advisory", text, re.IGNORECASE)
    assert re.search(r"cooperating", text, re.IGNORECASE)


def test_ac12_the_readme_crypto_section_states_the_advisory_truth() -> None:
    section = _crypto_readme_section()
    assert re.search(r"advisory", section, re.IGNORECASE)
    assert re.search(r"cooperating", section, re.IGNORECASE)


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["encrypt", "permissions"])
def test_ac12_help_never_over_claims(verb: str) -> None:
    text = run_cli(verb, "--help").stdout
    assert OVER_CLAIMING.findall(text) == []


def test_ac12_the_readme_crypto_section_never_over_claims() -> None:
    assert OVER_CLAIMING.findall(_crypto_readme_section()) == []


def test_ac12_the_over_claiming_pattern_can_actually_fire() -> None:
    """The positive control for the negative half."""
    assert OVER_CLAIMING.findall("this prevents extraction")
    assert OVER_CLAIMING.findall("the tool ENFORCES the bits")
    assert OVER_CLAIMING.findall("a byte-identical file")
    assert OVER_CLAIMING.findall("the page tree round-trips byte for byte") == []


@pytest.mark.parametrize(
    "needle",
    [
        r"chmod 600",
        r"/proc/<pid>/environ",
        r"secure erasure",
    ],
)
def test_ac12_the_readme_crypto_section_carries_each_required_caveat(needle: str) -> None:
    assert re.search(re.escape(needle), _crypto_readme_section(), re.IGNORECASE), needle


def test_ac12_the_json_payload_carries_advisory_as_data_and_not_as_prose(bed: Bed) -> None:
    """`-o json` carries ``"advisory": true`` -- a machine-readable field --
    and the SENTENCE lives in the human surfaces only."""
    result = run_cli(
        "permissions",
        str(bed.encrypted["ascii"]),
        "--password-file",
        str(bed.password_file["ascii"]),
        "-o",
        "json",
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    detail = json.loads(result.stdout)["items"][0]["detail"]
    assert detail["advisory"] is True
    assert not re.search(r"advisory", json.dumps(detail).replace('"advisory"', ""), re.IGNORECASE)


# --------------------------------------------------------------------------- #
# PDF-22 -- the code-derived secret-leak regression matrix, replacing B-068's
# hand-typed `_B068_FLAG_VERBS` / `_B068_SHAPES` guard (decision.md X-243).
#
# The population comes from `discover_verbs()` + the D2 rendered-`--help`
# probe (`registry.derive_password_file_pairs()`); the shape dimension comes
# from `OutputFormat` PLUS the absent-`-o` state PLUS the three `isatty()`
# axes (`registry.output_shape_states()` / `registry.run_cli_with_pty()`). A
# new verb or a new `OutputFormat` member joins every tier with zero author
# action, under a stated, self-enforcing cardinality cap (AC7).
#
# Four tiers (Design D3):
#   A -- subprocess, every derived `(flag, verb)` pair x ONE fixed shape.
#   B -- subprocess (incl. 3 real ptys), ONE representative pair x every
#        derived shape state.
#   C -- in-process, the FULL derived cross (>= 5,376 states), < 1s.
#   witness -- X-243's `5ff60a280e` scope-1 ruling: a derived, monotone
#        DEFECT baseline over the honoured/silently-ignored partition. It
#        WITNESSES the defect; it does not fix it (AC14: nothing under
#        src/ is touched by this spec).
# --------------------------------------------------------------------------- #

from pdf_toolkit.output import OutputFormat  # noqa: E402

PDF22_SUBPROCESS_CASE_CAP: Final[int] = 96
"""X-157 (decision.md D3) -- a stated, SELF-ENFORCING cardinality cap on
PDF-22's subprocess surface (Tiers A + B + the `5ff60a280e` witness). Tier C
is in-process and is not counted here -- it pays no per-case subprocess-spawn
tax (D3's own argument for why exhaustiveness there is free).

**THE CAP IS A TRIPWIRE, NOT A BUDGET LINE TO BE BUMPED.** If a future change
trips it, the correct response is a BLOCKER to the project-manager carrying
TWO MEASUREMENTS -- the case count and the wall clock -- never a larger
constant. This is the same escalation `decision.md` §2 already prescribes for
the PDF-17 / PDF-29 coverage/speed collision (X-157)."""


# --------------------------------------------------------------------------- #
# Tier A -- subprocess, every derived (flag, verb) pair x one fixed shape.
# --------------------------------------------------------------------------- #

_PASSWORD_FILE_PAIRS: Final[tuple[tuple[str, str], ...]] = derive_password_file_pairs()


def _tier_a_id(pair: tuple[str, str]) -> str:
    flag, verb = pair
    return f"{flag}::{verb}"


@pytest.mark.e2e
@pytest.mark.parametrize("pair", _PASSWORD_FILE_PAIRS, ids=_tier_a_id)
def test_tier_a_every_derived_pair_never_echoes_its_refused_value(
    pair: tuple[str, str], corpus: Any, tmp_path: Path
) -> None:
    """AC1 -- the verb dimension is derived; R1's control (a verb-local
    bypass) is caught only by that verb's own case here, and by nothing
    else in the suite.

    The base argv is `INVOCATIONS[verb].build(...)` (never hand-assembled --
    X-243's own warning: most verbs need required arguments beyond an input
    path), so every verb-specific requirement (`rotate` needing `--angle`,
    `merge` needing `-O`, ...) is satisfied before the refused password-file
    value is appended. Click's own last-scalar-wins semantics
    (`registry.py`'s own documented behaviour) means the appended flag
    always overrides whatever the base invocation supplied for the SAME
    flag, so this is safe even for `decrypt` (whose own registered
    invocation already carries a *valid* `--password-file`).
    """
    flag, verb = pair
    bad_value = f"{PW_SENTINEL}-tier-a-not-a-path"
    base = INVOCATIONS[verb].build(corpus, tmp_path)
    argv = [verb, *base, flag, bad_value]
    result = run_cli(*argv, env=_clean_env())
    combined = result.stdout + result.stderr

    assert result.returncode == 2, f"{_tier_a_id(pair)} -> {result.returncode}: {combined}"
    assert bad_value not in combined, f"{_tier_a_id(pair)} echoed its refused value: {combined}"
    assert PW_SENTINEL not in combined, f"{_tier_a_id(pair)} echoed the sentinel: {combined}"
    # Positive control (AC7's B-068 lesson): a populated, MEANINGFUL envelope,
    # not merely an absent sentinel -- which an early exit or empty stdout
    # could satisfy vacuously.
    assert combined.strip(), f"{_tier_a_id(pair)} produced no output at all"
    assert flag in combined, f"{_tier_a_id(pair)} did not name the flag: {combined}"


@pytest.mark.e2e
def test_tier_a_case_count_equals_a_fresh_re_probe() -> None:
    """AC1's structural half -- no literal on either side. `_PASSWORD_FILE_PAIRS`
    is computed once at import time; this re-runs `derive_password_file_pairs()`
    LIVE (a fresh rendered-`--help` probe over the current tree) and asserts the
    two agree, so a population that silently changed between import and test
    execution -- or a derivation that only worked once -- cannot hide."""
    assert _PASSWORD_FILE_PAIRS == derive_password_file_pairs()


# --------------------------------------------------------------------------- #
# Tier B -- subprocess, one representative pair x every derived shape state,
# including THREE REAL PTYS (Correction 3: no shipped test before this one
# ever made stdout or stderr a terminal).
# --------------------------------------------------------------------------- #

_TIER_B_FLAG: Final[str] = "--password-file"
_TIER_B_VERB: Final[str] = "info"


@dataclass(frozen=True)
class _TierBPoint:
    """One Tier-B subprocess case, and which axis point it contributes to
    the D4 coverage-by-construction claim."""

    id: str
    shape: OutputFormat | None
    pty_stream: str | None  # None == no pty; all three streams are pipes
    kind: str = "refused-value"  # or "wrong-password-prompt" (the stdin axis)


_TIER_B_POINTS: Final[tuple[_TierBPoint, ...]] = (
    _TierBPoint("explicit-table-piped", OutputFormat.TABLE, None),
    _TierBPoint("explicit-json-piped", OutputFormat.JSON, None),
    _TierBPoint("explicit-ndjson-piped", OutputFormat.NDJSON, None),
    _TierBPoint("absent-piped", None, None),
    _TierBPoint("absent-stdout-pty-sixth-shape", None, "stdout"),
    _TierBPoint("explicit-table-stderr-pty", OutputFormat.TABLE, "stderr"),
    _TierBPoint(
        "absent-stdin-pty-wrong-password-prompt", None, "stdin", kind="wrong-password-prompt"
    ),
)

_REFUSED_VALUE_POINTS: Final[tuple[_TierBPoint, ...]] = tuple(
    point for point in _TIER_B_POINTS if point.kind == "refused-value"
)


def test_tier_b_shape_states_are_fully_covered() -> None:
    """AC2 / D4's coverage-by-construction claim, half 1: every derived
    shape state (every `OutputFormat` member + the absent state) appears in
    at least one Tier-B point. Adding a member to `OutputFormat` grows
    `output_shape_states()` and this assertion fails until a point covering
    it exists -- loudly, not silently."""
    covered = {point.shape for point in _TIER_B_POINTS}
    assert covered == set(output_shape_states())


def test_tier_b_tty_axes_are_fully_covered() -> None:
    """AC2/AC3 / D4's coverage-by-construction claim, half 2: BOTH values of
    EACH of the three tty axes appear in at least one Tier-B point. A new
    `isatty()` branch on a FOURTH stream cannot be satisfied by the existing
    three axes, so a matrix built for it would fail this shape of assertion
    loudly rather than passing blind (D4's own stated mechanism)."""
    for stream in ("stdout", "stderr", "stdin"):
        seen = {point.pty_stream == stream for point in _TIER_B_POINTS}
        assert seen == set(tty_modes()), f"{stream} axis not fully covered by Tier B"


_ANSI_ESCAPE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """R5's own belt-and-braces: a leak spliced BETWEEN ANSI colour codes
    would survive a contiguous-substring grep on the raw text but not on
    this stripped form."""
    return _ANSI_ESCAPE.sub("", text)


@pytest.mark.e2e
@pytest.mark.parametrize("point", _REFUSED_VALUE_POINTS, ids=lambda p: p.id)
def test_tier_b_every_derived_shape_state_never_echoes_a_refused_value(
    point: _TierBPoint, bed: Bed
) -> None:
    """AC2 / AC3 / AC4 -- every derived shape state, including the SIXTH
    SHAPE (`absent-stdout-pty-sixth-shape`, R4's own arm: no `-o` flag,
    stdout a REAL terminal, so `auto_format()` resolves TABLE and the error
    renders to stderr) and R5's stderr-pty arm (asserted on BOTH the raw and
    the ANSI-stripped text)."""
    bad_value = f"{PW_SENTINEL}-tier-b-{point.id}-not-a-path"
    extra = () if point.shape is None else ("-o", point.shape.value)
    argv = [_TIER_B_VERB, str(bed.plain), _TIER_B_FLAG, bad_value, *extra]
    if point.pty_stream is None:
        result = run_cli(*argv, env=_clean_env())
        rc, combined = result.returncode, result.stdout + result.stderr
    else:
        pty_result = run_cli_with_pty(*argv, pty_stream=point.pty_stream, env=_clean_env())
        rc, combined = pty_result.returncode, pty_result.stdout + pty_result.stderr

    assert rc == 2, f"tier-b {point.id} -> {rc}: {combined!r}"
    assert bad_value not in combined, f"tier-b {point.id} echoed its refused value: {combined!r}"
    assert PW_SENTINEL not in combined, f"tier-b {point.id} echoed the sentinel: {combined!r}"
    stripped = _strip_ansi(combined)
    assert PW_SENTINEL not in stripped, f"tier-b {point.id} leaked ANSI-spliced (R5): {combined!r}"
    assert combined.strip(), f"tier-b {point.id} produced no output at all"


@pytest.mark.e2e
def test_tier_b_the_stdin_tty_axis_never_echoes_a_wrong_password_at_the_prompt(bed: Bed) -> None:
    """AC3's stdin arm, and R6's control target (`password.py:109`'s
    interactive `getpass` prompt path). `--password-file` is deliberately
    ABSENT here -- giving it would never reach the prompt path at all -- so
    `decrypt` falls through PLAN.md §5.7's resolution order to an
    interactive prompt on a real pty. A WRONG password is typed; the run
    must still refuse (exit 6) without echoing it anywhere."""
    wrong = f"{PW_SENTINEL}-tier-b-stdin-wrong"
    target = bed.out("tier-b-stdin-pty.pdf")
    result = run_cli_with_pty(
        "decrypt",
        str(bed.encrypted["ascii"]),
        "-O",
        str(target),
        "-o",
        "json",
        pty_stream="stdin",
        stdin_data=(wrong + "\n").encode(),
        env=_clean_env(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 6, f"tier-b stdin-pty -> {result.returncode}: {combined!r}"
    assert wrong not in combined, f"tier-b stdin-pty echoed the wrong password: {combined!r}"
    _assert_no_sentinel(combined, where="tier-b stdin-pty prompt")
    assert not target.exists()


# --------------------------------------------------------------------------- #
# Tier C -- in-process, the FULL derived cross product, < 1s (AC5).
# --------------------------------------------------------------------------- #


def _model_auto_format(*, stdout_tty: bool) -> OutputFormat:
    """PDF-22's OWN, independently-written copy of `auto_format()`'s
    `isatty()` branch. Used ONLY by Tier C, and deliberately NEVER imports
    the product's real `auto_format()` -- AC6's whole point is TWO
    independently-computed predictors (the product's second headline defect
    class: "an assertion made by a DIFFERENT consumer than the one that
    computes it"). If this function ever silently drifted from the real
    branch, `test_ac6_*` below is what catches it."""
    return OutputFormat.TABLE if stdout_tty else OutputFormat.JSON


_TIER_C_VERBOSITY: Final[tuple[str, ...]] = ("quiet", "-vv", "neither")
_TIER_C_TTY_STATES: Final[tuple[tuple[bool, bool, bool], ...]] = tuple(
    (stdout_tty, stderr_tty, stdin_tty)
    for stdout_tty in tty_modes()
    for stderr_tty in tty_modes()
    for stdin_tty in tty_modes()
)
_TIER_C_SENTINEL_LABELS: Final[tuple[str, ...]] = tuple(sorted(SENTINELS))


def _tier_c_cases() -> list[
    tuple[tuple[str, str], OutputFormat | None, str, tuple[bool, bool, bool], str]
]:
    return [
        (pair, shape, verbosity, tty_state, label)
        for pair in _PASSWORD_FILE_PAIRS
        for shape in output_shape_states()
        for verbosity in _TIER_C_VERBOSITY
        for tty_state in _TIER_C_TTY_STATES
        for label in _TIER_C_SENTINEL_LABELS
    ]


def test_ac5_tier_c_case_count_equals_the_derived_dimension_product() -> None:
    """AC5's own structural half: the case count equals the PRODUCT of the
    derived dimension sizes, never a literal on either side."""
    expected = (
        len(_PASSWORD_FILE_PAIRS)
        * len(output_shape_states())
        * len(_TIER_C_VERBOSITY)
        * len(_TIER_C_TTY_STATES)
        * len(_TIER_C_SENTINEL_LABELS)
    )
    assert len(_tier_c_cases()) == expected


def test_ac5_tier_c_the_full_cross_never_renders_either_sentinel() -> None:
    """AC5 -- exhaustive over the full derived cross (>= 5,376 states at
    landing), driven IN-PROCESS against the real renderers
    (`render_error_table` / `render_error_json`) so no subprocess-spawn tax
    is paid.

    R3's control does NOT fire here (measured, not assumed -- PDF-22
    Implementation Log): `render_error_table` alone cannot leak from a dict
    `to_dict()` has already redacted, and R3's own mutation lives in what
    gets PASSED to the renderer (`emit_error()`), which Tier C never calls.
    R3's own dedicated red control is `test_r3_emit_error_never_bypasses_
    to_dicts_redaction_on_the_table_branch` below.

    R7's control (the unicode sentinel leaking ONLY in its `\\uXXXX`-escaped
    form) DOES fire here, on the JSON/NDJSON-shaped cases -- checked
    EXPLICITLY against BOTH the raw sentinel and its `ensure_ascii=True`
    escaped form, mirroring `test_ac5_the_password_is_absent_from_the_json_
    payload`'s own pre-existing check above. A raw-only check was measured
    to MISS an escaped-only leak (PDF-22 Implementation Log) before this
    line was added -- the ASCII sentinel is byte-identical in both forms, so
    only the unicode label's own JSON cases exercise this arm.

    A FAILURE ACCUMULATOR, not a first-failure abort (AC5's own design
    note): a Tier C failure must name WHICH of 5,376+ states failed, not
    just report "1 failed"."""
    import json as _json

    from pdf_toolkit.errors import PdfToolkitError
    from pdf_toolkit.output.json import render_error_json
    from pdf_toolkit.output.table import render_error_table

    failures: list[str] = []
    for pair, shape, verbosity, tty_state, label in _tier_c_cases():
        flag, verb = pair
        stdout_tty, _stderr_tty, _stdin_tty = tty_state
        sentinel = SENTINELS[label]
        resolved = shape if shape is not None else _model_auto_format(stdout_tty=stdout_tty)
        error = PdfToolkitError(
            f"{flag} on {verb} takes a file path or '-'; the given value is not a "
            "readable file. Refusing to echo it, in case it is the password itself.",
            path=sentinel,
            redacted=True,
        )
        payload = error.to_dict()
        rendered = (
            render_error_table(payload)
            if resolved is OutputFormat.TABLE
            else render_error_json(payload)
        )
        leaked = sentinel in rendered
        if not leaked and resolved is not OutputFormat.TABLE:
            escaped = _json.dumps(sentinel, ensure_ascii=True)[1:-1]  # strip the wrapping quotes
            leaked = escaped != sentinel and escaped in rendered
        if leaked:
            failures.append(f"{flag}/{verb}/{shape}/{verbosity}/{tty_state}/{label}")

    assert not failures, (
        f"{len(failures)} of {len(_tier_c_cases())} Tier C states leaked a sentinel "
        f"(first 10 shown): {failures[:10]}"
    )


def test_r3_emit_error_never_bypasses_to_dicts_redaction_on_the_table_branch() -> None:
    """R3's own dedicated red control, and the reason it needs one: NO live
    call site in this product currently sets `path=` alongside
    `redacted=True` (every one of the four `redacted=True` sites is
    deliberately path-less -- verified first-hand, `PDF-22` Implementation
    Log), so no real CLI invocation can drive `errors.py:93`'s chokepoint
    with a genuine value to redact. This test builds the SYNTHETIC case
    directly (as Tier C already does) and calls `emit_error()` itself --
    the exact function R3's mutation targets (`table.py:73-74` via
    `output/__init__.py`'s own TABLE branch) -- rather than
    `render_error_table` in isolation, which cannot observe this defect
    class at all (an already-redacted dict has nothing left to leak; the
    mutation lives in what gets PASSED to the renderer, not in the renderer
    itself)."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from pdf_toolkit.errors import PdfToolkitError
    from pdf_toolkit.output import emit_error

    error = PdfToolkitError(
        "a synthetic refusal for R3's own red control",
        path=PW_SENTINEL,
        redacted=True,
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        emit_error(error, OutputFormat.TABLE)
    combined = out.getvalue() + err.getvalue()
    assert PW_SENTINEL not in combined, f"emit_error's TABLE branch leaked: {combined!r}"
    assert "error:" in err.getvalue(), "the TABLE branch did not render to stderr at all"


@pytest.mark.e2e
def test_ac6_the_in_process_model_agrees_with_the_real_subprocess_on_stdout_tty(bed: Bed) -> None:
    """AC6 -- Tier C's model (`_model_auto_format`) is cross-checked against
    a REAL subprocess for the axis that decides which renderer fires at
    all. Without this, Tier C's 5,376-state exhaustiveness would be "a very
    large control that cannot fail" (the Validation block's own warning) --
    exhaustive over a model nobody proved matches reality.
    """
    piped = run_cli("info", str(bed.plain), env=_clean_env())
    piped_payload = json.loads(piped.stdout)
    assert piped_payload["schema_version"] == 1
    assert _model_auto_format(stdout_tty=False) is OutputFormat.JSON, (
        "the model predicts JSON when stdout is piped, matching the real run above"
    )

    pty_result = run_cli_with_pty(
        "info",
        str(bed.plain),
        "--password-file",
        f"{PW_SENTINEL}-ac6-not-a-path",
        pty_stream="stdout",
        env=_clean_env(),
    )
    assert pty_result.returncode == 2
    # A TABLE render is `error: ...` prose on stderr per emit_error()'s own
    # contract; a JSON render is a parseable object on stdout. Asserting the
    # OBSERVED shape is what makes this a cross-check against reality rather
    # than a restatement of the model.
    assert pty_result.stdout.strip() == "", "the real run put nothing on stdout"
    assert pty_result.stderr.strip().startswith("error:"), (
        f"the real run did not render TABLE-shaped output on stderr: {pty_result.stderr!r}"
    )
    assert _model_auto_format(stdout_tty=True) is OutputFormat.TABLE, (
        "the model predicts TABLE when stdout is a real terminal, matching the run above"
    )


def test_ac7_the_subprocess_case_cap_is_not_exceeded() -> None:
    """AC7 -- the cap is asserted, not merely stated. Tier C is in-process
    and pays no subprocess tax, so it does not count against this cap."""
    subprocess_case_count = (
        len(_PASSWORD_FILE_PAIRS)  # Tier A
        + len(_TIER_B_POINTS)  # Tier B, incl. the 3 real ptys
        + len(INVOCATIONS)  # the 5ff60a280e witness -- one probed verb-pair below
    )
    assert subprocess_case_count <= PDF22_SUBPROCESS_CASE_CAP, (
        f"{subprocess_case_count} exceeds PDF22_SUBPROCESS_CASE_CAP="
        f"{PDF22_SUBPROCESS_CASE_CAP}. Per X-157, the correct response is a BLOCKER "
        f"to the project-manager with two measurements (this count and the measured "
        f"wall clock), never a larger constant."
    )


# --------------------------------------------------------------------------- #
# AC4 -- the sixth shape, pinned by NAME (not folded into a parametrized
# loop, which could silently drop it on a population change).
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac4_the_sixth_shape_is_pinned_by_name(bed: Bed) -> None:
    """`<verb> --password-file <literal>` with NO `-o` flag and stdout a
    REAL terminal exits 2 and echoes neither sentinel on stdout or stderr.

    Red: `git show 73f6722` reproduces the sixth shape (verified in a
    scratch worktree, PDF-22 Implementation Log) -- no `-o`, stdout a pty,
    the sentinel present in the stderr `error: ...` line. `33bf481` is
    clean. Both observed first-hand, recorded in the Implementation Log."""
    result = run_cli_with_pty(
        "info",
        str(bed.plain),
        "--password-file",
        PW_SENTINEL,
        pty_stream="stdout",
        env=_clean_env(),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, f"sixth shape -> {result.returncode}: {combined!r}"
    _assert_no_sentinel(combined, where="the sixth shape (no -o, stdout a real tty)")
    assert combined.strip(), "the sixth shape produced no output at all"


# --------------------------------------------------------------------------- #
# X-243 -- the `5ff60a280e` witness. This WITNESSES the silently-ignored
# `--password-file` tier; it does NOT fix it (AC14: nothing under src/ is
# touched). Both `HONOURED_FLOOR` and `IGNORED_DEFECT_BASELINE` are DEFECT
# baselines, never contracts -- shrinking `IGNORED_DEFECT_BASELINE` is the
# goal, and the honoured set is PROBED at runtime, never listed.
# --------------------------------------------------------------------------- #

#: PDF-37 -- GROWN from `{decrypt, permissions}` (the ratchet D7 requires,
#: AC8) to the full measured honoured set, against the `encrypted_aes256`
#: corpus fixture with the CORRECT password. This is a DEFECT baseline, not
#: a contract: a verb LEAVING this set is a security regression (test below
#: reds it); a verb JOINING it is welcome (the assertion below is `>=`,
#: never `==`).
#:
#: **`decrypt` and `permissions` may never leave this set. `encrypt` may
#: never join it (X-417/X-424) -- it is `OTHER_OBSERVED` below, invariantly,
#: through its own already-encrypted refusal (now exit 2 once
#: `--password-file` is given at all -- D2/D4's central refusal check runs
#: BEFORE `encrypt`'s own document-refusal logic ever sees the operand).**
#: The stale ledger `5ff60a280e` `Title` cell reading "honoured by 3" is NOT
#: evidence and this constant is not edited toward it (X-417).
HONOURED_FLOOR: Final[frozenset[str]] = frozenset(
    {
        "compress",
        "decrypt",
        "delete",
        "extract",
        "info",
        "linearize",
        "merge",
        "meta get",
        "meta set",
        "ocr",
        "permissions",
        "rasterize",
        "reorder",
        "repair",
        "rotate",
        "split",
        "stamp",
        "tables",
        "text",
        "watermark",
    }
)

#: PDF-37 -- EMPTIED (the goal D7 names): the eighteen-verb defect this
#: witness existed to SEE is now extinct. `tests/test_password_file_contract.
#: py` is the derived, product-wide proof; this frozenset staying empty is
#: what the arm below (`test_witness_..._the_ignored_set_never_grows`)
#: continues to protect against a REGRESSION reintroducing it. See
#: `test_witness_5ff60a280e_the_named_populations_partition_every_verb`'s own
#: retirement note for the arm that used to require this non-empty.
IGNORED_DEFECT_BASELINE: Final[frozenset[str]] = frozenset()

#: The residual X-243 warned the ledger's own arithmetic did not name: verbs
#: whose outcome never depends on `--password-file` at all, for a reason
#: OTHER than "silently ignored while otherwise needing a password". Named
#: and counted, never dropped silently. `compose`/`convert`/`create` build
#: their own non-PDF fixture directly and never touch the encrypted operand;
#: `doctor`/`version` take no document operand; `encrypt` refuses
#: `--password-file` centrally (exit 2, D2/D4) before its own document
#: refusal is ever reached -- unchanged by PDF-37, still OTHER, never
#: HONOURED (X-417/X-424).
OTHER_OBSERVED: Final[frozenset[str]] = frozenset(
    {"compose", "convert", "create", "doctor", "encrypt", "version"}
)


class _EncryptedOperandProxy:
    """Every `corpus.path(name)` call returns the ENCRYPTED fixture, so a
    verb's own registered `INVOCATIONS[verb].build(...)` argv (never
    hand-assembled -- X-243's own warning that most verbs need required
    arguments beyond an input path) operates on an encrypted document
    wherever it would normally have used a plaintext one.

    `compose`/`create` build their own non-PDF fixture directly
    (`_fixture_jpeg`/`_fixture_text` in `registry.py`) and never call
    `corpus.path()` at all, so this proxy correctly leaves them alone --
    which is exactly why they land in `OTHER_OBSERVED`: their operand is not
    a document that could be encrypted in the first place.
    """

    def __init__(self, encrypted_path: Path) -> None:
        self._encrypted_path = encrypted_path

    def path(self, name: str) -> Path:
        del name
        return self._encrypted_path


def _strip_password_file_flags(argv: list[str]) -> list[str]:
    """Remove any `PASSWORD_FILE_FLAGS` member + its value from *argv*, so
    the witness controls `--password-file` itself rather than inheriting
    whatever a verb's OWN registered invocation happened to bake in
    (`decrypt`'s row supplies a *valid* `--password-file` by construction;
    without stripping it first, a "no password" probe would silently run
    with a correct one already present)."""
    from pdf_toolkit.cli.common import PASSWORD_FILE_FLAGS

    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] in PASSWORD_FILE_FLAGS:
            index += 2
            continue
        out.append(argv[index])
        index += 1
    return out


@dataclass(frozen=True)
class _WitnessObservation:
    verb: str
    no_pw_rc: int
    correct_rc: int


def _witness_classify(observation: _WitnessObservation) -> str:
    """The three-class partition, MECHANICAL and MEASURED, never predicted.

    * ``no_pw_rc == 0`` -- the verb already succeeds with no password at
      all; `--password-file` cannot be said to matter to its outcome.
      OTHER.
    * ``no_pw_rc == 6 and correct_rc == 0`` -- the correct password resolves
      what no/any password does not. HONOURED.
    * ``no_pw_rc == 6 and correct_rc == 6`` -- identical AUTH failure
      regardless of the password's correctness: validated, never consulted.
      SILENTLY_IGNORED (the defect tier).
    * anything else -- a failure shape unrelated to AUTH's own exit 6 (e.g.
      `encrypt`'s exit 5 "already encrypted", identical either way): OTHER,
      named and explained rather than dropped.
    """
    if observation.no_pw_rc == 0:
        return "OTHER"
    if observation.no_pw_rc == 6 and observation.correct_rc == 0:
        return "HONOURED"
    if observation.no_pw_rc == 6 and observation.correct_rc == 6:
        return "SILENTLY_IGNORED"
    return "OTHER"


@pytest.fixture(scope="module")
def witness_partition(
    corpus: Any, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, _WitnessObservation]:
    """One probe per verb in `INVOCATIONS` (every verb `--password-file`
    reaches, per D2 -- all 26 at landing), TWO conditions each (no password
    at all; the correct password), built from each verb's OWN registered
    invocation via `_EncryptedOperandProxy` rather than a hand-assembled
    `[verb, path, "--password-file", pw]` -- X-243's own warning: most verbs
    need required arguments beyond an input path, and a verb failing on a
    MISSING argument would be misclassified.

    Deliberately TWO conditions, not one (D3's own "26 invocations, not 28"
    suggestion covers only the flag/verb population, not this witness's own
    classification need): a single correct-password run cannot distinguish
    HONOURED from OTHER-succeeds-regardless without a baseline to compare
    against. Reported as a judgement call in this engineer's own report.

    The 52 resulting subprocess calls are dispatched across a small thread
    pool, same reasoning as `registry.derive_password_file_pairs()`
    (AC8's `<= 30s` budget; I/O-bound subprocess wait, GIL released, each
    verb's two conditions write into their own `tmp_path_factory`
    subdirectories so there is no shared mutable state to race on).
    """
    from concurrent.futures import ThreadPoolExecutor

    from corpus import ENCRYPTED_PASSWORD

    proxy = _EncryptedOperandProxy(corpus.path("encrypted_aes256"))
    root = tmp_path_factory.mktemp("pdf22-witness")
    pw_correct = root / "pw-correct.txt"
    pw_correct.write_text(ENCRYPTED_PASSWORD, encoding="utf-8")
    pw_correct.chmod(0o600)
    env = _clean_env()

    def _probe(verb: str) -> tuple[str, _WitnessObservation]:
        verb_dir = root / verb.replace(" ", "_")
        verb_dir.mkdir()

        no_pw_dir = verb_dir / "no-pw"
        no_pw_dir.mkdir()
        no_pw_argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, no_pw_dir))
        no_pw_result = run_cli(verb, *no_pw_argv, "-o", "json", env=env)

        correct_dir = verb_dir / "correct"
        correct_dir.mkdir()
        correct_argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, correct_dir))
        correct_result = run_cli(
            verb, *correct_argv, "--password-file", str(pw_correct), "-o", "json", env=env
        )
        return verb, _WitnessObservation(
            verb=verb, no_pw_rc=no_pw_result.returncode, correct_rc=correct_result.returncode
        )

    verbs = sorted(INVOCATIONS)
    with ThreadPoolExecutor(max_workers=min(8, len(verbs))) as pool:
        observations = dict(pool.map(_probe, verbs))
    return observations


def _witness_classes(
    witness_partition: dict[str, _WitnessObservation],
) -> dict[str, str]:
    return {verb: _witness_classify(observation) for verb, observation in witness_partition.items()}


@pytest.mark.e2e
def test_witness_5ff60a280e_every_verb_lands_in_exactly_one_class(
    witness_partition: dict[str, _WitnessObservation],
) -> None:
    """Every verb in the derived `--password-file` population is classified
    into EXACTLY one observed class -- no unaudited residual (the trap
    X-243 warns the ledger's own arithmetic fell into: 26 declare, 19 reach
    the hint, 3 honour, 18 ignore -- 3+18=21, not 26, and five verbs were
    never named)."""
    classes = _witness_classes(witness_partition)
    honoured = {verb for verb, cls in classes.items() if cls == "HONOURED"}
    ignored = {verb for verb, cls in classes.items() if cls == "SILENTLY_IGNORED"}
    other = {verb for verb, cls in classes.items() if cls == "OTHER"}
    assert honoured | ignored | other == set(witness_partition)
    assert len(honoured) + len(ignored) + len(other) == len(witness_partition), (
        "a verb landed in more than one class or in none -- the partition is not exhaustive"
    )


@pytest.mark.e2e
def test_witness_5ff60a280e_the_honoured_set_never_shrinks(
    witness_partition: dict[str, _WitnessObservation],
) -> None:
    """`HONOURED_FLOOR` is a DEFECT baseline (a floor), not a contract:
    fixing a verb GROWS the probed honoured set (still a superset -> stays
    GREEN, never reds the suite). A verb LEAVING the floor is a SECURITY
    REGRESSION and REDS -- this is the arm that protects the verbs that
    already work. Ledger `5ff60a280e`."""
    classes = _witness_classes(witness_partition)
    honoured = {verb for verb, cls in classes.items() if cls == "HONOURED"}
    missing = HONOURED_FLOOR - honoured
    assert not missing, (
        f"REGRESSION (ledger 5ff60a280e): {sorted(missing)} left the honoured set for "
        f"`--password-file`. HONOURED_FLOOR is a DEFECT baseline, not a contract -- "
        f"a verb leaving it is a real security regression, never a stale-baseline issue."
    )


@pytest.mark.e2e
def test_witness_5ff60a280e_the_ignored_set_never_grows(
    witness_partition: dict[str, _WitnessObservation],
) -> None:
    """A NEW verb silently ignoring a correct `--password-file` is a
    REGRESSION and reds immediately. Ledger `5ff60a280e`."""
    classes = _witness_classes(witness_partition)
    ignored = {verb for verb, cls in classes.items() if cls == "SILENTLY_IGNORED"}
    new_members = ignored - IGNORED_DEFECT_BASELINE
    assert not new_members, (
        f"REGRESSION (ledger 5ff60a280e): {sorted(new_members)} newly silently ignore "
        f"a correct `--password-file`. IGNORED_DEFECT_BASELINE is a DEFECT baseline, "
        f"not a contract -- shrinking it is the goal, growing it is a real regression."
    )


@pytest.mark.e2e
def test_witness_5ff60a280e_a_verb_leaving_the_ignored_set_is_a_directed_pass_not_silence(
    witness_partition: dict[str, _WitnessObservation],
) -> None:
    """The other direction of the same defect baseline: a verb newly
    HONOURED while still recorded on `IGNORED_DEFECT_BASELINE` must not
    pass silently -- it fails, DIRECTED, naming the baseline as stale and
    instructing the author to SHRINK it. This is what stops the witness
    from decaying into a permanent silent exemption the day someone fixes
    verb #4 of 18 and nobody notices (the same shape X-253/`decision.md`
    ratifies for `xfail(strict=True)`: a stale baseline must fail loudly,
    not quietly stay green past its own truth). Ledger `5ff60a280e`."""
    classes = _witness_classes(witness_partition)
    ignored = {verb for verb, cls in classes.items() if cls == "SILENTLY_IGNORED"}
    stale = IGNORED_DEFECT_BASELINE - ignored
    assert not stale, (
        f"GOOD NEWS, ACT ON IT (ledger 5ff60a280e): {sorted(stale)} left the "
        f"silently-ignored set for `--password-file` -- still on "
        f"IGNORED_DEFECT_BASELINE but no longer reproducing. This is a DEFECT "
        f"baseline, not a contract: SHRINK IGNORED_DEFECT_BASELINE to drop "
        f"{sorted(stale)}, and consider whether HONOURED_FLOOR should grow to "
        f"include them. This failure is the witness DOING ITS JOB, not a bug in it."
    )


def test_witness_5ff60a280e_the_named_populations_partition_every_verb() -> None:
    """A purely structural check, independent of any live run: the three
    NAMED sets together cover the derived verb population exactly once each,
    with no verb unnamed and none double-counted. Protects against a future
    edit to any one of the three sets quietly dropping a verb."""
    populations = [HONOURED_FLOOR, IGNORED_DEFECT_BASELINE, OTHER_OBSERVED]
    union: set[str] = set()
    for population in populations:
        overlap = union & population
        assert not overlap, f"{sorted(overlap)} named in more than one baseline set"
        union |= population
    assert union == set(INVOCATIONS), (
        f"named sets do not cover the derived verb population. "
        f"missing: {sorted(set(INVOCATIONS) - union)}; extra: {sorted(union - set(INVOCATIONS))}"
    )
    # RETIRED by PDF-37 (D7/AC9), with this note as the record: this arm used
    # to assert `IGNORED_DEFECT_BASELINE` non-empty -- "this is the defect
    # this witness exists to see" -- from landing (`5ff60a280e`, `B-168`)
    # through PDF-37's own commit. `IGNORED_DEFECT_BASELINE` is now the empty
    # frozenset (all eighteen verbs it named are HONOURED_FLOOR members), so
    # the assertion would be false by construction, not a defect returning.
    # It is retired here, not weakened or narrowed: the class this witness
    # existed to see is gone, and this comment is the audit trail for why
    # that assertion no longer runs.


# --------------------------------------------------------------------------- #
# The two `_B068_...`-tied registry controls survive PDF-22, now sourced
# from the DERIVED population rather than the retired hand-typed tuple --
# both are R2's control (a fourth `PASSWORD_FILE_FLAGS` member with no
# proof).
# --------------------------------------------------------------------------- #


def test_b068_password_file_flag_registry_matches_reachable_verbs() -> None:
    """Structural tie, now against the DERIVED population: every flag in
    `PASSWORD_FILE_FLAGS` (the completeness registry) has at least one
    reachable pair in `derive_password_file_pairs()`, and vice versa -- so a
    flag added to the registry without gaining a reachable verb (and
    therefore without a Tier-A non-echo proof) fails the suite instead of
    shipping quietly, and a stale flag in the derived population without a
    matching registry member fails just as loudly."""
    from pdf_toolkit.cli.common import PASSWORD_FILE_FLAGS

    assert set(PASSWORD_FILE_FLAGS) == {flag for flag, _verb in _PASSWORD_FILE_PAIRS}


@pytest.mark.e2e
@pytest.mark.parametrize("verb", [*VERBS, "info"])
def test_b068_rendered_help_names_no_password_flag_outside_the_registry(verb: str) -> None:
    """Unchanged from B-068: guards against a NEW password-bearing flag
    landing without a completeness-registry entry (and therefore without
    the non-echo proof Tier A now provides for it)."""
    from pdf_toolkit.cli.common import PASSWORD_FILE_FLAGS

    result = run_cli(verb, "--help")
    assert result.returncode == 0
    normalized = re.sub(r"-[ \t]*\n[ \t]*", "-", result.stdout)
    offenders = [
        flag
        for flag in re.findall(r"--[a-z-]*password[a-z-]*", normalized)
        if flag not in PASSWORD_FILE_FLAGS
    ]
    assert offenders == [], f"`{verb} --help` names {offenders}, outside PASSWORD_FILE_FLAGS"
