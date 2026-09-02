"""PDF-13 — `encrypt`/`decrypt`/`permissions` as real behaviour.

Split on the same principle PDF-12's own integration module states: a
subprocess is bought only where a real process is the only observer (exit
codes, `--dry-run` purity as the filesystem sees it, `-o json` on a pipe).
Everything provable in process — the permission matrix, the page-tree
round trip, the algorithm mapping — is proven in process, which is what keeps
this module's contribution to B-061 proportionate.

The generic contract harness already covers unknown-flag / nonexistent-input /
no-clobber / OR-3 / dry-run-parity for all three verbs with **zero** action
from this file: C14 grew 52 -> 64 cells and C15 grew 20 -> 24 with no diff to
``tests/test_cli_contract.py`` at all.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real, prediction, real_envelope  # noqa: E402
from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from pagetree import page_tree_digest  # noqa: E402
from pdf_toolkit.ports.structure import (  # noqa: E402
    ALWAYS_GRANTED_TOKENS,
    PERMISSION_TOKENS,
)
from registry import run_cli  # noqa: E402

PW = "roundtrip-owner-password"
OTHER_PW = "not-the-right-password"


def _policy(**overrides: Any) -> Any:
    from pdf_toolkit.safety.policy import SafetyPolicy

    values: dict[str, Any] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)


def _password_file(tmp_path: Path, name: str = "pw.txt", value: str = PW) -> Path:
    path = tmp_path / name
    path.write_text(value)
    path.chmod(0o600)
    return path


def _slot(path: Path, slot: str = "owner") -> Any:
    from pdf_toolkit.cli.password import plan_password

    return plan_password(
        slot=slot,
        flag=f"--{slot}-password-file" if slot != "password" else "--password-file",
        value=str(path),
        env_names=(),
        prompt="x: ",
        allow_empty=slot != "owner",
    )


def _encrypt(
    source: Path,
    target: Path,
    pw: Path,
    *,
    allow: frozenset[str] = frozenset(),
    legacy: bool = False,
) -> Any:
    from pdf_toolkit.ops.crypto import encrypt_run

    return encrypt_run(
        source,
        owner=_slot(pw, "owner"),
        user=None,
        allow=allow,
        legacy=legacy,
        output=target,
        in_place=False,
        policy=_policy(),
    )


def _permissions(source: Path, pw: Path | None = None) -> dict[str, Any]:
    from pdf_toolkit.ops.crypto import PasswordSource, permissions_run

    slot = (
        _slot(pw, "password")
        if pw is not None
        else PasswordSource(slot="password", source=None, read=None)
    )
    result = permissions_run(source, password=slot, policy=_policy())
    return dict(result.items[0].detail or {})


def _clean_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PDF_TOOLKIT_PASSWORD", None)
    env.pop("PDF_TOOLKIT_OWNER_PASSWORD", None)
    env.update(extra)
    return env


# --------------------------------------------------------------------------- #
# AC8 / AC9 -- the algorithm is what the tool says it is
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac8_aes256_is_the_default_and_info_reports_the_exact_string(
    corpus: Any, tmp_path: Path
) -> None:
    """The exact string from `PLAN.md` §6's declared vocabulary, asserted
    literally: a near-miss like "AES256" would break every consumer keying
    off it."""
    pw = _password_file(tmp_path)
    target = tmp_path / "aes.pdf"
    encrypted = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--owner-password-file",
        str(pw),
        "-O",
        str(target),
        env=_clean_env(),
    )
    assert encrypted.returncode == 0, encrypted.stderr

    info = run_cli("info", str(target), "-o", "json", env=_clean_env())
    assert info.returncode == 0, info.stderr
    assert json.loads(info.stdout)["documents"][0]["encryption_algorithm"] == "AES-256"

    reported = _permissions(target, pw)
    assert reported["algorithm"] == "AES-256"
    assert reported["revision"] == 6
    assert reported["key_bits"] == 256


@pytest.mark.e2e
def test_ac9_rc4_128_is_reachable_only_behind_legacy_and_says_it_is_broken(
    corpus: Any, tmp_path: Path
) -> None:
    pw = _password_file(tmp_path)
    target = tmp_path / "legacy.pdf"
    result = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--legacy",
        "--owner-password-file",
        str(pw),
        "-O",
        str(target),
        "-o",
        "json",
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "broken" in result.stderr, "the --legacy warning never reached stderr"
    payload = json.loads(result.stdout)
    assert any("broken" in warning for warning in payload["warnings"]), payload["warnings"]

    info = run_cli("info", str(target), "-o", "json", env=_clean_env())
    assert json.loads(info.stdout)["documents"][0]["encryption_algorithm"] == "RC4-128"
    assert _permissions(target, pw)["algorithm"] == "RC4-128"


def test_ac9_no_flag_combination_other_than_legacy_produces_rc4(
    corpus: Any, tmp_path: Path
) -> None:
    """Exhaustive over the flags `encrypt` actually has: every combination
    without ``--legacy`` is AES-256."""
    pw = _password_file(tmp_path)
    source = corpus.path("single_page")
    combinations = [
        frozenset(),
        frozenset({"print"}),
        frozenset(PERMISSION_TOKENS),
    ]
    for index, allow in enumerate(combinations):
        target = tmp_path / f"nolegacy-{index}.pdf"
        _encrypt(source, target, pw, allow=allow, legacy=False)
        assert _permissions(target, pw)["algorithm"] == "AES-256"


# --------------------------------------------------------------------------- #
# AC10 -- the page tree round-trips, and the comparison can fail
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", ["multipage_text", "rotated", "jpeg_page"])
def test_ac10_the_page_tree_round_trips_byte_for_byte(
    corpus: Any, tmp_path: Path, fixture: str
) -> None:
    from pdf_toolkit.ops.crypto import decrypt_run

    pw = _password_file(tmp_path)
    source = corpus.path(fixture)
    encrypted = tmp_path / f"{fixture}-enc.pdf"
    decrypted = tmp_path / f"{fixture}-dec.pdf"
    _encrypt(source, encrypted, pw, allow=frozenset({"print"}))
    decrypt_run(
        encrypted,
        password=_slot(pw, "password"),
        output=decrypted,
        in_place=False,
        policy=_policy(),
    )
    assert page_tree_digest(source) == page_tree_digest(decrypted)


def test_ac10_the_comparison_has_teeth(corpus: Any, tmp_path: Path) -> None:
    """The negative control. A comparison that cannot fail is not a test, and
    "page count matches" or "extracted text matches" would both survive a
    re-encoded document -- which is why neither satisfies AC10.
    """
    import pikepdf

    source = corpus.path("multipage_text")
    mutated = tmp_path / "mutated.pdf"
    with pikepdf.Pdf.open(source) as pdf:
        page = pdf.pages[0]
        original = page.obj["/Contents"].read_bytes()
        # One byte, inside the content stream, on one page.
        flipped = bytearray(original)
        flipped[len(flipped) // 2] ^= 0x01
        page.obj["/Contents"] = pdf.make_stream(bytes(flipped))
        pdf.save(mutated)

    before = page_tree_digest(source)
    after = page_tree_digest(mutated)
    assert before != after, "flipping a content byte did not change the digest"
    assert before[1:] == after[1:], "only the mutated page's digest should differ"


# --------------------------------------------------------------------------- #
# AC11 -- the permission set is exact, with the one bit the FORMAT overrides
# --------------------------------------------------------------------------- #


def _expected(requested: frozenset[str]) -> set[str]:
    """What the document will actually grant.

    **Two measured deviations from AC11's literal wording, and both are the
    honest reading.** AC11 says ``--allow <token>`` returns *"exactly that
    token and nothing else"*. Verified against pikepdf 10.12.0 / libqpdf
    12.3.2 before this test was written:

    1. ``accessibility`` is granted whatever is requested, at R=4 and at R=6
       alike, because ISO 32000-2 deprecated that bit and conforming readers
       always permit it.
    2. ``print-highres`` also grants ``print`` (``print_lowres``). The format
       has no spelling for "may print at full resolution but not at low", and
       the implication is a fact about the bits rather than about this tool.

    This product reports what the document GRANTS rather than what was ASKED
    FOR, so the expectation carries both overrides explicitly instead of the
    test quietly asserting the request back at itself.
    """
    granted = set(requested) | set(ALWAYS_GRANTED_TOKENS)
    if "print-highres" in granted:
        granted.add("print")
    return granted


@pytest.mark.parametrize("token", PERMISSION_TOKENS)
def test_ac11_each_token_grants_exactly_itself(corpus: Any, tmp_path: Path, token: str) -> None:
    pw = _password_file(tmp_path)
    target = tmp_path / f"allow-{token}.pdf"
    _encrypt(corpus.path("single_page"), target, pw, allow=frozenset({token}))
    assert set(_permissions(target, pw)["granted"]) == _expected(frozenset({token}))


def test_ac11_all_grants_everything_and_none_grants_only_the_forced_bit(
    corpus: Any, tmp_path: Path
) -> None:
    pw = _password_file(tmp_path)
    every = tmp_path / "allow-all.pdf"
    _encrypt(corpus.path("single_page"), every, pw, allow=frozenset(PERMISSION_TOKENS))
    assert set(_permissions(every, pw)["granted"]) == set(PERMISSION_TOKENS)

    nothing = tmp_path / "allow-none.pdf"
    _encrypt(corpus.path("single_page"), nothing, pw, allow=frozenset())
    granted = set(_permissions(nothing, pw)["granted"])
    assert granted == set(ALWAYS_GRANTED_TOKENS)
    # The point of stating it twice: this is NOT the empty set, and reporting
    # it as empty would be reporting the request rather than the document.
    assert granted != set()
    assert "print" not in granted


def test_ac11_two_tokens_grant_both(corpus: Any, tmp_path: Path) -> None:
    pw = _password_file(tmp_path)
    target = tmp_path / "allow-two.pdf"
    _encrypt(corpus.path("single_page"), target, pw, allow=frozenset({"print", "copy"}))
    assert set(_permissions(target, pw)["granted"]) == _expected(frozenset({"print", "copy"}))


def test_ac11_permissions_reports_the_vocabulary_and_the_forced_bit(
    corpus: Any, tmp_path: Path
) -> None:
    pw = _password_file(tmp_path)
    target = tmp_path / "vocab.pdf"
    _encrypt(corpus.path("single_page"), target, pw, allow=frozenset({"print"}))
    detail = _permissions(target, pw)
    assert detail["vocabulary"] == list(PERMISSION_TOKENS)
    assert detail["always_granted"] == list(ALWAYS_GRANTED_TOKENS)
    assert detail["permissions_readable"] is True


def test_ac11_an_unencrypted_document_grants_everything(corpus: Any) -> None:
    detail = _permissions(corpus.path("single_page"))
    assert detail["encrypted"] is False
    assert detail["algorithm"] is None
    assert set(detail["granted"]) == set(PERMISSION_TOKENS)


@pytest.mark.e2e
@pytest.mark.parametrize(
    "value", ["bogus", "all,print", "none,print", "print,bogus", "all,none", ""]
)
def test_ac11_a_bad_allow_spelling_is_exit_2(corpus: Any, tmp_path: Path, value: str) -> None:
    result = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "--allow",
        value,
        "-O",
        str(tmp_path / "never.pdf"),
        env=_clean_env(),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (tmp_path / "never.pdf").exists()


@pytest.mark.e2e
def test_ac11_an_unknown_token_quotes_it_and_lists_the_vocabulary(
    corpus: Any, tmp_path: Path
) -> None:
    result = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "--allow",
        "bogus",
        "-O",
        str(tmp_path / "never.pdf"),
        env=_clean_env(),
    )
    combined = result.stdout + result.stderr
    assert "bogus" in combined
    for token in PERMISSION_TOKENS:
        assert token in combined


@pytest.mark.e2e
def test_ac11_omitting_allow_notes_the_deny_by_default(corpus: Any, tmp_path: Path) -> None:
    result = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "-O",
        str(tmp_path / "deny.pdf"),
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "--allow all" in result.stderr
    assert "advisory" in result.stderr.lower()


# --------------------------------------------------------------------------- #
# AC13 -- the exit-code matrix, with 6 distinct from 3 and 5
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac13_the_exit_code_matrix(corpus: Any, tmp_path: Path) -> None:
    """One table-driven arm over all three verbs.

    Exit **3** (`ENGINE_MISSING`) is deliberately absent and is asserted NOT
    to occur: `pikepdf` is a hard install dependency (`PLAN.md` §5.5), so
    "missing" would mean a broken install rather than a user configuration
    choice. Collapsing 6 into 3 or 5 is refused by PLAN §12 R-05 because a
    script's recovery differs -- a wrong password is retryable with different
    input, a missing engine needs an install, a clobber refusal needs a flag.
    """
    pw = _password_file(tmp_path, "good.pw")
    wrong = _password_file(tmp_path, "wrong.pw", OTHER_PW)
    encrypted = tmp_path / "matrix-enc.pdf"
    _encrypt(corpus.path("single_page"), encrypted, pw, allow=frozenset({"print"}))
    occupied = tmp_path / "occupied.pdf"
    occupied.write_bytes(b"%PDF-1.4\n%%EOF\n")
    # A genuinely UNPARSEABLE input. Truncating the encrypted file was tried
    # first and is the wrong fixture: pikepdf's recovery parser reconstructs
    # enough of it to report "not encrypted", and `decrypt` then answers 4
    # ("nothing to act on") -- which is the honest answer for that input, not
    # a defect. Garbage behind a PDF header defeats recovery outright.
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\n" + bytes(512))
    missing = tmp_path / "does-not-exist.pdf"
    plain = corpus.path("single_page")

    cases: list[tuple[str, list[str], int]] = [
        (
            "encrypt: correct password",
            [
                "encrypt",
                str(plain),
                "--owner-password-file",
                str(pw),
                "-O",
                str(tmp_path / "m1.pdf"),
            ],
            0,
        ),
        (
            "decrypt: correct password",
            ["decrypt", str(encrypted), "--password-file", str(pw), "-O", str(tmp_path / "m2.pdf")],
            0,
        ),
        (
            "permissions: correct password",
            ["permissions", str(encrypted), "--password-file", str(pw)],
            0,
        ),
        (
            "decrypt: wrong password",
            [
                "decrypt",
                str(encrypted),
                "--password-file",
                str(wrong),
                "-O",
                str(tmp_path / "m3.pdf"),
            ],
            6,
        ),
        (
            "decrypt: no password, non-TTY",
            ["decrypt", str(encrypted), "-O", str(tmp_path / "m4.pdf")],
            6,
        ),
        (
            "encrypt: no password, non-TTY",
            ["encrypt", str(plain), "-O", str(tmp_path / "m5.pdf")],
            6,
        ),
        (
            "encrypt: literal password value",
            ["encrypt", str(plain), "--owner-password", PW, "-O", str(tmp_path / "m6.pdf")],
            2,
        ),
        (
            "encrypt: unknown --allow token",
            [
                "encrypt",
                str(plain),
                "--owner-password-file",
                str(pw),
                "--allow",
                "bogus",
                "-O",
                str(tmp_path / "m7.pdf"),
            ],
            2,
        ),
        (
            "encrypt: nonexistent input",
            [
                "encrypt",
                str(missing),
                "--owner-password-file",
                str(pw),
                "-O",
                str(tmp_path / "m8.pdf"),
            ],
            4,
        ),
        (
            "decrypt: nonexistent input",
            ["decrypt", str(missing), "--password-file", str(pw), "-O", str(tmp_path / "m9.pdf")],
            4,
        ),
        ("permissions: nonexistent input", ["permissions", str(missing)], 4),
        (
            "decrypt: unencrypted document",
            ["decrypt", str(plain), "--password-file", str(pw), "-O", str(tmp_path / "m10.pdf")],
            4,
        ),
        (
            "encrypt: existing target, no --force",
            ["encrypt", str(plain), "--owner-password-file", str(pw), "-O", str(occupied)],
            5,
        ),
        (
            "encrypt: already-encrypted input",
            [
                "encrypt",
                str(encrypted),
                "--owner-password-file",
                str(pw),
                "-O",
                str(tmp_path / "m11.pdf"),
            ],
            5,
        ),
        (
            "decrypt: corrupt encrypted file",
            ["decrypt", str(corrupt), "--password-file", str(pw), "-O", str(tmp_path / "m12.pdf")],
            1,
        ),
    ]

    observed: dict[str, int] = {}
    for label, argv, expected in cases:
        result = run_cli(*argv, env=_clean_env())
        observed[label] = result.returncode
        assert result.returncode == expected, (
            f"{label}: expected {expected}, got {result.returncode}: {result.stdout}{result.stderr}"
        )

    # 6 is distinct from 3 and from 5 -- the whole point of PLAN §12 R-05.
    assert 3 not in observed.values(), "exit 3 is unreachable for these three verbs"
    assert observed["encrypt: already-encrypted input"] == 5
    assert observed["decrypt: wrong password"] == 6

    # "nothing written" for the two cases that promise it.
    assert not (tmp_path / "m10.pdf").exists()
    assert occupied.read_bytes() == b"%PDF-1.4\n%%EOF\n"


# --------------------------------------------------------------------------- #
# AC14 -- no plaintext residue
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac14_in_place_without_a_choice_refuses_and_leaves_the_input_untouched(
    corpus: Any, tmp_path: Path
) -> None:
    subject = tmp_path / "inplace.pdf"
    shutil.copy(corpus.path("single_page"), subject)
    before = subject.read_bytes()
    result = run_cli(
        "encrypt",
        str(subject),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "--in-place",
        env=_clean_env(),
    )
    assert result.returncode == 5, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "--no-backup" in combined and "-y" in combined
    assert "UNENCRYPTED" in combined
    assert subject.read_bytes() == before
    assert not (tmp_path / "inplace.pdf.bak").exists()


@pytest.mark.e2e
def test_ac14_with_yes_it_proceeds_and_warns_that_the_bak_is_plaintext(
    corpus: Any, tmp_path: Path
) -> None:
    subject = tmp_path / "yes.pdf"
    shutil.copy(corpus.path("single_page"), subject)
    original = subject.read_bytes()
    result = run_cli(
        "encrypt",
        str(subject),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "--in-place",
        "-y",
        "-o",
        "json",
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    sidecar = tmp_path / "yes.pdf.bak"
    assert sidecar.is_file()
    assert sidecar.read_bytes() == original, "the sidecar is the ORIGINAL, i.e. plaintext"
    assert subject.read_bytes() != original
    warnings = json.loads(result.stdout)["warnings"]
    assert any("UNENCRYPTED" in warning for warning in warnings), warnings
    assert any("UNENCRYPTED" in line for line in result.stderr.splitlines()), result.stderr


@pytest.mark.e2e
def test_ac14_with_no_backup_no_sidecar_is_created(corpus: Any, tmp_path: Path) -> None:
    subject = tmp_path / "nobak.pdf"
    shutil.copy(corpus.path("single_page"), subject)
    original = subject.read_bytes()
    result = run_cli(
        "encrypt",
        str(subject),
        "--owner-password-file",
        str(_password_file(tmp_path)),
        "--in-place",
        "--no-backup",
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "nobak.pdf.bak").exists()
    assert subject.read_bytes() != original


@pytest.mark.e2e
def test_ac14_no_password_material_reaches_disk_and_no_temp_survives(
    corpus: Any, tmp_path: Path
) -> None:
    """Every file created under the target directory and $TMPDIR during the
    run is scanned for the sentinel, and no `.pdftoolkit-*` temp survives."""
    sentinel = "Sentinel-PW-7f3a91c4e85b4d02"
    workspace = tmp_path / "work"
    workspace.mkdir()
    source = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), source)
    pw = _password_file(workspace, "pw.txt", sentinel)

    env, roots = redirected_environment(tmp_path)
    result = run_cli(
        "encrypt",
        str(source),
        "--owner-password-file",
        str(pw),
        "-O",
        str(workspace / "out.pdf"),
        env=env,
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr

    scanned = 0
    for root in (workspace, *roots):
        for path in Path(root).rglob("*"):
            if not path.is_file() or path == pw:
                continue
            scanned += 1
            assert sentinel.encode() not in path.read_bytes(), f"{path} carries the password"
            assert not path.name.startswith(".pdftoolkit-"), f"stray temp {path}"
    assert scanned > 0, "the residue scan looked at nothing"


# --------------------------------------------------------------------------- #
# AC15 / AC20 -- `--dry-run` predicts what it can, states what it cannot,
# and reads nothing
# --------------------------------------------------------------------------- #


def _dry(verb: str, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> Any:
    result = run_cli(verb, "--dry-run", *args, "-o", "json", env=env or _clean_env(), cwd=cwd)
    return result


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["encrypt", "decrypt", "permissions"])
def test_ac15_dry_run_is_pure_and_reads_no_password(corpus: Any, tmp_path: Path, verb: str) -> None:
    sentinel = "Sentinel-PW-7f3a91c4e85b4d02"
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace, "pw.txt", sentinel)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    encrypted = workspace / "enc.pdf"
    _encrypt(plain, encrypted, pw, allow=frozenset({"print"}))

    if verb == "encrypt":
        args = [str(plain), "--owner-password-file", str(pw), "-O", str(workspace / "out.pdf")]
    elif verb == "decrypt":
        args = [str(encrypted), "--password-file", str(pw), "-O", str(workspace / "out.pdf")]
    else:
        args = [str(encrypted), "--password-file", str(pw)]

    # The password file is made UNREADABLE before the dry run. A run that
    # opened it would fail; a run that only stat()ed it cannot tell.
    pw.chmod(0o000)
    env, roots = redirected_environment(tmp_path)
    env["PDF_TOOLKIT_PASSWORD"] = sentinel
    env["PDF_TOOLKIT_OWNER_PASSWORD"] = sentinel
    before = snapshot(workspace, *roots)
    try:
        result = _dry(verb, *args, env=env, cwd=workspace)
        # Snapshot INSIDE the try, before the mode is restored: restoring 0600
        # is itself a filesystem change, and taking `after` afterwards would
        # make this test fail on its own cleanup rather than on the product.
        after = snapshot(workspace, *roots)
    finally:
        pw.chmod(0o600)

    assert result.returncode == 0, result.stdout + result.stderr
    assert_unchanged(before, after)
    assert not list(workspace.glob(".pdftoolkit-*"))
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr

    detail = json.loads(result.stdout)["items"][0]["detail"]
    key = "owner_password_source" if verb == "encrypt" else "password_source"
    assert detail[key] == f"file:{pw}"
    assert detail["password_verified"] is False


@pytest.mark.e2e
def test_ac20a_an_occupied_target_is_predicted_character_identically(
    corpus: Any, tmp_path: Path
) -> None:
    """X-67 / C15. The dry run's ``would_refuse`` payload is the SAME object
    the real run renders -- compared with ``json.dumps`` so key ORDER counts,
    not merely key set.

    **AC20(a)'s "the dry run's process exit is 0" sub-clause is deliberately
    not asserted here.** Ruling X-116 settles it: ten producing verbs already
    exit non-zero under ``--dry-run`` when predicting a refusal, because
    ``models.RunResult.exit_code`` aggregates the highest non-ok item code;
    X-67 stands as doctrine, the behaviour violates it, `[B-054]` was accepted
    anyway, and **B-025 remains open and remains the operator's** to settle
    before v1.0.0 freezes exit codes. Correcting it here would be a per-verb
    divergence from a uniform-and-central behaviour, which is strictly worse
    than the state B-054 replaced. The dry/real pair is measured and reported
    as B-025 evidence instead.
    """
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    target = workspace / "occupied.pdf"
    seed = b"C15-SEEDED-BYTES"
    target.write_bytes(seed)

    args = [str(plain), "--owner-password-file", str(pw), "-O", str(target)]
    env, roots = redirected_environment(tmp_path)
    before = snapshot(workspace, *roots)
    dry = _dry("encrypt", *args, env=env, cwd=workspace)
    assert_unchanged(before, snapshot(workspace, *roots))
    assert target.read_bytes() == seed

    item = json.loads(dry.stdout)["items"][0]
    assert item["detail"]["would_exit"] == 5
    assert item["detail"]["planned_refusal"] == "TargetExistsError"

    real = run_cli("encrypt", *args, "-o", "json", env=env, cwd=workspace)
    assert real.returncode == 5, real.stdout + real.stderr
    real_error = json.loads(real.stdout)["error"]

    assert json.dumps(item["detail"]["would_refuse"]) == json.dumps(real_error), (
        "the predicted payload is not character-identical to the real refusal"
    )
    # B-025 evidence, recorded rather than asserted as doctrine.
    assert dry.returncode == real.returncode == 5


@pytest.mark.e2e
def test_ac20b_an_unwritable_destination_is_predicted_as_exit_1(
    corpus: Any, tmp_path: Path
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    locked = workspace / "locked"
    locked.mkdir()

    args = [str(plain), "--owner-password-file", str(pw), "-O", str(locked / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    locked.chmod(0o500)
    try:
        dry = _dry("encrypt", *args, env=env, cwd=workspace)
        real = run_cli("encrypt", *args, env=env, cwd=workspace)
    finally:
        locked.chmod(0o700)

    assert json.loads(dry.stdout)["items"][0]["detail"]["would_exit"] == 1
    assert real.returncode == 1


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["encrypt", "decrypt"])
def test_ac20c_resolvability_is_predicted_without_reading_anything(
    corpus: Any, tmp_path: Path, verb: str
) -> None:
    """Decidable from EXISTENCE alone: no flag, the variable absent from the
    environment, stdin not a TTY. No secret enters the process to decide it."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    encrypted = workspace / "enc.pdf"
    _encrypt(plain, encrypted, pw, allow=frozenset({"print"}))

    source = plain if verb == "encrypt" else encrypted
    args = [str(source), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry = _dry(verb, *args, env=env, cwd=workspace)

    detail = json.loads(dry.stdout)["items"][0]["detail"]
    assert detail["would_exit"] == 6
    assert detail["planned_refusal"] == "AuthError"
    assert detail["would_refuse"]["kind"] == "auth"

    real = run_cli(verb, *args, env=env, cwd=workspace)
    assert real.returncode == 6


@pytest.mark.e2e
def test_ac20d_correctness_is_not_predicted_because_a_preview_is_not_an_oracle(
    corpus: Any, tmp_path: Path
) -> None:
    """The subtle one. With a WRONG password supplied, the dry run must NOT
    say so: predicting it would mean reading the secret inside the planning
    path AND rendering a machine-readable field that distinguishes a right
    password from a wrong one into `-o json` plans that land in CI artifacts.

    The limit is STATED in the payload (``password_verified: false``) rather
    than left silent -- which is the whole difference between honouring X-67
    and re-committing X-89.

    **PDF-18 Design D7 -- unchanged and pinned, not "fixed".** The separating
    rule between this carve-out and `d231fbcec4` (AC16 above) is
    DECIDABILITY, not agreement: correctness requires attempting the
    decrypt, so it is undecidable at plan time and X-67 permits omitting it;
    directory writability is one ``os.access`` call, so it was decidable all
    along and PDF-18 closes the gap. A future reader who sees this test
    still asserting ``dry 0 / real 6`` after PDF-18 landed should read §D7
    before "fixing" it -- that would re-commit X-89.
    """
    workspace = tmp_path / "work"
    workspace.mkdir()
    good = _password_file(workspace, "good.pw")
    bad = _password_file(workspace, "bad.pw", OTHER_PW)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    encrypted = workspace / "enc.pdf"
    _encrypt(plain, encrypted, good, allow=frozenset({"print"}))

    args = [str(encrypted), "--password-file", str(bad), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry = _dry("decrypt", *args, env=env, cwd=workspace)
    assert dry.returncode == 0, dry.stdout + dry.stderr

    detail = json.loads(dry.stdout)["items"][0]["detail"]
    assert detail["would_exit"] == 0, "a wrong password must not be predicted"
    assert detail["password_verified"] is False
    assert detail["password_source"] == f"file:{bad}"
    assert "planned_refusal" not in detail

    # ...and the real run does refuse, which is what makes the omission a
    # deliberate limit rather than a missing check.
    real = run_cli("decrypt", *args, env=env, cwd=workspace)
    assert real.returncode == 6


# --------------------------------------------------------------------------- #
# PDF-18 AC16/AC17 -- `d231fbcec4`: the crypto refusal ladder now evaluates
# tiers in the SAME order under `--dry-run` as on a real run.
#
# Before PDF-18 unified the eight `ops/_plan_filesystem` copies, `encrypt`'s
# and `decrypt`'s own filesystem-tier check ran the writer-tier writability
# check only under `if policy.dry_run and out_dir is None:` -- a real run's
# guard was always false, so the check was SKIPPED, and the password-
# resolvability tier answered first instead: dry `1` (`DestinationUnwritableError`)
# vs real `6` (`AuthError`) for `encrypt`, dry `1` vs real `4`
# (`NoInputError`) for `decrypt`. `safety.atomic.plan_filesystem` now checks
# writability in BOTH modes unconditionally, so the real run raises AT the
# filesystem tier -- before the password loop is ever reached -- exactly
# like the dry run already predicted.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_pdf18_ac16_encrypt_ladder_agrees_on_an_unwritable_destination_with_no_password(
    corpus: Any, tmp_path: Path
) -> None:
    """`fa5736f2ae`/`d231fbcec4` red at HEAD `2d19bcb`: dry `1` / real `6`."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")
    workspace = tmp_path / "work"
    workspace.mkdir()
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    locked = workspace / "locked"
    locked.mkdir()

    # NO --owner-password-file, no env var, non-TTY: the password tier is
    # unresolvable -- exactly the SECOND tier that used to answer once the
    # filesystem check was skipped on a real run.
    args = [str(plain), "-O", str(locked / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    locked.chmod(0o500)
    try:
        dry, real = dry_and_real("encrypt", args, cwd=workspace, env=env)
    finally:
        locked.chmod(0o700)

    dry_detail = prediction(dry.stdout)
    assert dry_detail["would_exit"] == 1
    assert dry_detail["would_refuse"]["kind"] == "failure"
    assert real.returncode == 1, real.stdout + real.stderr
    assert dry.returncode == real.returncode == 1
    envelope = real_envelope(real.stdout)
    assert envelope is not None, "an empty -o json stdout is fa5736f2ae's own shape"
    assert envelope["error"]["kind"] == "failure"
    assert "Traceback (most recent call last)" not in real.stderr


@pytest.mark.e2e
def test_pdf18_ac16_decrypt_ladder_agrees_on_an_unwritable_destination_over_an_unencrypted_document(
    corpus: Any, tmp_path: Path
) -> None:
    """`d231fbcec4` red at HEAD `2d19bcb`: dry `1` / real `4`."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")
    workspace = tmp_path / "work"
    workspace.mkdir()
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    locked = workspace / "locked"
    locked.mkdir()

    args = [str(plain), "-O", str(locked / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    locked.chmod(0o500)
    try:
        dry, real = dry_and_real("decrypt", args, cwd=workspace, env=env)
    finally:
        locked.chmod(0o700)

    dry_detail = prediction(dry.stdout)
    assert dry_detail["would_exit"] == 1
    assert real.returncode == 1, real.stdout + real.stderr
    assert dry.returncode == real.returncode == 1


@pytest.mark.e2e
def test_pdf18_ac17_unwritable_with_a_resolvable_password_still_refuses_at_exit_1(
    corpus: Any, tmp_path: Path
) -> None:
    """Green control (a). A fix that reddens this one has broken the ladder
    rather than reordered it -- `plan_filesystem` must still answer FIRST,
    ahead of a perfectly good password."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    locked = workspace / "locked"
    locked.mkdir()

    args = [str(plain), "--owner-password-file", str(pw), "-O", str(locked / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    locked.chmod(0o500)
    try:
        real = run_cli("encrypt", *args, env=env, cwd=workspace)
    finally:
        locked.chmod(0o700)
    assert real.returncode == 1, real.stdout + real.stderr


@pytest.mark.e2e
def test_pdf18_ac17_writable_with_no_password_still_predicts_and_raises_auth(
    corpus: Any, tmp_path: Path
) -> None:
    """Green control (b), re-verified after the fix: `encrypt 6 == 6`,
    `decrypt 6 == 6` when the destination is writable -- unchanged behaviour,
    already proven by `test_ac20c_resolvability_is_predicted_without_reading_anything`;
    re-asserted here beside its siblings so the three-control story is
    visible in one place."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)

    args = [str(plain), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry, real = dry_and_real("encrypt", args, cwd=workspace, env=env)
    assert prediction(dry.stdout)["would_exit"] == 6
    assert real.returncode == 6
    assert dry.returncode == real.returncode == 6


@pytest.mark.e2e
def test_pdf18_ac17_writable_and_unencrypted_still_predicts_and_raises_not_encrypted(
    corpus: Any, tmp_path: Path
) -> None:
    """Green control (c), re-verified after the fix: `decrypt 4 == 4` over an
    unencrypted document with a writable destination -- the document tier
    fires before the password tier is ever reached, unaffected by the
    filesystem-tier widening."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    pw = _password_file(workspace)

    args = [str(plain), "--password-file", str(pw), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry, real = dry_and_real("decrypt", args, cwd=workspace, env=env)
    assert prediction(dry.stdout)["would_exit"] == 4
    assert real.returncode == 4
    assert dry.returncode == real.returncode == 4


# --------------------------------------------------------------------------- #
# PDF-18 AC19 -- `ops/crypto.py:315`'s "every tier is evaluated identically
# in both modes" is asserted MECHANICALLY: one stimulus per `_plan` tier,
# each arming only that tier, each measured `dry == real`.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_pdf18_ac19_tier1_pre_refusal_agrees_in_both_modes(corpus: Any, tmp_path: Path) -> None:
    """Tier 1: the invocation-shape refusal (`encrypt --in-place` without a
    backup choice, AC14's own gate) -- exit 5, computed by the CLI layer
    before `_plan` is ever called, so it is evaluated identically in both
    modes by construction."""
    subject = tmp_path / "inplace.pdf"
    shutil.copy(corpus.path("single_page"), subject)
    pw = _password_file(tmp_path)
    args = [str(subject), "--owner-password-file", str(pw), "--in-place"]
    dry = run_cli("encrypt", "--dry-run", *args, "-o", "json", env=_clean_env())
    real = run_cli("encrypt", *args, "-o", "json", env=_clean_env())
    assert prediction(dry.stdout)["would_exit"] == 5
    assert real.returncode == 5
    assert dry.returncode == real.returncode == 5


@pytest.mark.e2e
def test_pdf18_ac19_tier2_filesystem_agrees_in_both_modes(corpus: Any, tmp_path: Path) -> None:
    """Tier 2: the filesystem tier, isolated -- writable destination is the
    ONE thing this test perturbs, so this is `test_ac20b`'s own arm cited as
    AC19's tier-2 stimulus (an unwritable destination with a resolvable
    password reaches the filesystem tier and nothing beyond it)."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    locked = workspace / "locked"
    locked.mkdir()

    args = [str(plain), "--owner-password-file", str(pw), "-O", str(locked / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    locked.chmod(0o500)
    try:
        dry, real = dry_and_real("encrypt", args, cwd=workspace, env=env)
    finally:
        locked.chmod(0o700)
    assert prediction(dry.stdout)["would_exit"] == 1
    assert real.returncode == 1
    assert dry.returncode == real.returncode == 1


@pytest.mark.e2e
def test_pdf18_ac19_tier3_document_refusal_agrees_in_both_modes(
    corpus: Any, tmp_path: Path
) -> None:
    """Tier 3: `document_refusal` -- `decrypt` over an unencrypted document,
    writable destination, isolated from both the filesystem tier (writable)
    and the password tier (the document tier answers first regardless of
    whether a password was ever supplied)."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)

    args = [str(plain), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry, real = dry_and_real("decrypt", args, cwd=workspace, env=env)
    assert prediction(dry.stdout)["would_exit"] == 4
    assert real.returncode == 4
    assert dry.returncode == real.returncode == 4


@pytest.mark.e2e
def test_pdf18_ac19_tier4_password_resolvability_agrees_in_both_modes(
    corpus: Any, tmp_path: Path
) -> None:
    """Tier 4: password resolvability, isolated -- writable destination,
    document tier clean (already encrypted, for `decrypt`), no password
    supplied. This is `test_ac20c`'s own arm, cited as AC19's tier-4
    stimulus rather than re-derived."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    plain = workspace / "in.pdf"
    shutil.copy(corpus.path("single_page"), plain)
    encrypted = workspace / "enc.pdf"
    _encrypt(plain, encrypted, pw, allow=frozenset({"print"}))

    args = [str(encrypted), "-O", str(workspace / "out.pdf")]
    env, _roots = redirected_environment(tmp_path)
    dry, real = dry_and_real("decrypt", args, cwd=workspace, env=env)
    assert prediction(dry.stdout)["would_exit"] == 6
    assert real.returncode == 6
    assert dry.returncode == real.returncode == 6


# --------------------------------------------------------------------------- #
# AC19 -- OR-3, proven on the side C14 cannot: `permissions` creates NOTHING
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("flag", "extra"),
    [
        ("--output", ["-O", "report.json"]),
        ("--out-dir", ["--out-dir", "reports"]),
        ("--name", ["--name", "r-{index}.{ext}"]),
        ("--in-place", ["--in-place"]),
    ],
)
def test_ac19_permissions_refuses_every_output_flag_and_creates_nothing(
    corpus: Any, tmp_path: Path, flag: str, extra: list[str]
) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    before = snapshot(workspace)
    result = run_cli(
        "permissions", str(corpus.path("single_page")), *extra, env=_clean_env(), cwd=workspace
    )
    assert result.returncode == 2, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "permissions" in combined
    assert flag in combined
    assert_unchanged(before, snapshot(workspace))
    assert not (workspace / "report.json").exists()


def test_ac19_the_three_verbs_declare_what_the_ruling_says_they_declare() -> None:
    from pdf_toolkit.cli.common import consumed_output_flags

    assert consumed_output_flags("pdf_toolkit.cli.cmd_encrypt") == ("--output", "--in-place")
    assert consumed_output_flags("pdf_toolkit.cli.cmd_decrypt") == ("--output", "--in-place")
    assert consumed_output_flags("pdf_toolkit.cli.cmd_permissions") == ()


def test_ac19_each_verb_lives_in_its_own_cmd_module() -> None:
    """The OR-3 registry is keyed by MODULE
    (``_CONSUMES_BY_MODULE[func.__module__]``), so three decorators in one
    file would silently overwrite each other, last one winning, and the
    assertions above would all report `permissions`' empty tuple while each
    verb's runtime closure stayed correct -- an invisible OR-3 hole. PDF-12
    hit exactly this. This test is what stops a later tidy-up from re-merging
    the three files.
    """
    from pdf_toolkit.cli import cmd_decrypt, cmd_encrypt, cmd_permissions

    modules = {
        cmd_encrypt.encrypt_command.__module__,
        cmd_decrypt.decrypt_command.__module__,
        cmd_permissions.permissions_command.__module__,
    }
    assert len(modules) == 3, modules


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["encrypt", "decrypt"])
def test_ac19_a_declared_pair_genuinely_produces_a_file(
    corpus: Any, tmp_path: Path, verb: str
) -> None:
    """C14's honoured side asserts *some* new file appeared under `tmp_path`,
    which its own row builders also create files in. This arm closes that gap
    for PDF-13's own `--in-place` cells by asserting the INPUT's bytes changed
    -- something only the verb can do.
    """
    workspace = tmp_path / "work"
    workspace.mkdir()
    pw = _password_file(workspace)
    subject = workspace / "subject.pdf"
    if verb == "encrypt":
        shutil.copy(corpus.path("single_page"), subject)
        args = [str(subject), "--owner-password-file", str(pw), "--in-place", "--no-backup"]
    else:
        plain = workspace / "plain.pdf"
        shutil.copy(corpus.path("single_page"), plain)
        _encrypt(plain, subject, pw, allow=frozenset({"print"}))
        args = [str(subject), "--password-file", str(pw), "--in-place", "--no-backup"]
    original = subject.read_bytes()

    result = run_cli(verb, *args, env=_clean_env(), cwd=workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert subject.read_bytes() != original, "--in-place was declared but nothing changed"
