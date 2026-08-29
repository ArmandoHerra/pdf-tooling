"""L1. CLI — the ONLY layer that may import ``typer`` or ``click``.

Its job is to parse, validate flag combinations, build one frozen plan, pick a
renderer, call one op, and map the returned result to an exit code. It contains
no PDF logic, and no layer below it may import a CLI framework — a rule an
import-boundary test enforces rather than trusting.
"""
