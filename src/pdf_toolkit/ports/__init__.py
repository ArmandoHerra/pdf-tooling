"""L4. Ports — six ``typing.Protocol`` definitions and the resolution registry.

Each port names one engine capability; each has one primary adapter in
``pdf_toolkit.adapters`` and, for two of them, a capability-selected secondary.
Nothing in this package imports an engine library: a port is a shape, not an
implementation.

THE RULE THAT BINDS EVERY LATER SPEC — READ THIS BEFORE WIDENING ANYTHING
--------------------------------------------------------------------------
Each ``ports/<name>.py`` contains (a) its ``Protocol`` class, (b) a ``probe()``
returning one :class:`~pdf_toolkit.models.EngineReport`, and (c) ``adapters()``
listing its adapters in preference order. At this point in the build order the
Protocols declare the probe surface plus **only** the methods the ``doctor`` and
``info`` verbs actually call.

A later spec that needs a new operation **adds the method to the same port
file, beside the existing ones.** It does not:

* create a parallel interface or a second registry;
* import an engine library anywhere outside ``adapters/``;
* add a stub method it does not implement — a placeholder raising
  ``NotImplementedError`` type-checks, satisfies the Protocol, and then fails at
  runtime in front of a user, which is the failure mode the capability tokens
  exist to prevent.

This is why "is anything GPL on the call graph?" stays answerable by reading six
files.

HOW AN ENGINE IS DEMANDED — EXACTLY ONE WAY
-------------------------------------------
:func:`require` is the chokepoint. It raises
:class:`~pdf_toolkit.errors.EngineMissingError` — exit **3**, carrying the port
name, the OS-aware install hint, and the literal string ``pdftoolkit doctor``
(``PLAN.md`` §12 R-09: *doctor is the discovery path and is named in every
exit-3 message*). **No verb inspects ``available`` itself and branches.** One
way to demand an engine means one place a missing engine is reported, and one
message shape a user learns once.

ADAPTER SELECTION IS BY CAPABILITY, NEVER BY NAME
-------------------------------------------------
``require(port, capability="linearized")`` returns the first adapter declaring
that token. That is D-04's *"selected by capability, not by guesswork"* made
real: ``info`` asks for ``linearized`` and gets the pikepdf-backed adapter
without naming it, and the later repair/linearize work asks for ``repair`` or
``linearize`` through the same call rather than reaching into ``adapters/``
directly. A parallel pinning path inside ``ops/`` would defeat the point of
having this file.

MEMOIZATION AND ``PATH``
------------------------
Probes are memoized per process and per port. Two of the six cost a subprocess
each, and a verb that needs one port must not pay for six. :func:`reset_cache`
drops the memo; ``doctor`` calls it before probing so a long-lived process never
reports stale state, and so that a test which alters ``PATH`` measures the new
``PATH`` rather than the old answer.

LAZY IMPORTS ONLY
-----------------
Nothing here imports an adapter, or even a sibling port module, at module scope.
``PLAN.md`` §12 R-13 requires that ``cli/main.py`` import no engine library at
module scope, and ``doctor`` reaches all eight adapter modules — so the imports
live inside the functions that need them, and a test asserts ``sys.modules``
stays clean after importing the CLI.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Final, Protocol

from pdf_toolkit.errors import EngineMissingError
from pdf_toolkit.models import EngineReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = [
    "BROKEN_INSTALL_HINT",
    "KIND_OPTIONAL_EXTRA",
    "KIND_PYTHON_PACKAGE",
    "KIND_SYSTEM_BINARY",
    "PORTS",
    "Adapter",
    "build_report",
    "install_hint",
    "require",
    "reset_cache",
    "resolve",
    "resolve_all",
]

#: The six ports, in the order ``doctor`` prints them. These strings are PUBLIC
#: API: they appear in ``doctor -o json`` and in every exit-3 message. Note
#: ``OfficeConverter``, not ``OfficeEngine``.
PORTS: Final[tuple[str, ...]] = (
    "StructureEngine",
    "RasterEngine",
    "ComposeEngine",
    "TextEngine",
    "OcrEngine",
    "OfficeConverter",
)

KIND_PYTHON_PACKAGE: Final[str] = "python-package"
KIND_SYSTEM_BINARY: Final[str] = "system-binary"

#: Declared for the Phase-2 WeasyPrint row and deliberately unused by any v1
#: row. Removing it would make the ``kind`` enum a two-value enum that has to be
#: widened — a schema change — the moment the ``[html]`` extra ships.
KIND_OPTIONAL_EXTRA: Final[str] = "optional-extra"

#: What to tell a user whose *wheel* is missing. Those five engines are hard
#: install dependencies, so "absent" means a broken installation rather than a
#: system package they chose not to install (``PLAN.md`` §5.5).
BROKEN_INSTALL_HINT: Final[str] = "uv tool install --force pdf-toolkit"

#: OS-aware install hints for the two ports that can legitimately be absent.
#: A module-level table so a test can monkeypatch ``sys.platform`` and assert
#: both arms on one host. The ``OcrEngine`` strings are ``PLAN.md`` §5.5's own
#: words and are asserted literally.
_BINARY_HINTS: Final[dict[str, dict[str, str]]] = {
    "OcrEngine": {
        "linux": "apt install tesseract-ocr",
        "darwin": "brew install tesseract",
    },
    "OfficeConverter": {
        "linux": "apt install libreoffice",
        "darwin": "brew install --cask libreoffice",
    },
}

_FALLBACK_PLATFORM: Final[str] = "linux"

_NOT_PLATFORM_SPECIFIC: Final[str] = (
    "the install hint is not specific to this platform; it is the Linux command"
)


class Adapter(Protocol):
    """The surface every adapter has, whatever port it backs.

    Deliberately minimal. A port's own Protocol adds the operations that port
    performs; this is only what the registry itself needs in order to report and
    select.
    """

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...


def install_hint(port: str, kind: str) -> str:
    """The install command to print when *port* is unavailable.

    Resolved from ``sys.platform`` **at call time**, so the value is a property
    of the machine reading the message rather than of the machine that built the
    wheel.
    """
    if kind != KIND_SYSTEM_BINARY:
        return BROKEN_INSTALL_HINT
    table = _BINARY_HINTS.get(port)
    if table is None:  # pragma: no cover - every system-binary port has a row
        return BROKEN_INSTALL_HINT
    return table.get(sys.platform, table[_FALLBACK_PLATFORM])


def _platform_is_mapped(port: str, kind: str) -> bool:
    if kind != KIND_SYSTEM_BINARY:
        return True
    table = _BINARY_HINTS.get(port, {})
    return sys.platform in table


def build_report(
    port: str,
    *,
    adapter: str,
    kind: str,
    probe: AdapterProbe,
    extra_detail: str | None = None,
) -> EngineReport:
    """Assemble one ``doctor`` row from an adapter's self-report.

    The one place ``hint`` is decided, which is what makes "a hint on an
    available engine is a defect" true by construction rather than by review.
    """
    details = [text for text in (probe.detail, extra_detail) if text]
    hint: str | None = None
    if not probe.available:
        hint = install_hint(port, kind)
        if not _platform_is_mapped(port, kind):
            details.append(_NOT_PLATFORM_SPECIFIC)
    return EngineReport(
        port=port,
        adapter=adapter,
        available=probe.available,
        version=probe.version,
        kind=kind,
        detail="; ".join(details) if details else None,
        hint=hint,
    )


_CACHE: dict[str, EngineReport] = {}


def _probe_for(port: str) -> EngineReport:
    """Dispatch to a port module's ``probe()``. Imports are function-local."""
    from pdf_toolkit.ports import compose, ocr, office, raster, structure, text

    probes: dict[str, Callable[[], EngineReport]] = {
        "StructureEngine": structure.probe,
        "RasterEngine": raster.probe,
        "ComposeEngine": compose.probe,
        "TextEngine": text.probe,
        "OcrEngine": ocr.probe,
        "OfficeConverter": office.probe,
    }
    return probes[port]()


def _adapters_for(port: str) -> tuple[Adapter, ...]:
    """A port's adapters in preference order. Imports are function-local."""
    from pdf_toolkit.ports import compose, ocr, office, raster, structure, text

    registries: dict[str, Callable[[], tuple[Adapter, ...]]] = {
        "StructureEngine": structure.adapters,
        "RasterEngine": raster.adapters,
        "ComposeEngine": compose.adapters,
        "TextEngine": text.adapters,
        "OcrEngine": ocr.adapters,
        "OfficeConverter": office.adapters,
    }
    return registries[port]()


def _check_port(port: str) -> None:
    if port not in PORTS:
        raise KeyError(f"unknown port {port!r}; the six are {', '.join(PORTS)}")


def resolve(port: str) -> EngineReport:
    """The resolution report for one port. Memoized for the life of the process."""
    _check_port(port)
    cached = _CACHE.get(port)
    if cached is not None:
        return cached
    report = _probe_for(port)
    _CACHE[port] = report
    return report


def resolve_all() -> tuple[EngineReport, ...]:
    """One report per port, in :data:`PORTS` order. Always exactly six.

    A missing engine is a row with ``available:false``, never an absent row — a
    consumer counting rows gets the same number on every host, which is what
    makes the count assertable at all.
    """
    return tuple(resolve(port) for port in PORTS)


def reset_cache() -> None:
    """Drop the memo. A test seam, and what ``doctor`` calls before it probes."""
    _CACHE.clear()


def require(port: str, *, capability: str | None = None) -> Adapter:
    """Demand an engine. The single exit-3 chokepoint.

    Args:
        port: One of :data:`PORTS`.
        capability: Select the first adapter declaring this token instead of the
            port's primary. This is the whole adapter-selection seam — see the
            module docstring.

    Returns:
        The adapter to use. Callers wanting the port's own Protocol type narrow
        it in that port's module, next to the Protocol being narrowed to.

    Raises:
        EngineMissingError: Exit 3. The message always carries the install hint
            and always names ``pdftoolkit doctor``.
    """
    _check_port(port)
    report = resolve(port)
    if not report.available:
        raise EngineMissingError(_missing_message(report, capability))

    for adapter in _adapters_for(port):
        if capability is None or capability in adapter.capabilities():
            return adapter

    # The port resolved, but no adapter behind it claims what the caller needs.
    # That is still "the engine you need is not here", so it is still exit 3 and
    # still points at the discovery path -- not a traceback, and not a silent
    # fallback to an adapter that would answer wrongly.
    raise EngineMissingError(_missing_message(report, capability))


def _missing_message(report: EngineReport, capability: str | None) -> str:
    want = f" with the {capability!r} capability" if capability else ""
    hint = report.hint or install_hint(report.port, report.kind)
    detail = f" ({report.detail})" if report.detail else ""
    return (
        f"{report.port}{want} is unavailable{detail}. Install it with: {hint}. "
        f"Run 'pdftoolkit doctor' to see which engines resolved."
    )
