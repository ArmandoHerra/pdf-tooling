"""PDF-36 half two — no envelope message carries a heap address.

`5bd9143f61`: four verbs rendered a live heap address into the message a user
reads. These two lines are the SAME message on two runs::

    ... stream <_io.BytesIO object at 0x7bb18cbcbe70>: unable to find trailer ...
    ... stream <_io.BytesIO object at 0x70c30c7cbf10>: unable to find trailer ...

**Why that is not cosmetic.** `PDF-30` shipped the rule that a documented
figure must be *derived*, *gated by a run*, or *absent*. A message carrying
``0x70f73b1c7ec0`` is none of the three: it cannot be quoted in `README.md`
under that rule, and it cannot be diffed between two runs.

**The product had already written the argument and not applied it.**
`adapters/pikepdf_structure.py:61-66` says the address is *"per-process noise,
never a fact about the document"* — and then strips it from ``get_warnings()``
only, leaving six sibling ``{error}`` interpolations on the ERROR path
uncleaned. `B-101` → `B-106` exactly: a proposition fixed on one carrier and
left standing on its siblings.

**ONE SITE, on the `B-068` precedent.** Thirty ``{error}`` interpolations live
under ``src/`` (`git grep -nE '\\{error\\}|\\{exc\\}|\\{err\\}' -- src/pdf_toolkit`
→ 30 at `ae723bc`). Sanitizing at the call sites is a thirty-site pass that a
thirty-first reintroduces, so the normalization sits at
``PdfToolkitError.to_dict()`` — the same chokepoint, and the same argument, the
product already accepted for ``redacted``.

**THIS MODULE IS HALF TWO ONLY.** It must stay green when the engine-boundary
belts of half one are reverted, and go red when the normalizer is. The ledger
forbids merging the two halves, and `AC5` drives that in both directions rather
than arguing it.
"""

from __future__ import annotations

import json
import re
from typing import Final

import pytest

from pdf_toolkit.adapters.pikepdf_structure import _WARNING_PREFIX_RE, _clean_warning
from pdf_toolkit.errors import AuthError, FailureError, PdfToolkitError, normalize_object_reprs
from pdf_toolkit.models import SCHEMA_VERSION
from pdf_toolkit.output import OutputFormat, emit_error

#: The guard AC4 drives over the CLI surface, kept here so the unit controls
#: and the end-to-end census cannot drift apart. SIX-plus LOWERCASE hex digits:
#: narrow enough that it does not fire on a byte literal (``0xC0``) or on a
#: dimension string (``2550x3300``), wide enough that no real CPython address
#: escapes it.
HEAP_ADDRESS: Final = re.compile(r"0x[0-9a-f]{6,}")

#: libqpdf's own sentence — the USEFUL half of the message, which the
#: normalizer must never touch. Rewriting engine diagnostic wording is an
#: explicit non-goal: what changes is the unstable prefix, never the diagnosis.
LIBQPDF_SENTENCE: Final = "unable to find trailer dictionary while recovering damaged file"

#: The message as `5bd9143f61` recorded it, verbatim.
POLLUTED: Final = f"stream <_io.BytesIO object at 0x7bb18cbcbe70>: {LIBQPDF_SENTENCE}"


# --------------------------------------------------------------------------- #
# AC6 -- the normalizer's unit controls.
# --------------------------------------------------------------------------- #


def test_ac6i_the_engine_sentence_survives_byte_identical() -> None:
    """AC6(i): the address goes; libqpdf's diagnosis does not.

    RED: widen the pattern until it eats the surviving sentence.
    """
    cleaned = normalize_object_reprs(POLLUTED)

    assert LIBQPDF_SENTENCE in cleaned, (
        f"the normalizer consumed libqpdf's own diagnosis. Only the unstable "
        f"`stream <... at 0x...>` prefix goes -- rewriting engine wording is a non-goal. "
        f"Got {cleaned!r}"
    )
    assert not HEAP_ADDRESS.search(cleaned), f"the address survived normalization: {cleaned!r}"
    assert cleaned == f"stream <_io.BytesIO object>: {LIBQPDF_SENTENCE}", (
        f"the collapse is to a STABLE DESCRIPTOR, not to nothing -- the reader should "
        f"still learn the failure was about a stream. Got {cleaned!r}"
    )


def test_ac6ii_a_message_matching_no_repr_passes_through_unchanged() -> None:
    """AC6(ii): non-suppression, and it is a rule rather than an accident.

    A sanitizer that silently empties a message it did not recognise is a wrong
    answer carrying a success exit code.

    RED: make the normalizer return ``""`` on no match.
    """
    for message in (
        "could not read this document's encryption",
        "linearization did not verify: the saved output is not linearized",
        "",
        "a bare 0xdeadbeef with no repr around it",
        "dimensions 2550x3300 and a byte 0xC0",
    ):
        assert normalize_object_reprs(message) == message, (
            f"a message carrying no object repr must pass through UNCHANGED; "
            f"{message!r} became {normalize_object_reprs(message)!r}"
        )


def test_ac6iii_two_messages_differing_only_by_address_normalize_equal() -> None:
    """AC6(iii): the diffability property this whole half exists for.

    Two runs of the same failure produced two different strings. After
    normalization they are one string, which is what makes the message
    quotable under `PDF-30`'s closure rule and diffable between runs.
    """
    prefix = "could not open PDF for compression: stream"
    first = f"{prefix} <_io.BytesIO object at 0x7bb18cbcbe70>: {LIBQPDF_SENTENCE}"
    second = f"{prefix} <_io.BytesIO object at 0x70c30c7cbf10>: {LIBQPDF_SENTENCE}"

    assert first != second, "the fixture is meaningless unless the raw messages differ"
    assert normalize_object_reprs(first) == normalize_object_reprs(second), (
        "two runs of the SAME failure still produce two different strings after "
        "normalization -- the address is per-process noise and must not survive it"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "<_io.BytesIO object at 0x7bb18cbcbe70>",
        "<function compress at 0x7f0102030405>",
        "prefix <pikepdf.Pdf object at 0xABCDEF012345> suffix",
        "two <a object at 0x000000000001> and <b object at 0xfffffffffff0>",
    ],
)
def test_ac6_every_repr_shape_loses_its_address(raw: str) -> None:
    """The pattern is not `_io.BytesIO`-specific.

    Any engine that interpolates any CPython default repr is covered, which is
    the point of putting this at a chokepoint instead of at six call sites.
    """
    cleaned = normalize_object_reprs(raw)
    assert not HEAP_ADDRESS.search(cleaned), f"{raw!r} kept its address: {cleaned!r}"
    assert "<" in cleaned and ">" in cleaned, (
        f"the repr's brackets should survive -- only the address half goes. Got {cleaned!r}"
    )


def test_the_normalizer_is_idempotent() -> None:
    """Running it twice is running it once.

    `to_dict()` may be called more than once on the same error, and a
    normalizer that degraded on a second pass would make the envelope depend on
    how many times it was rendered.
    """
    once = normalize_object_reprs(POLLUTED)
    assert normalize_object_reprs(once) == once


# --------------------------------------------------------------------------- #
# AC6(iv) -- `_clean_warning`'s FIRST-EVER tests.
#
# `git grep -n '_clean_warning' -- tests/ src/` returned 2 hits at `ae723bc`,
# BOTH in `src/`. The product's only repr-stripper was unpinned, so nothing
# would have noticed if it stopped working -- a finding in its own right.
# Leaving it untested beside a newly-tested sibling would recreate the exact
# asymmetry this half exists to close.
# --------------------------------------------------------------------------- #


def test_ac6iv_clean_warning_strips_the_stream_prefix() -> None:
    """The shape `Pdf.get_warnings()` actually emits."""
    assert _clean_warning("stream <_io.BytesIO object at 0x7bb18cbcbe70>: file is damaged") == (
        "file is damaged"
    )


def test_ac6iv_clean_warning_strips_the_parenthesised_object_offset_shape() -> None:
    """The second documented shape, with libqpdf's ``(object N M, offset K)``."""
    raw = "stream <_io.BytesIO object at 0x7bb18cbcbe70> (object 5 0, offset 439): EOF reached"
    assert _clean_warning(raw) == "EOF reached"


def test_ac6iv_clean_warning_passes_an_unmatched_warning_through_unchanged() -> None:
    """Non-suppression, for the sibling too.

    RED: break `_WARNING_PREFIX_RE` -- nothing failed on it before this test.
    """
    for raw in ("file is damaged", "", "no repr here at all"):
        assert _clean_warning(raw) == raw


def test_ac6iv_clean_warning_leaves_no_address_behind() -> None:
    """The property, not the mechanism.

    Stated as an invariant so a future rewrite of `_WARNING_PREFIX_RE` is
    measured against what it is FOR, not against its current spelling.
    """
    cleaned = _clean_warning("stream <_io.BytesIO object at 0x7bb18cbcbe70>: file is damaged")
    assert not HEAP_ADDRESS.search(cleaned)


def test_ac6iv_the_warning_prefix_regex_is_anchored_and_that_is_why_it_is_not_reused() -> None:
    """The mechanical fact that shaped D2, pinned so it cannot silently change.

    `_WARNING_PREFIX_RE` is ``^``-anchored: it matches ``str(error)`` BEFORE
    interpolation and does NOT match the composed message. That is precisely
    why `errors.normalize_object_reprs` borrows the idiom and not the constant
    -- reusing the anchored pattern mid-string would have matched nothing and
    shipped a sanitizer that sanitized nothing.
    """
    assert _WARNING_PREFIX_RE.pattern.startswith("^")
    composed = f"could not open PDF for compression: {POLLUTED}"
    assert _WARNING_PREFIX_RE.match(composed) is None, (
        "the anchored warning pattern now matches a COMPOSED message. If that is "
        "deliberate, D2's reasoning needs re-deriving -- it chose a separate pattern "
        "specifically because this one could not reach mid-string reprs"
    )
    assert _clean_warning(composed) == composed


# --------------------------------------------------------------------------- #
# The chokepoint itself -- the invariant asserted where it is OBSERVED.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fmt", list(OutputFormat), ids=[f.value for f in OutputFormat])
def test_every_rendered_shape_loses_the_address(fmt: OutputFormat, capsys) -> None:
    """One change at `to_dict()` covers table, json AND ndjson.

    Modelled on `tests/test_password_leaks.py:1070`, which calls `emit_error()`
    directly with a synthetic error and greps the combined output for a
    sentinel. Asserting on the RENDERED envelope rather than on the normalizer
    means this stays honest regardless of which site the fix chose.
    """
    emit_error(FailureError(f"could not open PDF for compression: {POLLUTED}"), fmt)
    captured = capsys.readouterr()
    both = captured.out + captured.err

    assert both.strip(), f"-o {fmt.value} rendered nothing at all"
    assert not HEAP_ADDRESS.search(both), (
        f"-o {fmt.value}: a heap address reached the user -- {both!r}"
    )
    assert LIBQPDF_SENTENCE in both, (
        f"-o {fmt.value}: the engine's own diagnosis was lost along with the address -- {both!r}"
    )


# --------------------------------------------------------------------------- #
# AC9 -- X-410's freeze frame. Closure is by ADDITION only.
# --------------------------------------------------------------------------- #


def test_ac9_the_envelope_key_set_is_exactly_four_keys() -> None:
    """`to_dict()`'s keys are public API and PDF-36 adds none."""
    assert set(FailureError("x").to_dict()) == {"code", "kind", "message", "path"}


def test_ac9_the_schema_version_is_still_one() -> None:
    """`X-410`'s pre-`v1.0.0` freeze. The four envelope divergences and the
    `schema_version` question belong to `PDF-39`/`PDF-40`, not here."""
    assert SCHEMA_VERSION == 1
    rendered = json.loads(
        _render_json(FailureError("could not open PDF for compression: boom")),
    )
    assert rendered["schema_version"] == 1
    assert set(rendered["error"]) == {"code", "kind", "message", "path"}


def _render_json(error: PdfToolkitError) -> str:
    from pdf_toolkit.output.json import render_error_json

    return render_error_json(error.to_dict())


def test_ac9_redaction_still_redacts_the_path() -> None:
    """`B-068` must be PROVEN undisturbed, not assumed.

    D2 edited the same method that honours ``redacted``; a criterion that only
    checked the message would not notice if the redaction branch were dropped
    in the same edit.
    """
    from pdf_toolkit.secret import REDACTED

    payload = AuthError("nope", path="/secret/value", redacted=True).to_dict()
    assert payload["path"] == REDACTED
    assert payload["path"] != "/secret/value"


def test_ac9_a_non_redacted_path_is_untouched() -> None:
    """The complement — otherwise the redaction assertion above passes on a
    `to_dict()` that redacts unconditionally."""
    payload = FailureError("nope", path="/ordinary/path").to_dict()
    assert payload["path"] == "/ordinary/path"


def test_ac9_a_message_with_no_repr_is_bit_identical_through_the_envelope() -> None:
    """The overwhelming majority of errors carry no repr at all, and PDF-36
    must be invisible to every one of them."""
    message = "the supplied password did not open this document"
    assert FailureError(message).to_dict()["message"] == message
