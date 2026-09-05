"""PDF-37 — the one shared seam every newly-honouring read verb calls.

`PLAN.md` §5.7's resolution order is planned once, at the CLI layer
(``cli/password.py``'s ``plan_password``), for the **global** ``--password-
file`` slot. What was missing is not a fourth resolution tier -- it is
somewhere for the eighteen read-only verbs (``compress``, ``delete``,
``extract``, ``info``, ``linearize``, ``merge``, ``meta get``, ``meta set``,
``ocr``, ``rasterize``, ``reorder``, ``repair``, ``rotate``, ``split``,
``stamp``, ``tables``, ``text``, ``watermark``) to ask "does THIS document
even need it" before spending the cost of actually reading a password.

Two pieces, one fact, two audiences:

* :class:`PasswordResolver` -- for a REAL run. Resolves the planned secret
  AT MOST ONCE per verb invocation, reused across every source that turns
  out to need it (an N:1 or N:N verb may see several sources; a shared
  global flag is read at most once regardless of how many of them are
  encrypted). Never resolves for a source that is not encrypted -- the
  common case, and the whole reason this is not "resolve eagerly, always":
  `permissions_run`'s existing eager-if-given pattern is accepted THERE
  because prompting is part of that verb's own security surface (`B-168`);
  inheriting it onto eighteen report-only verbs would mean every one of
  them prompts for a password on every interactive invocation of a
  perfectly ordinary PDF.
* :func:`predict_password_refusal` -- for a DRY run that would otherwise
  never open the document at all (`compress`/`repair`/`linearize`,
  `watermark`/`stamp`): the same encrypted-or-not fact, without ever
  resolving a value, so OR-7's ``dry == real`` on the *resolvability* tier
  holds without turning the preview into an oracle (X-89).

Both route through :func:`~pdf_toolkit.ports.structure.require_encryption`'s
``read_encryption`` -- the SAME credential-free capability
``encrypt``/``decrypt``/``permissions`` already use to answer "is this
document encrypted" without needing a password at all (D8's resolvability
tier: decidable from existence alone). No cryptography, no new adapter and
no new capability are introduced here; this module is orchestration only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import AuthError
from pdf_toolkit.ports.structure import PASSWORD_HINT, require_encryption
from pdf_toolkit.safety.paths import read_source_bytes
from pdf_toolkit.secret import Secret

__all__ = [
    "NO_PASSWORD",
    "PasswordResolver",
    "PasswordSource",
    "predict_password_refusal",
    "unresolvable_password_error",
]


# --------------------------------------------------------------------------- #
# `PasswordSource` -- moved here from `ops/crypto.py` by PDF-37, which is
# also its own reason: `encrypt`/`decrypt`/`permissions` legitimately reach
# `safety.atomic.AtomicWriter` (they write), but the eighteen OTHER,
# report-only verbs this spec adds a `PasswordSource` parameter to must NOT
# become reachable to it merely by importing the type for an annotation
# (`tests/registry.py`'s `is_mutating` is a STATIC, TRANSITIVE AST-import
# walk for exactly that name -- `cli/common.py`'s own `not_a_readable_file`
# docstring already tells this story once, for a different import path, and
# it recurred here: `ops/crypto.py` importing INTO this module for the type
# alone made `info` (`ops/inspect.py` -> this module -> `ops/crypto.py` ->
# `safety.atomic`) reclassify as mutating, measured, not assumed). This
# module has no other reason to import `ops/crypto.py`, so `PasswordSource`
# now lives where the eighteen actually need it, and `ops/crypto.py` imports
# it back FROM here -- the dependency runs one way only.
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
            raise unresolvable_password_error(self.slot)
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


def unresolvable_password_error(slot: str) -> AuthError:
    """The exit-6 ``AuthError`` for a slot nothing could supply.

    Public (no leading underscore) and exported: it was module-private when
    it lived in ``ops/crypto.py`` (only ``PasswordSource.resolve`` reached
    it), but ``ops/crypto.py``'s OWN tier-4 dry-run prediction
    (``_plan_prediction``, `encrypt`/`decrypt`/`permissions`) needs the
    IDENTICAL message for the identical condition, and that call now crosses
    a module boundary the same way ``PasswordSource`` itself does above.
    """
    return AuthError(
        f"no {slot} password available: pass --{slot}-password-file PATH "
        f"(or '-' to read one line from stdin), set the matching environment "
        f"variable, or run on a terminal to be prompted",
        redacted=True,
    )


#: The default for every ``password: PasswordSource`` parameter this spec adds
#: across ``ops/*.py`` -- "nothing was given, nothing is resolvable", exactly
#: what ``plan_password`` itself returns for that case (`cli/password.py`'s
#: own ``PasswordSource(slot=slot, source=None, read=None)`` branch). A
#: default, not a required keyword, so the ~150 existing unit tests that call
#: these ops functions directly (`ocr_run`, `watermark_run`, `compress_run`,
#: ...) over a PLAIN fixture keep passing unchanged -- this spec's seam is
#: additive, never a breaking signature change for the common, unencrypted
#: case.
NO_PASSWORD: Final[PasswordSource] = PasswordSource(slot="password", source=None)


class PasswordResolver:
    """Resolves *password* at most once per verb invocation.

    ``for_source`` answers "does THIS source need the secret, and if so,
    here it is" independently for every source it is asked about (each
    check is credential-free and cheap -- `read_encryption` never needs a
    password to answer ``encrypted``), but the underlying
    :class:`~pdf_toolkit.secret.Secret` is read from its file / environment
    variable / prompt at most ONCE, the first time any source actually
    needs it, and reused for every source after that.
    """

    def __init__(self, password: PasswordSource) -> None:
        self._password = password
        self._secret: Secret | None = None

    def for_source(self, source: Path) -> Secret | None:
        """``None`` for a plain document, or when nothing is resolvable at
        all -- the caller's own ``open_document``/``read_document_info``/...
        call raises the correct "a password is required" :class:`AuthError`
        on its own, with the never-echo-safe message that call site owns.
        """
        if self._password.read is None:
            return None
        facts = require_encryption().read_encryption(read_source_bytes(source), None)
        if not facts.encrypted:
            return None
        if self._secret is None:
            self._secret = self._password.resolve()
        return self._secret

    def clear(self) -> None:
        """Best-effort zero of the resolved secret, once every source this
        invocation touches has been read. A no-op if nothing was ever
        resolved (the common, plain-document case)."""
        if self._secret is not None:
            self._secret.clear()


def predict_password_refusal(
    source: Path, *, password: PasswordSource, verb: str
) -> AuthError | None:
    """D8's resolvability tier, for a verb whose ``--dry-run`` does not
    otherwise open the document at all.

    Cheap and credential-free, exactly like :class:`PasswordResolver`
    above, but this one never resolves -- only whether a password IS
    resolvable, never whether it is correct (X-89's oracle limit: a
    resolvable-but-wrong password predicts success here, and the real run is
    what finds out, `ops/crypto.py:44-53`'s own ruling, inherited).
    """
    if password.resolvable:
        return None
    facts = require_encryption().read_encryption(read_source_bytes(source), None)
    if facts.encrypted and not facts.unlocked:
        return AuthError(f"a password is required to {verb} this document; {PASSWORD_HINT}")
    return None
