"""AC2 — `PLAN.md` §5.7's resolution chain, its conflicts, and the never-echo rule.

In-process against ``cli/password.py`` directly: the chain is deterministic
logic over a flag value, ``os.environ`` and ``stdin.isatty()``, none of which
needs a subprocess to exercise, so B-061's gate-duration budget pays for
subprocesses only where a real process is the only observer (the adversarial
proofs in ``tests/test_password_leaks.py``).

**The planning/reading split is what most of this module actually proves.**
:func:`plan_password` answers *"could a password be produced, and from
where"* from **existence alone** — never opening the file, never reading the
variable's value, never prompting. That is what makes ``--dry-run``'s exit-6
resolvability prediction possible without a secret entering the process, and
several tests below assert the negative directly by making a read explode.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from pdf_toolkit.cli.password import (
    ENV_OWNER_PASSWORD,
    ENV_PASSWORD,
    plan_password,
    reject_two_stdin_streams,
)
from pdf_toolkit.errors import UsageError

PW_SENTINEL = "Sentinel-PW-7f3a91c4e85b4d02"

SRC = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit"


def _pw_file(tmp_path: Path, name: str = "pw.txt", body: str = PW_SENTINEL) -> Path:
    path = tmp_path / name
    path.write_text(body)
    path.chmod(0o600)
    return path


class _FakeStdin:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _plan(value: str | None, **kwargs: object) -> object:
    defaults: dict[str, object] = {
        "slot": "password",
        "flag": "--password-file",
        "value": value,
        "env_names": (ENV_PASSWORD,),
        "prompt": "Password: ",
    }
    defaults.update(kwargs)
    return plan_password(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Order: file > stdin > env > prompt > nothing
# --------------------------------------------------------------------------- #


def test_ac2_a_file_beats_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PASSWORD, "from-the-environment")
    path = _pw_file(tmp_path)
    planned = _plan(str(path))
    assert planned.source == f"file:{path}"
    assert planned.read().reveal() == PW_SENTINEL


def test_ac2_stdin_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PASSWORD, "from-the-environment")
    assert _plan("-").source == "stdin"


def test_ac2_the_environment_is_used_when_no_flag_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_PASSWORD, PW_SENTINEL)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=True))
    planned = _plan(None)
    assert planned.source == f"env:{ENV_PASSWORD}"
    assert planned.read().reveal() == PW_SENTINEL


def test_ac2_the_owner_slot_reads_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PASSWORD, raising=False)
    monkeypatch.setenv(ENV_OWNER_PASSWORD, PW_SENTINEL)
    planned = _plan(None, slot="owner", env_names=(ENV_OWNER_PASSWORD,))
    assert planned.source == f"env:{ENV_OWNER_PASSWORD}"


def test_ac2_the_prompt_fires_only_on_a_tty_and_only_with_no_other_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(ENV_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=True))
    assert _plan(None).source == "prompt"

    # ...and never when a flag or the environment already supplied one.
    assert _plan(str(_pw_file(tmp_path))).source.startswith("file:")
    monkeypatch.setenv(ENV_PASSWORD, "x")
    assert _plan(None).source == f"env:{ENV_PASSWORD}"


def test_ac2_no_source_on_a_non_tty_is_unresolvable_which_is_exit_6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=False))
    planned = _plan(None)
    assert planned.source is None
    assert planned.read is None
    assert planned.resolvable is False


# --------------------------------------------------------------------------- #
# Planning reads NOTHING -- the property `--dry-run`'s exit-6 prediction rests on
# --------------------------------------------------------------------------- #


def test_ac2_planning_a_file_slot_never_opens_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _pw_file(tmp_path)

    def explode(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("plan_password opened the password file")

    monkeypatch.setattr(Path, "read_bytes", explode)
    planned = _plan(str(path))
    assert planned.source == f"file:{path}"


def test_ac2_planning_an_env_slot_never_reads_the_variables_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presence is consulted through ``in os.environ``; the value is not.

    Proven by making the mapping's ``__getitem__``/``get`` explode while
    leaving ``__contains__`` intact — the exact distinction the design rests
    on.
    """
    monkeypatch.setenv(ENV_PASSWORD, PW_SENTINEL)
    real_get = os.environ.get

    def explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("plan_password read the environment variable's VALUE")

    monkeypatch.setattr(os.environ, "get", explode)
    try:
        planned = _plan(None)
        assert planned.source == f"env:{ENV_PASSWORD}"
    finally:
        monkeypatch.setattr(os.environ, "get", real_get)


def test_ac2_planning_a_prompt_slot_never_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=True))

    def explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("plan_password prompted")

    monkeypatch.setattr("getpass.getpass", explode)
    assert _plan(None).source == "prompt"


# --------------------------------------------------------------------------- #
# Conflicts and usage errors -- every one of them exit 2
# --------------------------------------------------------------------------- #


def test_ac2_two_stdin_streams_is_a_usage_error() -> None:
    with pytest.raises(UsageError):
        reject_two_stdin_streams(["-", "-"])
    reject_two_stdin_streams(["-", "/tmp/pw"])
    reject_two_stdin_streams([None, None])


def test_ac2_a_value_that_is_not_a_readable_file_is_refused_without_echoing_it() -> None:
    """The never-echo rule. A typo'd path and a literal password are
    indistinguishable at this point, so the message names the FLAG."""
    with pytest.raises(UsageError) as caught:
        _plan(PW_SENTINEL, flag="--user-password-file")
    error = caught.value
    assert PW_SENTINEL not in error.message
    assert PW_SENTINEL not in str(error.path or "")
    assert PW_SENTINEL not in str(error.to_dict())
    assert "--user-password-file" in error.message
    assert error.redacted is True
    assert error.exit_code == 2


def test_ac2_a_directory_is_not_a_readable_file(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        _plan(str(tmp_path))


def test_ac2_the_prompt_is_asked_twice_and_a_mismatch_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_OWNER_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=True))
    answers = iter([PW_SENTINEL, "something-else"])
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(answers))
    planned = _plan(
        None,
        slot="owner",
        env_names=(ENV_OWNER_PASSWORD,),
        confirm_prompt="Owner password (again): ",
    )
    with pytest.raises(UsageError) as caught:
        planned.read()
    assert PW_SENTINEL not in caught.value.message


def test_ac2_a_matching_double_prompt_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_OWNER_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=True))
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: PW_SENTINEL)
    planned = _plan(
        None,
        slot="owner",
        env_names=(ENV_OWNER_PASSWORD,),
        confirm_prompt="Owner password (again): ",
    )
    assert planned.read().reveal() == PW_SENTINEL


def test_ac2_an_empty_owner_password_file_is_a_usage_error(tmp_path: Path) -> None:
    path = _pw_file(tmp_path, body="")
    planned = _plan(str(path), slot="owner", flag="--owner-password-file", allow_empty=False)
    with pytest.raises(UsageError):
        planned.read()


def test_ac2_an_empty_user_password_file_is_allowed(tmp_path: Path) -> None:
    path = _pw_file(tmp_path, body="")
    assert _plan(str(path), slot="user", allow_empty=True).read().reveal() == ""


# --------------------------------------------------------------------------- #
# Reading: the first line, and only the first line
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (PW_SENTINEL, PW_SENTINEL),
        (PW_SENTINEL + "\n", PW_SENTINEL),
        (PW_SENTINEL + "\r\n", PW_SENTINEL),
        (PW_SENTINEL + "\nsecond line\n", PW_SENTINEL),
        ("with trailing space  ", "with trailing space  "),
        ("  with leading space", "  with leading space"),
    ],
)
def test_ac2_only_a_single_trailing_newline_is_stripped(
    tmp_path: Path, body: str, expected: str
) -> None:
    """A password may legitimately end in a space, so nothing else is touched."""
    assert _plan(str(_pw_file(tmp_path, body=body))).read().reveal() == expected


def test_ac2_a_loose_mode_warns_and_recommends_chmod_600(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "loose.txt"
    path.write_text(PW_SENTINEL)
    path.chmod(0o644)
    with caplog.at_level("WARNING", logger="pdf_toolkit.cli.password"):
        _plan(str(path)).read()
    combined = caplog.text
    assert "chmod 600" in combined
    assert PW_SENTINEL not in combined


def test_ac2_more_than_one_line_warns_without_quoting_the_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _pw_file(tmp_path, body=f"{PW_SENTINEL}\nsecond line\n")
    with caplog.at_level("WARNING", logger="pdf_toolkit.cli.password"):
        _plan(str(path)).read()
    assert "using the first" in caplog.text
    assert PW_SENTINEL not in caplog.text
    assert "second line" not in caplog.text


def test_ac2_the_debug_record_names_the_source_and_never_the_length(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """AC4's positive control at unit level: the record EXISTS (so the
    subprocess grep cannot pass because logging was off) and carries the
    source label, the value's absence, and no length."""
    path = _pw_file(tmp_path)
    with caplog.at_level("DEBUG", logger="pdf_toolkit.cli.password"):
        _plan(str(path)).read()
    assert "password resolved from" in caplog.text
    assert f"file:{path}" in caplog.text
    assert PW_SENTINEL not in caplog.text
    # The LENGTH is a real, if small, leak. Asserted against each record's own
    # message rather than caplog's rendering, whose file/line prefix carries
    # unrelated digits ("password.py:283" contains "28").
    for record in caplog.records:
        message = record.getMessage()
        assert re.search(rf"\b{len(PW_SENTINEL)}\b", message) is None, message
        assert not re.search(r"\blen\b|\blength\b|characters\b", message, re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Structural
# --------------------------------------------------------------------------- #


def _calls_input(source: str) -> bool:
    """Whether *source* contains a real ``input(...)`` CALL, by AST.

    An AST walk rather than AC2's literal ``grep 'input('`` — **deviation
    with a reason, and the reason is that the grep fails on a correct
    implementation**: this module's own docstring documents the prohibition
    by naming the forbidden spelling, so a text search matches the sentence
    that promises the absence. That is X-121's harness lesson (validate a
    check against the code it must run over) reaching this file. The AST walk
    is strictly stronger: it matches a call and not a mention, and its own
    positive control below proves it can fail.
    """
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input"
        for node in ast.walk(tree)
    )


def test_ac2_input_is_never_called_in_the_password_module() -> None:
    """Only ``getpass``: ``input()`` echoes what is typed to the terminal."""
    text = (SRC / "cli" / "password.py").read_text()
    assert _calls_input(text) is False
    assert "getpass" in text


def test_ac2_the_input_check_can_actually_fail() -> None:
    """The positive control. A check that cannot go red is not a check —
    this cycle has found four of those (X-68, X-92, X-102, X-108)."""
    assert _calls_input("value = input('password: ')") is True
    assert _calls_input("# input('password: ') is forbidden") is False


def test_ac2_the_user_password_alias_conflict_is_now_unreachable() -> None:
    """`PLAN.md` §5.7 made ``--user-password-file`` + ``--user-password`` an
    exit-2 conflict. Ruling OR-4 / X-114 removed the second spelling
    altogether, so the conflict cannot be constructed: ``--user-password``
    is refused on its own, before any slot is planned. Asserted in
    ``tests/test_password_leaks.py`` (AC18); recorded here so the criterion
    reads as *superseded* rather than *dropped*."""
    from pdf_toolkit.cli.common import GLOBAL_OPTIONS, REFUSED_PASSWORD_FLAGS

    assert "--user-password" in REFUSED_PASSWORD_FLAGS
    assert "--user-password" not in GLOBAL_OPTIONS
