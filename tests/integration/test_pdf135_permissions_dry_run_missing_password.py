"""PDF-135 -- ``permissions --dry-run`` predicts the exit 6 a missing password gets.

README ``## Exit codes`` promises that an encrypted operand with no password to
resolve predicts ``6`` and exits ``6``. ``permissions`` used to plan an ok item
without looking at the document, so a user-password document with no password
previewed ``0`` and really exited ``6`` (ledger ``6d7b6c5321``, carrier B-473).

This module is independent of every other test module: fixtures are built here
with pikepdf in the shapes the spec's E2 measured, every expected cell is a
LITERAL, and every cell is a ``(dry, real)`` PAIR (GR-002).

Provenance of every literal: ``7b1286b``, 2026-10-25, PDF-135 E2 + D1.

The decisive arms (a plausible wrong fix answers differently):
  * a resolvable password steps the auth gate aside (a "locked -> 6" fix says 6);
  * the empty user password unlocks an owner-only file (an "encrypted -> 6" fix);
  * a lower tier (malformed / missing / directory) answers before the auth tier
    (a "predict 6 first" fix, or one that gates the read on resolvability).

Deviation from the house helper: ``tests/dryreal.py::dry_and_real`` cannot feed
stdin, and the ``stdin`` arm (``--password-file -``) needs a closed stdin, so
``_pair`` mirrors it over ``registry.run_cli`` with ``stdin=""``.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import redirected_environment  # noqa: E402
from registry import run_cli  # noqa: E402

CRYPTO_SOURCE = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling" / "ops" / "crypto.py"
MESSAGE = "a password is required to read this document's permissions"

INPUTS = (
    "PLAIN",
    "O-AES256",
    "O-RC4",
    "UO-AES256",
    "UO-RC4",
    "corrupt",
    "notpdf",
    "dir",
    "missing",
)
ARMS = ("none", "x", "u", "o", "empty", "badfile", "stdin", "env-u", "env-x")

_FILENAMES = {
    "PLAIN": "PLAIN.pdf",
    "O-AES256": "O-AES256.pdf",
    "O-RC4": "O-RC4.pdf",
    "UO-AES256": "UO-AES256.pdf",
    "UO-RC4": "UO-RC4.pdf",
    "corrupt": "corrupt.pdf",
    "notpdf": "notpdf.pdf",
    "dir": "dir.pdf",
    "missing": "missing.pdf",
}

_ARM_ARGS: dict[str, list[str]] = {
    "none": [],
    "x": ["--password-file", "x.pw"],
    "u": ["--password-file", "u.pw"],
    "o": ["--password-file", "o.pw"],
    "empty": ["--password-file", "empty.pw"],
    "badfile": ["--password-file", "missing.pw"],
    "stdin": ["--password-file", "-"],
    "env-u": [],
    "env-x": [],
}
_ARM_ENV = {"env-u": "u-pw", "env-x": "wrong"}

Outcome = tuple[int, str, int, str]

OK: Outcome = (0, "op", 0, "ok")
AUTH: Outcome = (6, "err", 6, "auth")
DRY_AUTH: Outcome = (6, "op", 6, "auth")
FAILURE: Outcome = (1, "err", 1, "failure")
USAGE: Outcome = (2, "err", 2, "usage")
NO_INPUT: Outcome = (4, "err", 4, "no_input")

_PLAIN = [OK, OK, OK, OK, OK, USAGE, OK, OK, OK]
_OWNER_ONLY = [OK, AUTH, AUTH, OK, OK, USAGE, OK, AUTH, AUTH]
_USER_PW = [AUTH, AUTH, OK, OK, AUTH, USAGE, AUTH, OK, AUTH]
_MALFORMED = [FAILURE] * 5 + [USAGE] + [FAILURE] * 3
_DIR = [USAGE] * 9
_MISSING = [NO_INPUT] * 5 + [USAGE] + [NO_INPUT] * 3

#: The REAL column (unchanged by PDF-135), input -> outcome per arm in ARMS order.
REAL: dict[str, list[Outcome]] = {
    "PLAIN": _PLAIN,
    "O-AES256": _OWNER_ONLY,
    "O-RC4": _OWNER_ONLY,
    "UO-AES256": _USER_PW,
    "UO-RC4": _USER_PW,
    "corrupt": _MALFORMED,
    "notpdf": _MALFORMED,
    "dir": _DIR,
    "missing": _MISSING,
}

#: The X-89 carve-out cells (16): a supplied password whose correctness decides.
#: Dry says ``0`` with ``password_verified: false``; the real run says ``6``.
CARVE_OUT = frozenset(
    {("O-AES256", a) for a in ("x", "u", "env-u", "env-x")}
    | {("O-RC4", a) for a in ("x", "u", "env-u", "env-x")}
    | {("UO-AES256", a) for a in ("x", "empty", "stdin", "env-x")}
    | {("UO-RC4", a) for a in ("x", "empty", "stdin", "env-x")}
)


def expected_pair(name: str, arm: str) -> tuple[Outcome, Outcome]:
    real = REAL[name][ARMS.index(arm)]
    if (name, arm) in CARVE_OUT:
        return OK, real
    if real == AUTH:
        # The dry refusal rides an OPERATION envelope (the house shape `decrypt`
        # and `encrypt` use); the real refusal is an ERROR envelope. Same code+kind.
        return DRY_AUTH, real
    return real, real


def same_verdict(dry: Outcome, real: Outcome) -> bool:
    """dry == real on the exit code, the item/error code and the kind (not the envelope shape)."""
    return (dry[0], dry[2], dry[3]) == (real[0], real[2], real[3])


# --------------------------------------------------------------------------- #
# The lab: fixtures + a cached (dry, real) runner.
# --------------------------------------------------------------------------- #


def _save(path: Path, **encryption: Any) -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    kwargs: dict[str, Any] = {}
    if encryption:
        kwargs["encryption"] = pikepdf.Encryption(**encryption)
    pdf.save(path, **kwargs)
    pdf.close()


class Lab:
    def __init__(self, root: Path) -> None:
        self.cwd = root / "fix"
        self.cwd.mkdir()
        self.env_base, _ = redirected_environment(root / "env")
        self.env_base.pop("PDF_TOOLING_PASSWORD", None)
        self.env_base.pop("PDF_TOOLING_OWNER_PASSWORD", None)
        self._cache: dict[tuple[str, str], tuple[Any, Any]] = {}
        cwd = self.cwd
        _save(cwd / "PLAIN.pdf")
        _save(cwd / "O-AES256.pdf", user="", owner="o-pw", R=6)
        _save(cwd / "O-RC4.pdf", user="", owner="o-pw", R=3, aes=False, metadata=False)
        _save(cwd / "UO-AES256.pdf", user="u-pw", owner="o-pw", R=6)
        _save(cwd / "UO-RC4.pdf", user="u-pw", owner="o-pw", R=3, aes=False, metadata=False)
        data = (cwd / "PLAIN.pdf").read_bytes()
        (cwd / "corrupt.pdf").write_bytes(data[:24])
        (cwd / "notpdf.pdf").write_text("this is not a pdf\n", encoding="utf-8")
        (cwd / "dir.pdf").mkdir()
        secrets = (("x.pw", "x-wrong"), ("u.pw", "u-pw"), ("o.pw", "o-pw"), ("empty.pw", ""))
        for name, text in secrets:
            (cwd / name).write_text(text, encoding="utf-8")
            (cwd / name).chmod(0o600)

    def env_for(self, arm: str) -> dict[str, str]:
        env = dict(self.env_base)
        if arm in _ARM_ENV:
            env["PDF_TOOLING_PASSWORD"] = _ARM_ENV[arm]
        return env

    def run(self, argv: list[str], arm: str = "none") -> Any:
        return run_cli(*argv, stdin="", env=self.env_for(arm), cwd=self.cwd)

    def pair(self, name: str, arm: str) -> tuple[Any, Any]:
        key = (name, arm)
        if key not in self._cache:
            args = [_FILENAMES[name], *_ARM_ARGS[arm]]
            dry = self.run(["permissions", "--dry-run", *args, "-o", "json"], arm)
            real = self.run(["permissions", *args, "-o", "json"], arm)
            self._cache[key] = (dry, real)
        return self._cache[key]


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Lab:
    return Lab(tmp_path_factory.mktemp("pdf135"))


def outcome(proc: Any) -> Outcome:
    body = json.loads(proc.stdout)
    if "error" in body:
        err = body["error"]
        return (proc.returncode, "err", err["code"], err["kind"])
    item = body["items"][0]
    kind = "ok" if item["ok"] else item["detail"]["would_refuse"]["kind"]
    return (proc.returncode, "op", item["exit_code"], kind)


def _cells() -> list[Any]:
    return [pytest.param(n, a, id=f"{n}-{a}") for n in INPUTS for a in ARMS]


# --------------------------------------------------------------------------- #
# AC1 -- the ledger repro.
# --------------------------------------------------------------------------- #

BASE_REAL_STDOUT = (
    '{"schema_version": 1, "error": {"code": 6, "kind": "auth", "message": '
    '"a password is required to read this document\'s permissions", "path": "%s"}}'
)


@pytest.mark.parametrize("name", ["UO-AES256", "UO-RC4"])
def test_ac1_ledger_repro_dry_rc_equals_real_rc_6(lab: Lab, name: str) -> None:
    dry, real = lab.pair(name, "none")
    assert real.returncode == 6, real.stdout + real.stderr
    assert dry.returncode == 6, dry.stdout + dry.stderr
    item = json.loads(dry.stdout)["items"][0]
    assert item["ok"] is False
    assert item["exit_code"] == 6
    want_error = {"code": 6, "kind": "auth", "message": MESSAGE, "path": _FILENAMES[name]}
    want_bytes = BASE_REAL_STDOUT % _FILENAMES[name]
    assert json.loads(real.stdout)["error"] == want_error
    assert real.stdout.strip() == want_bytes


# --------------------------------------------------------------------------- #
# AC2 -- the full 81-cell matrix, as pairs.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("name", "arm"), _cells())
def test_ac2_matrix_cell(lab: Lab, name: str, arm: str) -> None:
    dry, real = lab.pair(name, arm)
    want_dry, want_real = expected_pair(name, arm)
    assert (outcome(dry), outcome(real)) == (want_dry, want_real), (dry.stdout, real.stdout)
    if (name, arm) in CARVE_OUT:
        assert json.loads(dry.stdout)["items"][0]["detail"]["password_verified"] is False
    else:
        assert same_verdict(outcome(dry), outcome(real))


def test_ac2_matrix_reports_every_mismatching_cell(lab: Lab) -> None:
    mismatches = []
    carve = 0
    for name in INPUTS:
        for arm in ARMS:
            dry, real = lab.pair(name, arm)
            got = (outcome(dry), outcome(real))
            if got != expected_pair(name, arm):
                mismatches.append((name, arm, got, expected_pair(name, arm)))
            if not same_verdict(outcome(dry), outcome(real)):
                carve += 1
    assert not mismatches, mismatches
    assert carve == len(CARVE_OUT) == 16
    assert len(INPUTS) * len(ARMS) == 81


# --------------------------------------------------------------------------- #
# AC3 -- a lower tier answers when the auth gate steps aside.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("name", "arm"), [("corrupt", "u"), ("notpdf", "x")])
def test_ac3_a_lower_tier_answers_when_the_auth_gate_steps_aside(
    lab: Lab, name: str, arm: str
) -> None:
    dry, real = lab.pair(name, arm)
    assert real.returncode == 1, real.stdout + real.stderr
    assert dry.returncode == 1, dry.stdout + dry.stderr
    assert dry.stdout == real.stdout
    assert json.loads(real.stdout)["error"]["kind"] == "failure"


# --------------------------------------------------------------------------- #
# AC4 -- the auth gate opens only for a locked document with nothing resolvable.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "arm", "want"),
    [
        ("UO-AES256", "u", OK),
        ("UO-AES256", "o", OK),
        ("UO-AES256", "env-u", OK),
        ("O-AES256", "none", OK),
        ("O-RC4", "none", OK),
        ("missing", "none", NO_INPUT),
        ("dir", "none", USAGE),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_ac4_the_auth_gate_opens_only_for_a_locked_document_with_no_password(
    lab: Lab, name: str, arm: str, want: Outcome
) -> None:
    dry, real = lab.pair(name, arm)
    assert (outcome(dry), outcome(real)) == (want, want)


# --------------------------------------------------------------------------- #
# AC5 -- the prediction is the real run's own refusal.
# --------------------------------------------------------------------------- #


def test_ac5_the_prediction_is_the_real_runs_own_refusal(lab: Lab) -> None:
    dry, real = lab.pair("UO-AES256", "none")
    item = json.loads(dry.stdout)["items"][0]
    detail = item["detail"]
    assert detail["would_refuse"] == json.loads(real.stdout)["error"]
    assert item["message"] == json.loads(real.stdout)["error"]["message"]
    assert detail["planned_refusal"] == "AuthError"
    assert detail["would_exit"] == 6
    assert detail["password_source"] is None
    assert detail["password_verified"] is False
    assert json.loads(dry.stdout)["exit_code"] == 6


def test_ac5_crypto_spells_the_message_exactly_once() -> None:
    tree = ast.parse(CRYPTO_SOURCE.read_text(encoding="utf-8"))
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == MESSAGE]
    assert len(hits) == 1, [n.lineno for n in hits]
    constants = [
        n
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and any(c is hits[0] for c in ast.walk(n))
    ]
    assert constants, "the message must be a module-level constant"


# --------------------------------------------------------------------------- #
# AC6 -- no dry path reads a secret (M4).
# --------------------------------------------------------------------------- #


def test_ac6_no_secret_is_read_on_the_dry_path(lab: Lab) -> None:
    sentinel = "4e86c1d0-pdf135-sentinel"
    pw = lab.cwd / "p.pw"
    pw.write_text(sentinel, encoding="utf-8")
    pw.chmod(0o000)
    try:
        dry = lab.run(
            ["permissions", "UO-AES256.pdf", "--password-file", "p.pw", "--dry-run", "-o", "json"]
        )
    finally:
        pw.chmod(0o600)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert json.loads(dry.stdout)["items"][0]["detail"]["password_verified"] is False
    assert sentinel not in dry.stdout
    assert sentinel not in dry.stderr


# --------------------------------------------------------------------------- #
# AC7 -- the password-file classification does not move (M5).
# --------------------------------------------------------------------------- #


def test_ac7_crypto_imports_neither_resolver_nor_predictor() -> None:
    tree = ast.parse(CRYPTO_SOURCE.read_text(encoding="utf-8"))
    banned = {"PasswordResolver", "predict_password_refusal"}
    seen = [
        (node.lineno, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("document_password")
        for alias in node.names
        if alias.name in banned
    ]
    assert not seen, seen


def test_ac7_encrypt_still_refuses_password_file(lab: Lab) -> None:
    result = lab.run(
        [
            "encrypt",
            "PLAIN.pdf",
            "--owner-password-file",
            "o.pw",
            "--password-file",
            "u.pw",
            "-O",
            "e.pdf",
            "-o",
            "json",
        ]
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "does not accept --password-file" in json.loads(result.stdout)["error"]["message"]
    assert not (lab.cwd / "e.pdf").exists()
