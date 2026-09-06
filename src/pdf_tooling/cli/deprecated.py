"""The two deprecated console-script aliases: ``pdftoolkit`` and ``pdf-toolkit``.

**Removed at v1.0.0.** Behaviour and exit codes are identical to the canonical
``pdftooling``/``pdf-tooling`` scripts; the only difference is one line on
stderr naming the new command.

Four rules, each forbidding a plausible way to ship a shim that lies:

1. **The notice goes to stderr and nowhere else.** This product's structured
   output is a stability contract (``CLAUDE.md``); a notice on stdout would
   corrupt every ``-o json``/``-o ndjson`` payload the alias produces.
2. **The shim must not catch ``SystemExit``.** ``main()`` terminates by
   raising it. A ``try``/``except SystemExit`` — or a trailing
   ``sys.exit(0)`` — would silently flatten every non-zero exit to 0.
3. Exit-code equivalence with the primary is therefore whatever ``main()``
   itself raises: this module adds nothing on the exit path.
4. ``--help`` is expected to print ``Usage: pdftooling`` even when invoked as
   ``pdftoolkit``. That is correct and deliberate (see ``cli/main.py``'s
   ``PROG_NAME`` pin rationale): the help tells you the name you should be
   using. It is stated here so it is not "fixed" by a later reader.
"""

from __future__ import annotations

import sys

from pdf_tooling.cli.main import main

__all__ = ["main_pdf_toolkit", "main_pdftoolkit"]


def _notice(old: str) -> None:
    print(
        f"{old}: deprecated, use 'pdftooling' instead; this alias is removed in v1.0.0",
        file=sys.stderr,
    )


def main_pdftoolkit() -> None:
    # `main()` is typed `-> None` (see cli/main.py) but always terminates by
    # raising SystemExit -- matching its own typing here, rather than
    # annotating `NoReturn`, is what it takes to state the same fact mypy
    # cannot infer from that signature without ALSO adding an explicit
    # fallback statement after this call, which is exactly the shape rule 2
    # above forbids.
    _notice("pdftoolkit")
    main()  # NOT wrapped: SystemExit must propagate untouched


def main_pdf_toolkit() -> None:
    _notice("pdf-toolkit")
    main()  # NOT wrapped: SystemExit must propagate untouched
