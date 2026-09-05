"""PDF-40 — a ``--out-dir`` batch payload never denies an artifact that is on disk.

The defect this file measures: a multi-input ``--out-dir`` run with one bad
input aborted the batch and emitted the ERROR envelope in place of the
operation envelope — so the input that succeeded was unreported, the input
that failed was unnamed, and on the verbs that write before they fail the
payload actively denied a file already on disk.

**The headline assertion is filesystem-versus-payload, and it is two-sided.**
An assertion that the collection key merely exists, or that it has three
entries, would not catch this defect and would not catch the next one: the
defect is a *disagreement between two sources of truth*, so the filesystem
listing is taken INDEPENDENTLY by this harness (:func:`_walk`, stdlib
``os.walk``) and never from the tool's own stdout. Both directions are
required and they fail differently — direction (b) alone passes a payload that
omits a written file, direction (a) alone passes a payload that invents one,
and *a payload that agrees with itself is exactly what shipped*.

**The bad input goes in the MIDDLE.** A first-position failure cannot
distinguish *abort* from *continue*, so a position-1 arm is unfailable for the
property this file exists to establish. Position 2 also makes the
partial-artifact state reachable: ``[good, bad, good]`` produces TWO artifacts
and THREE items when the fix is correct, and produced ONE artifact and ZERO
items before it.

**The population is derived, never transcribed** —
:func:`registry.out_dir_batch_verbs`, whose three steps are the consumer set,
the operand arity, and the VERB name off the live command tree. A test that
hard-coded the ten names could not produce this file's own reds.

Every criterion here is expressed over *the verb's own declared collection
key, resolved from the payload at test time*, rather than over the literal
``items``. That is belt-and-braces rather than load-bearing — ``items`` is the
universal collection key and cannot be renamed inside this window — but it
costs nothing and it survives a later ruling that this file does not own.
"""

from __future__ import annotations

import ast
import json
import os
import stat
from pathlib import Path
from typing import Any, Final

import pytest

from registry import out_dir_batch_verbs, run_cli

# --------------------------------------------------------------------------- #
# The derived population, resolved ONCE at import so a parametrize set that
# went silently empty is a collection-time failure rather than a green run
# over nothing (AC1/AC12; the `test_c13_population_is_non_empty` pattern, which
# exists on this product because a parametrize set DID go empty unnoticed).
# --------------------------------------------------------------------------- #

BATCH_VERBS: Final[tuple[str, ...]] = out_dir_batch_verbs()

#: The verb-name keys of the three collection keys any payload may declare.
#: Resolved from the payload rather than assumed, per this module's docstring.
_COLLECTION_KEYS: Final[tuple[str, ...]] = ("items", "documents", "ports")

#: Per-verb argv between the operands and ``--out-dir``. Only what each verb
#: REQUIRES to reach its own write path; nothing here tunes behaviour.
_EXTRA_ARGV: Final[dict[str, list[str]]] = {
    "compress": [],
    "convert": [],
    "delete": ["--pages", "1"],
    "extract": ["--pages", "1"],
    # `ocr` takes its own documented ENGINE-FREE path here (`--skip-text-pages`
    # over a text fixture makes every selected page skip-eligible, so
    # `ops/ocr.py`'s lazy demand never spawns tesseract). This is not a
    # weakening: both failure kinds are decided at the classification and
    # document-open seams, long before any page is recognised, so the arm
    # measures exactly the same continuation property. It is here because
    # spawning tesseract once per arm per parallel worker saturates the host
    # and produces `tesseract timed out after 120s` -- a load artifact that
    # would masquerade as this spec's own failure.
    "ocr": ["--pages", "1", "--skip-text-pages"],
    "rasterize": ["--pages", "1"],
    "reorder": ["--pages", "1"],
    "rotate": ["--pages", "1", "--angle", "90"],
    "tables": [],
    "text": [],
}

#: The port each verb genuinely needs to reach a written artifact. An arm whose
#: engine is absent SKIPS WITH A REASON -- a skipped arm is not agreement.
_REQUIRES_ENGINE: Final[dict[str, str | None]] = {
    "compress": None,
    "convert": "OfficeConverter",
    "delete": None,
    "extract": None,
    "ocr": None,  # engine-free via the skip-eligible path (`ops/ocr.py`'s lazy demand)
    "rasterize": None,
    "reorder": None,
    "rotate": None,
    "tables": None,
    "text": None,
}


def _skip_unless_engine_available(verb: str) -> None:
    port = _REQUIRES_ENGINE.get(verb)
    if port is None:
        return
    from pdf_toolkit.ports import resolve

    if not resolve(port).available:
        pytest.skip(f"{verb} needs the {port} engine to reach a written artifact; not present")


# --------------------------------------------------------------------------- #
# Fixtures. A CORRUPT FIXTURE IS CHEAPER AND MORE DETERMINISTIC THAN A REAL
# DOCUMENT: nothing here reads the optional real-document corpus, and no
# criterion in this file needs one.
# --------------------------------------------------------------------------- #


def _good_pdf(root: Path, name: str) -> Path:
    """A real multi-page PDF, built through the product's own ``create`` verb.

    Built by the tool rather than by an engine import, so this file stays
    inside the same port discipline the product enforces on itself.
    """
    source = root / f"{name}.txt"
    source.write_text("".join(f"line {i} alpha beta gamma delta\n" for i in range(160)))
    target = root / f"{name}.pdf"
    result = run_cli("create", str(source), "-O", str(target), "-o", "json")
    assert result.returncode == 0, f"fixture build failed: {result.stdout}{result.stderr}"
    source.unlink()
    return target


def _corrupt_pdf(root: Path, name: str) -> Path:
    """A file that classifies clean and fails when an engine opens it.

    This is the kind that reaches the EXECUTION seam: it is perfectly readable,
    so operand classification passes it, and it blows up after an earlier input
    has already committed its artifact.
    """
    target = root / f"{name}.pdf"
    target.write_bytes(b"%PDF-1.4\nthis is not a pdf body at all\n")
    return target


def _unreadable_pdf(root: Path, name: str) -> Path:
    """An existing, mode-000 file — the kind that reaches the CLASSIFICATION seam.

    A different seam from the corrupt kind, in a different file, and the
    execution seam is never even reached. A fix that handles one kind is not a
    fix, which is why both arms exist as separate criteria.
    """
    target = _good_pdf(root, name)
    target.chmod(0o000)
    return target


@pytest.fixture
def restore_modes() -> Any:
    """Restore any mode-000 fixture, so tmp_path teardown can always clean up."""
    touched: list[Path] = []
    yield touched
    for path in touched:
        if path.exists():
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# --------------------------------------------------------------------------- #
# Driving helpers.
# --------------------------------------------------------------------------- #


def _walk(root: Path) -> list[Path]:
    """The filesystem listing, taken INDEPENDENTLY of the tool's own output.

    `os.walk` and nothing else -- no engine, no out-of-tree oracle. This is the
    whole point of D8: a guard that reads only the tool's stdout cannot catch a
    tool that lies in its stdout.
    """
    if not root.exists():
        return []
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        found.extend(Path(dirpath) / name for name in filenames)
    return sorted(found)


def _collection(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """The verb's own declared collection key and its rows, resolved at test time."""
    for key in _COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return key, value
    raise AssertionError(
        f"payload declares no collection key (looked for {_COLLECTION_KEYS}); "
        f"top-level keys were {sorted(payload)}"
    )


def _drive(
    verb: str,
    operands: list[Path],
    out_dir: Path,
    *,
    dry_run: bool = False,
    threads: int | None = None,
) -> tuple[int, dict[str, Any], str]:
    argv = [verb, *(str(p) for p in operands), "--out-dir", str(out_dir), *_EXTRA_ARGV[verb]]
    if threads is not None:
        argv += ["--threads", str(threads)]
    if dry_run:
        argv.append("--dry-run")
    argv += ["-y", "-o", "json"]
    result = run_cli(*argv)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:  # a traceback, not a payload
        raise AssertionError(
            f"{verb}: stdout was not JSON ({error}); "
            f"stdout={result.stdout[:400]!r} stderr={result.stderr[-800:]!r}"
        ) from None
    return result.returncode, payload, result.stderr


def _build_batch(root: Path, kind: str, restore: list[Path]) -> list[Path]:
    """``[good, bad, good]`` — D9: the bad input in POSITION 2, always."""
    first = _good_pdf(root, "a")
    if kind == "corrupt":
        bad = _corrupt_pdf(root, "b")
    else:
        bad = _unreadable_pdf(root, "b")
        restore.append(bad)
    last = _good_pdf(root, "c")
    return [first, bad, last]


# --------------------------------------------------------------------------- #
# AC1 / AC2 — the derived population.
# --------------------------------------------------------------------------- #


def test_ac1_population_is_derived_and_non_empty() -> None:
    """Derived, non-empty, and keyed on the VERB name rather than the module."""
    assert BATCH_VERBS, (
        "the --out-dir batch population derived empty; every arm below would "
        "collect zero cases and pass vacuously"
    )
    assert len(BATCH_VERBS) == 10, (
        f"population size moved: {len(BATCH_VERBS)} -> {BATCH_VERBS}. "
        "A different size after a later spec is INFORMATION, not an error -- "
        "re-derive, record the new figure, and update this pin deliberately."
    )


def test_ac1_population_is_keyed_on_the_verb_name_not_the_module_basename() -> None:
    """``cli/cmd_office.py`` registers ``convert``; a module-keyed census says ``office``.

    A criterion phrased over module names and one phrased over verb names are
    not the same criterion, and every planning artifact carries the verb-space
    list. This is the step a re-derivation is most likely to skip.
    """
    assert "convert" in BATCH_VERBS, (
        f"'convert' missing from {BATCH_VERBS} -- the derivation is keyed on the "
        "module basename ('office') rather than on the live command's VERB name"
    )
    assert "office" not in BATCH_VERBS


def test_ac2_split_is_excluded_by_arity_not_by_a_literal() -> None:
    """``split`` is the eleventh ``--out-dir`` consumer and the ONLY excluded one.

    Excluded because its operand is single (``nargs == 1``), so a bad input
    cannot be placed in the middle of one -- derived, so a future ``split`` that
    grew a variadic operand would enter the population with zero author action.
    """
    from registry import discover_verbs

    consumers = sorted(
        verb.name for verb in discover_verbs() if not verb.is_group and "--out-dir" in verb.consumes
    )
    assert "split" in consumers, "split no longer declares --out-dir; re-derive the exclusion"
    assert "split" not in BATCH_VERBS
    assert set(consumers) - set(BATCH_VERBS) == {"split"}, (
        "exactly one --out-dir consumer is excluded by arity; "
        f"consumers={consumers} population={BATCH_VERBS}"
    )


# --------------------------------------------------------------------------- #
# AC3 / AC4 — the headline contradiction, both failure kinds.
# --------------------------------------------------------------------------- #


def _assert_payload_agrees_with_disk(
    verb: str,
    kind: str,
    operands: list[Path],
    out_dir: Path,
    exit_code: int,
    payload: dict[str, Any],
) -> None:
    """D8's four directions, all required, checked in BOTH directions."""
    key, rows = _collection(payload)
    on_disk = _walk(out_dir)

    # Direction 3 first -- every operand is NAMED, once, in input order. The
    # failing one included: `"path": null` and an unnamed failure were the
    # second half of the defect.
    named = [row["input"] for row in rows]
    expected = [str(p) for p in operands]
    assert named == expected, (
        f"{verb}/{kind}: payload['{key}'] must name every operand exactly once, "
        f"IN INPUT ORDER.\n  expected: {expected}\n  observed: {named}"
    )

    ok_rows = [row for row in rows if row["ok"]]
    bad_rows = [row for row in rows if not row["ok"]]
    assert len(bad_rows) == 1, f"{verb}/{kind}: expected exactly one failed item, got {bad_rows}"

    # Direction 1 -- every artifact on disk is named by exactly ONE ok item.
    # Catches an artifact the payload OMITS (the shipped defect).
    claimed = [row["output"] for row in ok_rows if row["output"]]
    for artifact in on_disk:
        owners = [c for c in claimed if Path(c) == artifact]
        assert len(owners) == 1, (
            f"{verb}/{kind}: {artifact} is on disk but is named by {len(owners)} "
            f"ok items -- the payload denies (or double-claims) its own output.\n"
            f"  on disk: {on_disk}\n  claimed: {claimed}"
        )

    # Direction 2 -- every ok item names a path that EXISTS. Catches an
    # artifact the payload INVENTS.
    for row in ok_rows:
        if row["output"] is None:
            continue
        assert Path(row["output"]).exists(), (
            f"{verb}/{kind}: item claims ok with output {row['output']!r}, "
            f"which is not on disk. on disk: {on_disk}"
        )

    # Direction 4 -- the failed item carries a non-zero code and a message, and
    # names no existing output.
    failed = bad_rows[0]
    assert failed["input"] == str(operands[1]), (
        f"{verb}/{kind}: the failure must be attributed to the MIDDLE operand "
        f"{operands[1]}, not to {failed['input']}"
    )
    assert failed["exit_code"] != 0, f"{verb}/{kind}: failed item carries exit_code 0: {failed}"
    assert failed["message"], f"{verb}/{kind}: failed item carries no message: {failed}"
    if failed["output"] is not None:
        assert not Path(failed["output"]).exists(), (
            f"{verb}/{kind}: failed item names {failed['output']!r}, which EXISTS"
        )

    assert exit_code == 1, f"{verb}/{kind}: expected exit 1, got {exit_code}"
    assert payload["exit_code"] == 1, f"{verb}/{kind}: payload exit_code {payload['exit_code']}"
    assert payload["schema_version"] == 1


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac3_corrupt_input_in_the_middle_is_recorded_and_the_batch_continues(
    verb: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """The corrupt kind — reaches the EXECUTION seam, after an artifact is committed."""
    _skip_unless_engine_available(verb)
    operands = _build_batch(tmp_path, "corrupt", restore_modes)
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, operands, out_dir)
    _assert_payload_agrees_with_disk(verb, "corrupt", operands, out_dir, exit_code, payload)


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac4_unreadable_input_in_the_middle_is_recorded_and_the_batch_continues(
    verb: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """The unreadable kind — a DIFFERENT seam, and therefore a different criterion.

    Before this spec every verb produced ZERO artifacts here, because the
    pre-flight classification loop aborted before a single target was planned.
    A criterion that only drove the corrupt arm would be satisfied by a change
    touching only the execution loop, leaving this arm unfixed on all ten.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: mode 000 does not deny reads, so this arm cannot be built")
    _skip_unless_engine_available(verb)
    operands = _build_batch(tmp_path, "unreadable", restore_modes)
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, operands, out_dir)
    _assert_payload_agrees_with_disk(verb, "unreadable", operands, out_dir, exit_code, payload)


@pytest.mark.parametrize("verb", BATCH_VERBS)
@pytest.mark.parametrize("kind", ["corrupt", "unreadable"])
def test_ac3_ac4_the_good_inputs_still_produce_their_artifacts(
    verb: str, kind: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """The partial-artifact state is REACHABLE: two good inputs still produce two.

    The pre-fix signatures were ONE artifact (corrupt kind, on the verbs that
    write before they fail) and ZERO (unreadable kind, on all ten). Both are
    pinned here against the verb's own all-good control rather than against a
    constant, because *some verbs legitimately produce no artifact for a given
    document* -- ``tables`` over a table-free fixture is the live example, and a
    flat "expect artifacts" pin would read that correct behaviour as the defect.

    Deriving the expected count from the same verb's all-good run is what makes
    this criterion honest for all ten without a per-verb exception list.
    """
    if kind == "unreadable" and os.geteuid() == 0:
        pytest.skip("running as root: mode 000 does not deny reads, so this arm cannot be built")
    _skip_unless_engine_available(verb)

    # The control: the same batch, all three inputs good.
    control_root = tmp_path / "control"
    control_root.mkdir()
    control_operands = [_good_pdf(control_root, name) for name in ("a", "b", "c")]
    control_out = control_root / "out"
    control_code, _control_payload, _ = _drive(verb, control_operands, control_out)
    assert control_code == 0, f"{verb}: the all-good control did not exit 0 ({control_code})"
    control_artifacts = _walk(control_out)
    if not control_artifacts:
        pytest.skip(
            f"{verb} produces no artifact for this fixture even when every input is "
            "good, so an artifact count cannot discriminate the failure arms here"
        )

    failure_root = tmp_path / "failure"
    failure_root.mkdir()
    operands = _build_batch(failure_root, kind, restore_modes)
    out_dir = failure_root / "out"
    _drive(verb, operands, out_dir)
    produced = _walk(out_dir)
    assert produced, (
        f"{verb}/{kind}: a bad input in position 2 produced ZERO artifacts while the "
        f"all-good control produced {len(control_artifacts)} -- the batch is still "
        "aborting rather than recording the failure and continuing"
    )
    assert len(produced) < len(control_artifacts), (
        f"{verb}/{kind}: expected a PARTIAL result (fewer artifacts than the "
        f"all-good control's {len(control_artifacts)}), got {len(produced)}"
    )


# --------------------------------------------------------------------------- #
# AC5 — input order survives, including on the pooled verbs.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac5_items_are_in_command_line_order_under_threads(
    verb: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """``PLAN.md`` §5.4: output ordering is deterministic regardless of ``--threads``.

    A guard that appended failures as they completed, rather than collecting
    into the slot-indexed structure, would land the failing item out of
    position here -- and would do it only on the pooled verbs.
    """
    _skip_unless_engine_available(verb)
    operands = _build_batch(tmp_path, "corrupt", restore_modes)
    out_dir = tmp_path / "out"
    _, payload, _ = _drive(verb, operands, out_dir, threads=4)
    _key, rows = _collection(payload)
    observed = [row["input"] for row in rows]
    expected = [str(p) for p in operands]
    assert observed == expected, (
        f"{verb}: --threads 4 reordered the payload.\n"
        f"  expected: {expected}\n  observed: {observed}"
    )


# --------------------------------------------------------------------------- #
# AC7 / AC8 / AC9 — the boundaries that must hold.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac8_a_nonexistent_input_still_exits_4_before_any_work(verb: str, tmp_path: Path) -> None:
    """Exit 4 is unconditional and wins over any other usage error (``C5``).

    A property of how the command line was TYPED, not of what a file turned out
    to contain -- so it stays pre-flight. Moving this check inside the per-item
    guard would let the batch continue and exit 1, and would redden ``C5``.
    """
    _skip_unless_engine_available(verb)
    first = _good_pdf(tmp_path, "a")
    missing = tmp_path / "does-not-exist.pdf"
    last = _good_pdf(tmp_path, "c")
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, [first, missing, last], out_dir)
    assert exit_code == 4, f"{verb}: nonexistent input in the middle exited {exit_code}, not 4"
    assert "error" in payload, f"{verb}: expected the error envelope, got {sorted(payload)}"
    assert _walk(out_dir) == [], (
        f"{verb}: a nonexistent input must be refused BEFORE any earlier input is "
        f"processed; found {_walk(out_dir)}"
    )


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac8_a_directory_operand_still_exits_2_before_any_work(verb: str, tmp_path: Path) -> None:
    """A directory is a property of how the command was typed. Exit 2, pre-flight.

    ``ops/inspect.py`` states the reason in the donor itself: a pre-flight
    refusal means a twelve-file batch does not process eleven files before
    rejecting the twelfth.
    """
    _skip_unless_engine_available(verb)
    first = _good_pdf(tmp_path, "a")
    directory = tmp_path / "a-directory"
    directory.mkdir()
    last = _good_pdf(tmp_path, "c")
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, [first, directory, last], out_dir)
    assert exit_code == 2, f"{verb}: directory operand in the middle exited {exit_code}, not 2"
    assert "error" in payload
    assert _walk(out_dir) == [], (
        f"{verb}: a directory operand must be refused before any earlier input is "
        f"processed; found {_walk(out_dir)}"
    )


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac9_a_single_input_run_keeps_its_own_exit_code_and_envelope(
    verb: str, tmp_path: Path
) -> None:
    """One input, one bad input: the item's OWN code, not the batch's 1.

    ``cli/cmd_info.py``: *"A single-input run reports that item's own code,
    which is what makes 1/4/6 distinguishable at all."* Applying the multi-input
    envelope unconditionally would collapse this to 1.
    """
    _skip_unless_engine_available(verb)
    missing = tmp_path / "nope.pdf"
    out_dir = tmp_path / "out"
    exit_code, _payload, _ = _drive(verb, [missing], out_dir)
    assert exit_code == 4, (
        f"{verb}: a SINGLE nonexistent input must still exit 4, not the batch's 1; got {exit_code}"
    )


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac9_a_single_unreadable_input_keeps_the_error_envelope(
    verb: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """The ENVELOPE, not only the exit code — the half an exit-code-only arm misses.

    A single-operand run has no other input a per-item failure could cost, so
    recording rather than raising would change this run's shape for nothing.
    Emitting the operation envelope here collapses the run's exit code to the
    batch aggregate and makes the exit-`1`, exit-`4` and exit-`6` outcomes
    indistinguishable from outside. `C18` is the standing guard on this; this
    arm states the same requirement in the file that changed the behaviour.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: mode 000 does not deny reads, so this arm cannot be built")
    _skip_unless_engine_available(verb)
    only = _unreadable_pdf(tmp_path, "only")
    restore_modes.append(only)
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, [only], out_dir)
    assert exit_code == 1, f"{verb}: a single unreadable input must exit 1, got {exit_code}"
    assert "error" in payload, (
        f"{verb}: a SINGLE-input run must keep the ERROR envelope; got {sorted(payload)}"
    )
    assert not any(key in payload for key in _COLLECTION_KEYS), (
        f"{verb}: a single-input failure must not be rendered as a collection"
    )


def _path_without(binaries: set[str], root: Path) -> str:
    """A `PATH` with *binaries* removed, built by symlink — the host is untouched.

    The same mechanism `tests/conftest.py`'s `PDF_TOOLKIT_TEST_HIDE_ENGINES`
    shim uses, applied to ONE subprocess instead of the whole session, so this
    arm can drive the engine-missing path on a host where the engine is
    present. No system binary is renamed, moved or chmod-ed.
    """
    shim = root / "no-engine-bin"
    shim.mkdir(exist_ok=True)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry)
        if not directory.is_dir():
            continue
        try:
            candidates = list(directory.iterdir())
        except OSError:
            continue
        for exe in candidates:
            if exe.name in binaries:
                continue
            link = shim / exe.name
            if link.exists():
                continue
            try:
                link.symlink_to(exe)
            except OSError:
                continue
    return str(shim)


def test_ac7_run_scoped_engine_missing_still_aborts_with_the_error_envelope(
    tmp_path: Path,
) -> None:
    """An absent engine fails identically for every input, so it is not per-item.

    Rendering it as a row per input would replace one accurate diagnosis with
    copies of it AND change the exit code from the engine-missing code to the
    batch's aggregate — a public exit-table change wearing a bug fix's clothes.

    **This arm hides the engine rather than skipping when it is present.** A
    skipped arm is not agreement, and skipping here would also be invisible in
    the wrong direction: the reason text would name an engine, so the
    engines-present configuration — which asserts that NO engine-gated skip
    survives when the engines are installed — would count it and fail. An arm
    that can build its own precondition should build it.
    """
    first = _good_pdf(tmp_path, "a")
    second = _good_pdf(tmp_path, "b")
    third = _good_pdf(tmp_path, "c")
    out_dir = tmp_path / "out"
    env = dict(os.environ)
    env["PATH"] = _path_without({"soffice", "libreoffice"}, tmp_path)
    argv = [
        "convert",
        str(first),
        str(second),
        str(third),
        "--out-dir",
        str(out_dir),
        "-y",
        "-o",
        "json",
    ]
    result = run_cli(*argv, env=env)
    payload = json.loads(result.stdout)
    assert result.returncode == 3, (
        f"engine-missing must stay exit 3, got {result.returncode}: "
        f"{result.stdout[:300]}{result.stderr[-300:]}"
    )
    assert "error" in payload, f"expected the error envelope, got {sorted(payload)}"
    assert payload["error"]["kind"] == "engine_missing"
    assert not any(key in payload for key in _COLLECTION_KEYS), (
        "a run-scoped class must NOT be rendered as per-input items"
    )
    assert _walk(out_dir) == [], "an engine-missing run must not write an artifact"


# --------------------------------------------------------------------------- #
# AC10 — `--dry-run`, on both X-185 observables.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", BATCH_VERBS)
def test_ac10_unreadable_arm_dry_run_mirrors_the_real_run(
    verb: str, tmp_path: Path, restore_modes: list[Path]
) -> None:
    """OR-7 / X-185: BOTH observables — exit code AND envelope shape.

    Achievable for this kind because operand classification runs no engine, and
    the classification now sits inside the guard on both paths. The CORRUPT kind
    is deliberately not asserted here: a dry run that does not open a document
    cannot know a document is corrupt, and closing that gap would require the
    preview to parse -- which this product's dry-run contract forbids. That
    divergence is measured and reported, not silently closed.
    """
    if os.geteuid() == 0:
        pytest.skip("running as root: mode 000 does not deny reads, so this arm cannot be built")
    _skip_unless_engine_available(verb)

    real_root = tmp_path / "real"
    real_root.mkdir()
    real_operands = _build_batch(real_root, "unreadable", restore_modes)
    real_code, real_payload, _ = _drive(verb, real_operands, real_root / "out")

    dry_root = tmp_path / "dry"
    dry_root.mkdir()
    dry_operands = _build_batch(dry_root, "unreadable", restore_modes)
    dry_code, dry_payload, _ = _drive(verb, dry_operands, dry_root / "out", dry_run=True)

    assert dry_code == real_code, (
        f"{verb}: --dry-run exited {dry_code}, the real run exited {real_code}"
    )
    real_key, real_rows = _collection(real_payload)
    dry_key, dry_rows = _collection(dry_payload)
    assert dry_key == real_key, f"{verb}: collection key {dry_key!r} vs {real_key!r}"
    assert len(dry_rows) == len(real_rows), (
        f"{verb}: {len(dry_rows)} predicted items vs {len(real_rows)} real items"
    )
    assert [r["ok"] for r in dry_rows] == [r["ok"] for r in real_rows], (
        f"{verb}: ok flags diverge -- dry {[r['ok'] for r in dry_rows]} "
        f"vs real {[r['ok'] for r in real_rows]}"
    )
    assert [Path(r["input"]).name for r in dry_rows] == [
        Path(r["input"]).name for r in real_rows
    ], f"{verb}: input names or their order diverge between the preview and the real run"


# --------------------------------------------------------------------------- #
# AC13 / AC14 — the mechanization that keeps the boundary honest.
# --------------------------------------------------------------------------- #

_BATCH_MODULE: Final[Path] = (
    Path(__file__).resolve().parent.parent / "src" / "pdf_toolkit" / "ops" / "batch.py"
)

#: The six ops modules that must REACH the one guard rather than carry a copy.
_GUARD_CONSUMERS: Final[tuple[str, ...]] = (
    "optimize.py",
    "pages.py",
    "textract.py",
    "raster.py",
    "ocr.py",
    "office.py",
)


def test_ac13_the_guard_never_catches_a_broad_exception() -> None:
    """AST-walked, not grepped — a comment mentioning ``except Exception`` is not a catch.

    A broad catch would swallow the bare ``OSError``/``PdfError`` escapes that
    are a separate, still-open read-seam item's ENTIRE evidence base: it would
    make that item's reds disappear while this one went green. The boundary is
    mechanical -- a ``PdfToolkitError`` subclass reaching the guard belongs
    here; a bare ``OSError`` escaping to a traceback does not, and must keep
    escaping so it stays measurable.
    """
    tree = ast.parse(_BATCH_MODULE.read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            offenders.append(f"bare `except:` at line {node.lineno}")
            continue
        for name in _handler_names(node.type):
            if name in {"Exception", "BaseException"}:
                offenders.append(f"`except {name}` at line {node.lineno}")
    assert not offenders, (
        f"{_BATCH_MODULE.name} must never catch broadly: {offenders}. "
        "A broad catch annexes the read-seam item and destroys its evidence."
    )


def _handler_names(node: ast.expr) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _handler_names(element)]
    return []


def test_ac13_the_item_scoped_set_is_exactly_the_two_declared_classes() -> None:
    """The caught tuple IS the boundary; widening it changes a public exit code.

    Widening to ``PdfToolkitError`` would turn an absent engine from exit 3 into
    exit 1 on ``ocr``, and a refusal from exit 5 into exit 1 everywhere.
    """
    from pdf_toolkit.errors import AuthError, FailureError
    from pdf_toolkit.ops.batch import ITEM_SCOPED_ERRORS

    assert ITEM_SCOPED_ERRORS == (FailureError, AuthError), (
        f"the item-scoped set moved: {ITEM_SCOPED_ERRORS}. "
        "UsageError (2), EngineMissingError (3), NoInputError (4) and the "
        "RefusedError family (5) are run-scoped verdicts, not per-input ones."
    )


def test_ac13_the_guard_handler_catches_the_declared_set_and_nothing_wider() -> None:
    """The guard's own handler, located by AST, catches ``ITEM_SCOPED_ERRORS``."""
    tree = ast.parse(_BATCH_MODULE.read_text())
    guards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "guard"
    ]
    assert len(guards) == 1, f"expected exactly one `guard` in {_BATCH_MODULE.name}"
    handlers = [n for n in ast.walk(guards[0]) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1, f"the guard must have exactly one handler, found {len(handlers)}"
    assert handlers[0].type is not None
    assert _handler_names(handlers[0].type) == ["ITEM_SCOPED_ERRORS"], (
        "the guard must catch the DECLARED tuple, so widening it is a one-line "
        f"visible change; found {ast.dump(handlers[0].type)}"
    )


@pytest.mark.parametrize("module", _GUARD_CONSUMERS)
def test_ac14_every_batch_ops_module_reaches_the_one_guard(module: str) -> None:
    """One implementation, not six.

    ``cli/common.py``'s ``operand_argument()`` records that the same decision
    *"was wrong twenty-three times in a row and the mechanism that made it wrong
    was a default"*. Six private copies is how the twenty-fourth happens.
    """
    path = _BATCH_MODULE.parent / module
    tree = ast.parse(path.read_text())
    imports_guard = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "pdf_toolkit.ops.batch"
        and any(alias.name in {"BatchLedger", "preflight_operands"} for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imports_guard, (
        f"ops/{module} does not reach ops/batch.py -- either it grew a private "
        "copy of the guard, or its batch verb lost its continuation entirely"
    )


@pytest.mark.parametrize("module", _GUARD_CONSUMERS)
def test_ac14_no_batch_ops_module_carries_its_own_item_scoped_handler(module: str) -> None:
    """A private ``except FailureError`` around item construction IS the second copy."""
    path = _BATCH_MODULE.parent / module
    tree = ast.parse(path.read_text())
    offenders = [
        f"line {node.lineno}: except {_handler_names(node.type)}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and {"FailureError", "AuthError", "SourceUnreadableError"} & set(_handler_names(node.type))
    ]
    assert not offenders, (
        f"ops/{module} catches an item-scoped class itself: {offenders}. "
        "The run/item boundary is decided in ops/batch.py, once."
    )
