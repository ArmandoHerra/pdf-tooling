"""``python -m pdf_tooling`` entry point.

Delegates to the same callable as both console scripts so that all three
invocations share one code path — and, because the program name is pinned
inside ``main()``, one byte-identical ``--help`` output.
"""

from __future__ import annotations

from pdf_tooling.cli.main import main

if __name__ == "__main__":
    main()
