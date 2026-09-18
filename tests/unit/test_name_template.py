"""``safety/naming.py`` — the ``--name`` template renderer (Design §D6, AC8/AC9).

The binding invariant (§D6, verbatim): for every template and every set of
substituted values, rendering either **raises** a classified error, or
returns a path whose final component ``c`` is not one of ``""``, ``"."``,
``".."``; contains no ``/``, no ``os.sep``/``os.altsep``, and no NUL byte; is
not absolute; and whose parent, once both sides are resolved, is ``out_dir``
itself. AC8 asks for at least 1000 examples over templates and values drawn
from at least: ``../``, ``..\\``, ``/``, ``\\x00``, a leading ``/``, ``~``,
``.``, ``..``, the empty string, a >255-byte name, and ordinary names.

**PDF-77 — what changed, and why the search now reaches further.** The
generator used to draw stems from an alphabet that blacklisted the NUL byte,
``/`` and ``\\`` and capped at forty characters, so four of the renderer's
five refusal branches were unreachable from it and the property only ever
exercised the ones ordinary text can reach. Three things now hold instead:

* the seed roster is **guaranteed**, not sampled. Every value in
  ``_SEED_VALUES`` runs under every template in ``_TEMPLATES`` on every run,
  as explicit examples built from the two rosters rather than transcribed
  (``Phase.explicit`` is in the default phase list, which is what makes an
  ``@example`` guaranteed). A seed added without a matching example fails by
  name in the meta-arm below instead of quietly never running;
* ``_hostile_text`` sits beside ``_ordinary_text`` rather than replacing it,
  and admits path separators, leading separators and components long enough
  that no filesystem will take them. It deliberately does **not** admit the
  NUL byte: that branch has exactly the one trigger condition and no
  interaction with template shape, so sampling it would buy nothing and would
  cost the suite its one deterministic red control;
* the property records whether each example was refused or returned
  (``--hypothesis-show-statistics``), because widening a generator raises the
  share of examples that take the early ``return`` where nothing is asserted,
  and a property whose interesting branch has quietly become rare is a
  vacuous control with excellent branding.

**PDF-85 — what this module's oracle now discriminates, and the premise it
corrects.** ``PDF-77`` paid out through its **oracle**, not
through its generator: ``_ordinary_text``'s alphabet is byte-identical across
that commit and an unassigned codepoint was drawable from it before — what
``PDF-77`` added was this module's first filesystem-touching assertion. That
assertion called itself a byte-length oracle and then caught **every**
``OSError``, so on the four ``macos-14`` legs of CI run ``35295764623`` it
reddened on an **eight-byte** component against the 255-byte limit it exists to
police, while ``render_name`` returned the identical component here, where the
filesystem takes it. The refusal is now classified by ``errno``: a length
refusal is still the renderer's defect and still reds, driven by a real
syscall; the one measured encoding refusal is RECORDED against ledger
``2b88707a36``; and every other ``errno`` reds as unclassified, so the
narrowing can never become a swallow. A reader who inherits the falsified
premise goes looking for the fix in the generator, and correctly finds nothing
there.

The profile that makes a failure here recoverable — ``print_blob`` and a
persisted example database outside the repository tree — lives in
``tests/conftest.py`` and reaches this module because pytest imports that file
before any test module. It used to reach here only because
``tests/test_pagerange.py`` sorts earlier during collection (``B-147``).
"""

from __future__ import annotations

import errno
import os
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import pytest  # noqa: E402
from hypothesis import HealthCheck, Phase, event, example, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.database import DirectoryBasedExampleDatabase  # noqa: E402
from hypothesis.errors import InvalidArgument  # noqa: E402

import conftest  # noqa: E402
from pdf_tooling.errors import OutputEscapesDirError  # noqa: E402
from pdf_tooling.safety import naming  # noqa: E402
from pdf_tooling.safety.naming import render_name, used_fields  # noqa: E402

#: The measured ``macos-14`` counterexample, spelled ONCE so the seed roster
#: and the control arms below cannot drift apart on it. ``U+1239A`` is category
#: ``Cn`` (unassigned), ``unicodedata.name`` raises on it, four UTF-8 bytes,
#: an eight-byte rendered component under ``{stem}.{ext}`` — accepted by every
#: filesystem this loop can reach, and refused by the one it cannot.
_MACOS_COUNTEREXAMPLE: Final[str] = "\U0001239a"

#: AC8's own named seed values, always included alongside hypothesis-generated
#: ordinary text — the property must hold on the adversarial values named in
#: the spec, not merely on whatever hypothesis happens to draw. Since PDF-85
#: this roster holds AC8's seeds **plus measured counterexamples** — values no
#: spec named, which a real filesystem was observed to refuse — and the second
#: kind is labelled in place so the roster's meaning cannot quietly change.
_SEED_VALUES = (
    "../",
    "..\\",
    "/",
    "\x00",
    "/leading",
    "~",
    ".",
    "..",
    "",
    "a" * 300,
    "ordinary-name",
    # PDF-85, and deliberately NOT one of AC8's named adversarial values: the
    # counterexample all four macos-14 legs of CI run 35295764623 shrank to,
    # identically, across four interpreters and two xdist workers. It is pinned
    # here rather than left to the hypothesis example database because CI
    # runners are ephemeral and carry that database nowhere — `Phase.explicit`
    # is the only carry that replays it on every run, everywhere.
    _MACOS_COUNTEREXAMPLE,
)

#: The template roster, lifted out of the strategy so ONE roster feeds both
#: the generator and the explicit examples (PDF-77 D6). Listing the shapes
#: twice is how a seed ends up guaranteed under four templates and missing
#: under the fifth, with nothing able to say so.
_TEMPLATES: Final[tuple[str, ...]] = (
    "{stem}.{ext}",
    "{stem}-{index:03}.{ext}",
    "{stem}-{page:03}.{ext}",
    "{index:03}-{stem}.{ext}",
    "{stem}",
)

_templates = st.sampled_from(_TEMPLATES)

_ordinary_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00/\\"),
    max_size=40,
)

#: Both spellings, so the strategy is correct on a platform where `os.sep` is
#: the backslash and `os.altsep` the forward slash as well as on this one.
_SEPARATORS = st.sampled_from(("/", "\\"))

#: Deliberately adversarial component text, kept OUT of `_ordinary_text` on
#: purpose: a strategy called *ordinary* that draws separators and 300-byte
#: components is a name that lies to its next reader, and the two need
#: different size caps — forty characters is the right cap for ordinary text
#: and cannot reach a byte limit at all.
#:
#: Note that raising a CHARACTER cap is not the same as reaching a BYTE limit:
#: `st.text(max_size=n)` counts characters, and hypothesis biases hard toward
#: short draws, so a long free-form text strategy reaches an over-length
#: component approximately never. The over-long shape below is therefore built
#: rather than hoped for, and AC11's probe counts what it actually reaches.
_hostile_text = st.one_of(
    st.builds(
        lambda left, sep, right: f"{left}{sep}{right}",
        _ordinary_text,
        _SEPARATORS,
        _ordinary_text,
    ),
    st.builds(lambda sep, rest: f"{sep}{rest}", _SEPARATORS, _ordinary_text),
    st.builds(
        lambda char, count: char * count,
        st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00/\\"),
        st.integers(min_value=300, max_value=400),
    ),
)

#: The seeds are NOT a branch here, and that is deliberate (a declared
#: deviation from the spec's §D7 sentence, which offers them as one). They are
#: guaranteed by `@example` instead, which is strictly stronger than sampling
#: them — and leaving them in the generator as well would make the NUL byte
#: generator-reachable, which is precisely what AC14 requires it not to be:
#: a control that reds whether or not the seeds are pinned proves nothing
#: about pinning.
_stem_strategy = st.one_of(_ordinary_text, _hostile_text)

#: The vacuity meter's two outcomes, named once so the strings cannot drift
#: between the emit sites and whatever reads `--hypothesis-show-statistics`.
_REFUSED: Final[str] = "render_name refused the rendered component"
_RETURNED: Final[str] = "render_name returned a contained component"

#: The meter's THIRD outcome (PDF-85 D6), emitted where ``event()`` is in
#: domain and guarded where it is not (PDF-88 D6).
#:
#: **PDF-88 CORRECTS THE CLAIM THIS COMMENT USED TO MAKE.** It said that where
#: this event fires, ``--hypothesis-show-statistics`` names it and the operator
#: sees the observation without reading a spec. Measured, and false for the only
#: firing pattern that matters: the statistics block tallies the GENERATE phase,
#: and the pinned counterexample is reachable only through the EXPLICIT-example
#: phase -- ``Phase.explicit``, which is precisely the carry PDF-85 chose so the
#: counterexample replays everywhere, CI runners included. Under a faithful
#: component-scoped refusal the recorded branch fired six times and the
#: statistics block named it ZERO times; only an artificial blanket refusal,
#: which refuses ordinary generated components too, makes the meter report it.
#:
#: So the event stays for the one caller that is inside its domain -- the
#: property -- and the channel the OPERATOR actually reads is the
#: ``_EncodingRefusalRecorded`` warning the oracle publishes beside it, which
#: renders in the warnings summary on every host, on red runs and green ones,
#: and is the instrument the arms below assert AGREEMENT against.
_ENCODING_REFUSED: Final[str] = "the filesystem refused the component's ENCODING, not its length"

#: The publication's text, INVARIANT and spelled once (PDF-88 D4).
#:
#: **Invariant is a declared divergence from PDF-86's precedent, on a measured
#: reason.** PDF-86's message embeds its measured numbers because it fires at
#: most once per leg. This one is reachable from the property, which draws a
#: ``Cn`` codepoint in roughly 44% of examples, so a message carrying the
#: component would scatter the warnings summary into hundreds of distinct lines
#: on a refusing host. The varying detail stays where it belongs -- in the
#: ``_DEFECT`` and ``_UNCLASSIFIED`` assertion messages, which already name the
#: component, the byte count and the errno. What rides here is the invariant
#: citation, and the errno by SYMBOLIC name for the reason
#: ``_ENCODING_REFUSAL_ERRNOS`` states below: the integer is wrong on one half
#: of this product's CI matrix whichever half it was copied from.
_ENCODING_REFUSAL_PUBLICATION: Final[str] = (
    "THE FILESYSTEM REFUSED THE COMPONENT'S ENCODING and this run RECORDED it rather than "
    "reddening: there is no pathconf for which codepoints a kernel's table knows, so the "
    "renderer is not contracted to predict it. Refusal errno, symbolic: "
    f"{errno.errorcode[errno.EILSEQ]}. The measured counterexample this verdict was derived "
    "from is U+1239A, category Cn (unassigned), four UTF-8 bytes, an eight-byte rendered "
    "component. The product consequence -- a bare OSError escaping "
    "safety/atomic.py::AtomicWriter._replace onto cli/main.py's bug path -- is filed at "
    "ledger 2b88707a36, carrier B-352, and is NOT closed by the arm that published this."
)

#: The one refusal class this oracle RECORDS instead of reddening on, held as a
#: named frozenset of SYMBOLIC ``errno`` constants — the shape
#: ``safety/atomic.py:205``'s ``_LINK_FALLBACK_ERRNOS`` already uses one layer
#: down, because it is the same idea one layer up. **One member, measured.** A
#: second joins it when a run produces one, and not before.
#:
#: **Symbolic, never the integer, and that is the load-bearing choice.**
#: ``errno.EILSEQ`` resolves to a different number here than it does on the
#: host that produced the measurement, and ``errno.ENAMETOOLONG`` likewise, so
#: a transcribed integer is wrong on one half of this product's CI matrix
#: whichever half it was copied from — and a transcribed length number would
#: retire the renderer-defect verdict exactly where it has already fired once.
#: The interpreter resolves these names on the host it runs on, which is the
#: only spelling that is correct on both.
_ENCODING_REFUSAL_ERRNOS: Final[frozenset[int]] = frozenset({errno.EILSEQ})

#: The three verdicts, named once so the oracle and the control arms cannot
#: drift apart on a string. Two of them red; the middle one is the whole of
#: what PDF-85 moved.
_DEFECT: Final[str] = "the renderer's defect"
_RECORDED: Final[str] = "recorded, not the renderer's contract"
_UNCLASSIFIED: Final[str] = "unclassified, and therefore still red"


def _guaranteed_seed_examples(test: Callable[..., None]) -> Callable[..., None]:
    """Pin every seed under every template — the cross-product, DERIVED.

    A seed roster without the template it bites under is a roster of
    near-misses: only ``"{stem}"`` renders the component as the seed verbatim,
    so under ``"{stem}.{ext}"`` the seed ``".."`` renders ``"...pdf"``, which
    refuses nothing. Taking the cross-product means nobody has to reason about
    which pairing bites, and a twelfth seed value or a sixth template extends
    the guaranteed set with no second edit — which AC8 demonstrates by
    extension rather than asserting.
    """
    for stem in _SEED_VALUES:
        for template in _TEMPLATES:
            test = example(template=template, stem=stem)(test)
    return test


def _is_single_component(candidate: Path, *, out_dir: Path) -> bool:
    resolved_parent = candidate.resolve(strict=False).parent
    resolved_base = out_dir.resolve(strict=False)
    return resolved_parent == resolved_base


@dataclass(frozen=True)
class _Verdict:
    """What :func:`_classify_filesystem_refusal` decided about one ``OSError``.

    Exactly one of ``message`` and ``event_name`` is ever populated, and that
    is the structural form of "this is a narrowing, not a swallow": a verdict
    carrying neither would be a refusal the oracle returns from having neither
    reddened nor recorded. The roster arm asserts the exclusive-or on every
    member rather than trusting this sentence.
    """

    kind: str
    message: str = ""
    event_name: str = ""


def _classify_filesystem_refusal(error: OSError, *, name: str, out_dir: Path) -> _Verdict:
    """Which of THREE verdicts a refusal from ``candidate.touch()`` carries.

    A pure function over the exception, and module-level rather than an ``if``
    chain inside the ``except`` block, because the two readers need different
    things from it: the oracle runs inside a hypothesis property, where
    assertions shrink and ``event()`` is available, while the control arms
    below need to interrogate the verdict deterministically, once, with no
    property around them. Splitting the decision from the syscall gives both
    without either compromising the other.

    **A declared deviation from PDF-85 §D2, in one detail.** §D2 has the
    recorded branch emit its ``event()`` here. It does not: ``event()`` raises
    ``InvalidArgument("Cannot record events outside of a test")`` when there is
    no hypothesis build context, which every deterministic arm below is, so a
    classifier that emitted would be a classifier no control could call. The
    decision — including WHICH event — stays wholly here; the oracle performs
    the one line this function names.
    """
    encoded = len(name.encode("utf-8", "surrogateescape"))
    if error.errno == errno.ENAMETOOLONG:
        return _Verdict(
            kind=_DEFECT,
            message=(
                f"render_name returned a component of {encoded} bytes that the filesystem "
                f"under {out_dir} refuses as ENAMETOOLONG ({error}); the renderer handed a "
                "name to a caller that AtomicWriter could only fail on with a bare OSError"
            ),
        )
    if error.errno in _ENCODING_REFUSAL_ERRNOS:
        # THE MEASURED OBSERVATION, CARRIED WHERE IT IS READ (PDF-85 D5).
        #
        # Ledger row `2b88707a36`, carrier `B-352`, CI run 35295764623 and its
        # four `test (3.1x, macos-14)` jobs. `render_name` returned
        # `'\U0001239a.pdf'` — U+1239A, category `Cn` (unassigned), four UTF-8
        # bytes, an eight-byte component — every clause of the §D6 containment
        # invariant held, and macOS's filesystem refused it with that host's
        # own `errno.EILSEQ`. Nothing in §D6, in README.md's frozen section, or
        # in `naming.py`'s own docstring promises that an arbitrary filesystem
        # will accept a returned component; the only filesystem-facing promise
        # the module makes is the byte-length one, and there is no `pathconf`
        # for "which codepoints does this kernel's table know", so the renderer
        # is not contracted to predict this and is not asked to here.
        #
        # WHAT IS STILL BROKEN, AND WHERE IT IS FILED — a citation, never a fix.
        # The product consequence of this refusal is a bare `OSError` escaping
        # `safety/atomic.py::AtomicWriter._replace` onto `cli/main.py`'s bug
        # path: a traceback and exit 1 with no error envelope. It is filed as a
        # `low` row at `2b88707a36`/`B-352` and is DELIBERATELY unspecced —
        # this loop has no host that can drive it red, and a spec would ship
        # with an acceptance criterion nobody here could satisfy. Editing
        # `atomic.py` is that row's work, not this arm's.
        return _Verdict(kind=_RECORDED, event_name=_ENCODING_REFUSED)
    return _Verdict(
        kind=_UNCLASSIFIED,
        message=(
            f"UNCLASSIFIED errno {error.errno} "
            f"({errno.errorcode.get(error.errno, 'no symbolic name')}): the filesystem under "
            f"{out_dir} refused the {encoded}-byte component {name!r} ({error}) for a reason "
            "this oracle neither predicts nor has ever measured. It reds on purpose: a "
            "two-way split would pass here, which is how an oracle goes green on an "
            "unwritable tmp_path. Read the errno name out of this message and take it back "
            "to the PM as a measurement — it is the second data point this loop does not have"
        ),
    )


def _the_filesystem_accepts(candidate: Path, *, out_dir: Path) -> None:
    """A behavioural oracle for the byte-length refusal, not a copy of it.

    The over-length branch is the one refusal the containment assertions
    cannot observe: raise the product's byte limit so an over-long component
    is RETURNED and every one of them stays green, because none of them
    asserts anything about length. Transcribing the product's own limit here
    would pin the constant to itself. Creating the file asks the filesystem
    instead — which is the authority the limit exists to keep the product away
    from — inside this test's own `tmp_path`, and removes it again.

    **PDF-85: the docstring above and the code below now agree.** This block
    caught every ``OSError`` and called them all the renderer's fault, so a
    255-byte oracle reddened on an eight-byte name. It still asks the same
    filesystem the same question — the authority is unchanged and the limit is
    still not transcribed — and :func:`_classify_filesystem_refusal` decides
    which of the three answers came back.
    """
    try:
        candidate.touch()
    except OSError as error:
        verdict = _classify_filesystem_refusal(error, name=candidate.name, out_dir=out_dir)
        if verdict.kind == _RECORDED:
            # THE PUBLICATION (PDF-88 D4), on every recorded refusal and on
            # every host. It is not decoration: it is the instrument that makes
            # half 1's two worlds distinguishable at all, because
            # `assert not candidate.exists()` is TRUE IN BOTH -- a refused
            # `touch()` never created the file an accepted one is unlinked
            # from. It is also the ONLY channel that can carry this
            # observation, since `--hypothesis-show-statistics` tallies the
            # generate phase and the pinned counterexample is reachable only
            # through the explicit-example phase (see `_ENCODING_REFUSED`).
            #
            # NO `stacklevel`, and the linter is overruled on the same
            # measurement `tests/test_import_boundaries.py` records at its own
            # publication: B028's advice reports `_pytest/python.py`, which
            # localises nothing, while the default reports this module and this
            # line, which is the exact publication point.
            warnings.warn(  # noqa: B028 - measured, see the comment above
                conftest._EncodingRefusalRecorded(_ENCODING_REFUSAL_PUBLICATION)
            )
            # `event()`'s DOMAIN is the hypothesis build context, and FOUR of
            # this oracle's five call sites are outside it. The call is kept
            # rather than dropped -- half 2 below substitutes its own in-domain
            # `event` and asserts the emission -- and guarded by the narrowest
            # thing that works.
            #
            # EXCEPTION-SHAPED, NOT PREDICATE-SHAPED, and that was measured
            # rather than chosen: `currently_in_test_context()` asks "am I
            # inside a build context?", answers no under half 2's substituted
            # callable, and skips a channel the caller had already put in
            # domain -- which reds half 2 with `recorded == []`. The narrow
            # question is "did THIS channel refuse THIS call", and a
            # substituted in-domain `event` never refuses it.
            try:
                event(verdict.event_name)
            except InvalidArgument:
                pass
            return
        raise AssertionError(verdict.message) from error
    candidate.unlink()


# --------------------------------------------------------------------------- #
# PDF-88 — the premise is DERIVED from the host, and the branch is ASSERTED
# --------------------------------------------------------------------------- #

#: The two legal answers a host can give, named once so the helper below, the
#: arms that call it and its own failure messages cannot drift apart on a
#: string.
_HOST_ACCEPTED: Final[str] = "accepted"
_HOST_RECORDED: Final[str] = "recorded"
_HOST_BRANCHES: Final[tuple[str, ...]] = (_HOST_ACCEPTED, _HOST_RECORDED)


def _published_refusals(caught: list[warnings.WarningMessage]) -> list[str]:
    """The channel's own messages out of a ``catch_warnings`` record, and nothing else.

    Filtering by CLASS rather than by text is what makes the reader specific to
    this channel: an unrelated ``UserWarning`` from anywhere in the call path
    would otherwise be counted as a published encoding refusal, and an arm that
    counts the wrong warnings agrees with the probe by accident.
    """
    return [
        str(entry.message)
        for entry in caught
        if isinstance(entry.message, conftest._EncodingRefusalRecorded)
    ]


def _host_refusal_for(candidate: Path, *, out_dir: Path) -> OSError | None:
    """Ask THIS host the same question the oracle is about to ask, one call earlier.

    Returns the ``OSError`` a refusing filesystem raised, or ``None`` on a
    filesystem that took the name -- in which case the file it created is
    removed again, so the probe leaves the directory exactly as it found it.

    **It calls nothing from hypothesis, so its domain is every caller.** That
    is the whole point of splitting it out: the oracle's own refusal happens
    inside a `try` whose `except` has already decided what to do about it, so
    a caller outside a build context cannot see WHICH answer came back. This
    performs the same syscall one call earlier, where the answer can be
    branched on, exactly as PDF-85's pure classifier does one layer down.

    **The filesystem stays the authority, and that is why this is not a
    platform branch.** It does not ask which platform is running or which
    codepoint is in the name -- there is no `pathconf` for "which codepoints
    does this kernel's table know", and transcribing a rule here would pin a
    premise to itself. It asks the filesystem, which is the only observer that
    has ever answered this question on either host.
    """
    assert _is_single_component(candidate, out_dir=out_dir), (
        f"the probe would create {candidate} outside {out_dir}; a helper that writes to "
        "disk asserts its own containment before it writes, never after"
    )
    try:
        candidate.touch()
    except OSError as error:
        return error
    candidate.unlink()
    return None


def _the_hosts_answer_for(candidate: Path, *, out_dir: Path) -> str:
    """Branch on the measured premise, assert WHICH branch was taken, and name it.

    **Two instruments, independently derived, asserted to AGREE — and that is
    the clause that closes this class rather than patching it.** The premise
    comes from :func:`_host_refusal_for`; the branch evidence comes from the
    publication channel. If the channel is ever silenced, the probe still says
    *refused* while the channel says *nothing*, and this reds. If the probe is
    ever stubbed to claim acceptance, the channel still publishes, and this
    reds the other way. A design that took the premise from the channel alone
    would read "accepted" on a refusing host the moment the channel went
    quiet, which is this defect rebuilt one level up.

    **The stated assumption, rather than a hidden one:** the two calls hit the
    same path microseconds apart, so if a filesystem's answer changed between
    them the agreement assertion fails. The helper cannot pass vacuously in
    either direction.

    **Both observers set their own filter state.** The channel is read through
    `warnings.catch_warnings(record=True)` with an explicit
    `simplefilter("always")` -- which is what `pytest.warns` does internally --
    and never by inheriting whatever filter the ambient process happens to
    carry. That is the channel-domain lesson applied to the READER: an observer
    that inherits a filter is an observer whose result depends on what ran
    before it.
    """
    refusal = _host_refusal_for(candidate, out_dir=out_dir)

    # The third answer, handed UP as a measurement and never skipped: a host
    # that refuses for a reason this design has never measured is information
    # the loop does not have, and the only honest thing to do with it is red
    # while naming it. Decided BEFORE the oracle runs so that the message the
    # reader gets is the PREMISE's, naming the answer the host actually gave.
    if refusal is not None and refusal.errno not in _ENCODING_REFUSAL_ERRNOS:
        raise AssertionError(
            f"UNCLASSIFIED host answer: the filesystem under {out_dir} refused the probe "
            f"with errno {refusal.errno} "
            f"({errno.errorcode.get(refusal.errno, 'no symbolic name')}), which this arm "
            f"neither predicts nor has ever measured ({refusal}). It reds on purpose: a "
            "two-way split would take an unwritable tmp_path for a measured encoding "
            "refusal. Read the errno NAME out of this message and take it back to the PM "
            "as a measurement -- it is a data point this loop does not have"
        )

    with warnings.catch_warnings(record=True) as published:
        warnings.simplefilter("always")
        _the_filesystem_accepts(candidate, out_dir=out_dir)
    recorded = _published_refusals(published)

    if refusal is None:
        assert recorded == [], (
            f"the probe measured this host ACCEPTING the component, and the oracle then "
            f"published {len(recorded)} encoding refusal(s) on the same name. The two "
            "instruments disagree, so one of them is lying and this helper cannot say "
            f"which branch the host took: {recorded!r}"
        )
        assert not candidate.exists(), (
            "the host ACCEPTED the component and the oracle left its own probe file "
            "behind -- note that this assertion is true on a REFUSING host for a trivial "
            "reason (nothing was ever created), which is why it is made here, inside the "
            "branch where the file did exist, and never as the arm's only assertion"
        )
        return _HOST_ACCEPTED

    assert len(recorded) == 1, (
        f"the probe measured this host REFUSING the component with "
        f"{errno.errorcode.get(refusal.errno, refusal.errno)}, and the oracle published "
        f"{len(recorded)} encoding refusal(s) rather than exactly one. The two instruments "
        "disagree: a silenced channel reads as an accepting host, which is the premise "
        "PDF-88 exists to stop this arm from assuming"
    )
    return _HOST_RECORDED


@_guaranteed_seed_examples
@given(template=_templates, stem=_stem_strategy)
@settings(
    max_examples=1000,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_render_name_either_raises_or_returns_a_single_contained_component(
    tmp_path: Path, template: str, stem: str
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    try:
        candidate = render_name(
            template, out_dir=out_dir, stem=stem, ext="pdf", index=1, page=1, range_text="1"
        )
    except OutputEscapesDirError:
        event(_REFUSED)
        return  # a raise satisfies the invariant -- nothing more to check
    event(_RETURNED)
    name = candidate.name
    assert name not in ("", ".", "..")
    assert "/" not in name
    if os.sep and os.sep != "/":
        assert os.sep not in name
    if os.altsep:
        assert os.altsep not in name
    assert "\x00" not in name
    assert not os.path.isabs(name)
    assert _is_single_component(candidate, out_dir=out_dir)
    _the_filesystem_accepts(candidate, out_dir=out_dir)


def test_every_seed_value_is_guaranteed_under_every_template() -> None:
    """AC7. The seeds are pinned, and the pinning is checked STRUCTURALLY.

    Reading the decorated function's own explicit-example list, rather than
    reading the source or counting decorators by eye, is what makes "adding a
    seed without a matching example" fail by name instead of silently
    shrinking the guaranteed set.
    """
    property_under_test = test_render_name_either_raises_or_returns_a_single_contained_component
    examples = getattr(property_under_test, "hypothesis_explicit_examples", [])
    assert examples, (
        "the property carries NO explicit examples, so every adversarial value in "
        "_SEED_VALUES is merely sampled -- AC7's whole point is that they are not"
    )
    stems = {entry.kwargs["stem"] for entry in examples}
    assert stems == set(_SEED_VALUES), (
        "the guaranteed stem set is not the seed roster; missing "
        f"{sorted(set(_SEED_VALUES) - stems)!r}, unexpected {sorted(stems - set(_SEED_VALUES))!r}"
    )
    templates = {entry.kwargs["template"] for entry in examples}
    assert templates == set(_TEMPLATES), (
        "the guaranteed template set is not the template roster; a seed pinned under "
        "some templates and not others is a near-miss wearing a guarantee"
    )
    assert len(examples) == len(_SEED_VALUES) * len(_TEMPLATES), (
        f"{len(examples)} explicit examples for {len(_SEED_VALUES)} seeds x "
        f"{len(_TEMPLATES)} templates -- the cross-product is the contract, so this is "
        "either a duplicate pairing or a missing one"
    )


# --------------------------------------------------------------------------- #
# PDF-85 — the three control arms for the re-scoped oracle
# --------------------------------------------------------------------------- #


def _refusing_touch(errno_value: int) -> Callable[..., None]:
    """A ``Path.touch`` that refuses with *errno_value*, and refuses nothing else.

    The injection point is the ``touch`` the oracle itself calls — never
    ``errno``, whose numbers are the one thing in this design that must stay
    the interpreter's to resolve, and never a branch on which host is running,
    which would encode a rule about a filesystem nobody in this loop has
    measured. Only the ONE arm that cannot be driven against a real syscall
    here uses this; the byte-length arm above deliberately does not.
    """

    def touch(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(errno_value, os.strerror(errno_value), str(self))

    return touch


def test_an_over_long_component_still_reds_the_oracle_on_a_real_syscall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2. The byte-length branch is LIVE, and the filesystem is still the authority.

    Driven exactly as the oracle's own docstring prescribes: raise the
    product's byte limit so an over-long component is RETURNED, then hand it to
    a real `tmp_path`. **Nothing is injected anywhere in this arm's path** — the
    errno in the message is the one the kernel produced, which is what makes
    this arm evidence about a filesystem rather than about a stand-in.

    The first half is this arm's own red-of-the-red: at the SHIPPED limit the
    case cannot be constructed at all, because `render_name` refuses first. The
    arm asserts that rather than quietly passing through it, so a change that
    made the over-long component unreachable fails loudly here instead of
    leaving an oracle with nothing left to observe.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    shipped_limit = naming._MAX_COMPONENT_BYTES

    with pytest.raises(OutputEscapesDirError):
        render_name("{stem}.{ext}", out_dir=out_dir, stem="a" * 300, ext="pdf")

    monkeypatch.setattr(naming, "_MAX_COMPONENT_BYTES", 10_000)
    candidate = render_name("{stem}.{ext}", out_dir=out_dir, stem="a" * 300, ext="pdf")
    encoded = len(candidate.name.encode("utf-8", "surrogateescape"))
    assert encoded > shipped_limit, (
        f"the raised limit returned a {encoded}-byte component, inside the shipped "
        f"{shipped_limit}-byte limit — this arm did not construct its own case, and an "
        "oracle asked a question the filesystem was always going to answer yes to"
    )

    with pytest.raises(AssertionError) as caught:
        _the_filesystem_accepts(candidate, out_dir=out_dir)

    message = str(caught.value)
    assert "ENAMETOOLONG" in message, (
        f"the refusal reddened without naming ENAMETOOLONG, so the next reader has to "
        f"look a number up to know which branch fired: {message}"
    )
    assert f"{encoded} bytes" in message, (
        f"the message lost the component's byte count, which is the one figure that says "
        f"WHY this is the renderer's defect: {message}"
    )


#: The verdict roster: every ``errno`` this design has an opinion about, and
#: three it deliberately does not. SYMBOLIC constants only — an integer here
#: would be correct on at most one half of this product's CI matrix, for the
#: reason ``_ENCODING_REFUSAL_ERRNOS`` states above.
_VERDICT_ROSTER: Final[tuple[tuple[int, str], ...]] = (
    (errno.ENAMETOOLONG, _DEFECT),
    (errno.EILSEQ, _RECORDED),
    (errno.EACCES, _UNCLASSIFIED),
    (errno.ENOENT, _UNCLASSIFIED),
    (errno.ENOSPC, _UNCLASSIFIED),
)


@pytest.mark.parametrize(
    ("errno_value", "expected"),
    _VERDICT_ROSTER,
    ids=[errno.errorcode[value] for value, _ in _VERDICT_ROSTER],
)
def test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts(
    tmp_path: Path, errno_value: int, expected: str
) -> None:
    """AC4/AC6/AC8. The whole contract of the re-scope, pinned in one arm.

    **This is where the monotonicity claim is discharged in mechanism rather
    than in prose.** Before PDF-85 every member of this roster reached an
    `AssertionError`; after it, every member except `errno.EILSEQ` still does.
    Exactly one verdict moved, in exactly one direction, and the allowlist's
    width is that claim's own measure — which is why the width is asserted here
    and not merely described above.

    **It runs against the EIGHT-BYTE counterexample rather than a long name**,
    which is what makes the `ENAMETOOLONG` cell load-bearing: the length
    verdict follows the errno NAME, never a transcribed number and never the
    component's own size. A design that had hard-coded this host's own
    `ENAMETOOLONG` integer would mis-read a genuine length refusal from the one
    host that has ever produced a second data point — retiring, there, the very
    branch this item exists to keep alive.
    """
    assert len(_ENCODING_REFUSAL_ERRNOS) == 1, (
        "the recorded-verdict allowlist is no longer exactly one member wide. The narrowing "
        "PDF-85 landed is exactly one verdict wide: a second member is a new measurement and "
        "arrives with its own evidence beside it, never as an entry added to reach green, and "
        "an empty allowlist retires the one observation this arm exists to carry"
    )
    name = f"{_MACOS_COUNTEREXAMPLE}.pdf"
    encoded = len(name.encode("utf-8", "surrogateescape"))
    assert encoded < naming._MAX_COMPONENT_BYTES, (
        f"the roster's component is {encoded} bytes, no longer inside the product's own "
        "limit — the ENAMETOOLONG cell would then prove nothing about the verdict "
        "following the NAME rather than the size"
    )

    verdict = _classify_filesystem_refusal(
        OSError(errno_value, os.strerror(errno_value), name), name=name, out_dir=tmp_path
    )

    assert verdict.kind == expected, (
        f"{errno.errorcode[errno_value]} was classified {verdict.kind!r}, not {expected!r}"
    )
    carries = "both a message and an event" if verdict.message else "neither"
    assert bool(verdict.message) != bool(verdict.event_name), (
        f"the verdict for {errno.errorcode[errno_value]} carries {carries} — a branch the "
        "oracle returns from having neither reddened nor recorded is a SWALLOW, which is "
        "the one shape this re-scope must never become"
    )
    if expected == _DEFECT:
        assert "ENAMETOOLONG" in verdict.message
        assert f"{encoded} bytes" in verdict.message
    elif expected == _RECORDED:
        assert verdict.event_name == _ENCODING_REFUSED
    else:
        assert f"UNCLASSIFIED errno {errno_value}" in verdict.message, (
            f"the unclassified verdict did not name the errno it could not classify, which "
            f"is the entire value it has: {verdict.message}"
        )
        assert errno.errorcode[errno_value] in verdict.message, (
            f"the unclassified verdict named a number and not its symbolic name, so the "
            f"reader on the other host has to look it up: {verdict.message}"
        )


def test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3/AC10. The macos-14 observation, made executable on BOTH kinds of host.

    Three halves, in the order that makes each mean something:

    1. the premise is MEASURED AT RUNTIME, and both answers are asserted. A
       probe performs the same syscall the oracle performs, one call earlier,
       and this half asserts WHICH branch the host took: `accepted` — the
       oracle passes, publishes nothing, and its own probe file is gone — or
       `recorded`, where the oracle does not raise and publishes exactly one
       `_EncodingRefusalRecorded`. Any other answer reds, naming the errno.

       **Before PDF-88 this half asserted the first outcome as a fact about
       "this host"** — an undeclared Linux premise in an arm that runs on both
       platforms, which is what crashed the four `macos-14` legs inside
       `event()`. The crash was the only honest thing in it: the half's one
       surviving assertion, `assert not candidate.exists()`, passes in BOTH
       worlds, because a refused `touch()` never created the file an accepted
       one is unlinked from. Stopping the crash alone would have left this half
       asserting nothing whatsoever, on the exact platform where its own claim
       was false;
    2. a filesystem that refuses it with the measured ENCODING errno is
       RECORDED and not reddened, and the emission is OBSERVED rather than
       assumed. `event()` raises outside a hypothesis build context, so
       capturing the module's own name is the only way a deterministic arm can
       watch the recorded verdict happen at all;
    3. the SAME eight-byte component refused for LENGTH is still the renderer's
       defect. Nothing about the component changed between halves 2 and 3 — only
       the errno — which is the property that keeps a real length refusal red on
       a host this loop cannot run.

    Halves 2 and 3 are byte-untouched by PDF-88. Half 2's oracle call now also
    publishes the channel UNCAUGHT, which is what exercises the
    worker-to-controller crossing on every leg of an ordinary `-n auto` run
    rather than only on the four that refuse.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    candidate = render_name("{stem}.{ext}", out_dir=out_dir, stem=_MACOS_COUNTEREXAMPLE, ext="pdf")

    branch = _the_hosts_answer_for(candidate, out_dir=out_dir)
    assert branch in _HOST_BRANCHES, (
        f"the host's answer was classified {branch!r}, which is neither {_HOST_ACCEPTED!r} "
        f"nor {_HOST_RECORDED!r} — an arm that cannot name the branch it took is an arm "
        "back to having an unasserted premise"
    )

    recorded: list[str] = []
    monkeypatch.setattr(sys.modules[__name__], "event", recorded.append)
    monkeypatch.setattr(Path, "touch", _refusing_touch(errno.EILSEQ))

    _the_filesystem_accepts(candidate, out_dir=out_dir)

    assert recorded == [_ENCODING_REFUSED], (
        f"the encoding refusal recorded {recorded!r}; an observation nobody emits is an "
        "observation the operator never sees in --hypothesis-show-statistics"
    )

    monkeypatch.setattr(Path, "touch", _refusing_touch(errno.ENAMETOOLONG))
    with pytest.raises(AssertionError) as caught:
        _the_filesystem_accepts(candidate, out_dir=out_dir)

    assert "ENAMETOOLONG" in str(caught.value)
    assert recorded == [_ENCODING_REFUSED], (
        "the length refusal emitted the encoding event as well, so the meter can no longer "
        "tell the two refusal classes apart"
    )


# --------------------------------------------------------------------------- #
# PDF-88 — the four control arms for the host-derived premise
# --------------------------------------------------------------------------- #


def test_the_unmutated_host_decides_the_branch_and_both_instruments_agree(
    tmp_path: Path,
) -> None:
    """AC1/AC3. NO injection anywhere: the premise is taken from the host this arm runs on.

    On every Linux leg the probe accepts and the branch is `accepted`; on the
    four `macos-14` legs the probe refuses with the measured encoding errno and
    the branch is `recorded`. **The arm asserts the MAPPING and never the
    value** — which of the two answers this host gave, and that the helper
    reached the branch that answer implies. Asserting the value is precisely
    the undeclared premise PDF-88 exists to remove, and an arm that re-asserted
    it here would rebuild the defect one file down from where it was fixed.

    The discrimination lives in the helper's two agreement assertions, and both
    directions have been driven: stub the probe to return `None` while the
    channel publishes and this reds on the accepting clause; silence the
    channel while the probe refuses and it reds on the recording clause.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    candidate = render_name("{stem}.{ext}", out_dir=out_dir, stem=_MACOS_COUNTEREXAMPLE, ext="pdf")

    refusal = _host_refusal_for(candidate, out_dir=out_dir)
    expected = _HOST_ACCEPTED if refusal is None else _HOST_RECORDED

    assert _the_hosts_answer_for(candidate, out_dir=out_dir) == expected, (
        f"the probe answered {'acceptance' if refusal is None else 'refusal'} and the "
        f"branch helper did not reach {expected!r}. The premise and the branch are the two "
        "halves of this arm's only discriminating assertion, and they have come apart"
    )
    assert not candidate.exists(), (
        "the probe or the oracle left a file behind in the caller's own out_dir"
    )


def test_a_refusing_host_is_recorded_and_published_rather_than_reddened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5. The channel fires on a refusing filesystem, exactly once, with an INVARIANT text.

    `_refusing_touch` is the instrument half 1 always needed and was never
    pointed at (`X-850`): it presents a refusing filesystem on a host that
    accepts, which is why every criterion of this item is drivable here and the
    macOS-only reds before it were not.

    The message assertions are the interesting half. It must carry the ledger
    row, the carrier, the codepoint and its category, and the errno by SYMBOLIC
    name; it must carry NO component text and NO errno integer. The first set
    is what a reader needs; the second set is what keeps the warnings summary
    to one line on a host that refuses hundreds of generated components, and
    keeps a transcribed integer — wrong on one half of the CI matrix whichever
    half it was copied from — out of an operator-facing string.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    candidate = render_name("{stem}.{ext}", out_dir=out_dir, stem=_MACOS_COUNTEREXAMPLE, ext="pdf")

    monkeypatch.setattr(Path, "touch", _refusing_touch(errno.EILSEQ))

    assert _the_hosts_answer_for(candidate, out_dir=out_dir) == _HOST_RECORDED, (
        "a filesystem refusing with the one measured encoding errno did not reach the "
        "recorded branch, so the oracle either reddened on it or the channel went quiet"
    )

    with warnings.catch_warnings(record=True) as published:
        warnings.simplefilter("always")
        _the_filesystem_accepts(candidate, out_dir=out_dir)
    messages = _published_refusals(published)

    assert len(messages) == 1, (
        f"the recorded refusal published {len(messages)} times, not once: {messages!r}"
    )
    message = messages[0]
    for token in ("2b88707a36", "B-352", "U+1239A", "Cn", errno.errorcode[errno.EILSEQ]):
        assert token in message, (
            f"the publication dropped {token!r}, so the operator who reads this line in a "
            f"job log cannot get from it to the row it is filed under: {message}"
        )
    assert str(errno.EILSEQ) not in message, (
        f"the publication carries the errno INTEGER ({errno.EILSEQ}), which resolves to a "
        f"different number on the other half of this product's CI matrix: {message}"
    )
    for varying in (_MACOS_COUNTEREXAMPLE, candidate.name):
        assert varying not in message, (
            f"the publication carries component text ({varying!r}), so a host that refuses "
            "many generated components scatters the warnings summary into one distinct "
            "line per component instead of one line per host"
        )


def test_an_unclassified_host_answer_reds_the_branch_helper_naming_its_errno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4. A host answer this design has never measured is handed UP, never skipped.

    The third verdict is what keeps the host-derived premise from becoming a
    swallow: a two-way split would take an unwritable `tmp_path` for a measured
    encoding refusal and return `recorded` from it. Driven the other way as
    well — widen `_ENCODING_REFUSAL_ERRNOS` to admit `EACCES` and this arm goes
    green with `DID NOT RAISE`, which is exactly the swallow the verdict exists
    to prevent, and the roster arm's width assertion reds alongside it.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    candidate = render_name("{stem}.{ext}", out_dir=out_dir, stem=_MACOS_COUNTEREXAMPLE, ext="pdf")

    monkeypatch.setattr(Path, "touch", _refusing_touch(errno.EACCES))

    with pytest.raises(AssertionError) as caught:
        _the_hosts_answer_for(candidate, out_dir=out_dir)

    message = str(caught.value)
    assert str(errno.EACCES) in message, (
        f"the unclassified host answer did not name the errno it could not classify, which "
        f"is the entire value it has: {message}"
    )
    assert errno.errorcode[errno.EACCES] in message, (
        f"the unclassified host answer named a number and not its symbolic name, so the "
        f"reader on the other host has to look it up: {message}"
    )


def test_the_publication_channel_is_defined_where_every_process_can_import_it() -> None:
    """AC6. WHERE the class lives decides whether the channel works at all.

    When a warning escapes uncaught under this project's own `-n auto`,
    pytest-xdist ships it worker → controller and the CONTROLLER rebuilds the
    class with `importlib.import_module(<the class's __module__>)`. A class
    defined in THIS module carries `__module__ == "test_name_template"`, and
    `tests/unit/` is on no controller's `sys.path` — measured, that kills the
    run 3 of 3 with `INTERNALERROR … ModuleNotFoundError: No module named
    'test_name_template'` → `node down` → `KeyError: <WorkerController gw0>`,
    which is an `INTERNALERROR` shipped straight at the four legs this item
    exists to turn green. `tests/conftest.py` is loaded in every process, so
    `tests/` — and only `tests/` — is on the controller's `sys.path`.

    The rule is NOT "a custom subclass is unsafe in a test module":
    `tests/test_import_boundaries.py` sits directly under `tests/` and renders
    its own subclass cleanly on all four `macos-14` legs. The rule is that the
    class must be defined where every process that may have to render it can
    import it, and the failing control for this arm is one move of the class.
    """
    channel = conftest._EncodingRefusalRecorded

    assert channel.__module__ == "conftest", (
        f"the publication channel is defined in {channel.__module__!r}. Under `-n auto` "
        "the xdist CONTROLLER rebuilds a reported warning by importing that module, and "
        "only `tests/` is on its sys.path — so this ships an INTERNALERROR, not a warning"
    )
    assert channel.__module__ != __name__, (
        "the channel is defined in the arm's own module, which is under `tests/unit/` and "
        "on no controller's sys.path"
    )
    # `UserWarning`, not bare `Warning`, and the subclassing is the MECHANISM
    # rather than a style choice: PDF-86's landed `publication_channel_defects`
    # guard reads `pyproject.toml` and matches a `filterwarnings` entry's dotted
    # TAIL against a category name-set containing `"UserWarning"`. This channel
    # inherits that protection only for as long as it subclasses `UserWarning`;
    # a rebase onto bare `Warning` would drop it with nothing to say so. (The
    # one residual, handed up rather than closed: a filter scoped to this
    # class's OWN dotted name slips that category clause — it does not slip the
    # arm, which refuses any `filterwarnings` entry at all.)
    assert issubclass(channel, UserWarning), (
        f"the channel's base is {channel.__mro__[1].__name__}, not UserWarning, so it has "
        "silently left the category set PDF-86's landed liveness guard matches on"
    )


def test_the_conftest_profile_reaches_this_modules_property() -> None:
    """AC4. The profile supplies only what the decorator does not set.

    This is the load-bearing assumption of the whole arrangement: a profile
    loaded in `tests/conftest.py` must be in force when THIS module's
    `@settings(...)` decorator is evaluated, so the decorator keeps its own
    `max_examples` and `deadline` while inheriting the database and the blob
    setting. Asserting both halves means a profile that started carrying
    `max_examples` would be caught here rather than silently halving the
    search.
    """
    property_under_test = test_render_name_either_raises_or_returns_a_single_contained_component
    configured = property_under_test._hypothesis_internal_use_settings
    assert configured.print_blob is True, (
        "print_blob is off, so a property failure prints no @reproduce_failure token "
        "and a counterexample found on one CI leg is observed once and lost"
    )
    assert isinstance(configured.database, DirectoryBasedExampleDatabase), (
        f"the example database is {type(configured.database).__name__}; an in-memory "
        "database is discarded at process exit, so Phase.reuse has nothing to replay"
    )
    assert Path(configured.database.path) == conftest.HYPOTHESIS_DATABASE_DIR
    assert Phase.explicit in configured.phases, "no @example above would be guaranteed"
    assert Phase.reuse in configured.phases, "a persisted counterexample would never replay"
    assert configured.max_examples == 1000, "the decorator's own value did not survive"
    assert configured.deadline is None, "the decorator's own value did not survive"


def test_the_resolved_example_database_sits_outside_the_repository_tree() -> None:
    """AC3. The database persists, so WHERE it persists is the whole question."""
    database_dir = conftest.HYPOTHESIS_DATABASE_DIR
    assert not database_dir.is_relative_to(conftest.REPO_ROOT), (
        f"the example database resolves to {database_dir}, inside the repository at "
        f"{conftest.REPO_ROOT} -- that is B-147 under a different name"
    )
    assert database_dir.is_dir(), (
        f"{database_dir} does not exist, so the path the run header names is not a "
        "place a reader can go and look, and a persisted counterexample has nowhere "
        "to land"
    )


def test_a_database_path_inside_the_repository_is_refused_not_relocated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3's red half. A misconfiguration must fail loudly, never fall back.

    Silently relocating a hostile `PDF_TOOLING_HYPOTHESIS_DB` to somewhere
    safe would leave the operator believing the database is where they pointed
    it; refusing at resolution time is the only answer that cannot be
    mistaken for success.
    """
    monkeypatch.setenv(conftest.HYPOTHESIS_DB_ENV, str(conftest.REPO_ROOT / ".hypothesis"))
    with pytest.raises(RuntimeError, match="INSIDE"):
        conftest.hypothesis_database_dir()


def test_used_fields_finds_every_referenced_token() -> None:
    assert used_fields("{stem}-{page:03}.{ext}") == {"stem", "page", "ext"}
    assert used_fields("{stem}-{index:03}.{ext}") == {"stem", "index", "ext"}
    assert used_fields("{stem}.{ext}") == {"stem", "ext"}
    assert used_fields("no-fields-here") == set()


def test_ext_renders_without_a_leading_dot(tmp_path: Path) -> None:
    out_dir = tmp_path
    rendered = render_name("{stem}.{ext}", out_dir=out_dir, stem="a", ext=".pdf")
    assert rendered.name == "a.pdf"
    assert ".." not in rendered.name.split(".")


def test_range_renders_the_resolved_extent_not_raw_range_text(tmp_path: Path) -> None:
    """A comma, `!`, or `/` in the user's raw expression must never reach a
    filename -- `{range}` renders the resolved extent (e.g. "1-3"), which is
    computed by the caller and handed in as plain text, never the original
    page-range spec string."""
    rendered = render_name(
        "{stem}-{range}.{ext}",
        out_dir=tmp_path,
        stem="doc",
        ext="pdf",
        range_text="1-3",
    )
    assert rendered.name == "doc-1-3.pdf"


def test_page_outside_each_page_is_a_caller_concern_not_this_modules(tmp_path: Path) -> None:
    """render_name itself has no opinion on which mode a template is valid
    for -- that vocabulary rule is Design §D6's "verb's concern", enforced by
    `ops/split.py` using `used_fields()` before this function is ever called.
    Passing `page=None` while the template references `{page}` therefore
    surfaces as this module's own generic unavailable-field refusal."""
    try:
        render_name("{page}.{ext}", out_dir=tmp_path, stem="a", ext="pdf", page=None)
    except OutputEscapesDirError:
        pass
    else:  # pragma: no cover - documents the contract, never expected to run
        raise AssertionError("expected an OutputEscapesDirError for an unavailable field")


def test_collision_two_distinct_stems_still_only_refused_by_the_caller(tmp_path: Path) -> None:
    """`ensure_within` is the containment half; render_name never checks
    against sibling outputs -- that is `check_output_collisions`'s job at the
    `ops/split.py` planning stage (AC10), and is proven there, not here."""
    first = render_name("{stem}.{ext}", out_dir=tmp_path, stem="a", ext="pdf")
    second = render_name("{stem}.{ext}", out_dir=tmp_path, stem="a", ext="pdf")
    assert first == second
