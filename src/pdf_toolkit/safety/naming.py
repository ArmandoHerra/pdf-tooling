"""The ``--name`` template renderer, and its containment guarantee (Design §D6).

**Where this lives, and why it exists at all (X-70 / E11).** PDF-04 shipped only
the containment *primitive* — :func:`pdf_toolkit.safety.paths.ensure_within` — and
no renderer. `decision.md` §8 X-70 ratifies that as verified fact, so PDF-07 (the
first ``--name`` consumer) adds this module rather than choosing between two
paths: token substitution, plus the containment invariant below, then a call to
``ensure_within(out_dir, rendered)`` on every rendered path before it ever reaches
``AtomicWriter``. `split` (PDF-07) is its first consumer; `rasterize` (PDF-09) is
its second, so it lives here — shared from the first line, never copied.

**Two tiers, and this module owns only the second.**

* Exit **2** (bad invocation) — a malformed *template literal* (a path
  separator, an absolute leading slash, or ``..`` in the template text itself,
  or an empty template) is caught by ``cli/common.py::_validate_name_template``
  at flag-validation time, before any verb body runs. This module does **not**
  re-check or weaken any of that — see its docstring for the deliberate split.
* Exit **5** (safety refusal) — a *substituted value* (``{stem}`` carrying
  ``../``, a NUL byte, an absolute prefix, or a rendered component over 255
  bytes) is discovered only after substitution, from *data* rather than from
  the invocation, so it is :class:`~pdf_toolkit.errors.OutputEscapesDirError`
  — the same family as no-clobber and planned-output collision — rather than a
  usage error.

**The binding invariant** (Design §D6, verbatim): for every template and every
set of substituted values, :func:`render_name` either **raises** a classified
error, or returns a path whose final component ``c`` is not one of ``""``,
``"."``, ``".."``; contains no ``/``, no ``os.sep``/``os.altsep``, and no NUL
byte; is not absolute; and whose parent, once both sides are resolved, is
`out_dir` itself. Rejection is the answer, never sanitization: silently
rewriting ``../evil`` to ``evil`` invents a filename the user did not ask for
and can collide with a real part.

**Vocabulary is a verb's concern; this module only parses shape.** Which
tokens exist (``{stem}``, ``{page}``, ``{page:03}``, ``{index}``, ``{range}``,
``{ext}``) and which of them a given split *mode* may use (``{page}`` outside
``--each-page`` is exit 2) is `split`'s own domain knowledge and is checked in
``ops/split.py``, using :func:`used_fields` from here to ask "which fields does
this template reference" without duplicating a parser.
"""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import OutputEscapesDirError
from pdf_toolkit.safety.paths import ensure_within

__all__ = ["FIELDS", "render_name", "used_fields"]

#: The five substitution fields §4.2 defines. No sixth field is ever added —
#: see PDF-07's spec, Scope > Out ("A `{title}` name token").
FIELDS: Final[frozenset[str]] = frozenset({"stem", "page", "index", "range", "ext"})

#: A rendered component longer than this is refused rather than handed to the
#: filesystem, which would otherwise fail with a bare ``OSError`` (AC9).
_MAX_COMPONENT_BYTES: Final[int] = 255

_formatter: Final[string.Formatter] = string.Formatter()


def used_fields(template: str) -> frozenset[str]:
    """Which of :data:`FIELDS` *template* references, by name only.

    Parsing mechanics live here so a verb never hand-rolls a second template
    tokenizer; the question of whether a particular field is *allowed* in a
    particular mode stays with the verb that owns that vocabulary.
    """
    fields: set[str] = set()
    for _literal, field_name, _format_spec, _conversion in _formatter.parse(template):
        if field_name:
            fields.add(field_name)
    return frozenset(fields)


def _reject_unsafe_component(rendered: str) -> None:
    """The exit-5 tier's own checks, before the path ever reaches ``ensure_within``.

    ``ensure_within`` alone would already catch most of these once the
    component is joined onto ``out_dir`` and resolved, but a NUL byte reaches
    the OS layer before that resolution can even run (``Path.resolve()``
    raises a bare ``ValueError`` on one), and an absolute component would
    silently *discard* ``out_dir`` under ``pathlib``'s own ``/`` operator
    (``Path("/a") / "/b" == Path("/b")``) rather than escape it in a form
    ``ensure_within`` would notice as an escape. Both are therefore caught
    explicitly, here, before any path join is attempted.
    """
    if rendered in ("", ".", ".."):
        raise OutputEscapesDirError(
            f"the rendered output name {rendered!r} is not a valid filename",
            path=rendered,
        )
    if "\x00" in rendered:
        raise OutputEscapesDirError(
            f"the rendered output name {rendered!r} contains a NUL byte",
            path=rendered,
        )
    separators = {"/", os.sep, os.altsep} - {None, ""}
    if any(separator in rendered for separator in separators if separator):
        raise OutputEscapesDirError(
            f"the rendered output name {rendered!r} contains a path separator",
            path=rendered,
        )
    if os.path.isabs(rendered):
        raise OutputEscapesDirError(
            f"the rendered output name {rendered!r} is an absolute path",
            path=rendered,
        )
    encoded_length = len(rendered.encode("utf-8", "surrogateescape"))
    if encoded_length > _MAX_COMPONENT_BYTES:
        raise OutputEscapesDirError(
            f"the rendered output name is {encoded_length} bytes, over the "
            f"{_MAX_COMPONENT_BYTES}-byte filename limit: {rendered!r}",
            path=rendered,
        )


def render_name(
    template: str,
    *,
    out_dir: Path,
    stem: str,
    ext: str,
    index: int | None = None,
    page: int | None = None,
    range_text: str | None = None,
) -> Path:
    """Render *template* against the given values, inside *out_dir*.

    ``template`` has already passed ``cli/common.py::_validate_name_template``
    (the exit-2 tier); this function owns only the exit-5 tier and the
    :func:`~pdf_toolkit.safety.paths.ensure_within` call. Callers pass only the
    values their mode has available — a field the template references but the
    caller did not pass raises ``KeyError`` from :meth:`str.format`, converted
    here into the same classified refusal as any other unusable substitution,
    since by the time this function runs the vocabulary check (a verb-level
    concern) has already run.

    Returns:
        The full path (``out_dir`` joined with the rendered, validated
        component) — never handed to a caller without having already
        satisfied the binding containment invariant.
    """
    values: dict[str, object] = {"stem": stem, "ext": ext.lstrip(".")}
    if index is not None:
        values["index"] = index
    if page is not None:
        values["page"] = page
    if range_text is not None:
        values["range"] = range_text

    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError) as error:
        raise OutputEscapesDirError(
            f"--name {template!r} references a field that is unavailable here: {error}",
            path=template,
        ) from error

    _reject_unsafe_component(rendered)
    candidate = out_dir / rendered
    ensure_within(out_dir, candidate)
    return candidate
