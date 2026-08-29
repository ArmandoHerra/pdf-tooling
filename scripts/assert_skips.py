#!/usr/bin/env python3
"""Assert engine-gated tests render a VISIBLE SKIP when engines are absent.

PDF-02, consumed by the `without-engines` CI job. Reads a pytest JUnit XML
report and:

  * exits non-zero if any testcase carries <failure> or <error>;
  * counts skips whose reason names an engine and prints the count.

STATED VACUITY — READ THIS BEFORE TRUSTING THE PASS
---------------------------------------------------
At PDF-02 time there are NO engine-gated tests: PDF-05 introduces
`ports.resolve()` and PDF-06 introduces the markers. This assertion therefore
passes on an empty input, and it SAYS SO on every run rather than implying
coverage it does not have. A gate that silently passes on empty input is the
silently-skipped-verification defect class; a gate that announces its own
vacuity and names the spec that closes it is not.

PDF-06 may replace the reason-regex with a marker-based query once
`requires_engine` exists — PDF-06 owns the markers.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path

ENGINE_REASON = re.compile(r"engine|tesseract|soffice|libreoffice", re.IGNORECASE)

VACUITY_NOTE = """\
NOTE: no engine-gated tests exist yet. PDF-06's acceptance criterion requires this
      count to be NON-ZERO in the without-engines job; until PDF-06 lands, this
      assertion is vacuous by construction and says so rather than implying coverage."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assert engine-gated SKIP visibility.")
    parser.add_argument("report", type=Path, help="pytest JUnit XML report")
    parser.add_argument(
        "--expect-zero",
        action="store_true",
        help=(
            "invert the assertion: FAIL if any engine-gated skip is present. "
            "Used by the engines-present job, where a skip means a test that "
            "should have exercised a real engine silently did not."
        ),
    )
    args = parser.parse_args(argv)

    if not args.report.is_file():
        print(f"assert_skips: report not found: {args.report}", file=sys.stderr)
        return 2

    tree = ET.parse(args.report)  # noqa: S314
    cases = list(tree.iter("testcase"))

    broken = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    if broken:
        print(f"assert_skips: {len(broken)} test(s) FAILED or ERRORED:", file=sys.stderr)
        for case in broken:
            print(
                f"  - {case.get('classname')}::{case.get('name')}",
                file=sys.stderr,
            )
        return 1

    engine_skips = 0
    for case in cases:
        skipped = case.find("skipped")
        if skipped is None:
            continue
        reason = f"{skipped.get('message', '')} {skipped.text or ''}"
        if ENGINE_REASON.search(reason):
            engine_skips += 1

    print(f"engine-gated skips: {engine_skips}")
    print(f"(scanned {len(cases)} testcases, 0 failures, 0 errors)")

    if args.expect_zero:
        if engine_skips:
            print(
                f"assert_skips: {engine_skips} engine-gated skip(s) with engines INSTALLED — "
                "a test that should have exercised a real engine silently did not.",
                file=sys.stderr,
            )
            return 1
        return 0

    if engine_skips == 0:
        print(VACUITY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
