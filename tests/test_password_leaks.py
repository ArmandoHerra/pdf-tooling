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
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import console_script, run_cli  # noqa: E402

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

#: The one file permitted to call ``Secret.reveal()`` (`PLAN.md` §5.7).
REVEAL_ALLOWLIST: Final[frozenset[str]] = frozenset({"adapters/pikepdf_structure.py"})


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
    would mean it was rejected as unknown."""
    source = bed.plain if verb in {"encrypt", "info"} else bed.encrypted["ascii"]
    args = [verb, str(source), "--password-file", str(bed.password_file["ascii"])]
    if verb in {"encrypt", "decrypt"}:
        args += ["-O", str(bed.out(f"regression-{verb}.pdf"))]
    if verb == "encrypt":
        args += ["--owner-password-file", str(bed.password_file["ascii"])]
    result = run_cli(*args, env=_clean_env())
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
