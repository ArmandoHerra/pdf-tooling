"""L5. Adapters — the ONLY modules that import an engine library or spawn a process.

This restriction is what makes the licensing guarantee auditable: the question
"is anything AGPL/GPL/LGPL reachable?" is answered by reading this package, not
the whole tree. The forbidden list is absolute — never an import, never an
extra, and never a ``subprocess`` fallback.

Two AST walks hold the boundary from outside: ``tests/test_import_boundaries.py``
Section 2 fails if any module outside this package imports an engine library,
and ``tests/test_license_policy.py`` fails if any module outside
``subprocess_util.py`` reaches ``subprocess`` or an ``os`` spawn at all.

The eight v1 adapter modules, and the two ports that have two
-----------------------------------------------------------
``pypdf_structure`` · ``pikepdf_structure`` · ``pdfium_raster`` ·
``pdfium_text`` · ``pdfplumber_text`` · ``reportlab_compose`` ·
``tesseract_ocr`` · ``soffice_office``

Eight modules back **six** ports: ``pdfium`` backs two (raster and a text fast
path), and ``StructureEngine`` and ``TextEngine`` each have a primary and a
secondary. ``doctor`` still prints six rows — a secondary is named in its port's
``detail``, never given a row of its own. ``weasyprint_compose`` is deliberately
absent: WeasyPrint is the ``[html]`` extra and Phase 2, so ``ComposeEngine``
resolves to reportlab in v1.

Two rules every adapter here follows
------------------------------------
1. **The engine import is function-local.** Probing asks
   ``importlib.util.find_spec`` whether a package is present and reads its
   version from distribution metadata; it never imports the library. That is
   what keeps ``--help`` and ``--version`` inside the startup budget
   (``PLAN.md`` §12 R-13) even though ``doctor`` loads all eight modules.
2. **An adapter never chooses a destination path.** It receives the path it is
   told to write to. That is the structural half of the safety guarantee that an
   AST walk cannot see, because engines write through their own C code.

Each adapter exposes a module-level ``ADAPTER`` singleton implementing its
port's ``Protocol``, plus :class:`AdapterProbe` from :func:`probe`. The
singleton rather than the module itself is what lets ``mypy --strict``
structurally check the adapter against the Protocol at the seam.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass

__all__ = ["AdapterProbe", "package_probe"]


@dataclass(frozen=True, slots=True)
class AdapterProbe:
    """What an adapter can say about itself without doing any real work.

    Deliberately *not* an ``EngineReport``: the report is a port-level artefact
    that also carries the port name and the OS-aware install hint, and an
    adapter has no business knowing either. This is the smaller thing an adapter
    actually knows, and ``ports/`` assembles the row from it.
    """

    available: bool

    version: str | None
    """``None`` is meaningful: present but *unparsed*. A version this product
    prints is a version it actually read (``PLAN.md`` §5.5)."""

    detail: str | None
    """Secondary adapter and version, installed language packs, or the raw
    version line when it did not parse."""


def package_probe(module: str, distribution: str, *, detail: str | None = None) -> AdapterProbe:
    """Probe a wheel-installed engine **without importing it**.

    ``importlib.util.find_spec`` answers "is it installed?" by consulting the
    import machinery's finders; for a top-level name it does not execute the
    module. The version comes from *distribution metadata*, never from an
    engine's ``__version__`` attribute, because reading that attribute means
    importing the engine — and ``doctor`` loads all eight adapter modules.

    A present package whose metadata is missing reports ``available=True`` with
    ``version=None`` rather than claiming a version it did not read.
    """
    try:
        found = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        # A broken or partially-removed installation can raise rather than
        # return None. That is "not available", not a crash in `doctor`.
        found = False

    if not found:
        return AdapterProbe(
            available=False,
            version=None,
            detail=(
                f"{distribution} is a hard install dependency and is missing: this is a "
                "broken installation, not an optional engine you chose not to install"
            ),
        )

    try:
        version: str | None = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = None
    return AdapterProbe(available=True, version=version, detail=detail)
