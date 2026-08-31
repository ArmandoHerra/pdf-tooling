"""``OfficeConverter`` adapter — the ``soffice`` (LibreOffice) binary.

The second of the two ports that can legitimately be absent. LibreOffice is
MPL-2.0, which ``PLAN.md`` §12 R-11 records as permitted: MPL is file-level
copyleft, this product neither modifies nor vendors it, and the licence gate's
deny pattern is ``AGPL|GPL|LGPL`` only.

Conversion itself arrives with the office spec. What matters here is that the
spawn goes through ``subprocess_util.run``: ``soffice`` starts a background
process of its own and is the second binary this product will drive, so the
process-**group** kill is the reason a converted-document timeout does not leave
an office daemon resident.
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING, Final

from pdf_toolkit.adapters import AdapterProbe, subprocess_util
from pdf_toolkit.errors import FailureError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

__all__ = ["ADAPTER", "BINARY", "PROBE_TIMEOUT_S", "SofficeOfficeAdapter", "binary_present"]

_NAME: Final[str] = "soffice"

#: A module-level string literal on purpose -- see the note on the same constant
#: in ``tesseract_ocr``: this is the shape the licence walk can resolve.
BINARY: Final[str] = "soffice"

#: LibreOffice's first start can be slow, but a *version* query is not a
#: conversion. Kept short so `doctor` stays fast, and generous enough that a cold
#: profile directory does not read as an absent engine.
PROBE_TIMEOUT_S: Final[float] = 20.0

_CAPABILITIES: Final[frozenset[str]] = frozenset({"office-convert", "to-pdf"})

#: ``LibreOffice 26.2.5.2 620(Build:2)`` -> ``26.2.5.2``.
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"([0-9]+(?:\.[0-9]+)+)")

#: PDF-15 (`convert`), Design §D6 -- the two SUBdirectories `convert_to_pdf`
#: creates under its caller's `scratch_dir`. LibreOffice creates both itself
#: on first use (verified empirically against LibreOffice 26.2.5.2: an
#: absent `-env:UserInstallation` directory AND an absent `--outdir` are
#: both bootstrapped by soffice without error) -- so neither is pre-created
#: here, matching `ScratchDir`'s own docstring.
_PROFILE_SUBDIR: Final[str] = "profile"
_OUTPUT_SUBDIR: Final[str] = "out"


def _parse_version(line: str) -> str | None:
    match = _VERSION_RE.search(line.strip())
    return match.group(1) if match else None


def binary_present() -> bool:
    """Is ``soffice`` on PATH? Answered WITHOUT spawning anything (B-096).

    This is the exact short-circuit :meth:`SofficeOfficeAdapter.probe` opens
    with, factored out so it has ONE call site in the codebase and the two
    cannot drift: ``probe()`` itself calls this, so "the engine is absent"
    means the same thing to a preview as it does to `doctor`.

    A ``--dry-run`` preview needs this and cannot use the full probe. Presence
    is all exit 3 turns on, but ``probe()``'s *version* query spawns ``soffice
    --version`` -- and that command **creates ``$HOME/.config``** (measured
    against LibreOffice 26.2.5.2), which would break the non-negotiable
    ``--dry-run`` purity rule (``CLAUDE.md`` rule 2, enforced by the C10
    contract row against a redirected ``HOME``). ``shutil.which`` writes
    nothing, so the absent case stays both predictable and pure.
    """
    return shutil.which(BINARY) is not None


class SofficeOfficeAdapter:
    """The ``soffice``-binary-backed ``OfficeConverter``."""

    kind: Final[str] = "system-binary"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        # The ONE presence check (`binary_present`), shared with the
        # `--dry-run` preview path so the two can never disagree.
        if not binary_present():
            return AdapterProbe(available=False, version=None, detail=None)

        # argv[0] is the module-level constant, not the located path -- see the
        # note on the same line in `tesseract_ocr`.
        run = subprocess_util.run([BINARY, "--version"], timeout=PROBE_TIMEOUT_S, check=False)
        first = run.first_line() or run.first_line("stderr")
        version = _parse_version(first)
        if version is None:
            detail = f"version line not recognised: {first!r}" if first else "no version line"
            return AdapterProbe(available=True, version=None, detail=detail)
        return AdapterProbe(available=True, version=version, detail=first or None)

    # -- PDF-15 (`convert`), appended at the end of the class ---------------- #

    def convert_to_pdf(
        self,
        source: Path,
        *,
        scratch_dir: Path,
        filter_name: str | None,
        timeout: float,
    ) -> Path:
        """See the Protocol docstring in ``ports/office.py``."""
        profile_dir = scratch_dir / _PROFILE_SUBDIR
        out_dir = scratch_dir / _OUTPUT_SUBDIR
        convert_to = f"pdf:{filter_name}" if filter_name else "pdf"

        # argv[0] is the module-level constant -- see the note on the same
        # line in `probe()`. Isolated profile per invocation (Design §D6):
        # LibreOffice serialises on a shared user profile, and a shared or
        # absent one causes intermittent failures under concurrency.
        # The list literal is inlined directly into the call -- not built up
        # in a local `argv` variable first -- because
        # `tests/test_import_boundaries.py` Section 2's `_static_argv0` reads
        # `node.args[0]` at the CALL SITE itself; a variable reference is not
        # statically resolvable even though its value is (see the identical
        # note on the same shape in `probe()` above).
        run = subprocess_util.run(
            [
                BINARY,
                "--headless",
                "--norestore",
                "--invisible",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                convert_to,
                "--outdir",
                str(out_dir),
                str(source),
            ],
            timeout=timeout,
            check=False,
        )
        if run.timed_out:
            raise FailureError(f"{source}: soffice timed out after {timeout:g}s")

        # D6: exit 0 with no output file is a FAILURE -- LibreOffice
        # frequently exits 0 having converted nothing. Success is measured
        # by the artefact, never by the return code.
        expected = out_dir / f"{source.stem}.pdf"
        if not expected.is_file() or expected.stat().st_size == 0:
            tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-5:])
            detail = f": {tail}" if tail else ""
            raise FailureError(
                f"{source}: soffice exited {run.returncode} but produced no "
                f"non-empty PDF at {expected}{detail}"
            )
        return expected


ADAPTER: Final[SofficeOfficeAdapter] = SofficeOfficeAdapter()
