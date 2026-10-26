"""PDF-143 D6 -- the four "In 1.2" cells of ``## Upgrading to 1.2`` are bound to driven behaviour.

THE GAP (ledger ``99ce1f45b9``, backlog ``B-480``). Falsifying all four cells (exit ``5`` -> ``1``,
``1`` -> ``6``, "exits ``0`` on every verb", "the whole run still ends with the error
envelope") stayed green: only the row count and the verb lists were bound (PDF-127 AC14,
PDF-128 AC10). Nothing read an In-1.2 cell's CLAIM.

THE BINDING. The claim lives in the In-1.2 cell and is PARSED out of it (a clause regex per
figure); the truth is what the product does when DRIVEN. They are compared; a disagreement reds
and names the verb. A clause that is missing from a cell is a red, never a skip. A row that no
binder claims, a binder that claims no row, and a backticked integer that no binder consumes all
red in ``test_every_upgrading_1_2_row_and_figure_is_bound`` -- so a new row or a new figure cannot
sit in the table unbound.

THE IDENTITY of a row is its In-1.1 cell (a row is claimed by a predicate over it). The In-1.1
column is history -- a 1.1 binary cannot be driven in-loop -- so it is only read for identity and
for the verb list it names. Populations are DERIVED (the row's own cell, the operand metavars,
the option table) and never listed here; a frozen list is the B-372 failure.

INDEPENDENCE. Fixtures are built here with pikepdf. The module may borrow PDF-128's per-verb
ARGUMENT tables (they say how to call a verb, not what it answers) and may not borrow its
expected-outcome literals. The engine-blind verb is spelt once, in one module-level name
(``tests/test_engine_gating_census.py``).
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NamedTuple

import pikepdf
import pytest
import typer.main

TESTS_DIR = Path(__file__).resolve().parents[1]
for _path in (TESTS_DIR, Path(__file__).resolve().parent):
    if str(_path) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(_path))

from test_pdf128_batch_auth_and_owner_only_password import (  # noqa: E402  (argument tables only)
    NO_OUTPUT,
    OUT_DIR_ONLY,
    TAIL,
)

import fs_snapshot  # noqa: E402
from pdf_tooling.cli.main import app  # noqa: E402
from registry import discover_verbs, operand_metavars, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
README: Final[Path] = REPO_ROOT / "README.md"
SECTION_HEADING: Final[str] = "## Upgrading to 1.2"
PASSWORD_FLAG: Final[str] = "--password-file"
DECRYPT_FLAG: Final[str] = "--allow-decrypted-output"
HAS_TESSERACT: Final[bool] = shutil.which("tesseract") is not None
#: The engine-blind verb lives in ONE module-level name so that no test body carries its
#: literal (tests/test_engine_gating_census.py).
ENGINE_BLIND: Final[str] = "ocr"
ENGINE_REASON: Final[str] = "tesseract is absent: this cell would reach the OCR engine"

# --------------------------------------------------------------------------- #
# The README section, parsed
# --------------------------------------------------------------------------- #


class Row(NamedTuple):
    in_1_1: str
    in_1_2: str


def section_text(readme: str) -> str:
    assert SECTION_HEADING in readme, f"README carries no `{SECTION_HEADING}` section"
    return readme.split(SECTION_HEADING, 1)[1].split("\n## ", 1)[0]


def parse_rows(section: str) -> list[Row]:
    """Pipe lines, minus the header and the separator."""
    pipes = [line for line in section.splitlines() if line.lstrip().startswith("|")]
    assert len(pipes) >= 3, "the section carries no table body"
    rows: list[Row] = []
    for line in pipes[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) >= 2, f"a table row without two cells: {line!r}"
        rows.append(Row(cells[0], cells[1]))
    return rows


def live_rows() -> list[Row]:
    return parse_rows(section_text(README.read_text()))


def backticked(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def backticked_integers(text: str) -> list[int]:
    return [int(token) for token in backticked(text) if token.isdigit()]


def clause(cell: str, pattern: str, what: str) -> int:
    """One figure out of a cell. A missing clause is a red, never a skip."""
    match = re.search(pattern, cell)
    assert match is not None, f"the cell no longer states {what} (looked for /{pattern}/): {cell!r}"
    return int(match.group(1))


def phrase(cell: str, text: str, what: str) -> None:
    assert text in cell, f"the cell no longer states {what} (looked for {text!r}): {cell!r}"


# --------------------------------------------------------------------------- #
# Clause parsers: In-1.2 cell -> {name: figure}. Pure, so the completeness arm can run them
# without driving anything.
# --------------------------------------------------------------------------- #


def parse_clear_all(cell: str) -> dict[str, int]:
    claims = {
        "refusal": clause(cell, r"refused at exit `(\d+)`", "the refusal code"),
        "dry": clause(cell, r"`--dry-run` predicts the same `(\d+)`", "the dry-run prediction"),
    }
    phrase(cell, "no output", "that nothing is written")
    phrase(cell, "no `.bak`", "that no sidecar is left")
    phrase(cell, "byte-identical", "that the input is untouched")
    return claims


def parse_batch_exit(cell: str) -> dict[str, int]:
    return {
        "run": clause(
            cell, r"it exits `(\d+)`, like any other failing input", "the batch run code"
        ),
        "row": clause(cell, r"row still carries `exit_code` `(\d+)`", "the failing row's code"),
        "single": clause(
            cell, r"A single-input run still exits `(\d+)`", "the single-input run code"
        ),
    }


def parse_owner_only(cell: str) -> dict[str, int]:
    return {
        "every": clause(cell, r"it exits `(\d+)` on every verb", "the every-verb code"),
        "row": clause(cell, r"that input's row fails with `(\d+)`", "the batch row code"),
        "run": clause(cell, r"the run exits `(\d+)`", "the batch run code"),
    }


PER_ITEM_PHRASES: Final[tuple[str, ...]] = ("failed row", "other inputs are processed")
RUN_LEVEL_PHRASES: Final[tuple[str, ...]] = ("error envelope",)


def parse_text_tables(cell: str) -> dict[str, int]:
    """The cell carries no figure; its claim is an outcome, checked against a closed vocabulary."""
    assert any(p in cell for p in (*PER_ITEM_PHRASES, *RUN_LEVEL_PHRASES)), (
        f"the cell states no recognisable outcome (per-item: {PER_ITEM_PHRASES}, "
        f"run-level: {RUN_LEVEL_PHRASES}): {cell!r}"
    )
    return {}


# --------------------------------------------------------------------------- #
# The world: fixtures + driver
# --------------------------------------------------------------------------- #


def _blank(path: Path, encryption: pikepdf.Encryption | None = None) -> None:
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    pdf.save(path, encryption=encryption)


def _build_e(path: Path) -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Author"] = "E-AUTHOR"
    with pdf.open_metadata() as meta:
        meta["dc:creator"] = ["E-CREATOR"]
        meta["dc:title"] = "E-TITLE"
    pdf.save(path)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Run(NamedTuple):
    rc: int
    env: dict[str, Any]
    stdout: str
    stderr: str
    dest: Path


def _leaf_commands() -> dict[str, Any]:
    """Every leaf command off the live click tree, keyed by space-joined verb name."""
    found: dict[str, Any] = {}

    def _walk(cmd: Any, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        found[" ".join(path)] = cmd

    _walk(typer.main.get_command(app), ())
    return found


def declares(verb: str, option: str) -> bool:
    """Whether the verb's OPTION TABLE (never its help prose) has *option*."""
    return any(option in getattr(p, "opts", ()) for p in _leaf_commands()[verb].params)


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.env, _roots = fs_snapshot.redirected_environment(root)
        self.fx = root / "fx"
        self.fx.mkdir()
        _blank(self.fx / "plain.pdf")
        _blank(self.fx / "plain-b.pdf")
        _blank(self.fx / "owner.pdf", pikepdf.Encryption(user="", owner="o-pw", R=6))
        _blank(self.fx / "user.pdf", pikepdf.Encryption(user="u-pw", owner="o-pw", R=6))
        (self.fx / "x.pw").write_text("x-pw\n")
        (self.fx / "x.pw").chmod(0o600)
        self._n = 0

    def _cell(self) -> Path:
        self._n += 1
        dest = self.root / "cells" / f"c{self._n:04d}"
        dest.mkdir(parents=True)
        return dest

    def _run(self, verb: str, argv: list[str], dest: Path) -> Run:
        proc = run_cli(verb, *argv, env=self.env, cwd=dest)
        text = proc.stdout.strip()
        try:
            env = json.loads(text) if text.startswith("{") else {}
        except json.JSONDecodeError:  # pragma: no cover - the assertions then name it
            env = {}
        return Run(proc.returncode, env, proc.stdout, proc.stderr, dest)

    def drive(
        self,
        verb: str,
        inputs: tuple[str, ...],
        *,
        pw: str | None = None,
        batch: bool = False,
    ) -> Run:
        """One CLI run in a private directory: the verb's tail, its output flag, the opt-in
        where its option table declares one, ``-o json``."""
        dest = self._cell()
        argv = [str(self.fx / name) for name in inputs]
        assert verb in TAIL, f"PDF-128's argument table has no tail for {verb!r}: add it there"
        argv += list(TAIL[verb])
        if verb == "stamp":
            argv += ["--from", str(self.fx / "plain-b.pdf")]
        if verb not in NO_OUTPUT:
            if batch or verb in OUT_DIR_ONLY:
                argv += ["--out-dir", str(dest / "d")]
            else:
                argv += ["-O", str(dest / "out.pdf")]
        if pw is not None:
            argv += [PASSWORD_FLAG, str(self.fx / pw)]
        if declares(verb, DECRYPT_FLAG):
            argv.append(DECRYPT_FLAG)
        argv += ["-o", "json"]
        return self._run(verb, argv, dest)

    def clear_all(self, *, dry: bool) -> tuple[Run, list[str]]:
        """``meta set E.pdf --clear-all --in-place`` against a fresh E.pdf; the complaints are
        the three 'nothing happened' claims, checked against the filesystem."""
        dest = self._cell()
        target = _build_e(dest / "E.pdf")
        before_sha = _sha(target)
        before_listing = sorted(p.name for p in dest.iterdir())
        argv = [str(target), "--clear-all", "--in-place"]
        if dry:
            argv.append("--dry-run")
        run = self._run("meta set", [*argv, "-o", "json"], dest)
        complaints: list[str] = []
        if (dest / "E.pdf.bak").exists():
            complaints.append("a `.bak` sidecar exists beside the input (cell: no `.bak`)")
        if _sha(target) != before_sha:
            complaints.append("the input is not byte-identical (cell: byte-identical)")
        after_listing = sorted(p.name for p in dest.iterdir())
        if after_listing != before_listing:
            complaints.append(
                f"the directory listing moved {before_listing} -> {after_listing} (cell: no output)"
            )
        return run, complaints


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    return World(tmp_path_factory.mktemp("pdf143"))


def engine_available(verb: str) -> bool:
    return not (verb == ENGINE_BLIND and not HAS_TESSERACT)


# --------------------------------------------------------------------------- #
# Binders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Binder:
    name: str
    claims: Callable[[str], bool]
    """Predicate over the row's In-1.1 cell: the row's identity."""
    parse: Callable[[str], dict[str, int]]
    check: Callable[[World, Row], list[str]]
    """Drive the product and compare with the cell. Returns every disagreement."""


def verbs_in_parenthesis(cell: str) -> list[str]:
    match = re.search(r"\(([^)]*)\)", cell)
    assert match is not None, f"the In-1.1 cell names no parenthesised verb list: {cell!r}"
    verbs = backticked(match.group(1))
    assert verbs, f"the parenthesised verb list is empty: {cell!r}"
    return verbs


def check_clear_all(world: World, row: Row) -> list[str]:
    claims = parse_clear_all(row.in_1_2)
    complaints: list[str] = []
    real, real_complaints = world.clear_all(dry=False)
    dry, dry_complaints = world.clear_all(dry=True)
    complaints += [f"real run: {c}" for c in real_complaints]
    complaints += [f"dry run: {c}" for c in dry_complaints]
    if claims["refusal"] != real.rc:
        complaints.append(
            f"the cell states refusal `{claims['refusal']}`, the product exited `{real.rc}`"
        )
    if claims["dry"] != dry.rc:
        complaints.append(
            f"the cell states the dry prediction `{claims['dry']}`, the dry run exited `{dry.rc}`"
        )
    if claims["dry"] != claims["refusal"]:
        complaints.append(
            f"the cell says --dry-run predicts the SAME code but states `{claims['dry']}` "
            f"against refusal `{claims['refusal']}`"
        )
    return complaints


def failing_row_code(run: Run) -> int | None:
    """The code of the single failing row. ``items[].exit_code``; when that is absent (the
    ``info`` envelope), ``documents[].error.code``. ``None`` = neither shape."""
    items = [r for r in run.env.get("items", []) if isinstance(r, dict) and not r.get("ok")]
    if len(items) != 1:
        return None
    code = items[0].get("exit_code")
    if isinstance(code, int):
        return code
    docs = [d for d in run.env.get("documents", []) if isinstance(d, dict) and not d.get("ok")]
    if len(docs) == 1 and isinstance(docs[0].get("error"), dict):
        return docs[0]["error"].get("code")
    return None


def check_batch_exit(world: World, row: Row) -> list[str]:
    claims = parse_batch_exit(row.in_1_2)
    verbs = verbs_in_parenthesis(row.in_1_1)
    complaints: list[str] = []
    driven = 0
    for verb in verbs:
        if not engine_available(verb):
            print(f"batch-exit: {verb} skipped ({ENGINE_REASON})")
            continue
        driven += 1
        batch = world.drive(verb, ("plain.pdf", "user.pdf"), batch=True)
        single = world.drive(verb, ("user.pdf",))
        if batch.rc != claims["run"]:
            complaints.append(
                f"{verb}: the cell states run code `{claims['run']}`, the product's batch exited "
                f"`{batch.rc}`"
            )
        observed_row = failing_row_code(batch)
        if observed_row != claims["row"]:
            complaints.append(
                f"{verb}: the cell states row code `{claims['row']}`, the failing row carries "
                f"`{observed_row}`"
            )
        if single.rc != claims["single"]:
            complaints.append(
                f"{verb}: the cell states single-input code `{claims['single']}`, the product "
                f"exited `{single.rc}`"
            )
    assert driven > 0, "no verb of the row's In-1.1 list could be driven"
    return complaints


def owner_only_populations() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(every-verb population, batch subset), derived exactly as PDF-128 AC7 does and
    cross-checked against the OPTION TABLE, never help prose."""
    metavars = operand_metavars()
    every: list[str] = []
    batch: list[str] = []
    for verb in discover_verbs():
        if verb.is_group:
            continue
        metavar = metavars.get(verb.name)
        # `merge` declares its operands without a metavar; `encrypt` owns a second password flag.
        member = (metavar is not None and metavar.startswith("PDF")) or verb.name == "merge"
        if not member or verb.name == "encrypt":
            continue
        every.append(verb.name)
        if metavar == "PDF...":
            batch.append(verb.name)
    missing = [v for v in every if not declares(v, PASSWORD_FLAG)]
    assert missing == [], f"verbs of the population with no {PASSWORD_FLAG} option: {missing}"
    return tuple(every), tuple(batch)


def check_owner_only(world: World, row: Row) -> list[str]:
    claims = parse_owner_only(row.in_1_2)
    every, batch_subset = owner_only_populations()
    assert len(every) > 0 and len(batch_subset) > 0
    assert "merge" in every and "merge" not in batch_subset, (
        "merge's operands form one combined document: an auth failure fails the whole run, "
        "which is not the cell's batch"
    )
    print(f"owner-only: {len(every)} every-verb members, {len(batch_subset)} batch members")
    complaints: list[str] = []
    for verb in every:
        if not engine_available(verb):
            print(f"owner-only: {verb} skipped ({ENGINE_REASON})")
            continue
        run = world.drive(verb, ("owner.pdf",), pw="x.pw")
        if run.rc != claims["every"]:
            complaints.append(
                f"{verb}: the cell states `{claims['every']}` on every verb, the product exited "
                f"`{run.rc}`"
            )
    for verb in batch_subset:
        if not engine_available(verb):
            continue
        run = world.drive(verb, ("plain.pdf", "owner.pdf"), pw="x.pw", batch=True)
        if run.rc != claims["run"]:
            complaints.append(
                f"{verb}: the cell states batch run code `{claims['run']}`, the product's batch "
                f"exited `{run.rc}`"
            )
        if "error" in run.env:
            complaints.append(f"{verb}: the batch ended with a top-level error envelope")
            continue
        observed_row = failing_row_code(run)
        if observed_row is None:
            complaints.append(
                f"{verb}: the envelope has neither exactly one failing items[] row nor one "
                "failing documents[] entry"
            )
        elif observed_row != claims["row"]:
            complaints.append(
                f"{verb}: the cell states batch row code `{claims['row']}`, the failing row "
                f"carries `{observed_row}`"
            )
    return complaints


def observed_text_tables_outcome(run: Run) -> str:
    if "error" in run.env:
        return "run-level"
    rows = {Path(r["input"]).name: r for r in run.env.get("items", []) if isinstance(r, dict)}
    owner, plain = rows.get("owner.pdf"), rows.get("plain.pdf")
    if owner and not owner["ok"] and plain and plain["ok"]:
        return "per-item"
    raise AssertionError(f"neither a run-level error nor a per-item outcome: {run.stdout[:300]!r}")


def check_text_tables(world: World, row: Row) -> list[str]:
    parse_text_tables(row.in_1_2)
    verbs = backticked(row.in_1_1)
    assert verbs, f"the In-1.1 cell names no verb: {row.in_1_1!r}"
    complaints: list[str] = []
    for verb in verbs:
        if not engine_available(verb):
            continue
        run = world.drive(verb, ("owner.pdf", "plain.pdf"), pw="x.pw", batch=True)
        outcome = observed_text_tables_outcome(run)
        wanted, forbidden = (
            (PER_ITEM_PHRASES, RUN_LEVEL_PHRASES)
            if outcome == "per-item"
            else (RUN_LEVEL_PHRASES, PER_ITEM_PHRASES)
        )
        lacking = [p for p in wanted if p not in row.in_1_2]
        carrying = [p for p in forbidden if p in row.in_1_2]
        if lacking or carrying:
            complaints.append(
                f"{verb}: the observed outcome is {outcome}; the cell lacks {lacking} and "
                f"carries the other outcome's {carrying}"
            )
    return complaints


BINDERS: Final[tuple[Binder, ...]] = (
    Binder(
        "clear-all",
        lambda cell: "`meta set --clear-all --in-place`" in cell,
        parse_clear_all,
        check_clear_all,
    ),
    Binder(
        "batch-exit",
        lambda cell: cell.startswith("a multi-input run (") and "exited `6`" in cell,
        parse_batch_exit,
        check_batch_exit,
    ),
    Binder(
        "owner-only",
        lambda cell: "owner-only encrypted input with a `--password-file`" in cell,
        parse_owner_only,
        check_owner_only,
    ),
    Binder(
        "text-tables",
        lambda cell: "multi-input `text` or `tables` run" in cell,
        parse_text_tables,
        check_text_tables,
    ),
)


def claimed_rows(rows: list[Row], binder: Binder) -> list[Row]:
    return [row for row in rows if binder.claims(row.in_1_1)]


def completeness_complaints(rows: list[Row], binders: tuple[Binder, ...]) -> list[str]:
    """Pure over its inputs, so the red controls feed it scratch rows."""
    complaints: list[str] = []
    for row in rows:
        claimers = [b.name for b in binders if b.claims(row.in_1_1)]
        if len(claimers) != 1:
            complaints.append(
                f"row {row.in_1_1[:60]!r} is claimed by {len(claimers)} binders ({claimers}); "
                "exactly one is required"
            )
    for binder in binders:
        n = len(claimed_rows(rows, binder))
        if n != 1:
            complaints.append(f"binder {binder.name} claims {n} rows; exactly one is required")
    for row in rows:
        for binder in binders:
            if not binder.claims(row.in_1_1):
                continue
            try:
                consumed = collections.Counter(binder.parse(row.in_1_2).values())
            except AssertionError as err:
                complaints.append(f"{binder.name}: {err}")
                continue
            present = collections.Counter(backticked_integers(row.in_1_2))
            for figure, count in (present - consumed).items():
                complaints.append(
                    f"unbound figure `{figure}` in the In-1.2 cell of the {binder.name} row "
                    f"({count} occurrence(s) no clause consumes)"
                )
    return complaints


# --------------------------------------------------------------------------- #
# Arms
# --------------------------------------------------------------------------- #


def test_every_upgrading_1_2_row_and_figure_is_bound() -> None:
    """AC7. Each README row is claimed by exactly one binder, each binder by exactly one row, and
    no backticked integer in an In-1.2 cell is left unconsumed."""
    assert completeness_complaints(live_rows(), BINDERS) == []


def test_the_completeness_arm_can_fail() -> None:
    """AC7's red control, on scratch rows: an extra row, an extra figure, a dropped clause."""
    rows = live_rows()
    extra_row = [*rows, Row("a brand new row", "it exits `9`")]
    assert any("claimed by 0 binders" in c for c in completeness_complaints(extra_row, BINDERS))
    clear_all = next(r for r in rows if BINDERS[0].claims(r.in_1_1))
    poisoned = [
        Row(r.in_1_1, r.in_1_2 + "; it then exits `7`") if r is clear_all else r for r in rows
    ]
    assert any("unbound figure `7`" in c for c in completeness_complaints(poisoned, BINDERS))
    dropped = [
        Row(r.in_1_1, r.in_1_2.replace("refused at exit", "turned away at exit"))
        if r is clear_all
        else r
        for r in rows
    ]
    assert any(
        "no longer states the refusal code" in c for c in completeness_complaints(dropped, BINDERS)
    )
    assert any("claims 0 rows" in c for c in completeness_complaints(rows[:-1], BINDERS))


@pytest.mark.parametrize("binder", [pytest.param(b, id=b.name) for b in BINDERS])
def test_the_in_1_2_cell_matches_the_product(binder: Binder, world: World) -> None:
    """AC8-AC11. The cell's claims, parsed out of the live README, equal what the product does
    when driven."""
    rows = claimed_rows(live_rows(), binder)
    assert len(rows) == 1, f"binder {binder.name} claims {len(rows)} rows; exactly one is required"
    complaints = binder.check(world, rows[0])
    assert complaints == [], "\n".join(complaints)
