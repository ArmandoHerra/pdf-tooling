# `perf/` — the gate-timing trend, and the protocol that makes it readable

**This directory is dev data.** It is deliberately **not** in
`[tool.hatch.build.targets.sdist] include`: it changes nothing about the
distributed artifact, and `scripts/assert_artifacts.py` gates that artifact in
CI's `build` job.

## Why this exists

`make ci` was reported to have grown "from ~152 s to 331.25 s over six
measurements". Ruling `X-109` recorded what those six numbers actually were:
**each one was self-measured by the agent that produced it**, on a host of
unknown load, with unknown cache state, against a suite that grew **+25.6 %**
(1387 → 1742 tests) across the same interval.

Six agents, six protocols, one trend. Such a trend cannot tell scope growth from
a regression, so **none of its numbers could justify a decision** — which is the
whole reason `PDF-29` shipped a protocol before it shipped a target.

Two concrete casualties, both on the record:

* **331.25 s and 492.20 s were compared as though they were the same
  measurement.** They were not: the 492.20 s figure was taken after
  `make clean`, so `mypy`, `ruff` and `pytest` caches were all cold. That single
  unrecorded field is why the two figures were never comparable.
* **860 s and 529 s** were the *same suite* on the *same host*, differing only
  in whether `tesseract` and `soffice` were on `PATH`. Engine presence is not a
  footnote.

## The record schema

One JSON object per line in `gate-timings.jsonl`, newest last. **Every field
below is required. A record missing one is invalid** and
`scripts/measure_gate.py` refuses to append it — `tests/test_gate_budget.py`
proves that refusal by removing each required field in turn.

| Field | What it is | Why it is not optional |
|---|---|---|
| `timestamp` | local ISO-8601 with offset | ordering, and correlating with a CI run |
| `commit` | `git rev-parse HEAD` | a timing not attributable to a tree is not a timing |
| `dirty` / `dirty_paths` | `git status --porcelain` | a dirty-tree figure is admissible *only* when the diff is named. `dirty_paths` is what makes it attributable rather than merely disqualified |
| `target` | `ci` \| `cover` \| `test` \| `help-startup` | the six historical figures did not all measure the same target |
| `variant` | free-form, default `default` | carries e.g. `branch-true` for a coverage-configuration arm |
| `interpreter` | version, executable, prefix — resolved through **`uv run python`** | on this project's dev host `python3 -V` says 3.14.4 and `uv run python -V` says 3.12.13. **The system Python is never recorded.** The harness refuses if the resolved interpreter is not a venv under this repository |
| `binary` / `binary_arm` | the resolved `pdftoolkit` and which arm produced it | `console_script()` falls back venv-sibling → `PATH` → `python -m`. `make install` leaves a possibly **stale** build on `PATH`, and the `-m` arm has a measurably different bootstrap. `--baseline` refuses any arm but the project venv's own console script |
| `cache_state` | `clean` (immediately after `make clean`) \| `warm` \| `n/a` | see the 331.25 vs 492.20 casualty above |
| `engines` | resolved paths for `tesseract` and `soffice` | see the 860 vs 529 casualty above |
| `tests_collected` / `coverage_pct` | parsed from the run's own output | the one thing that distinguishes **scope growth** from a **regression** |
| `cpu_count`, `loadavg_start`, `loadavg_peak`, `loadavg_end` | `os.cpu_count()` / `os.getloadavg()`, sampled throughout | `os.getloadavg()` exists on Linux and macOS, this project's two supported platforms |
| `foreign_processes` | non-descendant processes at or above 25 % CPU **that have been alive at least 10 s**, captured **while alive** | a foreign `make ci` (pid 2893548, cwd `apps/kubewright`) was caught live during one sweep, loadavg peaking near 7. Once it exits the contention is unprovable and the anomalous timing reads as a product regression |
| `quiet` | derived — see below | the single field that makes a number usable |
| `wall_clock_s` | measured | the point |
| `distribution` | `help-startup` only: the **statistic**, then min / median / p95 / max / spread | a single derived headroom figure is how the ledger came to contradict itself. Two figures taken with different statistics — *median under contention* and *fastest-of-5 at low load* — are not comparable, and quoting either as "headroom" without naming the statistic is how they got compared |

## What `quiet` means

```
quiet  ==  loadavg_start <= 0.25 * cpu_count
           AND no foreign (non-descendant) process at or above 25 % CPU,
                alive for at least 10 s, at any sample during the run
```

**The ten-second lifetime guard is arithmetic, not convenience.** `ps -o pcpu`
reports CPU time divided by *elapsed* time — a lifetime average. On a process a
few milliseconds old that ratio is meaningless: the transient `ps` invocations
another tool on this box makes were measured at **200 % and 400 %**, which are
not even valid CPU fractions for the single-threaded snapshots they describe.
Without the guard the detector returned `quiet: false` on a demonstrably idle
host — and a detector that answers "not quiet" for every host is exactly as dead
as one that answers "quiet" for every host. The census is re-taken every few
seconds for the whole run, so anything that *persists* is still caught by a later
sample; only sub-ten-second transients are missed, and those are precisely what
should be.

Our own `make`/`pytest`/`ps` children are **descendants** and are never counted:
they are the measurement, not contention. Under `-n auto` the suite saturates
the box by design, so peak load is not, and must not be, part of this test.

## THE RULE

> **A record with `quiet: false` is admissible as an OBSERVATION and
> inadmissible as a BASELINE.**

`--baseline` therefore **exits non-zero and writes nothing** on a host it cannot
verify quiet. Without `--baseline` the observation is recorded with
`quiet: false` and said loudly. This is `PLAN.md` §10.1 rule 5 — *absent
precondition, skip with a reason, never pass* — applied to timing.

## How to take a measurement

```bash
# The two `make ci` arms. `clean` and `warm` are DIFFERENT measurements.
uv run python scripts/measure_gate.py --target ci --cache-state warm  --baseline
make clean && uv run python scripts/measure_gate.py --target ci --cache-state clean --baseline

# The startup distribution: 20 independent fastest-of-5 trials.
uv run python scripts/measure_gate.py --target help-startup --cache-state n/a \
    --trials 20 --baseline

# Or, for the common case:
make gate-timing                      # warm `ci`, baseline
make gate-timing GATE_TIMING_ARGS="--target help-startup --cache-state n/a"
```

`make gate-timing` is deliberately **not** a prerequisite of `make ci`. A gate
that measures itself on every run pays the cost of the measurement on every run,
and the measurement is only meaningful on a quiet host anyway.

## How to READ this file

1. **Never compare across differing `target`, `cache_state`, `engines` or
   `variant`.** That mistake is exactly what produced the incommensurable
   six-point trend this directory exists to replace.
2. **Never compare a `quiet: false` record to anything.** Read it, note the
   `foreign_processes` census, and move on.
3. **For `help-startup`, compare the STATISTIC, not the number.** `median` and
   `fastest-of-5` are different statistics of the same distribution and differ
   by tens of milliseconds; `distribution.statistic` names which one a record
   carries so they cannot be silently mixed.
4. **Re-measure, do not re-read.** A number in this file is evidence about the
   host and commit that produced it, and about nothing else.
