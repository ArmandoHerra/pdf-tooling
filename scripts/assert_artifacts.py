#!/usr/bin/env python3
"""Assert the built sdist and wheel BOTH carry the license files, and (PDF-58)
that the wheel declares exactly the two canonical console-script entry points.

PLAN.md §11: "LICENSE, NOTICE, and THIRD_PARTY_LICENSES are included in both
artifacts." This asserts it by READING the archives, never by trusting the build
backend's include configuration to have stayed correct — a packaging config can
silently stop matching a file (a renamed target, a changed include glob) and the
build still succeeds. Stdlib only, so it runs under `uv run --no-project`.

PDF-58 D2/AC3/AC4. The oracle for "the deprecated console scripts are gone from
the distribution" is a LOCALLY BUILT wheel, never PyPI (X-703, B-250) -- wired
in here because `uv build` inside the test suite is slow, and this script
already reads archives instead of trusting `pyproject.toml`. Three
non-vacuity rules, each closing a way this could pass while being wrong:

  * absence of an artifact is a FAILURE, never a pass (pre-existing, below);
  * MORE THAN ONE wheel or sdist in `dist/` is a FAILURE, not a `[0]`
    selection (F3) -- `uv build` does not clear `dist/`, only `make clean`
    does, so a stale pre-removal wheel left beside a fresh one could
    otherwise make this exact check pass over the wrong bytes;
  * the two CANONICAL scripts are asserted PRESENT before the two deprecated
    ones are asserted ABSENT, in the same arm -- an absence-only check passes
    against an empty `[console_scripts]` section too.
"""

from __future__ import annotations

import configparser
import glob
import sys
import tarfile
import zipfile

REQUIRED = ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES")

#: PDF-58 D2/D7. After the removal, [project.scripts] declares exactly these
#: two keys, both pointed at the one canonical target.
EXPECTED_CONSOLE_SCRIPTS = {
    "pdftooling": "pdf_tooling.cli.main:main",
    "pdf-tooling": "pdf_tooling.cli.main:main",
}
#: PDF-58 D2. The shim module the sdist must no longer carry, as a path
#: suffix (the sdist's top-level directory name is the version-qualified
#: distribution name, not fixed across builds).
REMOVED_SDIST_MEMBER_SUFFIX = "src/pdf_tooling/cli/deprecated.py"


def main() -> int:
    wheels = glob.glob("dist/*.whl")
    sdists = glob.glob("dist/*.tar.gz")
    if not wheels or not sdists:
        print(
            f"assert_artifacts: expected both a wheel and an sdist in dist/, got {wheels + sdists}",
            file=sys.stderr,
        )
        return 1
    if len(wheels) > 1 or len(sdists) > 1:
        # F3. `uv build` does not clear dist/, only `make clean` does. A
        # stale wheel/sdist left over from before a removal makes `[0]` an
        # ARBITRARY choice -- exactly how an absence assertion can go green
        # over the wrong bytes. Multiplicity is a failure, never a selection.
        print(
            "assert_artifacts: FAILED -- more than one wheel or sdist in dist/; "
            f"run `make clean && make build` first. wheels={sorted(wheels)} "
            f"sdists={sorted(sdists)}",
            file=sys.stderr,
        )
        return 1

    wheel_path, sdist_path = wheels[0], sdists[0]

    with zipfile.ZipFile(wheel_path) as zf:
        wheel_names = zf.namelist()
        entry_points_member = next(
            (name for name in wheel_names if name.endswith(".dist-info/entry_points.txt")),
            None,
        )
        entry_points_text = (
            zf.read(entry_points_member).decode("utf-8") if entry_points_member else ""
        )
    with tarfile.open(sdist_path) as tf:
        sdist_names = tf.getnames()

    missing: list[str] = []
    for name in REQUIRED:
        if not any(p.rsplit("/", 1)[-1] == name for p in wheel_names):
            missing.append(f"{name} missing from wheel {wheel_path}")
        if not any(p.rsplit("/", 1)[-1] == name for p in sdist_names):
            missing.append(f"{name} missing from sdist {sdist_path}")

    # PDF-58 AC3/AC4 -- the console-script entry points, read from the wheel.
    if entry_points_member is None:
        missing.append(f"no *.dist-info/entry_points.txt found in wheel {wheel_path}")
    else:
        parser = configparser.ConfigParser()
        parser.read_string(entry_points_text)
        console_scripts = (
            dict(parser["console_scripts"]) if parser.has_section("console_scripts") else {}
        )
        # AC4 -- the two canonical scripts are present, asserted BEFORE the
        # absence check below, in the same arm: an absence-only check would
        # pass against an empty [console_scripts] section too.
        for script_name, target in EXPECTED_CONSOLE_SCRIPTS.items():
            actual = console_scripts.get(script_name)
            if actual != target:
                missing.append(
                    f"wheel entry_points.txt [console_scripts] {script_name!r} is "
                    f"{actual!r}, expected {target!r}"
                )
        # AC3 -- exactly the two canonical scripts, no fewer and no more.
        extra = sorted(set(console_scripts) - set(EXPECTED_CONSOLE_SCRIPTS))
        if extra:
            missing.append(
                f"wheel entry_points.txt [console_scripts] declares unexpected "
                f"key(s) {extra}; the deprecated console scripts must be absent"
            )

    # AC3 -- the sdist no longer carries the removed shim module.
    if any(name.endswith(REMOVED_SDIST_MEMBER_SUFFIX) for name in sdist_names):
        missing.append(f"sdist {sdist_path} still carries {REMOVED_SDIST_MEMBER_SUFFIX}")

    if missing:
        print("assert_artifacts: FAILED", file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        print("\nRemedy: add the file to [project] license-files and/or the", file=sys.stderr)
        print("[tool.hatch.build.targets.sdist] include list in pyproject.toml,", file=sys.stderr)
        print("or fix [project.scripts] if a console-script check failed above.", file=sys.stderr)
        return 1

    print(f"both artifacts carry {', '.join(REQUIRED)}")
    print(f"  wheel: {wheel_path}")
    print(f"  sdist: {sdist_path}")
    print(f"  console_scripts: {sorted(EXPECTED_CONSOLE_SCRIPTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
