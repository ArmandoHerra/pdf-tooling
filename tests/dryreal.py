"""The shared dry/real invocation pair — PDF-18 Design D8.

No dry/real pair helper existed at HEAD (`2d19bcb` / `882acb0`): the pattern
is written inline at nine-plus call sites (`tests/test_cli_contract.py`,
`tests/integration/test_or7_engine_absent.py`,
`tests/integration/test_or7_bulk_destructive.py`,
`tests/integration/test_crypto_roundtrip.py`,
`tests/integration/test_pages_cli.py`, `tests/integration/test_ocr.py`), and
the only NAMED one is module-local
(`tests/integration/test_text_tables_cli.py:364`'s own ``_dry_and_real``).

PDF-18 Design D8 creates exactly ONE new shared helper here, for its own
11 x 5 out-dir-planning matrix (`tests/integration/test_out_dir_planning.py`).
It does **not** refactor any of the existing inline pairs into it — widening
that blast radius is out of this spec's Scope, and every existing call site
keeps working exactly as it does today. If a later spec wants to consolidate
the rest, this is the module to consume.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

__all__ = ["dry_and_real", "prediction", "real_envelope"]


def dry_and_real(
    verb: str,
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Any, Any]:
    """Run *verb* once under ``--dry-run -o json`` and once for real, over the
    identical argv, and return ``(dry, real)`` as two
    ``subprocess.CompletedProcess`` objects.

    Both runs carry ``-o json`` so a caller can compare the STRUCTURED
    ENVELOPE, not only the exit code (X-185: an OR-7 ``dry == real`` claim is
    read as the exit code AND the envelope shape — a `fa5736f2ae`-shaped
    defect can agree on the integer while the real run's stdout is empty and
    its stderr carries a traceback, which is exactly the trap a
    code-only comparison misses).
    """
    dry = run_cli(verb, "--dry-run", *args, "-o", "json", cwd=cwd, env=env)
    real = run_cli(verb, *args, "-o", "json", cwd=cwd, env=env)
    return dry, real


#: How much of a failing dry run's ``stderr`` the empty-stdout message repeats.
#: The signal is almost always in the first few lines; the cap exists so a
#: verb that printed a megabyte of warnings cannot bury the assertion that
#: names it.
_STDERR_BUDGET = 800


def _stdout_of(dry: Any) -> str:
    """The captured stdout of *dry*, whether it IS the text or produced it.

    ``prediction()`` accepts either spelling (see its own docstring), so the
    unwrapping happens in exactly one place rather than at each guard.
    """
    if isinstance(dry, str):
        return dry
    return dry.stdout or ""


def _no_stdout_message(dry: Any, context: str | None) -> str:
    """Why a dry run printed nothing, in the terms the next reader needs.

    An empty ``-o json`` stdout is a `fa5736f2ae`-shaped finding, and its
    ACTUAL signal is almost always sitting in ``stderr`` — which a bare
    ``json.JSONDecodeError`` from ``json.loads("")`` discards entirely, along
    with the argv and the exit code. So this names the run: ``argv`` (and
    therefore the VERB), the ``returncode``, and the ``stderr`` — plus the
    CELL, when the caller labelled one.
    """
    label = f"{context}: " if context else ""
    if isinstance(dry, str):
        detail = (
            "called with bare stdout, so argv/returncode/stderr are not "
            "reachable from this call site; pass the CompletedProcess itself "
            "(`prediction(dry)`) to have them named here"
        )
    else:
        argv = getattr(dry, "args", None)
        rendered = (
            " ".join(str(part) for part in argv) if isinstance(argv, (list, tuple)) else str(argv)
        )
        stderr = (getattr(dry, "stderr", None) or "").strip()
        shown = stderr[:_STDERR_BUDGET]
        if len(stderr) > _STDERR_BUDGET:
            shown += " ...[truncated]"
        detail = (
            f"argv={rendered!r} returncode={getattr(dry, 'returncode', None)!r} stderr={shown!r}"
        )
    return (
        f"{label}the dry run produced NO STDOUT under `-o json` — {detail}. "
        "See `75447d838b` (this blindfold) / `a31cd2a739` (the flake it hid)."
    )


def prediction(dry: Any, *, index: int = 0, context: str | None = None) -> dict[str, Any]:
    """The dry run's own ``detail`` payload for item *index*.

    Accepts EITHER the ``str`` stdout or the ``CompletedProcess`` that
    ``dry_and_real()`` returns. The tolerant spelling is a scope decision, not
    a convenience: it lets the guard below protect every existing call site
    without editing one of them.

    TWO DISTINCT VACUITY CONDITIONS, KEPT DISTINGUISHABLE (`75447d838b`)
    -------------------------------------------------------------------
    This helper's docstring claimed a non-vacuity guard while ``json.loads``
    ran FIRST and unguarded, so on EMPTY stdout the assertion below could
    never be reached — the caller got a stdlib ``JSONDecodeError`` traceback
    with the argv, the exit code and the stderr all thrown away. That is the
    blindfold `a31cd2a739` was diagnosed through, and it cost a full
    re-investigation.

    The fix is the guard ``real_envelope()`` already carries twenty-two lines
    below (`fa5736f2ae`), NOT a merged message. The two conditions have
    completely different causes and stay separately worded:

      * ``""``              → "produced NO STDOUT", naming argv/rc/stderr/cell
      * ``'{"items": []}'`` → "produced no items to carry a prediction"

    A single message would answer *"there is no prediction"* without answering
    *"because the process printed nothing"* versus *"because it printed an
    empty batch"*.
    """
    dry_stdout = _stdout_of(dry)
    if not dry_stdout.strip():
        raise AssertionError(_no_stdout_message(dry, context))
    payload = json.loads(dry_stdout)
    items = payload["items"]
    assert items, "the dry run produced no items to carry a prediction"
    detail = items[index].get("detail")
    return dict(detail) if detail else {}


def real_envelope(real_stdout: str) -> dict[str, Any] | None:
    """Parse the real run's ``-o json`` stdout, or ``None`` when it is empty.

    Empty stdout under ``-o json`` is itself a finding (`fa5736f2ae`): a
    caller that needs to assert non-emptiness does so explicitly, rather
    than this helper raising ``json.JSONDecodeError`` on its behalf and
    hiding the real signal behind a traceback of its own.
    """
    if not real_stdout.strip():
        return None
    return json.loads(real_stdout)
