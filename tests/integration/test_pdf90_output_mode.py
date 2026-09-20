"""PDF-90 — the output mode posture, decided: PRESERVE.

`safety/paths.py`'s own `UNREADABLE_MESSAGE` comment used to claim *"this
product does not change a mode bit"*. It was false: `tempfile.NamedTemporaryFile`
creates every temp at `0600` and `os.replace` carries that inode's mode onto the
destination, so an overwrite rewrote the destination's mode, a read-only target
gained back the owner write bit, and under `--in-place` the `.bak` sidecar
(linked or `copy2`'d from the ORIGINAL inode, before the replace) kept the
original mode while the file it backs up did not.

The ruling (`X-911`) is (B), PRESERVE: an overwrite keeps the destination's own
nine permission bits, and a destination that did not exist is created at
`0666 & ~umask` — what a shell redirect would have produced. `setuid`, `setgid`
and `sticky` are never carried. The `.bak` sidecar was already right on both of
its own paths and is not touched by this item; the ruling makes the destination
come to agree with it.

Every arm here is driven through the real CLI, in a subprocess, so the umask
and the mode landing on disk are both genuine kernel behaviour rather than an
in-process assertion about an argument passed to `os.chmod`. `compress` is the
one verb used throughout: it touches no external engine, so this module joins
no engine-gating population (`tests/test_engine_gating_census.py` only ever
counts `convert`/`ocr` node ids) — a property this module preserves
deliberately rather than by accident.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import _password_file, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

OK = 0


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _run_under_umask(
    umask_value: int, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> Any:
    """`tests/integration/test_purity_primitive.py:480-489`'s own idiom,
    copied rather than re-derived: a chosen umask around `run_cli`, restored
    in a `finally` regardless of outcome. `run_cli` takes no `umask=` keyword
    on purpose (`registry.py` is a census-bearing module) — the child
    inherits whatever the parent's umask is at fork/exec time, which is
    exactly what setting it here, before the subprocess call, produces."""
    previous = os.umask(umask_value)
    try:
        return run_cli(*args, cwd=cwd, env=env)
    finally:
        os.umask(previous)


def _fresh_source(corpus: Any, tmp_path: Path, name: str = "in.pdf") -> Path:
    source = tmp_path / name
    shutil.copy(corpus.path("single_page"), source)
    return source


def _clean_password_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PDF_TOOLING_PASSWORD", None)
    env.pop("PDF_TOOLING_OWNER_PASSWORD", None)
    return env


# --------------------------------------------------------------------------- #
# AC2 — a fresh destination is created at 0666 & ~umask.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("umask_value", "expected"),
    [(0o002, 0o664), (0o022, 0o644)],
    ids=["umask-002", "umask-022"],
)
def test_ac2_a_fresh_destination_is_created_at_0666_and_umask(
    corpus: Any, tmp_path: Path, umask_value: int, expected: int
) -> None:
    source = _fresh_source(corpus, tmp_path)
    target = tmp_path / "fresh.pdf"
    result = _run_under_umask(
        umask_value, "compress", str(source), "-O", str(target), "-o", "json", cwd=tmp_path
    )
    assert result.returncode == OK, result.stderr
    assert _mode(target) == expected, (
        f"umask {oct(umask_value)}: a fresh create landed at {oct(_mode(target))}, "
        f"expected {oct(expected)} (0o666 & ~umask)"
    )


def test_ac2_umask_077_fresh_create_is_a_negative_control(corpus: Any, tmp_path: Path) -> None:
    """The NEGATIVE CONTROL, named as one rather than left to be mistaken for
    a third positive cell. `0o600` is ALSO the pre-fix defect's own answer
    under `umask 077`, so this cell cannot discriminate the fix from the
    defect it replaces — `tests/integration/test_purity_primitive.py:472`'s
    own docstring records this product being bitten by exactly this vacuity
    once already, on a different control. It is retained and labelled rather
    than dropped, because silently omitting the cell that cannot discriminate
    is how the NEXT vacuous control goes unnoticed."""
    source = _fresh_source(corpus, tmp_path)
    target = tmp_path / "fresh.pdf"
    result = _run_under_umask(
        0o077, "compress", str(source), "-O", str(target), "-o", "json", cwd=tmp_path
    )
    assert result.returncode == OK, result.stderr
    assert _mode(target) == 0o600


# --------------------------------------------------------------------------- #
# AC3 — an overwrite preserves the destination's nine permission bits.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "umask_value", [0o002, 0o022, 0o077], ids=["umask-002", "umask-022", "umask-077"]
)
@pytest.mark.parametrize("pre_existing_mode", [0o664, 0o600], ids=["pre-0664", "pre-0600"])
def test_ac3_an_overwrite_preserves_the_destinations_nine_bits(
    corpus: Any, tmp_path: Path, pre_existing_mode: int, umask_value: int
) -> None:
    source = _fresh_source(corpus, tmp_path)
    target = tmp_path / "dest.pdf"
    target.write_bytes(b"")
    target.chmod(pre_existing_mode)

    result = _run_under_umask(
        umask_value, "compress", str(source), "-f", "-O", str(target), "-o", "json", cwd=tmp_path
    )
    assert result.returncode == OK, result.stderr
    assert _mode(target) == pre_existing_mode, (
        f"pre-existing {oct(pre_existing_mode)} under umask {oct(umask_value)}: landed at "
        f"{oct(_mode(target))} instead of being preserved"
    )


# --------------------------------------------------------------------------- #
# AC4 — a 0400 destination stays 0400: no bit the owner removed comes back.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "umask_value", [0o002, 0o022, 0o077], ids=["umask-002", "umask-022", "umask-077"]
)
def test_ac4_a_read_only_destination_stays_read_only(
    corpus: Any, tmp_path: Path, umask_value: int
) -> None:
    """`X-911` rules `0o400 -> 0o600` indefensible under EITHER posture, so
    this arm's own failure message names the OWNER-WRITE bit specifically —
    the same `0o600`-unconditionally mutation that reddens AC3 also reddens
    this cell, and a reader comparing the two failure messages must be able
    to tell them apart (AC4's own text)."""
    source = _fresh_source(corpus, tmp_path)
    target = tmp_path / "ro.pdf"
    target.write_bytes(b"")
    target.chmod(0o400)

    result = _run_under_umask(
        umask_value, "compress", str(source), "-f", "-O", str(target), "-o", "json", cwd=tmp_path
    )
    assert result.returncode == OK, result.stderr
    assert _mode(target) == 0o400, (
        f"umask {oct(umask_value)}: a 0o400 destination landed at {oct(_mode(target))} -- "
        "the owner write bit the owner had removed was added back"
    )


# --------------------------------------------------------------------------- #
# AC5 — setuid, setgid and sticky are not carried.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "pre_existing_mode",
    [0o2664, 0o4664, 0o1664],
    ids=["setgid-2664", "setuid-4664", "sticky-1664"],
)
def test_ac5_special_bits_are_not_carried(
    corpus: Any, tmp_path: Path, pre_existing_mode: int
) -> None:
    source = _fresh_source(corpus, tmp_path)
    target = tmp_path / "dest.pdf"
    target.write_bytes(b"")
    target.chmod(pre_existing_mode)

    result = run_cli("compress", str(source), "-f", "-O", str(target), "-o", "json", cwd=tmp_path)
    assert result.returncode == OK, result.stderr
    assert _mode(target) == 0o664, (
        f"pre-existing {oct(pre_existing_mode)} landed at {oct(_mode(target))}, "
        "expected the special bits stripped down to 0o664"
    )


# --------------------------------------------------------------------------- #
# AC6 — --in-place leaves the target and its .bak at the SAME mode, and it is
# the pre-run mode.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pre_existing_mode", [0o664, 0o400], ids=["pre-0664", "pre-0400"])
def test_ac6_in_place_target_and_sidecar_share_the_pre_run_mode(
    corpus: Any, tmp_path: Path, pre_existing_mode: int
) -> None:
    target = tmp_path / "t.pdf"
    shutil.copy(corpus.path("single_page"), target)
    target.chmod(pre_existing_mode)

    result = run_cli("compress", str(target), "--in-place", "-o", "json", cwd=tmp_path)
    assert result.returncode == OK, result.stderr

    sidecar = tmp_path / "t.pdf.bak"
    target_mode = _mode(target)
    sidecar_mode = _mode(sidecar)
    assert target_mode == sidecar_mode == pre_existing_mode, (
        f"pre-run mode {oct(pre_existing_mode)}: target ended {oct(target_mode)}, "
        f"sidecar ended {oct(sidecar_mode)} -- both must equal each other AND the "
        "pre-run mode, not merely agree by coincidence"
    )


# --------------------------------------------------------------------------- #
# AC7 — encrypt --in-place -y never leaves the plaintext sidecar more
# permissive than the ciphertext.
# --------------------------------------------------------------------------- #


def test_ac7_encrypt_in_place_leaves_ciphertext_and_plaintext_sidecar_equal(
    corpus: Any, tmp_path: Path
) -> None:
    """`README.md:217`'s own paragraph exists because the `.bak` sidecar of
    `encrypt --in-place` is a security object: at `f2abeb1` the ciphertext
    landed `0o600` while the plaintext sidecar stayed `0o664`, so the
    plaintext copy was STRICTLY MORE ACCESSIBLE than the AES-256 ciphertext
    beside it. Under PRESERVE both are `0o664` -- equal, never the plaintext
    ahead."""
    subject = tmp_path / "secret.pdf"
    shutil.copy(corpus.path("single_page"), subject)
    subject.chmod(0o664)
    owner_password = _password_file(tmp_path, "owner.txt", "swordfish")

    result = run_cli(
        "encrypt",
        str(subject),
        "--owner-password-file",
        str(owner_password),
        "--in-place",
        "-y",
        "-o",
        "json",
        cwd=tmp_path,
        env=_clean_password_env(),
    )
    assert result.returncode == OK, result.stderr

    sidecar = tmp_path / "secret.pdf.bak"
    ciphertext_mode = _mode(subject)
    sidecar_mode = _mode(sidecar)
    assert ciphertext_mode == sidecar_mode == 0o664, (
        f"ciphertext ended {oct(ciphertext_mode)}, plaintext sidecar ended "
        f"{oct(sidecar_mode)} -- the plaintext copy must never be more accessible "
        "than the ciphertext it backs up"
    )


# --------------------------------------------------------------------------- #
# AC11 — directory modes are untouched.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("umask_value", "expected_dir"),
    [(0o002, 0o775), (0o022, 0o755), (0o077, 0o700)],
    ids=["umask-002", "umask-022", "umask-077"],
)
def test_ac11_a_created_out_dir_keeps_its_umask_derived_mode(
    corpus: Any, tmp_path: Path, umask_value: int, expected_dir: int
) -> None:
    """`atomic.py:389`'s bare `resolved.mkdir(parents=True, exist_ok=True)`
    is untouched by this item -- a created `--out-dir` already answered
    `0o777 & ~umask` before PDF-90 and still does. The boundary this arm pins
    is "files", not "everything": this item's remedy must never chmod a
    directory."""
    source = _fresh_source(corpus, tmp_path)
    out_dir = tmp_path / "parts"
    result = _run_under_umask(
        umask_value,
        "split",
        str(source),
        "--each-page",
        "--out-dir",
        str(out_dir),
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert result.returncode == OK, result.stderr
    assert _mode(out_dir) == expected_dir, (
        f"umask {oct(umask_value)}: --out-dir landed at {oct(_mode(out_dir))}, "
        f"expected {oct(expected_dir)} -- unrelated to this item's diff"
    )
