"""Hide a system engine binary from a CHILD process — the shared instrument.

Promoted out of ``tests/integration/test_ocr.py`` (B-096) once a second module
needed it: the OR-7 ``dry == real`` mirror is a **cross-verb** contract covering
both system-binary verbs (``ocr``/tesseract and ``convert``/soffice), so the
hiding mechanism can no longer live inside one verb's own test module.

Hiding means ``shutil.which`` → ``None`` — a PATH that EXCLUDES the real
binary's directory — and never a shadowing shim. That distinction is the whole
point and is load-bearing: a shim that exists but fails makes the engine
*present but broken*, which is D12.2's explicit **carve-out** row (dry 0 / real
non-zero, correct and not a defect), i.e. silently a different contract than the
*absent* row (dry 3 / real 3) this instrument exists to probe.

``conftest.py::_apply_engine_hiding_shim`` does the same thing for the
``PDF_TOOLKIT_TEST_HIDE_ENGINES`` env var, but mutates the CURRENT (pytest)
process's own ``os.environ["PATH"]`` — right for collection-time
``requires(engine)`` skips, wrong here: this helper returns an env dict for a
CHILD process without touching the test process's PATH, which every other test
in the session still depends on.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = ["hidden_engine_env"]


def hidden_engine_env(hidden: str, *, tmp_path: Path) -> dict[str, str]:
    """An environment whose PATH resolves everything EXCEPT *hidden*.

    Every executable reachable on the current PATH is symlinked into a fresh
    directory under *tmp_path* except the named one, and PATH is repointed
    there. No system binary is ever renamed, moved or chmod-ed (AC13).

    The returned env is asserted to actually hide *hidden* before it is handed
    back, so a probe built on it can never be silently blind.
    """
    shim_dir = tmp_path / f"hide-{hidden}"
    shim_dir.mkdir(exist_ok=True)
    original_path = os.environ.get("PATH", "")
    for entry in original_path.split(os.pathsep):
        entry_path = Path(entry)
        if not entry_path.is_dir():
            continue
        try:
            candidates = list(entry_path.iterdir())
        except OSError:
            continue
        for exe in candidates:
            if exe.name == hidden:
                continue
            link = shim_dir / exe.name
            if link.exists():
                continue
            try:
                link.symlink_to(exe)
            except OSError:
                continue
    env = dict(os.environ)
    env["PATH"] = str(shim_dir)
    # The instrument proves itself before its result is trusted: a shim that
    # still resolves `hidden` would probe the carve-out row, not the absent one.
    assert shutil.which(hidden, path=env["PATH"]) is None, f"{hidden} is still on the shimmed PATH"
    return env
