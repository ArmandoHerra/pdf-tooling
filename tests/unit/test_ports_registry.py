"""The port registry: six rows, one way to demand an engine, honest versions.

These are the unit-level assertions about the seam itself. The end-to-end
``doctor`` behaviour — the countable acceptance signal, the ``PATH`` mechanic,
the exit codes — lives in ``tests/test_doctor.py``, which runs the real CLI as a
subprocess because that is the only place an exit code is real.
"""

from __future__ import annotations

import shutil
import sys
from typing import Any

import pytest

from pdf_toolkit import ports
from pdf_toolkit.adapters import AdapterProbe, subprocess_util, tesseract_ocr
from pdf_toolkit.errors import EngineMissingError
from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import (
    BROKEN_INSTALL_HINT,
    KIND_PYTHON_PACKAGE,
    KIND_SYSTEM_BINARY,
    PORTS,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """Never let one test's memo answer another test's probe."""
    ports.reset_cache()
    yield
    ports.reset_cache()


# --------------------------------------------------------------------------- #
# The six, and their order.
# --------------------------------------------------------------------------- #


def test_there_are_exactly_six_ports_in_a_pinned_order() -> None:
    """The tuple IS the ``doctor`` row order, and the strings are public API."""
    assert PORTS == (
        "StructureEngine",
        "RasterEngine",
        "ComposeEngine",
        "TextEngine",
        "OcrEngine",
        "OfficeConverter",
    )
    assert len(PORTS) == 6
    assert len(set(PORTS)) == 6


def test_the_office_port_is_not_called_office_engine() -> None:
    """A published contract string, and an easy one to 'correct' by accident."""
    assert "OfficeConverter" in PORTS
    assert "OfficeEngine" not in PORTS


def test_resolve_all_returns_one_row_per_port_in_order() -> None:
    reports = ports.resolve_all()
    assert len(reports) == 6
    assert tuple(report.port for report in reports) == PORTS


def test_every_port_resolves_to_a_well_formed_row() -> None:
    for report in ports.resolve_all():
        payload = report.to_dict()
        assert payload["port"], report
        assert isinstance(payload["available"], bool), report
        assert payload["kind"] in {KIND_PYTHON_PACKAGE, KIND_SYSTEM_BINARY}, report
        assert "version" in payload, report


def test_an_unknown_port_is_a_key_error_not_a_silent_none() -> None:
    with pytest.raises(KeyError, match="unknown port"):
        ports.resolve("PdfMagicEngine")


# --------------------------------------------------------------------------- #
# Hints. AC7's two literals are PLAN.md §5.5's own words.
# --------------------------------------------------------------------------- #


def test_ocr_hint_is_platform_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert ports.install_hint("OcrEngine", KIND_SYSTEM_BINARY) == "apt install tesseract-ocr"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert ports.install_hint("OcrEngine", KIND_SYSTEM_BINARY) == "brew install tesseract"


def test_office_hint_is_platform_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert ports.install_hint("OfficeConverter", KIND_SYSTEM_BINARY) == "apt install libreoffice"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert (
        ports.install_hint("OfficeConverter", KIND_SYSTEM_BINARY)
        == "brew install --cask libreoffice"
    )


def test_an_unmapped_platform_falls_back_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Honest degradation: the Linux command, plus a note that it is not yours."""
    monkeypatch.setattr(sys, "platform", "sunos5")
    report = ports.build_report(
        "OcrEngine",
        adapter="tesseract",
        kind=KIND_SYSTEM_BINARY,
        probe=AdapterProbe(available=False, version=None, detail=None),
    )
    assert report.hint == "apt install tesseract-ocr"
    assert report.detail is not None
    assert "not specific to this platform" in report.detail


def test_a_missing_wheel_reports_a_broken_install_not_a_missing_engine() -> None:
    """The five wheel-backed ports cannot be "not installed by choice"."""
    report = ports.build_report(
        "StructureEngine",
        adapter="pypdf",
        kind=KIND_PYTHON_PACKAGE,
        probe=AdapterProbe(
            available=False, version=None, detail="pypdf is a hard install dependency"
        ),
    )
    assert report.hint == BROKEN_INSTALL_HINT
    assert report.detail is not None
    assert "hard install dependency" in report.detail


def test_a_hint_on_an_available_engine_is_impossible_by_construction() -> None:
    """`build_report` is the one place `hint` is decided, so this holds always."""
    report = ports.build_report(
        "RasterEngine",
        adapter="pypdfium2",
        kind=KIND_PYTHON_PACKAGE,
        probe=AdapterProbe(available=True, version="5.13.0", detail=None),
    )
    assert report.hint is None


# --------------------------------------------------------------------------- #
# Version honesty.
# --------------------------------------------------------------------------- #


def _fake_run(stdout: str) -> Any:
    def runner(argv: Any, **kwargs: Any) -> subprocess_util.ProcRun:
        return subprocess_util.ProcRun(
            argv=tuple(argv),
            returncode=0,
            stdout=stdout,
            stderr="",
            duration_ms=1,
            timed_out=False,
            pgid=0,
        )

    return runner


def test_an_unparseable_version_yields_null_and_the_raw_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Present but unreadable is ``available:true, version:null`` — never a guess.

    A tool that invented "5.5.0" from a banner it could not parse would be wrong
    exactly when a user was debugging a version problem.
    """
    monkeypatch.setattr(tesseract_ocr.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        tesseract_ocr.subprocess_util, "run", _fake_run("Tesseract Open Source OCR\nfoo\n")
    )

    probe = tesseract_ocr.ADAPTER.probe()
    assert probe.available is True
    assert probe.version is None
    assert probe.detail is not None
    assert "version line not recognised" in probe.detail
    assert "Tesseract Open Source OCR" in probe.detail


def test_a_parseable_version_is_reported_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tesseract_ocr.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        tesseract_ocr.subprocess_util, "run", _fake_run("tesseract 5.5.0\nleptonica-1.86.0\n")
    )
    probe = tesseract_ocr.ADAPTER.probe()
    assert probe.version == "5.5.0"


def test_an_absent_binary_is_a_row_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tesseract_ocr.shutil, "which", lambda _name: None)
    probe = tesseract_ocr.ADAPTER.probe()
    assert probe.available is False
    assert probe.version is None


def test_language_enumeration_drops_the_header_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first line of ``--list-langs`` is prose, not a language."""
    monkeypatch.setattr(tesseract_ocr.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        tesseract_ocr.subprocess_util,
        "run",
        _fake_run('List of available languages in "/usr/share/tessdata/" (3):\nosd\neng\nosd\n'),
    )
    assert tesseract_ocr.ADAPTER.languages() == ("eng", "osd")


# --------------------------------------------------------------------------- #
# `require()` — the single exit-3 chokepoint.
# --------------------------------------------------------------------------- #


def _unavailable(port: str) -> EngineReport:
    return EngineReport(
        port=port,
        adapter="tesseract",
        available=False,
        version=None,
        kind=KIND_SYSTEM_BINARY,
        detail="binary not found",
        hint="apt install tesseract-ocr",
    )


def test_requiring_a_missing_engine_is_exit_three_with_the_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ports, "_probe_for", lambda port: _unavailable(port))
    with pytest.raises(EngineMissingError) as caught:
        ports.require("OcrEngine")
    assert caught.value.exit_code == 3
    assert caught.value.kind == "engine_missing"
    assert "apt install tesseract-ocr" in caught.value.message


def test_every_exit_three_message_names_the_discovery_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PLAN.md`` §12 R-09: ``doctor`` is named in every exit-3 message.

    Asserted over all six ports rather than one, because the value of "there is
    one way to find out what is wrong" is that a user learns it once.
    """
    monkeypatch.setattr(ports, "_probe_for", lambda port: _unavailable(port))
    for port in PORTS:
        ports.reset_cache()
        with pytest.raises(EngineMissingError) as caught:
            ports.require(port)
        assert "pdftoolkit doctor" in caught.value.message, port
        assert port in caught.value.message, port


def test_requiring_an_unclaimed_capability_is_also_exit_three() -> None:
    """The port resolved, but nothing behind it can do the thing asked for.

    Still "the engine you need is not here", so still exit 3 and still pointing
    at the discovery path — never a silent fallback to an adapter that would
    answer the question wrongly.
    """
    with pytest.raises(EngineMissingError) as caught:
        ports.require("StructureEngine", capability="time-travel")
    assert caught.value.exit_code == 3
    assert "time-travel" in caught.value.message


def test_capability_selection_picks_the_secondary_not_the_primary() -> None:
    """The adapter-pinning affordance, exercised.

    ``linearized`` is declared by the pikepdf adapter and not by the pypdf
    primary, so asking for the capability must return the secondary — without
    any caller naming an adapter. This is the seam a later structure verb pins
    through; a parallel path inside ``ops/`` would defeat the point of having a
    registry at all.
    """
    primary = ports.require("StructureEngine")
    selected = ports.require("StructureEngine", capability="linearized")
    assert primary.adapter_name == "pypdf"
    assert selected.adapter_name == "pikepdf"
    assert "linearized" in selected.capabilities()
    assert "linearized" not in primary.capabilities()


@pytest.mark.parametrize("capability", ["repair", "linearize", "object-streams"])
def test_the_capabilities_a_later_verb_will_pin_on_already_resolve(capability: str) -> None:
    """Named now so that adding those verbs is not also a registry change."""
    assert ports.require("StructureEngine", capability=capability).adapter_name == "pikepdf"


# --------------------------------------------------------------------------- #
# Memoization, and the reason it must be resettable.
# --------------------------------------------------------------------------- #


def test_probes_are_memoized_per_port() -> None:
    calls: list[str] = []
    real = ports._probe_for

    def counting(port: str) -> EngineReport:
        calls.append(port)
        return real(port)

    original = ports._probe_for
    ports._probe_for = counting  # type: ignore[assignment]
    try:
        ports.resolve("RasterEngine")
        ports.resolve("RasterEngine")
        ports.resolve("RasterEngine")
    finally:
        ports._probe_for = original  # type: ignore[assignment]
    assert calls == ["RasterEngine"], "a verb needing one port paid for it more than once"


def test_reset_cache_forces_a_fresh_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PATH`` is consulted at probe time, which only means anything if the
    memo can be dropped — the acceptance signal for this whole spec changes
    ``PATH`` and expects the next answer to reflect it."""
    first = ports.resolve("OcrEngine")
    monkeypatch.setattr(tesseract_ocr.shutil, "which", lambda _name: None)
    assert ports.resolve("OcrEngine") is first, "the memo did not hold"
    ports.reset_cache()
    assert ports.resolve("OcrEngine").available is False


def test_resolving_one_port_does_not_probe_the_other_five() -> None:
    ports.reset_cache()
    ports.resolve("ComposeEngine")
    assert set(ports._CACHE) == {"ComposeEngine"}


def test_shutil_is_imported_so_the_which_monkeypatches_above_are_real() -> None:
    """Guards the fixture, not the product: a patch of a name the adapter does
    not actually use would make four tests above pass vacuously."""
    assert tesseract_ocr.shutil is shutil
