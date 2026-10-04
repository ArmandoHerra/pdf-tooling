"""The one place a spec id's spelling is defined for the guards (PDF-100, X-953, B-383).

Every guard that parses a spec id composes its pattern from `SPEC_ID_GRAMMAR`; a census arm
(`tests/test_spec_id_grammar.py`) fails if a second copy of the two-digit grammar appears.
Compose by string concatenation, never an f-string: `\\d{4}` inside an f-string becomes `\\d4`.
"""

from __future__ import annotations

import re
from typing import Final

#: Two digits (the whole of the old grammar), or three-plus digits that do not start with 0.
#: So `PDF-100` and `PDF-1000` are legal while `PDF-1`, `PDF-007` and `PDF-099` are not: each
#: of those would be a second spelling of an id that already has one. Non-capturing, because
#: every consumer wraps it in its own group. No upper bound: a cap would bring this defect
#: back one decade later.
SPEC_ID_GRAMMAR: Final[str] = r"PDF-(?:\d{2}|[1-9]\d{2,})"

#: FROZEN on purpose (X-953, PDF-100 D3). The `[Task: ...]` heading form is a closed
#: population of two landed entries, size-asserted elsewhere. Widening it admits no real
#: heading; it would only widen an exemption, and the one thing it could newly admit is a
#: non-canonical three-digit heading that the forward test should refuse. Do not "fix" it.
HISTORICAL_SPEC_ID_GRAMMAR: Final[str] = r"PDF-\d\d"

CHANGELOG_CANONICAL: Final = re.compile(
    r"^## \[(?P<id>" + SPEC_ID_GRAMMAR + r"|B-\d+)\] .+ — (?P<date>\d{4}-\d{2}-\d{2})$"
)
CHANGELOG_HISTORICAL: Final = re.compile(
    r"^## \[Task: (?P<id>" + HISTORICAL_SPEC_ID_GRAMMAR + r") — .+\] - (?P<date>\d{4}-\d{2}-\d{2})$"
)
