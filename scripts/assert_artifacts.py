#!/usr/bin/env python3
"""Assert the built sdist and wheel BOTH carry the license files.

PLAN.md §11: "LICENSE, NOTICE, and THIRD_PARTY_LICENSES are included in both
artifacts." This asserts it by READING the archives, never by trusting the build
backend's include configuration to have stayed correct — a packaging config can
silently stop matching a file (a renamed target, a changed include glob) and the
build still succeeds. Stdlib only, so it runs under `uv run --no-project`.
"""

from __future__ import annotations

import glob
import sys
import tarfile
import zipfile

REQUIRED = ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES")


def main() -> int:
    wheels = glob.glob("dist/*.whl")
    sdists = glob.glob("dist/*.tar.gz")
    if not wheels or not sdists:
        print(
            f"assert_artifacts: expected both a wheel and an sdist in dist/, got {wheels + sdists}",
            file=sys.stderr,
        )
        return 1

    with zipfile.ZipFile(wheels[0]) as zf:
        wheel_names = zf.namelist()
    with tarfile.open(sdists[0]) as tf:
        sdist_names = tf.getnames()

    missing: list[str] = []
    for name in REQUIRED:
        if not any(p.rsplit("/", 1)[-1] == name for p in wheel_names):
            missing.append(f"{name} missing from wheel {wheels[0]}")
        if not any(p.rsplit("/", 1)[-1] == name for p in sdist_names):
            missing.append(f"{name} missing from sdist {sdists[0]}")

    if missing:
        print("assert_artifacts: FAILED", file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        print("\nRemedy: add the file to [project] license-files and/or the", file=sys.stderr)
        print("[tool.hatch.build.targets.sdist] include list in pyproject.toml.", file=sys.stderr)
        return 1

    print(f"both artifacts carry {', '.join(REQUIRED)}")
    print(f"  wheel: {wheels[0]}")
    print(f"  sdist: {sdists[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
