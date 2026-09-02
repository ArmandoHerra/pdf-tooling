#!/usr/bin/env python3
"""Assert engine-gated tests render a VISIBLE SKIP when engines are absent.

PDF-02, consumed by the `without-engines` and `engines-present` CI jobs. Reads
a pytest JUnit XML report and:

  * exits non-zero if any testcase carries <failure> or <error>;
  * counts skips whose reason names an engine and prints the count.

NO LONGER VACUOUS, AS OF PDF-06
--------------------------------
PDF-05 introduced `ports.resolve()`; PDF-06 introduces `@pytest.mark.requires(
engine)` (`tests/conftest.py`) and the PATH-shadowing engine-hiding shim
(`PDF_TOOLKIT_TEST_HIDE_ENGINES`). This assertion's count is real from PDF-06
onward — it is no longer possible for the `without-engines` job to pass on an
empty input, because at least one engine-gated test (`tests/test_testdata.py`'s
tesseract-recovery arm) now exists and skips visibly whenever the engine is
absent, in addition to the engine-gated arms PDF-05 already shipped in
`tests/test_doctor.py`.

The reason-regex below (`ENGINE_REASON`) was kept rather than replaced with a
marker-based query: `@pytest.mark.requires(engine)`'s own skip reason already
names the engine literally (`"{engine} unavailable (port {port}); install
with: {hint}"` — see `tests/conftest.py::pytest_collection_modifyitems`), so
the regex already matches every marker-driven skip without needing to import
pytest's own marker metadata from a JUnit report, which does not carry it.
Replacing a working, simpler mechanism with a more complex one that answers
the same question was not worth the diff.

B-081 -- THE `type="pytest.xfail"` EXCLUSION (PDF-28)
------------------------------------------------------
`ENGINE_REASON` matches on PROSE, not on why pytest recorded the skip. pytest
serializes an `xfail` outcome as `<skipped type="pytest.xfail" message="...">`
in JUnit XML -- the SAME element shape a real skip uses. If a deliberate
`@pytest.mark.xfail(reason="... engine ...")` ever lands, its reason text can
happen to name an engine, a port class, or the literal word "engine" (e.g.
"StructureEngine port unavailable"), and this script would count it as an
engine-gated SKIP -- under `--expect-zero` (the `engines-present` job) that
reddens the run with a message that blames the wrong thing: it looks like an
engine silently failed to exercise, when the real cause is an unrelated xfail.
The fix excludes any `<skipped type="pytest.xfail">` element from the count
BEFORE the `ENGINE_REASON` regex ever sees it -- see
`tests/test_assert_skips.py` for the red/complement pair that proves this
does not also silence a REAL engine-gated skip (`type="pytest.skip"`, the
shape `tests/conftest.py::pytest_collection_modifyitems` actually emits).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path

ENGINE_REASON = re.compile(r"engine|tesseract|soffice|libreoffice", re.IGNORECASE)


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
        if skipped.get("type") == "pytest.xfail":
            # B-081: an xfail is not a skip -- its reason text may still name
            # an engine, but that is not what this count is asking about.
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
        # PDF-06 makes this count non-vacuous: at least one engine-gated test
        # exists (`tests/test_testdata.py`, plus PDF-05's own arms in
        # `tests/test_doctor.py`), so a without-engines run reporting ZERO
        # engine-gated skips is a REGRESSION -- the harness stopped skipping
        # and started passing, or an engine-gated test was silently removed --
        # not the vacuity this script used to (correctly) report before PDF-06
        # landed. "Make the unverifiable case FAIL, not SKIP."
        print(
            "assert_skips: 0 engine-gated skips in a without-engines run. This count has been "
            "non-vacuous since PDF-06; a zero here means the harness stopped skipping visibly, "
            "or every engine-gated test was removed -- both are regressions.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
