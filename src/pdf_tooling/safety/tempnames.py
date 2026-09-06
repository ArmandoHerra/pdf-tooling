"""The toolkit temp-file namespace — one literal, one owner.

Every temp file the write chokepoint creates is named with :data:`TEMP_PREFIX`
and lives **beside its destination**, never in the system temp directory. That
co-location is what makes the final ``os.replace`` atomic, and the shared prefix
is what makes the residue of a hard kill identifiable afterwards.

This module is the namespace's only owner. The prefix literal may not appear
anywhere else under ``src/`` — an import-boundary grep asserts it — so the
discovery walk that must *exclude* these files cannot drift out of step with the
writer that *creates* them by hardcoding a second copy of the string.

**Report, never sweep** (``PLAN.md`` §12 R-07, decided). :func:`find_stray_temps`
returns paths and deletes nothing. There is no janitor, no background thread and
no age-gated cleanup: a stray file is evidence that a process was killed between
create and replace, and evidence that deletes itself is not evidence. ``doctor
--strict`` reports them; a human removes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = ["TEMP_PREFIX", "find_stray_temps", "is_toolkit_temp"]

#: The prefix every toolkit temp file carries. Leading dot so the file is hidden
#: from a shell glob while it exists, and a product-specific stem so that
#: identifying residue never depends on guessing.
TEMP_PREFIX: Final[str] = ".pdftoolkit-"


def is_toolkit_temp(path: Path | str) -> bool:
    """Whether *path* names a toolkit temp file.

    A name test, not an existence test: the caller may be filtering a directory
    listing, a plan, or a set of paths that no longer exist.
    """
    return Path(path).name.startswith(TEMP_PREFIX)


def find_stray_temps(root: Path | str) -> tuple[Path, ...]:
    """Report every toolkit temp file under *root*, sorted. Deletes nothing.

    A stray is what a ``SIGKILL`` or an OOM kill between temp-create and
    ``os.replace`` leaves behind. That residue is expected and harmless — the
    destination was never touched — and this function exists so ``doctor
    --strict`` can surface it.

    Returns an empty tuple when *root* is not a directory, so a caller can point
    it at a path that may not exist without guarding first.
    """
    base = Path(root)
    if not base.is_dir():
        return ()
    found = [candidate for candidate in base.rglob(TEMP_PREFIX + "*") if candidate.is_file()]
    return tuple(sorted(found))
