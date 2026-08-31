"""``convert`` -- Office document to PDF via headless LibreOffice (PDF-15).

Framework-free per L2: no ``typer``/``click`` import, and **no engine library
import either** -- there is no engine library to import for this verb at all
(``soffice`` is driven entirely as an external process, never as a Python
binding); the port boundary crosses only plain ``bytes``/``Path`` values.
This module prints nothing and calls no ``sys.exit``.

D6 -- exit 0 with no output file is a FAILURE
----------------------------------------------
LibreOffice frequently exits 0 having converted nothing (an unsupported
input shape, a corrupt document it silently gives up on). Success here is
measured, never assumed: the adapter (``adapters/soffice_office.py``)
already refuses (``FailureError``, exit 1) when the expected output file
does not exist or is empty, so this module never has to re-check the
adapter's own promise -- it only reads the bytes back and hands them to
``AtomicWriter``.

LibreOffice NEVER writes to the user's target
------------------------------------------------
The adapter converts into a private, per-invocation ``safety.atomic.
ScratchDir`` (isolated ``-env:UserInstallation`` profile + a private
``--outdir``, Design §D6); this module reads the resulting bytes and writes
them through the ONE chokepoint, exactly like every other producing verb.
That is what keeps ``--dry-run`` pure, ``-f``/no-clobber meaningful, and a
failed conversion from leaving a half-file (or someone else's stray
``<stem>.pdf``) at the destination.

Nothing here writes directly. Every byte reaches disk through
``safety.AtomicWriter``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, PdfToolkitError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ports.office import office_binary_present, require_office
from pdf_toolkit.safety.atomic import AtomicWriter, ScratchDir, plan_output_set
from pdf_toolkit.safety.naming import render_name
from pdf_toolkit.safety.paths import canonical, check_output_collisions, ensure_destination_writable
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_CONVERT_NAME_TEMPLATE",
    "DEFAULT_TIMEOUT_S",
    "FILTER_RE",
    "VERB_CONVERT",
    "convert_run",
    "resolve_convert_targets",
    "validate_filter",
]

VERB_CONVERT: Final[str] = "convert"

#: PLAN.md §5.4 -- office 180 s/file default; overridable via `--timeout`.
DEFAULT_TIMEOUT_S: Final[float] = 180.0

#: D6 -- `--filter` shape, e.g. `writer_pdf_Export`.
FILTER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")

#: `convert --out-dir`'s default filename template.
DEFAULT_CONVERT_NAME_TEMPLATE: Final[str] = "{stem}.pdf"

_NAME_WITHOUT_OUT_DIR: Final[str] = (
    "--name templates a filename inside --out-dir; pass --out-dir or -O to name one file"
)


def validate_filter(filter_name: str | None) -> None:
    """D6 -- `--filter` shape validation, exit 2. Called from the CLI layer,
    exposed here so the shape rule lives beside the argv it feeds."""
    if filter_name is not None and not FILTER_RE.match(filter_name):
        raise UsageError(
            f"--filter {filter_name!r} is not a valid LibreOffice filter name "
            f"(expected letters, digits and underscores only)"
        )


def _validate_sources(sources: Sequence[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a file, not a directory", path=str(source))


@dataclass(frozen=True, slots=True)
class _ConvertTarget:
    source: Path
    target: Path


def resolve_convert_targets(
    sources: Sequence[Path],
    *,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
) -> list[_ConvertTarget]:
    """Every source's own destination, computed before anything runs.

    Public (unlike ``compress``'s own private ``_resolve_compress_targets``):
    ``cli/cmd_office.py``'s B-076/B-079 confirmation check needs the SAME
    resolved target set, to decide whether a bulk ``--force`` run would
    actually clobber anything, before ``convert_run`` is ever called --
    reusing this function is what keeps that decision and the real run's
    own targets from being able to drift apart.
    """
    if output is not None:
        return [_ConvertTarget(source=sources[0], target=output)]
    if out_dir is None:  # pragma: no cover - the CLI layer requires a destination first
        raise UsageError("convert requires --output or --out-dir")
    template = name_template if name_template is not None else DEFAULT_CONVERT_NAME_TEMPLATE
    return [
        _ConvertTarget(
            source=source,
            target=render_name(template, out_dir=out_dir, stem=source.stem, ext="pdf", index=index),
        )
        for index, source in enumerate(sources, start=1)
    ]


@dataclass(frozen=True, slots=True)
class _FilesystemPlan:
    would_exit: int
    would_refuse: dict[str, object] | None
    message: str | None

    @property
    def refused(self) -> bool:
        return self.would_refuse is not None

    def detail(self) -> dict[str, object]:
        payload: dict[str, object] = {"would_exit": self.would_exit}
        if self.would_refuse is not None:
            payload["would_refuse"] = self.would_refuse
        return payload


def _plan_filesystem(
    targets: Sequence[Path], *, out_dir: Path | None, policy: SafetyPolicy
) -> _FilesystemPlan:
    """The filesystem tier, through the SHARED primitives only (B-054/X-67).

    **Deliberately widened beyond ``compress``'s own donor shape for the
    single-target (``-O``, ``out_dir is None``) case.** ``ensure_destination_
    writable``'s own docstring states the rule directly: "checked at plan
    time, before an engine runs... producing bytes and only then discovering
    there is nowhere to put them wastes the expensive half of the operation."
    For ``compress`` (a hard, always-present wheel dependency) skipping this
    in the real-run branch is merely wasteful; for ``convert`` -- whose
    engine can be legitimately ABSENT -- skipping it would additionally
    break OR-7's own ``dry == real`` guarantee for an unwritable destination
    (verified: without it, dry predicted **1** while a real run with
    ``soffice`` absent returned **3**, engine-missing, never having reached
    the writability check at all). So this runs the writability check for
    EVERY target in BOTH modes when ``out_dir is None`` -- raising
    immediately for a real run, exactly mirroring what ``AtomicWriter``'s
    own ``_plan()`` would have raised, but before ``require_office()`` is
    ever reached.
    """
    plan = plan_output_set(targets, out_dir=out_dir, policy=policy)
    if plan.refusal is not None:
        return _FilesystemPlan(
            would_exit=plan.would_exit,
            would_refuse=plan.would_refuse,
            message=plan.refusal.message,
        )
    if out_dir is None:
        for target in targets:
            try:
                ensure_destination_writable(canonical(target).parent, as_written=target.parent)
            except PdfToolkitError as refusal:
                if not policy.dry_run:
                    raise
                return _FilesystemPlan(
                    would_exit=refusal.exit_code,
                    would_refuse=refusal.to_dict(),
                    message=refusal.message,
                )
    return _FilesystemPlan(would_exit=plan.would_exit, would_refuse=None, message=None)


def convert_run(
    sources: Sequence[Path],
    *,
    filter_name: str | None,
    timeout: float,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    policy: SafetyPolicy,
) -> OperationResult:
    """Convert every source to PDF, one output per input, in input order.

    Under ``--dry-run`` nothing is spawned at all and nothing is written
    anywhere, yet the run is still predicted to the depth the real run
    resolves (OR-7 / D12.1, B-096): the filesystem tier first, then -- only
    when that tier did not already refuse -- whether the engine is even there,
    via the spawn-free :func:`~pdf_toolkit.ports.office.office_binary_present`.
    An ABSENT ``soffice`` therefore predicts and exits **3** exactly as the
    real run does, so ``convert --dry-run && convert`` short-circuits instead
    of green-lighting a run that then fails.
    """
    _validate_sources(sources)
    if name_template is not None and out_dir is None:
        raise UsageError(_NAME_WITHOUT_OUT_DIR)

    planned = resolve_convert_targets(
        sources, output=output, out_dir=out_dir, name_template=name_template
    )
    targets = [item.target for item in planned]
    check_output_collisions(targets)

    plan = _plan_filesystem(targets, out_dir=out_dir, policy=policy)

    if policy.dry_run:
        # OR-7 / D12.1 (B-096) -- an ABSENT engine is knowable at plan time, so
        # predict it HERE rather than reporting `would_exit: 0` and letting the
        # real run discover exit 3. `ops/ocr.py` demands its engine above its
        # own dry-run return for exactly this reason (`require_ocr()` at its
        # :328, above `if policy.dry_run:` at :331); this is that ordering,
        # expressed the one way `convert` can afford it (see below).
        #
        # `not plan.refused` keeps the FILESYSTEM tier's precedence, matching
        # what the real run does: `_plan_filesystem` RAISES for a real run
        # (`safety/atomic.py:319-320`, and its own widened check at `:182-183`,
        # both re-raise unless `policy.dry_run`), so a real run never reaches
        # its engine demand carrying a pending filesystem refusal. Getting this
        # order wrong regresses an unwritable destination from `dry 1 / real 1`
        # back to the `dry 1 / real 3` split `_plan_filesystem`'s own docstring
        # measured.
        #
        # Why the PRESENCE check and not `require_office()` itself: the latter
        # is spawn-free only when the binary is ABSENT. With `soffice` PRESENT,
        # resolution runs `soffice --version`, and that command CREATES
        # `$HOME/.config` (measured, LibreOffice 26.2.5.2) -- which would break
        # the non-negotiable `--dry-run` purity rule (`CLAUDE.md` rule 2), as
        # the C10 contract row proves against a redirected `HOME`. Presence is
        # the only fact exit 3 turns on, and `shutil.which` writes nothing, so
        # this branch is pure AND predictive rather than one or the other.
        if not plan.refused and not office_binary_present():
            # Provably zero-spawn on THIS branch: `probe()` short-circuits on
            # the very `shutil.which` just evaluated (`soffice_office.py::
            # probe`), so this raises `EngineMissingError` -- exit 3, with the
            # install hint and the `doctor` pointer -- through the ONE
            # chokepoint, never a second, drifting copy of that message.
            require_office()
        detail = plan.detail()
        items = tuple(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=not plan.refused,
                exit_code=plan.would_exit,
                message=("planned: convert" if not plan.refused else plan.message),
                bytes_before=item.source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for item in planned
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_CONVERT,
            dry_run=True,
            items=items,
            warnings=(),
            duration_ms=0,
        )

    engine = require_office()

    written: list[ItemResult] = []
    for item in planned:
        started = time.monotonic()
        bytes_before = item.source.stat().st_size
        with ScratchDir() as scratch_root:
            produced = engine.convert_to_pdf(
                item.source,
                scratch_dir=scratch_root,
                filter_name=filter_name,
                timeout=timeout,
            )
            output_bytes = produced.read_bytes()
            with AtomicWriter(item.target, policy=policy, kind="pdf") as atomic:
                atomic.stream.write(output_bytes)
        bytes_after = item.target.stat().st_size
        duration_ms = int((time.monotonic() - started) * 1000)
        written.append(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=True,
                exit_code=0,
                message=f"converted ({bytes_before} -> {bytes_after} bytes)",
                bytes_before=bytes_before,
                bytes_after=bytes_after,
                duration_ms=duration_ms,
                detail={"filter": filter_name} if filter_name else None,
            )
        )

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_CONVERT,
        dry_run=False,
        items=tuple(written),
        warnings=(),
        duration_ms=0,
    )
