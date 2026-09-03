"""``encrypt`` + ``decrypt`` + ``permissions`` — pure plan/result functions over
``StructureEngine``'s ``"robust-encryption"`` capability (PDF-13).

Framework-free per L2: no typer/click import (PDF-06's AST test enforces it),
and **no engine library import either** — every byte crosses the port boundary
through ``ports/structure.py``'s plain dataclasses, never a ``pikepdf``
object. No cryptography is implemented anywhere in this product: key
derivation, ciphers and password comparison are libqpdf's.

**One ops module, three cmd modules.** `cli/cmd_encrypt.py`,
`cli/cmd_decrypt.py` and `cli/cmd_permissions.py` are separate files because
`cli/common.py`'s OR-3 declaration is keyed by module name
(``_CONSUMES_BY_MODULE[func.__module__]``) and three
``@global_options(consumes=…)`` decorators in one module would silently
overwrite each other, last one winning — the same trap PDF-12 hit and split
out of. The *ops* layer has no such constraint and stays shared, exactly as
`text`/`tables` share ``ops/textract.py`` and `compress`/`repair`/`linearize`
share ``ops/optimize.py``.

The password never enters this module's data
--------------------------------------------
``OperationPlan``/``ItemResult`` feed the JSON renderer (§6), so a
:class:`~pdf_toolkit.secret.Secret` never enters either. What crosses into
this module is a :class:`PasswordSource`: a **safe-to-log source label** plus
a thunk the CLI layer built. This module renders the label and, on a real
run only, calls the thunk.

That indirection is not decoration. It is what keeps three properties true at
once:

1. ``ops/`` stays pure (§5.2) — reading a file, an environment variable, or a
   TTY is L1's job, so the thunk is built in ``cli/password.py``.
2. **The exit-code ladder holds.** A refusal at the filesystem tier (5)
   precedes an unresolvable password (6), which is only expressible if the
   password is read *after* the plan rather than before the call.
3. ``--dry-run`` **never reads the secret**: it renders ``source`` and never
   touches ``read``.

The exit-6 oracle split (the subtle one)
----------------------------------------
Exit **6** has two sub-cases and they are deliberately not equally
predictable.

* **Resolvability** — no flag, the variable is not *present* in the
  environment, stdin is not a TTY — **is** predicted: ``would_exit: 6``,
  ``planned_refusal: "AuthError"``. It is decidable from *existence alone*,
  so no secret enters the process to decide it.
* **Correctness** — a password was supplied and is wrong — is **deliberately
  not predicted**. Predicting it means reading the secret inside the planning
  path, and the answer is a machine-readable field distinguishing a right
  password from a wrong one, rendered into ``-o json`` plans that land in CI
  artifacts. A preview must not become an oracle. The limit is **stated in
  the payload** (``"password_verified": false``) rather than left silent —
  that is the whole difference between honouring X-67 and re-committing X-89.

**The filesystem tier runs in both modes (B-054, extending X-67), through the
ONE shared planner (PDF-18).** `encrypt`/`decrypt` carry **only** the
single-target shape (``-O``/``--in-place``; ``out_dir`` is always ``None``
for them, exactly as `repair`/`linearize` do), so
:func:`~pdf_toolkit.safety.atomic.plan_filesystem`'s own ``out_dir is None``
branch is what checks this module's destination writability — in both
modes now, which is what closes `d231fbcec4` (the ladder disagreeing on tier
order between a dry run and a real run) as a byproduct of the eight-copy
unification rather than as a second, separate fix. This module no longer
owns a planner of its own; :meth:`_plan` below still owns the *ladder* —
the ordering of the filesystem tier against ``document_refusal`` and
password resolvability, which is `encrypt`/`decrypt`'s own concern and
stays here.

**Nothing here writes.** Every byte reaches disk through
``safety.AtomicWriter``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import (
    AuthError,
    NoInputError,
    PdfToolkitError,
    RefusedError,
    UsageError,
)
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ports.structure import (
    ALWAYS_GRANTED_TOKENS,
    PERMISSION_TOKENS,
    EncryptionFacts,
    require_encryption,
)
from pdf_toolkit.safety.atomic import AtomicWriter, plan_filesystem
from pdf_toolkit.safety.paths import classify_operand, read_source_bytes
from pdf_toolkit.safety.policy import SafetyPolicy
from pdf_toolkit.secret import Secret

__all__ = [
    "ALGORITHM_AES256",
    "ALGORITHM_RC4128",
    "LEGACY_WARNING",
    "VERB_DECRYPT",
    "VERB_ENCRYPT",
    "VERB_PERMISSIONS",
    "PasswordSource",
    "decrypt_run",
    "encrypt_run",
    "permissions_run",
]

VERB_ENCRYPT: Final[str] = "encrypt"
VERB_DECRYPT: Final[str] = "decrypt"
VERB_PERMISSIONS: Final[str] = "permissions"

ALGORITHM_AES256: Final[str] = "AES-256"
ALGORITHM_RC4128: Final[str] = "RC4-128"

#: `--legacy`'s warning, on stderr AND in ``OperationResult.warnings`` so the
#: `-o json` consumer sees exactly what the human sees. The word "broken" is
#: asserted by AC9; the reason it exists at all is stated so the warning is
#: information rather than scolding.
LEGACY_WARNING: Final[str] = (
    "--legacy selects RC4-128, which is cryptographically broken and provides "
    "no meaningful confidentiality; it exists only for readers that predate "
    "PDF 1.7 ExtensionLevel 3. Document metadata is left unencrypted in this "
    "mode, because the format cannot encrypt it without AES."
)

_ALREADY_ENCRYPTED: Final[str] = (
    "this document is already encrypted; run 'pdftoolkit decrypt' first"
)

_NOT_ENCRYPTED: Final[str] = "document is not encrypted; nothing to decrypt"


# --------------------------------------------------------------------------- #
# The password seam
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PasswordSource:
    """One password slot, as the CLI layer *planned* it — never as it read it.

    Attributes:
        slot: ``"owner"`` | ``"user"`` | ``"password"``. Names the plan key
            this slot renders under, so a caller never has to build one.
        source: The safe-to-log label — ``"file:/home/u/pw.txt"``,
            ``"stdin"``, ``"env:PDF_TOOLKIT_PASSWORD"``, ``"prompt"`` — or
            ``None`` when *nothing* could supply a password. ``None`` is
            decided from existence alone: no file was read, no variable's
            value was read, nothing was prompted.
        read: The thunk that actually resolves the value. Called **only** on a
            real run, **only** after the filesystem tier has been planned, and
            never under ``--dry-run``.
    """

    slot: str
    source: str | None
    read: Callable[[], Secret] | None = None

    @property
    def resolvable(self) -> bool:
        return self.source is not None

    def resolve(self) -> Secret:
        """Read the value. Callers reach this only after ``_plan`` cleared the
        resolvability tier, so a ``None`` thunk here is a broken invariant --
        raised as the honest exit-6 rather than asserted away (``assert`` is
        stripped under ``-O`` and `bandit` B101 flags it for exactly that
        reason)."""
        if self.read is None:
            raise _unresolvable(self.slot)
        return self.read()

    @property
    def key(self) -> str:
        """The plan/result key this slot's label is rendered under.

        ``owner`` -> ``owner_password_source``, ``user`` ->
        ``user_password_source``, and the single-slot ``password`` ->
        ``password_source`` rather than the stuttering
        ``password_password_source``.
        """
        return "password_source" if self.slot == "password" else f"{self.slot}_password_source"


def _unresolvable(slot: str) -> AuthError:
    return AuthError(
        f"no {slot} password available: pass --{slot}-password-file PATH "
        f"(or '-' to read one line from stdin), set the matching environment "
        f"variable, or run on a terminal to be prompted",
        redacted=True,
    )


def _password_detail(sources: Sequence[PasswordSource], *, verified: bool) -> dict[str, object]:
    """The source labels, plus the honest statement of what was NOT checked.

    ``password_verified`` is ``False`` for every dry run by construction: a
    dry run does not read the secret, so it cannot know. Stating that in the
    payload is what keeps the preview from reading like success.
    """
    detail: dict[str, object] = {source.key: source.source for source in sources}
    detail["password_verified"] = verified
    return detail


# --------------------------------------------------------------------------- #
# Shared prediction — the filesystem tier plus this spec's own two refusals.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Prediction:
    """What a real run of this invocation would do, before any engine work.

    Mirrors :class:`~pdf_toolkit.safety.atomic.PlannedOutputs`' X-67
    vocabulary, because that is what makes a prediction and an outcome
    comparable like with like rather than two hand-rolled shapes that agree
    by luck. ``planned_refusal`` carries the exception *class name*: two
    refusals can share a ``kind`` (``TargetExistsError`` and
    ``BackupExistsError`` are both ``"refused"``), and the class is what
    names which gate spoke.
    """

    refusal: PdfToolkitError | None

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    @property
    def would_exit(self) -> int:
        return 0 if self.refusal is None else self.refusal.exit_code

    def detail(self) -> dict[str, object]:
        payload: dict[str, object] = {"would_exit": self.would_exit}
        if self.refusal is not None:
            payload["planned_refusal"] = type(self.refusal).__name__
            payload["would_refuse"] = self.refusal.to_dict()
        return payload

    def raise_if_refused(self) -> None:
        if self.refusal is not None:
            raise self.refusal


def _validate_sources(sources: Sequence[Path]) -> None:
    for source in sources:
        classify_operand(source)


def _resolve_single_target(source: Path, *, output: Path | None, in_place: bool, verb: str) -> Path:
    if in_place:
        return source
    if output is not None:
        return output
    raise UsageError(f"{verb} requires -O/--output or --in-place")


def _plan(
    *,
    target: Path,
    policy: SafetyPolicy,
    pre_refusal: PdfToolkitError | None,
    document_refusal: PdfToolkitError | None,
    passwords: Sequence[PasswordSource],
) -> _Prediction:
    """The whole exit-code ladder above the engine, in one place and one order.

    Order is `PLAN.md` §5.6's ladder, and it is what makes the ACs
    deterministic rather than flaky:

    1. ``pre_refusal`` — the invocation-shape refusal the CLI layer computed
       (`encrypt --in-place`'s plaintext-``.bak`` gate). Exit 5.
    2. The filesystem tier — no-clobber, unwritable destination. Exit 5 or 1.
    3. ``document_refusal`` — already-encrypted (5) or not-encrypted (4),
       read from the document itself.
    4. Password **resolvability**. Exit 6.

    Every tier is evaluated identically in both modes: a dry run captures the
    first refusal into the prediction, a real run raises it.
    """
    if pre_refusal is not None:
        return _Prediction(refusal=pre_refusal)
    filesystem = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")
    if filesystem.refusal is not None:
        return _Prediction(refusal=filesystem.refusal)
    if document_refusal is not None:
        return _Prediction(refusal=document_refusal)
    for source in passwords:
        if not source.resolvable:
            return _Prediction(refusal=_unresolvable(source.slot))
    return _Prediction(refusal=None)


def _refusal_result(
    verb: str,
    *,
    source: Path,
    target: Path | None,
    refusal: PdfToolkitError,
    would_exit: int,
    detail: dict[str, object],
) -> OperationResult:
    """One refused item, in the shape every other producing verb already uses.

    Takes the refusal itself rather than the whole ``_Prediction`` so the
    non-``None`` invariant is expressed in the signature instead of asserted
    inside the body.
    """
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=verb,
        dry_run=True,
        items=(
            ItemResult(
                input=str(source),
                output=str(target) if target is not None else None,
                ok=False,
                exit_code=would_exit,
                message=refusal.message,
                bytes_before=source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            ),
        ),
        warnings=(),
        duration_ms=0,
    )


def _read_facts(source: Path, password: Secret | None) -> EncryptionFacts:
    engine = require_encryption()
    return engine.read_encryption(read_source_bytes(source), password)


# --------------------------------------------------------------------------- #
# `encrypt`
# --------------------------------------------------------------------------- #


def encrypt_run(
    source: Path,
    *,
    owner: PasswordSource,
    user: PasswordSource | None,
    allow: frozenset[str],
    legacy: bool,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
    pre_refusal: PdfToolkitError | None = None,
) -> OperationResult:
    """Encrypt *source*: AES-256 (R6) by default, RC4-128 (R4) under ``legacy``.

    ``pre_refusal`` is `cmd_encrypt.py`'s plaintext-``.bak`` gate (AC14),
    computed there because the vocabulary and the remedies are that verb's,
    and surfaced here because a refusal a dry run cannot see is the
    preview-lies defect class X-67 exists to end.
    """
    _validate_sources([source])
    target = _resolve_single_target(source, output=output, in_place=in_place, verb=VERB_ENCRYPT)

    # Read-only, credential-free, and run in BOTH modes: "is this already
    # encrypted?" is answerable from the security handler alone, so the dry
    # run predicts the same 5 the real run raises rather than promising a
    # write that cannot happen.
    facts = _read_facts(source, None)
    document_refusal = (
        RefusedError(_ALREADY_ENCRYPTED, path=str(source)) if facts.encrypted else None
    )

    passwords = [owner] if user is None else [owner, user]
    plan = _plan(
        target=target,
        policy=policy,
        pre_refusal=pre_refusal,
        document_refusal=document_refusal,
        passwords=passwords,
    )
    detail = {**plan.detail(), **_password_detail(passwords, verified=False)}
    detail["algorithm"] = ALGORITHM_RC4128 if legacy else ALGORITHM_AES256
    detail["allow"] = sorted(allow)

    if policy.dry_run:
        if plan.refusal is not None:
            return _refusal_result(
                VERB_ENCRYPT,
                source=source,
                target=target,
                refusal=plan.refusal,
                would_exit=plan.would_exit,
                detail=detail,
            )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_ENCRYPT,
            dry_run=True,
            items=(
                ItemResult(
                    input=str(source),
                    output=str(target),
                    ok=True,
                    exit_code=0,
                    message="planned: encrypt",
                    bytes_before=source.stat().st_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail=detail,
                ),
            ),
            warnings=(LEGACY_WARNING,) if legacy else (),
            duration_ms=0,
        )

    plan.raise_if_refused()

    started = time.monotonic()
    bytes_before = source.stat().st_size
    data = read_source_bytes(source)
    # The ONLY point a secret exists, and it is after every refusal above.
    owner_secret = owner.resolve()
    user_secret = user.resolve() if user is not None and user.read is not None else None
    try:
        engine = require_encryption()
        encrypted = engine.encrypt(
            data, owner=owner_secret, user=user_secret, allow=allow, legacy=legacy
        )
    finally:
        owner_secret.clear()
        if user_secret is not None:
            user_secret.clear()

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        writer.stream.write(encrypted)
    # Read AFTER the with-block, not inside it: `AtomicWriter.__exit__` ->
    # `_commit()` -> `_make_backup()` is what populates `backup_path`, so the
    # inside-the-block read this line replaced was always `None` and the
    # plaintext-`.bak` warning AC14 requires never fired.
    backup_path = writer.backup_path
    bytes_after = target.stat().st_size

    warnings: list[str] = [LEGACY_WARNING] if legacy else []
    if backup_path is not None:
        warnings.append(
            f"{backup_path} is an UNENCRYPTED copy of the original; delete it if you do not want it"
        )

    item_detail = {**_password_detail(passwords, verified=True)}
    item_detail["algorithm"] = ALGORITHM_RC4128 if legacy else ALGORITHM_AES256
    item_detail["allow"] = sorted(allow)
    item_detail["always_granted"] = list(ALWAYS_GRANTED_TOKENS)
    item_detail["advisory"] = True
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_ENCRYPT,
        dry_run=False,
        items=(
            ItemResult(
                input=str(source),
                output=str(target),
                ok=True,
                exit_code=0,
                message=f"encrypted with {item_detail['algorithm']}",
                bytes_before=bytes_before,
                bytes_after=bytes_after,
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=item_detail,
            ),
        ),
        warnings=tuple(warnings),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# `decrypt`
# --------------------------------------------------------------------------- #


def decrypt_run(
    source: Path,
    *,
    password: PasswordSource,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Remove encryption from *source* given the correct password.

    A document that is **not** encrypted is exit **4** (`NO_INPUT` — "valid
    invocation, nothing to act on"), writing nothing: it is not a failure and
    it is certainly not a wrong password.
    """
    _validate_sources([source])
    target = _resolve_single_target(source, output=output, in_place=in_place, verb=VERB_DECRYPT)

    facts = _read_facts(source, None)
    document_refusal = None if facts.encrypted else NoInputError(_NOT_ENCRYPTED, path=str(source))

    plan = _plan(
        target=target,
        policy=policy,
        pre_refusal=None,
        document_refusal=document_refusal,
        passwords=[password],
    )
    detail = {**plan.detail(), **_password_detail([password], verified=False)}

    if policy.dry_run:
        if plan.refusal is not None:
            return _refusal_result(
                VERB_DECRYPT,
                source=source,
                target=target,
                refusal=plan.refusal,
                would_exit=plan.would_exit,
                detail=detail,
            )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_DECRYPT,
            dry_run=True,
            items=(
                ItemResult(
                    input=str(source),
                    output=str(target),
                    ok=True,
                    exit_code=0,
                    message="planned: decrypt",
                    bytes_before=source.stat().st_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail=detail,
                ),
            ),
            warnings=(),
            duration_ms=0,
        )

    plan.raise_if_refused()

    started = time.monotonic()
    bytes_before = source.stat().st_size
    data = read_source_bytes(source)
    secret = password.resolve()
    try:
        engine = require_encryption()
        decrypted = engine.decrypt(data, password=secret)
    finally:
        secret.clear()

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        writer.stream.write(decrypted)
    bytes_after = target.stat().st_size

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_DECRYPT,
        dry_run=False,
        items=(
            ItemResult(
                input=str(source),
                output=str(target),
                ok=True,
                exit_code=0,
                message="decrypted",
                bytes_before=bytes_before,
                bytes_after=bytes_after,
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=_password_detail([password], verified=True),
            ),
        ),
        warnings=(),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# `permissions`
# --------------------------------------------------------------------------- #


def permissions_run(
    source: Path,
    *,
    password: PasswordSource,
    policy: SafetyPolicy,
) -> OperationResult:
    """Report the algorithm, revision, key bits and granted permission set.

    **Non-producing**: it writes nothing, declares ``consumes=()`` under OR-3,
    and therefore has no filesystem tier to plan at all. ``--dry-run`` renders
    the plan and stops without opening the engine, which is the only honest
    thing a preview of a pure report can say.

    ``advisory`` rides the payload as a machine-readable ``True`` and no
    prose: PDF permission bits are a request to the reader, not an
    enforcement mechanism, and the sentence saying so lives in the human
    surfaces (`--help`, README).
    """
    _validate_sources([source])

    if policy.dry_run:
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_PERMISSIONS,
            dry_run=True,
            items=(
                ItemResult(
                    input=str(source),
                    output=None,
                    ok=True,
                    exit_code=0,
                    message="planned: permissions",
                    bytes_before=source.stat().st_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail={"would_exit": 0, **_password_detail([password], verified=False)},
                ),
            ),
            warnings=(),
            duration_ms=0,
        )

    started = time.monotonic()
    secret: Secret | None = None
    try:
        if password.read is not None:
            secret = password.read()
        facts = _read_facts(source, secret)
    finally:
        if secret is not None:
            secret.clear()

    if facts.encrypted and not facts.unlocked:
        # `path` here is the TARGET DOCUMENT, not a password -- safe to show,
        # and useful (it says which file needs a password). `redacted=True`
        # does not belong on this one: found while landing B-068's
        # `PdfToolkitError.to_dict()` chokepoint, which makes `redacted`
        # actually do something for the first time -- this call site was
        # unaffected by it being a no-op, but would have silently started
        # rendering `path` as `<redacted>` instead of the document path once
        # the flag gained teeth. Removed rather than left in place with the
        # chokepoint softened for it: `redacted=True` communicates "this path
        # might be a secret," which was never true here.
        raise AuthError(
            "a password is required to read this document's permissions",
            path=str(source),
        )

    detail: dict[str, object] = {
        **facts.to_dict(),
        **_password_detail([password], verified=facts.unlocked and password.resolvable),
        "always_granted": list(ALWAYS_GRANTED_TOKENS),
        "vocabulary": list(PERMISSION_TOKENS),
        "advisory": True,
    }
    if facts.encrypted:
        algorithm = facts.algorithm or "unknown algorithm"
        message = f"{algorithm}, revision {facts.revision}, {facts.key_bits}-bit"
    else:
        message = "not encrypted; every permission granted"

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_PERMISSIONS,
        dry_run=False,
        items=(
            ItemResult(
                input=str(source),
                output=None,
                ok=True,
                exit_code=0,
                message=message,
                bytes_before=source.stat().st_size,
                bytes_after=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=detail,
            ),
        ),
        warnings=(),
        duration_ms=0,
    )
