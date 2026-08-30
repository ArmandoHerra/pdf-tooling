"""The ``meta`` grouping parent (PDF-14).

Holds **only** the ``meta`` sub-``Typer`` and its help text. **No
``@global_options`` decorator, ever**: a group is not a verb, records no
``consumes``, and must not pollute ``cli/common.py``'s
``_CONSUMES_BY_MODULE`` (keyed by module — a group sharing a module with a
verb would collide with it, exactly the trap `cmd_encrypt.py`'s own
docstring names). ``meta get``/``meta set`` each live in their OWN module
(``cmd_meta_get.py``/``cmd_meta_set.py``) for that reason — see either
module's docstring for the mechanism.

``meta`` is the CLI's first (and, as of this spec, only) grouping parent.
``tests/registry.py::discover_groups()`` picks it up automatically the
moment it exists on the live tree — its own docstring already named
``meta`` as the group PDF-14 would add.
"""

from __future__ import annotations

import typer

__all__ = ["meta_app"]

meta_app = typer.Typer(
    name="meta",
    help="Read or write a document's information dictionary and XMP.",
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)
