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


def prediction(dry_stdout: str, *, index: int = 0) -> dict[str, Any]:
    """The dry run's own ``detail`` payload for item *index*.

    Asserts the dry run actually produced an item to carry a prediction —
    the non-vacuity guard every prediction-reading helper in this suite
    carries (`test_text_tables_cli.py::_prediction`'s own precedent).
    """
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
