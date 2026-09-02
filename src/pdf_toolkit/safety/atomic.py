"""``AtomicWriter`` — the one place in this product that writes.

Everything the tool promises about safety is a property of this file. Not of a
convention, not of a review checklist, and not of twenty verb authors each
remembering ``PLAN.md`` §5.2: an import-boundary test over ``src/`` fails the
build when any module outside this one performs a filesystem mutation, so the
chokepoint is structural. That is the whole reason this lands in wave 2, before
the verbs, rather than after them.

The shape a verb sees::

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        engine.save(writer.path)      # the engine writes to writer.path, only

``__enter__`` plans and opens; ``__exit__`` commits or unwinds. A verb never
chooses whether to consult the dry-run gate, because a verb never gets to reach
past the writer.

The seven steps, exactly (``PLAN.md`` §5.3)
-------------------------------------------
1. **Dry-run gate** — the statement immediately above ``_open_temp()``, which is
   the first genuinely *mutating* call. It is deliberately **not** the first
   statement of ``__enter__``: step 2 runs above it, in both modes. In a dry run
   the writer hands back an object whose ``.path`` raises — there is nothing to
   write to, so asking for somewhere to write is a bug the writer names
   immediately rather than a directory it silently invents.
2. **Plan** — resolve the destination, refuse an existing target without
   ``--force`` (exit 5), and fail early if the destination directory cannot
   accept a write (exit 1). Both happen before an engine runs, **and both are
   computed under ``--dry-run`` as well** (X-67). See "A dry run predicts the
   refusal" below; this is the ordering rule to read before touching
   ``__enter__``.
3. **Temp** — a temp file **beside the resolved destination**, never in the
   system temp directory. That co-location is not a preference; it is what makes
   step 6 atomic, and a test asserts the temp's parent directly rather than
   assuming it.
4. **Commit** — ``flush`` → ``os.fsync`` → close. Any exception unlinks the temp
   and re-raises, so no *handled* error leaves residue.
5. **Backup** — with ``--in-place`` and backups enabled, the original is linked
   (or copied) to a ``.bak`` sidecar. ``os.link`` first: it is instant, and it is
   *correct* precisely because step 6 replaces the directory entry rather than
   truncating the file, so the sidecar keeps the original inode. ``shutil.copy2``
   is the fallback where linking is refused.
6. **Replace** — ``os.replace``, atomic within a filesystem.
7. **Crash residue** — a hard kill between 3 and 6 can leave a toolkit temp
   file. That is expected, it is reported by ``doctor --strict`` and never swept
   (``PLAN.md`` §12 R-07), and the destination is untouched either way.

``--in-place`` is never an in-place mutation
--------------------------------------------
It is this identical path with the destination equal to the input, plus step 5.
Nothing in this product ever opens a user's file for writing. That one sentence
is why a ``SIGKILL`` mid-write leaves the original byte-identical for
``--in-place`` exactly as it does for a fresh output, and it is why the product
ships without a transaction log (D-07): safety here is immutability, not
reversibility.

A dry run predicts the refusal (X-67)
-------------------------------------
Real runs are protected by construction; dry runs would be protected only by
convention. A verb author cannot forget the gate — there is no path into the
writer that misses it — but a verb author *can* forget to call the read-only
planning helpers themselves, and then a ``--dry-run`` against an occupied target
would enter cleanly, predict nothing, and be contradicted by the real run's exit
5. A preview that lies is worse than no preview, so the planning step moved
above the gate rather than being left to each caller's diligence.

Under ``--dry-run`` the plan is therefore **computed and captured** instead of
raised: :attr:`planned_refusal` holds the exception the real run *would* have
raised, :attr:`would_exit` is the status it *would* have exited with, and
:meth:`plan_item` renders both as one machine-readable item. The dry run itself
still exits 0 — the prediction completed successfully, and ``-o json`` carries a
richer answer than an exit code can. Mirroring the predicted status into the dry
run's own exit code is a separate ergonomic question, deliberately not settled
here.

Capture stops at the **first** refusal, exactly where a real run would have
stopped. A real run that refuses at no-clobber never reaches the writability
check and never emits the cross-filesystem warning, so a dry run that reported
them anyway would be lying in the other direction.

**Nothing about this makes a dry run touch the filesystem.** The three helpers
the plan calls use ``resolve()``, ``.exists()``, ``os.path.lexists()``,
``.is_dir()``, ``os.access`` and ``stat`` — reads, every one. Access time is the
only thing they can move, and the purity comparator excludes it deliberately
(``PLAN.md`` §D2), so the snapshot assertion stays at zero differences and now
means something, because the plan actually executes.

Multi-target planning (B-054)
------------------------------
:meth:`AtomicWriter._plan` predicts refusals for **one** destination. `split`
and `rasterize` share **one** ``--out-dir`` across **many** targets, and called
the read-only directory-tier helpers (``ensure_out_dir``,
``ensure_destination_writable``, ``ensure_no_clobber``) directly, inside their
own real-run branch only — a second, uninspected copy of the exact planning
step X-67 already fixed once, reachable only when ``policy.dry_run`` was
``False``. A ``--dry-run`` split or rasterize therefore entered cleanly over an
occupied ``--out-dir`` while the real run refused with exit 5: the same
preview-lies defect class, recurring on a verb shape ``AtomicWriter`` alone
cannot see, because its own gate covers one file, not a directory shared by
many.

:func:`plan_output_set` is the same idea, run once for a whole target *set*:
create the directory (real run only — :func:`_ensure_out_dir` is already a
no-op under ``--dry-run``), check it is writable, then check every target for
no-clobber, in the real run's own order — and under ``--dry-run``, capture the
first refusal instead of raising it, exactly mirroring ``_plan``'s own
first-refusal-only rule above. ``ensure_out_dir`` is now private
(:func:`_ensure_out_dir`) and this function is its **only** caller: a future
``--out-dir`` verb cannot obtain a created output directory except through the
planner, so skipping the planner is not a silent diagnostic gap — it is a real
run that cannot write at all.

Recorded simplification (OR-1)
------------------------------
No-clobber is a check at plan time plus a re-check immediately before
``os.replace``. That narrows the window in which another process could create
the destination to microseconds, but it does not close it: an exclusive create
(``os.link`` of the temp onto the destination, which fails with ``EEXIST``)
would. This is a decision, not an oversight — the exclusive-create hardening is
an additive change at this same seam, and the re-check is deliberately written
as its own method so that seam stays obvious.

Cross-filesystem degradation
----------------------------
``os.replace`` is atomic *within* a filesystem. Two situations end the guarantee
and both warn on stderr in one class, ``atomicity degraded``:

* the destination resolves onto a different filesystem than the one the user
  named (an ``--out-dir`` that is a symlink to another mount) — atomicity is
  preserved because the temp sits beside the *real* destination, but the bytes
  do not land where the user pointed, and they should be told before the write
  rather than after it;
* a real ``EXDEV`` from ``os.replace``, which is completed by copying into a
  second temp on the destination filesystem, fsyncing, replacing, and then
  verifying size **and** SHA-256. A degraded path that did not verify would be a
  worse guarantee wearing the same name.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Final

from pdf_toolkit.cli.exit_codes import OK
from pdf_toolkit.errors import (
    BackupExistsError,
    DestinationUnwritableError,
    FailureError,
    PdfToolkitError,
    TargetExistsError,
)
from pdf_toolkit.safety._faults import checkpoint
from pdf_toolkit.safety.paths import (
    canonical,
    declared_device,
    ensure_destination_writable,
    ensure_no_clobber,
    nearest_existing_ancestor,
    resolved_device,
)
from pdf_toolkit.safety.policy import SafetyPolicy
from pdf_toolkit.safety.tempnames import TEMP_PREFIX

__all__ = [
    "AtomicWriter",
    "DEGRADED_PREFIX",
    "PlannedOutputs",
    "ScratchDir",
    "plan_filesystem",
    "plan_output_set",
]

#: The one warning class both cross-filesystem conditions are reported under, so
#: a caller can match on a stable prefix instead of on prose.
DEGRADED_PREFIX: Final[str] = "atomicity degraded"

#: Copy chunk for the ``EXDEV`` fallback. Large enough not to syscall per line,
#: small enough that a multi-gigabyte document is never held in memory.
_CHUNK: Final[int] = 1 << 20

#: ``os.link`` refusals that mean "this filesystem will not hard-link", as
#: opposed to a real error worth propagating.
_LINK_FALLBACK_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        errno.EPERM,
        errno.EOPNOTSUPP,
        errno.EMLINK,
        errno.EXDEV,
        errno.EACCES,
    }
)


def _default_warn(message: str) -> None:
    """Warnings go to stderr. stdout is the payload and nothing else."""
    print(f"warning: {message}", file=sys.stderr)


def _digest(path: Path) -> tuple[int, str]:
    """``(size, sha256)`` for *path*, streamed rather than read whole."""
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _predict_name_too_long(out_dir: Path, ancestor: Path) -> None:
    """``ENAMETOOLONG``, predicted rather than performed (PDF-18 Design D4,
    implementation note 2, resolution (a)).

    A non-existent ``out_dir`` whose ancestor is writable is not yet fully
    decidable: ``mkdir(parents=True)`` still has to create every component
    between *ancestor* and *out_dir*, and one of those components can be too
    long for the filesystem to accept, which is a refusal the ancestor's own
    writability check cannot see. Every not-yet-existing component is
    checked against the *ancestor*'s own ``PC_NAME_MAX`` -- the components
    ``mkdir`` would create all land on the same filesystem as the ancestor
    that hosts them, so its limit is theirs too. Stdlib, one
    :func:`os.pathconf` call, decidable without performing the operation --
    squarely inside §D3's invariant.

    If ``PC_NAME_MAX`` is unavailable for this attribute on this platform,
    the check is silently skipped: the real ``mkdir`` still refuses
    (§D4's errno table), this tier of the *prediction* is simply not
    decidable here, exactly as X-67 already permits for password
    correctness.
    """
    try:
        limit = os.pathconf(str(ancestor), "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):
        return
    remainder = out_dir.relative_to(ancestor) if out_dir != ancestor else Path()
    for part in remainder.parts:
        if len(os.fsencode(part)) > limit:
            raise DestinationUnwritableError(
                f"destination directory cannot be created: {out_dir} "
                f"(path component {part!r} exceeds the filesystem's {limit}-byte "
                f"name limit)",
                path=str(out_dir),
            )


def _predict_out_dir_creation(out_dir: Path) -> None:
    """Would ``out_dir.mkdir(parents=True, exist_ok=True)`` succeed? (X-184/D4)

    Mirrors ``Path.mkdir(exist_ok=True)``'s own two-branch behaviour exactly,
    read-only:

    * ``out_dir`` already exists (as anything at all) -- the real ``mkdir``
      is a no-op regardless of its own permission bits (only *search*
      permission on the parent is needed to discover ``EEXIST``, never
      *write*). Predicting anything here would duplicate -- and could
      disagree with -- :func:`~pdf_toolkit.safety.paths.
      ensure_destination_writable`, which `plan_output_set` already calls
      right after this one whenever ``out_dir`` exists (Trap 1's own
      exemption is keyed on existence for exactly this reason). So this
      function returns and lets that check own the "exists but unwritable"
      and "exists but is a file" cases -- AC6's wire-compatibility pin
      covers both and neither may change shape.
    * ``out_dir`` does not exist -- walk to the deepest existing ancestor.
      If that ancestor is not a directory (``ENOTDIR``/``EEXIST``-as-file,
      the trigger `fa5736f2ae` names) or is not writable+executable
      (``EACCES``), the real ``mkdir`` would refuse; predict it. Otherwise,
      check the remaining not-yet-created path components for
      ``ENAMETOOLONG``.

    **Existence is decided through :func:`nearest_existing_ancestor` alone,
    never a direct ``out_dir.exists()`` call.** ``Path.exists()`` does not
    swallow ``ENAMETOOLONG`` (see that function's own docstring), and this
    function is exactly the place a too-long ``out_dir`` would reach first —
    a direct call here would raise instead of predicting.
    """
    absolute = Path(out_dir).expanduser().absolute()
    ancestor = nearest_existing_ancestor(out_dir)
    if ancestor == absolute:
        return
    if not ancestor.is_dir():
        raise DestinationUnwritableError(
            f"destination directory cannot be created: {out_dir} "
            f"({ancestor} exists and is not a directory)",
            path=str(out_dir),
        )
    if not os.access(ancestor, os.W_OK | os.X_OK):
        raise DestinationUnwritableError(
            f"destination directory cannot be created: {out_dir} "
            f"(the nearest existing directory, {ancestor}, is not writable)",
            path=str(out_dir),
        )
    _predict_name_too_long(out_dir, ancestor)


def _ensure_out_dir(out_dir: Path, *, policy: SafetyPolicy) -> None:
    """Create ``--out-dir`` if it does not exist, unless ``--dry-run`` (`PLAN.md` §4.2).

    PDF-07 is the first spec to consume this: `split` is the CLI's first verb
    with a ``--out-dir`` shared by many targets, so creating it once, as its
    own plan step before the per-target loop, is the correct place for this —
    folding it into :class:`AtomicWriter`'s own per-target gate would create
    it once per part instead of once per run.

    ``Path.mkdir`` is a row-11 mutation the write chokepoint's own AST walk
    forbids everywhere outside this file; this is that mutation's one
    confined call site, mirroring every other step this module already owns.

    **PDF-18 (`d55b302668` / `fa5736f2ae`): this call is now guarded on the
    real run and PREDICTED on the dry run, instead of the dry run being an
    unconditional no-op.** A dry run never calls the real ``mkdir`` -- the
    function's dry-run branch is :func:`_predict_out_dir_creation`, entirely
    read-only, which is what keeps a non-existent ``--out-dir`` non-existent
    under ``--dry-run`` (AC9, AC18). Any ``OSError`` the real ``mkdir`` raises
    -- ``EACCES``, ``ENOTDIR``, ``EEXIST``-as-file, ``ENAMETOOLONG``, ``EROFS``,
    the whole errno family, never only ``PermissionError`` -- becomes
    :class:`~pdf_toolkit.errors.DestinationUnwritableError`, echoing the path
    **as the user wrote it**. `cli/main.py`'s single ``except PdfToolkitError``
    handler already routes that class through the product's structured
    envelope (exit 1) -- raising it is the entire fix; nothing else in the
    envelope path changes.

    **Private as of B-054.** :func:`plan_output_set` is this function's only
    caller: a verb author who reaches past the planner cannot obtain a
    created output directory at all, which is what makes skipping the
    planner a real run that cannot write rather than a silent diagnostic gap.
    """
    if policy.dry_run:
        _predict_out_dir_creation(out_dir)
        return
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        detail = f" ({error.strerror})" if error.strerror else ""
        raise DestinationUnwritableError(
            f"destination directory could not be created: {out_dir}{detail}",
            path=str(out_dir),
        ) from error


@dataclass(frozen=True, slots=True)
class PlannedOutputs:
    """B-054: the filesystem-tier plan for one multi-target ``--out-dir`` run.

    Mirrors :class:`AtomicWriter`'s own X-67 vocabulary exactly, so a caller
    comparing a prediction against an outcome is comparing like with like:
    :attr:`refusal` is the exception a real run *would* have raised (``None``
    when the plan is clean), :attr:`would_exit` is the status it would have
    exited with, and :attr:`would_refuse` is the same structured payload the
    real run's own error prints under ``-o json``.

    **PDF-18 Design D2 — the eight ``ops/`` copies of ``_FilesystemPlan``
    collapse into this one type.** Every construction in those seven
    dataclasses (plus `ops/crypto.py`'s own divergent ``PdfToolkitError |
    None`` return) derived its stored ``would_exit``/``would_refuse`` from a
    refusal, so absorbing them here is behaviour-preserving by inspection —
    and AC6 pins the emitted per-item payload byte-for-byte rather than
    trusting that inspection alone. :attr:`message` and :attr:`refused` and
    :meth:`detail` are the three members every copy defined identically;
    they are copied here unchanged.
    """

    refusal: PdfToolkitError | None

    @property
    def would_exit(self) -> int:
        return OK if self.refusal is None else self.refusal.exit_code

    @property
    def would_refuse(self) -> dict[str, object] | None:
        return None if self.refusal is None else self.refusal.to_dict()

    @property
    def message(self) -> str | None:
        return None if self.refusal is None else self.refusal.message

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    def detail(self) -> dict[str, object]:
        """The per-item ``detail`` payload a ``--dry-run`` item carries."""
        payload: dict[str, object] = {"would_exit": self.would_exit}
        if self.would_refuse is not None:
            payload["would_refuse"] = self.would_refuse
        return payload


def plan_output_set(
    targets: Sequence[Path],
    *,
    out_dir: Path | None,
    policy: SafetyPolicy,
) -> PlannedOutputs:
    """The filesystem tier for a multi-target ``--out-dir`` run (B-054).

    Runs in **both** modes, mirroring :meth:`AtomicWriter._plan` (X-67): a real
    run raises exactly as before — same classes, same codes, same messages,
    same order — and a dry run captures the **first** refusal and stops,
    exactly where the real run would have stopped.

    The real run's own order, unchanged:

    1. :func:`_ensure_out_dir` — now able to refuse in both modes (PDF-18).
    2. :func:`~pdf_toolkit.safety.paths.ensure_destination_writable`.
    3. per *target*, in order:
       :func:`~pdf_toolkit.safety.paths.ensure_no_clobber`.

    ``out_dir`` is ``Path | None`` so a future caller with no shared directory
    (a single-target run) can still route its per-target no-clobber check
    through the same planner; every ``--out-dir`` verb today always supplies
    one, since the CLI declares it required for this shape.

    **Trap 1, and this is the one thing to read before touching this
    function.** A ``--out-dir`` that does not exist yet must not be predicted
    as a refusal by *this* function's own writability check. Checking
    writability on a directory that legitimately does not exist yet would
    turn every ordinary ``split --dry-run --out-dir parts/`` into a false
    exit-1 refusal, so under ``--dry-run``, when *out_dir* does not exist,
    :func:`ensure_destination_writable` is skipped entirely and only the
    (trivially passing) per-target no-clobber checks run — exactly what the
    real run's own create-then-succeed path would have reached.

    **PDF-18 (`d55b302668` / `fa5736f2ae`): the case Trap 1 exempts is no
    longer the case nobody predicts.** A non-existent ``out_dir`` whose
    *parent* is itself unwritable used to reach the real run's unhandled
    ``mkdir`` — the writability tier here skipped it (correctly, per Trap 1)
    and :func:`_ensure_out_dir` skipped it too (it was an unconditional
    no-op under ``--dry-run``). :func:`_ensure_out_dir` now predicts that
    exact question itself — see its own docstring — so the tier this
    function's Trap 1 exemption steps around is covered by the step
    *before* it rather than by nothing at all.
    """
    try:
        if out_dir is not None:
            _ensure_out_dir(out_dir, policy=policy)
            if not (policy.dry_run and not out_dir.exists()):
                ensure_destination_writable(out_dir)
        for target in targets:
            ensure_no_clobber(target, force=policy.force, in_place=policy.in_place)
    except PdfToolkitError as refusal:
        if not policy.dry_run:
            raise
        return PlannedOutputs(refusal=refusal)
    return PlannedOutputs(refusal=None)


def plan_filesystem(
    targets: Sequence[Path],
    *,
    out_dir: Path | None,
    policy: SafetyPolicy,
    kind: str,
) -> PlannedOutputs:
    """The ONE filesystem-tier planner (PDF-18 Design D1), reached by every
    producing verb including `ops/crypto.py`'s divergent former copy.

    Collapses eight ``ops/_plan_filesystem`` definitions in four signature
    shapes into one signature that expresses both destination forms:

    ============================================  ===================================
    old call (module)                              new call
    ============================================  ===================================
    ``(targets, out_dir=od, policy=p, kind=k)``     unchanged but for the name
    (optimize, pages, textract)
    ``(targets, out_dir=od, policy=p)``             ``kind=`` supplied explicitly
    (ocr, office)
    ``(target, policy=p)``                          ``plan_filesystem([target],
    (metadata, overlay)                             out_dir=None, policy=p, kind="pdf")``
    ``(...) -> PdfToolkitError | None`` (crypto)     same call; consumes ``.refusal``
    ============================================  ===================================

    ``kind`` is **not** optional. A default is how the ocr/office shape
    drifted from the other six in the first place: a parameter one author
    may omit is a parameter two authors will disagree about.

    **The firing moment: both modes, at plan time (Design D3). This is
    forced, not a style choice.** Six of the eight collapsed copies
    consulted the single-destination writer tier (below) only under
    ``if policy.dry_run and out_dir is None:`` — a real run's guard was
    always false, so the check was *skipped*, and control fell through to
    whichever tier answered next. That is not a firing-moment choice; it is
    a mode-dependent ladder, and OR-7 forbids a plan that evaluates a
    different *set* of tiers per mode. `ops/ocr.py`/`ops/office.py` already
    widened past this (their own docstrings measure why: skipping it broke
    OR-7's ``dry == real`` guarantee the moment their engine could be
    legitimately absent). This function generalises that widening to every
    caller, which is what closes `d231fbcec4` (the ``crypto`` ladder
    disagreeing on tier order) as a byproduct of unification rather than as
    a second, separate fix — Design D3 concludes the two are not separable.

    A tier may be omitted from the plan only if it is undecidable without
    performing the operation (password correctness; not directory
    writability, which is one ``os.access`` call).
    """
    plan = plan_output_set(targets, out_dir=out_dir, policy=policy)
    if plan.refusal is not None:
        return plan
    if out_dir is None:
        for target in targets:
            try:
                ensure_destination_writable(canonical(target).parent, as_written=target.parent)
            except PdfToolkitError as refusal:
                if not policy.dry_run:
                    raise
                return PlannedOutputs(refusal=refusal)
    return plan


class AtomicWriter:
    """A context manager that owns one destination, one temp, and one replace.

    Args:
        target: The destination, spelled as the user spelled it. Echoed verbatim
            in every message; canonicalized only as a comparison key.
        policy: The resolved safety posture for this invocation.
        kind: A short label for the artefact, used in diagnostics.
        warn: Where warnings go. Injectable so a test can capture them without
            parsing stderr; defaults to stderr.
        _temp_dir: **Test-only.** Forces the temp onto a chosen directory so the
            cross-filesystem arm can produce a genuine kernel ``EXDEV`` instead
            of a monkeypatched ``st_dev``. Never set by product code.
    """

    def __init__(
        self,
        target: Path | str,
        *,
        policy: SafetyPolicy,
        kind: str = "pdf",
        warn: Callable[[str], None] | None = None,
        _temp_dir: Path | str | None = None,
    ) -> None:
        self.target = Path(target)
        self.policy = policy
        self.kind = kind
        self.warnings: list[str] = []
        self.backup_path: Path | None = None
        #: X-67. Under ``--dry-run``, the refusal the real run *would* have
        #: raised, computed rather than thrown. ``None`` when the plan is clean,
        #: and always ``None`` after a real run — a real run raises instead.
        self.planned_refusal: PdfToolkitError | None = None
        self.destination: Path = canonical(target)
        self._warn_sink = warn if warn is not None else _default_warn
        self._temp_dir = Path(_temp_dir) if _temp_dir is not None else None
        self._handle: IO[bytes] | None = None
        self._temp_path: Path | None = None
        self._dry_run = False

    # -- the surface a verb touches ---------------------------------------- #

    @property
    def path(self) -> Path:
        """The path the engine writes to. Never the destination."""
        if self._dry_run:
            raise RuntimeError(
                "--dry-run writes nothing: this writer has no path to hand out. "
                "Render the plan instead of asking for a destination."
            )
        if self._temp_path is None:
            raise RuntimeError("AtomicWriter.path is only valid inside the with-block")
        return self._temp_path

    @property
    def stream(self) -> IO[bytes]:
        """The open file handle an engine should write through — never a path.

        PDF-07 Design §D7's specific trap: a third-party writer that accepts a
        path (``pypdf.PdfWriter.write("out.pdf")``) opens it itself, which
        bypasses this chokepoint from inside a call a source-level AST walk
        cannot see. Handing the writer THIS handle instead keeps the write on
        the one file descriptor this class already tracks, so the
        flush/fsync/close sequence :meth:`_commit` runs is the sequence that
        actually matters, rather than a second, untracked handle to the same
        path.
        """
        if self._dry_run:
            raise RuntimeError(
                "--dry-run writes nothing: this writer has no stream to hand out. "
                "Render the plan instead of asking for a destination."
            )
        if self._handle is None:
            raise RuntimeError("AtomicWriter.stream is only valid inside the with-block")
        return self._handle

    @property
    def is_dry_run(self) -> bool:
        """Whether this writer stopped at the dry-run gate.

        A dry-run writer has still *planned*: consult :attr:`would_exit` and
        :meth:`plan_item` for what the real run would have done.
        """
        return self._dry_run

    @property
    def would_exit(self) -> int:
        """The status a real run of this invocation would have exited with.

        ``OK`` when the plan found nothing to refuse. Under ``--dry-run`` over an
        occupied target this is ``5``; over an unwritable destination, ``1``. The
        dry run's *own* exit status is 0 either way — this is the prediction, not
        the verdict on the prediction.
        """
        refusal = self.planned_refusal
        return OK if refusal is None else refusal.exit_code

    def plan_item(self) -> dict[str, object]:
        """The plan as one machine-readable item (X-67).

        ``would_refuse`` is the product's own structured error payload — the
        *identical* object the real run prints under ``-o json`` — so a caller
        comparing a prediction against the outcome is comparing like with like
        rather than two hand-rolled shapes that agree by luck.
        """
        item: dict[str, object] = {
            "target": str(self.target),
            "would_exit": self.would_exit,
            "warnings": list(self.warnings),
        }
        refusal = self.planned_refusal
        if refusal is not None:
            item["would_refuse"] = refusal.to_dict()
        return item

    def __enter__(self) -> AtomicWriter:
        # X-67: the plan runs in BOTH modes. Everything it calls is read-only,
        # and a dry run that skipped it could not predict its own refusals.
        self._dry_run = self.policy.dry_run
        self._plan()
        # THE GATE. Immediately above _open_temp(), the first mutating call.
        if self._dry_run:
            return self
        self._open_temp()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._dry_run:
            return
        if exc_type is not None:
            self._discard()
            return
        try:
            self._commit()
        except BaseException:
            self._discard()
            raise

    # -- steps 2 and 3 ------------------------------------------------------ #

    def _plan(self) -> None:
        """Steps 2 and 3 — read-only, and run under ``--dry-run`` too (X-67).

        A real run raises: same classes, same codes, same messages, same order as
        before this method learned about dry runs. A dry run captures the first
        refusal into :attr:`planned_refusal` and returns, stopping exactly where
        the real run would have stopped — which is why the warning below sits
        after the ``except`` and not inside a ``finally``.
        """
        try:
            ensure_no_clobber(
                self.target,
                force=self.policy.force,
                in_place=self.policy.in_place,
            )
            ensure_destination_writable(
                self.destination.parent,
                as_written=self.target.parent,
            )
        except PdfToolkitError as refusal:
            if not self._dry_run:
                raise
            self.planned_refusal = refusal
            return
        self._warn_if_destination_moved()

    def _warn_if_destination_moved(self) -> None:
        """Condition 1: the bytes land on a filesystem the user did not name."""
        named = declared_device(self.target)
        actual = resolved_device(self.destination.parent)
        if named is None or actual is None or named == actual:
            return
        self._warn(
            f"{DEGRADED_PREFIX}: {self.target} (device {named}) resolves to "
            f"{self.destination} (device {actual}) on a different filesystem; the write "
            f"stays atomic on the destination filesystem, but not on the one you named"
        )

    def _open_temp(self) -> None:
        directory = self._temp_dir if self._temp_dir is not None else self.destination.parent
        # Closed in _commit (after fsync) or _discard (on any failure).
        handle = tempfile.NamedTemporaryFile(
            dir=directory,
            prefix=TEMP_PREFIX,
            delete=False,
        )
        self._handle = handle
        self._temp_path = Path(handle.name)
        checkpoint("after_temp_create", str(self._temp_path))

    # -- steps 4 to 6 ------------------------------------------------------- #

    def _commit(self) -> None:
        handle = self._handle
        temp = self._temp_path
        if handle is None or temp is None:  # pragma: no cover - unreachable by construction
            raise RuntimeError("AtomicWriter was committed without having been entered")

        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        self._handle = None
        checkpoint("after_fsync", str(temp))

        self._make_backup()
        checkpoint("after_backup", str(temp))

        self._replace(temp)
        self._temp_path = None

    def _make_backup(self) -> None:
        if not (self.policy.in_place and self.policy.backup):
            return
        if not self.destination.exists():
            return

        sidecar = self.destination.with_name(self.destination.name + ".bak")
        if sidecar.exists():
            if not self.policy.force:
                raise BackupExistsError(
                    f"{sidecar.name} already exists beside {self.target}; "
                    f"pass --force to replace the sidecar",
                    path=str(sidecar),
                )
            os.unlink(sidecar)

        try:
            os.link(self.destination, sidecar)
        except OSError as error:
            if error.errno not in _LINK_FALLBACK_ERRNOS:
                raise
            shutil.copy2(self.destination, sidecar)
        self.backup_path = sidecar

    def _recheck_no_clobber(self) -> None:
        """OR-1: the second half of the narrowed TOCTOU window.

        The exclusive-create hardening, if it is ever wanted, replaces this
        method and nothing else.
        """
        if self.policy.force or self.policy.in_place:
            return
        if self.destination.exists():
            raise TargetExistsError(
                f"{self.target} appeared while the write was in flight; "
                f"pass --force to overwrite it",
                path=str(self.target),
            )

    def _replace(self, temp: Path) -> None:
        self._recheck_no_clobber()
        try:
            os.replace(temp, self.destination)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            self._replace_across_devices(temp)

    def _replace_across_devices(self, temp: Path) -> None:
        """Condition 2: a real ``EXDEV``, completed and then verified."""
        source_device = declared_device(temp)
        target_device = resolved_device(self.destination.parent)
        self._warn(
            f"{DEGRADED_PREFIX}: cross-device rename from {temp} (device {source_device}) "
            f"to {self.destination} (device {target_device}); completing with "
            f"copy, fsync, replace and a size plus SHA-256 verification"
        )

        expected_size, expected_digest = _digest(temp)
        staged = tempfile.NamedTemporaryFile(
            dir=self.destination.parent,
            prefix=TEMP_PREFIX,
            delete=False,
        )
        staged_path = Path(staged.name)
        try:
            with open(temp, "rb") as source:
                while True:
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    staged.write(chunk)
            staged.flush()
            os.fsync(staged.fileno())
        finally:
            staged.close()

        self._recheck_no_clobber()
        os.replace(staged_path, self.destination)
        self._unlink_quietly(temp)

        actual_size, actual_digest = _digest(self.destination)
        if (actual_size, actual_digest) != (expected_size, expected_digest):
            raise FailureError(
                f"the degraded write to {self.target} did not verify: "
                f"expected {expected_size} bytes / {expected_digest}, "
                f"got {actual_size} bytes / {actual_digest}",
                path=str(self.target),
            )

    # -- unwinding ---------------------------------------------------------- #

    def _discard(self) -> None:
        """Close and remove the temp. Never touches the destination."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:  # pragma: no cover - close after a partial failure
                pass
        temp, self._temp_path = self._temp_path, None
        if temp is not None:
            self._unlink_quietly(temp)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            os.unlink(path)
        except OSError:  # pragma: no cover - already gone
            pass

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        self._warn_sink(message)


# --------------------------------------------------------------------------- #
# PDF-15 -- ``ScratchDir``: a private, per-invocation SCRATCH directory for an
# external engine's own working files. Additive; nothing above this comment
# changes.
# --------------------------------------------------------------------------- #


#: Deliberately NOT :data:`TEMP_PREFIX` and does not contain its literal
#: (``.pdftoolkit-``): that prefix means *crash residue beside a destination*
#: (``find_stray_temps`` / ``doctor --strict``), a promise this class must not
#: make -- a :class:`ScratchDir` never sits beside any destination and is
#: reliably removed on every exit path, so a leftover one here would be a
#: bug report, not evidence ``doctor`` is designed to surface.
_SCRATCH_PREFIX: Final[str] = "pdftoolkit-scratch-"


class ScratchDir:
    """A private, per-invocation working directory for an external engine
    (``convert``'s LibreOffice profile + conversion outdir; PDF-15, Design
    §D6) -- never a product destination.

    **Why this lives here, in the write chokepoint, rather than in the
    adapter that needs it.** ``tests/test_import_boundaries.py`` Section 1
    forbids ``tempfile.mkdtemp``/``shutil.rmtree`` (and every other
    filesystem-mutating stdlib call) anywhere under ``src/`` except this one
    file -- ``pdf_toolkit.safety.atomic`` is the single module the walk's
    own ``CHOKEPOINT`` constant exempts, on both tiers. Scattering a SECOND,
    parallel raw-mutation site into ``adapters/soffice_office.py`` would be
    exactly the "verb creates its own tempfile" defect shape that module's
    docstring names -- even though this scratch space is never the user's
    OWN output (``convert``'s actual PDF bytes still cross the destination
    through :class:`AtomicWriter`, unchanged), keeping the raw ``tempfile``/
    ``shutil.rmtree`` calls themselves confined to the one auditable file is
    what the chokepoint's whole design is for: every filesystem mutation the
    product performs stays in one place, whatever it is *for*.

    **Not a second write chokepoint.** This class never resolves, plans or
    writes a user-visible destination; it hands back one throwaway directory
    an external process may use as it likes, and guarantees it is gone
    afterwards (``shutil.rmtree(..., ignore_errors=True)`` in
    ``__exit__`` -- errors are swallowed deliberately, mirroring
    :meth:`AtomicWriter._discard`'s own best-effort cleanup posture, because
    a cleanup failure must never mask the real error a ``with`` block is
    already unwinding for).

    LibreOffice creates both the ``-env:UserInstallation`` profile directory
    and a ``--outdir`` target directory itself when they do not yet exist
    (verified empirically against LibreOffice 26.2.5), so the caller never
    needs to create the two *subdirectories* it hands soffice as argv values
    -- only this one root, which is genuinely needed so ``__exit__`` has a
    single tree to remove.
    """

    def __init__(self, *, prefix: str = _SCRATCH_PREFIX) -> None:
        self._prefix = prefix
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix=self._prefix))
        return self.path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)
            self.path = None
