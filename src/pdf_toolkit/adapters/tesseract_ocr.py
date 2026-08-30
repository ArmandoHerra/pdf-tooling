"""``OcrEngine`` adapter — the ``tesseract`` binary, bound by pytesseract.

Unlike the five wheel-backed ports, this one can legitimately be absent: the
binary is a system package the user installs. Absence is therefore a *report*
(``available:false`` with an OS-aware hint), and a verb that needs it exits
**3** — never a traceback, and never a degraded result that looks real
(``PLAN.md`` §12 R-09).

HONEST LANGUAGE ENUMERATION
---------------------------
``detail`` lists the tessdata languages that are **actually installed**, read
from the binary itself. A tool that advertised language support it does not have
would fail at the worst possible moment — mid-batch, on someone's documents —
and multi-language OCR is deferred (B-009) precisely so this stays a statement
of fact rather than a promise.

WHY THE SPAWN IS OURS AND NOT pytesseract's
-------------------------------------------
Every spawn here goes through ``subprocess_util.run``, which puts the child in
its own process group and kills the **group** on timeout. pytesseract 0.3.13's
own ``run_tesseract()`` does not pass ``start_new_session`` and calls
``terminate()`` on the direct child only, so a tesseract that has itself forked
leaves the grandchild running. That is the exact shape of the leak recorded in
``expertise/product.yaml`` — 163 orphaned daemons, roughly 6.5 GiB resident, on
this host — and it is why the OCR spec builds its argv and spawns it here rather
than calling the binding's runner.
"""

from __future__ import annotations

import re
import shutil
from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe, subprocess_util

__all__ = ["ADAPTER", "BINARY", "PROBE_TIMEOUT_S", "TesseractOcrAdapter"]

_NAME: Final[str] = "tesseract"

#: A module-level string literal on purpose: the licence walk in
#: ``tests/test_license_policy.py`` resolves a spawn's ``argv[0]`` through
#: exactly this shape, so a binary name that lives in a `Final[str]` stays
#: statically auditable while a computed one would be refused outright.
BINARY: Final[str] = "tesseract"

_BINDING_DISTRIBUTION: Final[str] = "pytesseract"
_BINDING_MODULE: Final[str] = "pytesseract"

#: Short by design. A version probe that hangs is an unavailable engine, not a
#: reason for ``doctor`` to hang with it.
PROBE_TIMEOUT_S: Final[float] = 5.0

_CAPABILITIES: Final[frozenset[str]] = frozenset({"ocr", "hocr", "languages"})

#: ``tesseract 5.5.0`` -> ``5.5.0``. Anchored, so a line that merely mentions the
#: binary cannot be mistaken for a version line.
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^tesseract\s+v?([0-9][0-9A-Za-z.\-]*)")


def _parse_version(line: str) -> str | None:
    match = _VERSION_RE.match(line.strip())
    return match.group(1) if match else None


def _parse_languages(stdout: str) -> tuple[str, ...]:
    """Languages from ``--list-langs``, header line dropped, sorted and deduped.

    The first line is a human sentence naming the tessdata directory and a
    count; everything after it is one language code per line.
    """
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    body = [line for line in lines[1:] if " " not in line]
    return tuple(sorted(set(body)))


class TesseractOcrAdapter:
    """The ``tesseract``-binary-backed ``OcrEngine``."""

    kind: Final[str] = "system-binary"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        """Locate the binary, read its version, and enumerate its languages.

        ``PATH`` is consulted at probe time and never cached across
        ``ports.reset_cache()``: the acceptance signal for this whole spec
        manipulates ``PATH`` and expects exactly one row to flip.
        """
        if shutil.which(BINARY) is None:
            return AdapterProbe(available=False, version=None, detail=None)

        # argv[0] is the module-level `Final[str]`, NOT the absolute path
        # `shutil.which` just returned. Both consult PATH identically -- Popen
        # without a shell uses execvp semantics for a name containing no slash --
        # but only the constant is statically resolvable, and
        # tests/test_import_boundaries.py Section 2 refuses a spawn whose argv[0]
        # it cannot resolve and check against the forbidden set. A guarantee that
        # a reader can verify by grepping one constant beats one that requires
        # tracing a local variable.
        run = subprocess_util.run([BINARY, "--version"], timeout=PROBE_TIMEOUT_S, check=False)
        first = run.first_line() or run.first_line("stderr")
        version = _parse_version(first)

        details: list[str] = []
        if version is None:
            # Present but unparsed. Report the raw line and NOT a version --
            # `doctor` never prints a version it did not actually read.
            unparsed = f"version line not recognised: {first!r}" if first else "no version line"
            details.append(unparsed)
        languages = self.languages()
        if languages:
            details.append("languages: " + ", ".join(languages))
        else:
            details.append("languages: none reported")

        return AdapterProbe(available=True, version=version, detail="; ".join(details))

    def languages(self) -> tuple[str, ...]:
        """The tessdata languages installed on this host, sorted.

        What is reported is what ``--list-langs`` says is there. This product
        does not claim language support it cannot demonstrate.
        """
        if shutil.which(BINARY) is None:
            return ()
        run = subprocess_util.run([BINARY, "--list-langs"], timeout=PROBE_TIMEOUT_S, check=False)
        return _parse_languages(run.stdout or run.stderr)

    def binding_probe(self) -> AdapterProbe:
        """The Python binding's own presence, reported separately from the binary.

        The binding is a hard dependency (a wheel) and the binary is not, so
        conflating them would report a broken install and a missing system
        package identically.
        """
        return package_probe(_BINDING_MODULE, _BINDING_DISTRIBUTION)


ADAPTER: Final[TesseractOcrAdapter] = TesseractOcrAdapter()
