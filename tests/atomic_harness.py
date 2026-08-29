"""A subprocess-level driver for the safety spine — deliberately not a verb.

Several of this spec's guarantees are only real at a **process** boundary. An
exit code is a property of a process, a ``SIGKILL`` is delivered to a process,
"must not hang on a non-terminal" is a claim about a process reading stdin, and
the structured error object on stdout is what a caller of a process parses. A
test that called ``AtomicWriter`` in-process and asserted on an exception would
prove a parallel mapping, not the real one.

So the spine gets a driver rather than a hidden verb. A test-only verb would
appear in ``--help`` and in PDF-06's contract harness, which is parameterized
over the verb registry, and a product's public surface should not grow a
scaffolding entry that exists for its own test suite. This file is in ``tests/``
where it can be seen, invoked, and deleted independently of the CLI.

Run it as a module from the repository root::

    uv run python -m tests.atomic_harness write --target out.pdf ; echo $?
    uv run python -m tests.atomic_harness write --target out.pdf --no-backup ; echo $?

Errors are routed through the product's own ``emit_error`` and its own
``exit_code``, so the exit statuses these commands produce are the exact
statuses the CLI produces for the same errors — the mapping is exercised, never
restated.

``tests/`` is exempt from the write-chokepoint import-boundary walk on purpose:
the tests must be able to *construct* violations in order to prove the guard
fires, and this file legitimately opens a file for writing to stand in for an
engine writing to ``writer.path``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pdf_toolkit.cli.main import build_rerun_hint
from pdf_toolkit.errors import PdfToolkitError
from pdf_toolkit.output import OutputFormat, emit_error
from pdf_toolkit.safety import (
    AtomicWriter,
    SafetyPolicy,
    check_output_collisions,
    ensure_within,
    find_stray_temps,
    require_confirmation,
)

DEFAULT_CONTENT = "PDF-04 payload\n"

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_harness(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    stdin: object = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Invoke this harness in a child process — the one way the tests reach it.

    The timeout is not decoration. "The confirmation gate must not block on
    stdin when stdin is not a terminal" is only tested if a hang *fails*, so
    every arm that could hang runs with a deadline and a ``TimeoutExpired``
    turns the test red rather than the suite slow.
    """
    command = [sys.executable, "-m", "tests.atomic_harness", *args]
    return subprocess.run(
        command,
        cwd=str(cwd or REPO_ROOT),
        env=dict(env) if env is not None else None,
        stdin=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _policy(args: argparse.Namespace) -> SafetyPolicy:
    try:
        is_tty = sys.stdin.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    return SafetyPolicy(
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        in_place=bool(args.in_place),
        backup=not bool(args.no_backup),
        assume_yes=bool(args.yes),
        is_tty=is_tty,
        threads=1,
    )


def _report(payload: dict[str, object], fmt: OutputFormat) -> None:
    if fmt is OutputFormat.TABLE:
        print(" ".join(f"{key}={value}" for key, value in sorted(payload.items())))
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _cmd_write(args: argparse.Namespace, fmt: OutputFormat) -> int:
    policy = _policy(args)
    policy.validate()
    content = args.content if args.content is not None else DEFAULT_CONTENT
    target = Path(args.target)
    with AtomicWriter(target, policy=policy, _temp_dir=args.temp_dir) as writer:
        if writer.is_dry_run:
            _report({"target": str(target), "dry_run": True, "written": False}, fmt)
            return 0
        with open(writer.path, "wb") as handle:
            handle.write(content.encode("utf-8"))
    _report(
        {
            "target": str(target),
            "dry_run": False,
            "written": True,
            "backup": str(writer.backup_path) if writer.backup_path else None,
            "warnings": list(writer.warnings),
        },
        fmt,
    )
    return 0


def _cmd_confirm(args: argparse.Namespace, fmt: OutputFormat) -> int:
    policy = _policy(args)
    policy.validate()
    hint = build_rerun_hint([sys.executable, "-m", "tests.atomic_harness", *sys.argv[1:]])
    require_confirmation(
        policy,
        input_count=int(args.inputs),
        clobbered=tuple(args.clobber or ()),
        in_place=bool(args.in_place),
        rerun_hint=hint,
    )
    _report({"confirmed": True, "inputs": int(args.inputs)}, fmt)
    return 0


def _cmd_collide(args: argparse.Namespace, fmt: OutputFormat) -> int:
    check_output_collisions(tuple(args.output or ()))
    _report({"outputs": len(args.output or ()), "collision": False}, fmt)
    return 0


def _cmd_contain(args: argparse.Namespace, fmt: OutputFormat) -> int:
    ensure_within(args.out_dir, args.candidate)
    _report({"candidate": str(args.candidate), "contained": True}, fmt)
    return 0


def _cmd_strays(args: argparse.Namespace, fmt: OutputFormat) -> int:
    strays = find_stray_temps(args.root)
    _report({"strays": len(strays), "paths": [str(item) for item in strays]}, fmt)
    return 0


#: The safety flags, in the harness's own spelling. Declared at BOTH levels for
#: the same reason the real CLI declares its global block twice: the spec's
#: validation commands write ``write --target x --no-backup``, and a harness that
#: only accepted the flag before the subcommand would exit 2 for an argparse
#: usage error rather than for the safety rule under test — a green that proved
#: the wrong thing. Every one of these is an opt-in boolean, so merging the two
#: levels with OR is exactly "explicit wins".
_FLAGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("--dry-run",), "dry_run"),
    (("-f", "--force"), "force"),
    (("--in-place",), "in_place"),
    (("--no-backup",), "no_backup"),
    (("-y", "--yes"), "yes"),
)


def _add_flags(parser: argparse.ArgumentParser, *, prefix: str = "") -> None:
    for spellings, dest in _FLAGS:
        parser.add_argument(*spellings, dest=prefix + dest, action="store_true")
    parser.add_argument(
        "-o",
        "--output-format",
        dest=prefix + "output_format",
        default=None,
        choices=[item.value for item in OutputFormat],
    )


def _merge_flags(args: argparse.Namespace) -> None:
    """Fold the subcommand-level spellings into the top-level ones."""
    for _, dest in _FLAGS:
        merged = bool(getattr(args, dest, False)) or bool(getattr(args, "sub_" + dest, False))
        setattr(args, dest, merged)
    chosen = getattr(args, "sub_output_format", None) or args.output_format or "table"
    args.output_format = chosen


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tests.atomic_harness", description=__doc__)
    _add_flags(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="drive AtomicWriter over one target")
    write.add_argument("--target", required=True)
    write.add_argument("--content", default=None)
    write.add_argument("--temp-dir", default=None, help="test-only: force a cross-device replace")
    _add_flags(write, prefix="sub_")
    write.set_defaults(handler=_cmd_write)

    confirm = sub.add_parser("confirm", help="drive the confirmation gate")
    confirm.add_argument("--inputs", type=int, default=1)
    confirm.add_argument("--clobber", action="append", default=[])
    _add_flags(confirm, prefix="sub_")
    confirm.set_defaults(handler=_cmd_confirm)

    collide = sub.add_parser("collide", help="drive planned-output collision detection")
    collide.add_argument("--output", action="append", default=[])
    _add_flags(collide, prefix="sub_")
    collide.set_defaults(handler=_cmd_collide)

    contain = sub.add_parser("contain", help="drive --out-dir containment")
    contain.add_argument("--out-dir", required=True)
    contain.add_argument("--candidate", required=True)
    _add_flags(contain, prefix="sub_")
    contain.set_defaults(handler=_cmd_contain)

    strays = sub.add_parser("strays", help="report toolkit temp residue; removes nothing")
    strays.add_argument("--root", required=True)
    _add_flags(strays, prefix="sub_")
    strays.set_defaults(handler=_cmd_strays)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _merge_flags(args)
    fmt = OutputFormat(args.output_format)
    try:
        return int(args.handler(args, fmt))
    except PdfToolkitError as error:
        emit_error(error, fmt)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
