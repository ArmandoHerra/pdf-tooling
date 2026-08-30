"""Unit tests for `tests/registry.py` — `discover_verbs()`, the structural
predicates, and the `reaches_atomic_writer` scan that stands in for the
literal (and, in this codebase, unsatisfiable) `is_mutating` predicate. See
`registry.py`'s module docstring for why.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    INVOCATIONS,
    VerbSpec,
    discover_verbs,
    reaches_atomic_writer,
)


def test_discover_verbs_finds_exactly_the_three_landed_verbs() -> None:
    verbs = discover_verbs()
    names = {verb.name for verb in verbs}
    assert names == {"version", "doctor", "info"}


def test_discover_verbs_returns_no_duplicates() -> None:
    verbs = discover_verbs()
    names = [verb.name for verb in verbs]
    assert len(names) == len(set(names))


def test_info_is_the_only_verb_that_takes_input_paths() -> None:
    verbs = {verb.name: verb for verb in discover_verbs()}
    assert verbs["info"].takes_input_paths is True
    assert verbs["doctor"].takes_input_paths is False
    assert verbs["version"].takes_input_paths is False


def test_no_current_verb_is_page_addressing() -> None:
    for verb in discover_verbs():
        assert verb.is_page_addressing is False


def test_no_current_verb_is_mutating() -> None:
    """version/doctor/info write nothing -- confirmed against the live tree."""
    for verb in discover_verbs():
        assert verb.is_mutating is False, f"{verb.name} unexpectedly classified as mutating"


def test_every_discovered_verb_is_registered_in_invocations() -> None:
    """The AC10 anti-lapse guard's own precondition, proven independently of
    `test_cli_contract.py::test_every_verb_is_registered` so a break in one
    location is caught by two."""
    names = {verb.name for verb in discover_verbs()}
    assert names - set(INVOCATIONS) == set()


def test_verb_spec_is_a_frozen_dataclass_with_the_documented_fields() -> None:
    verb = VerbSpec(
        name="x",
        path=("x",),
        is_group=False,
        takes_input_paths=False,
        is_page_addressing=False,
        is_mutating=False,
    )
    assert verb.name == "x"


# --------------------------------------------------------------------------- #
# `reaches_atomic_writer` -- proven with planted synthetic modules, the same
# negative-control discipline `tests/test_import_boundaries.py` uses.
# --------------------------------------------------------------------------- #


def test_reaches_atomic_writer_is_true_for_a_module_that_imports_it() -> None:
    assert reaches_atomic_writer("pdf_toolkit.safety.atomic") is True


def test_reaches_atomic_writer_is_false_for_the_three_current_cli_modules() -> None:
    for module in (
        "pdf_toolkit.cli.cmd_version",
        "pdf_toolkit.cli.cmd_doctor",
        "pdf_toolkit.cli.cmd_info",
    ):
        assert reaches_atomic_writer(module) is False, module


def test_reaches_atomic_writer_is_false_for_an_unknown_module() -> None:
    assert reaches_atomic_writer("pdf_toolkit.this_module_does_not_exist") is False


def test_reaches_atomic_writer_follows_a_transitive_import_chain(
    tmp_path: Path, monkeypatch
) -> None:
    """A planted two-hop chain: cmd_fake -> ops_fake -> AtomicWriter, none of
    which import it directly -- proving the scan is transitive, not one-hop."""
    import registry

    fake_src = tmp_path / "src"
    (fake_src / "pdf_toolkit" / "cli").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "ops").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "cli" / "cmd_fake.py").write_text(
        "from pdf_toolkit.ops.ops_fake import do_it\n\n\ndef go():\n    return do_it()\n"
    )
    (fake_src / "pdf_toolkit" / "ops" / "ops_fake.py").write_text(
        "from pdf_toolkit.safety.atomic import AtomicWriter\n\n\n"
        "def do_it():\n    return AtomicWriter\n"
    )
    monkeypatch.setattr(registry, "SRC", fake_src)
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_fake") is True


def test_reaches_atomic_writer_does_not_false_positive_on_an_unrelated_chain(
    tmp_path: Path, monkeypatch
) -> None:
    import registry

    fake_src = tmp_path / "src"
    (fake_src / "pdf_toolkit" / "cli").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "ops").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "cli" / "cmd_fake.py").write_text(
        "from pdf_toolkit.ops.ops_fake import do_it\n\n\ndef go():\n    return do_it()\n"
    )
    (fake_src / "pdf_toolkit" / "ops" / "ops_fake.py").write_text(
        "def do_it():\n    return 'no writer here'\n"
    )
    monkeypatch.setattr(registry, "SRC", fake_src)
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_fake") is False
