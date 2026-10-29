"""PDF-153 -- the demo render is pinned, installs the tree, and shows current output.

Pure-text arms: no docker, no subprocess, no network, no skip. Each predicate has an
arm-can-fail companion.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "docs" / "demo"
DOCKERFILE = DEMO / "Dockerfile"
RENDER = DEMO / "render.sh"
TAPE = DEMO / "pdf-tooling.tape"
TRANSCRIPT = DEMO / "pdf-tooling.txt"

VHS_DIGEST = "ea49a6a1c529be83153e88321892b5585964418f0b9055e8c1e0d732194234a3"
VHS_IMAGE = f"ghcr.io/charmbracelet/vhs:v0.12.1@sha256:{VHS_DIGEST}"
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}")
CHECKSUM_RE = re.compile(r"--checksum=sha256:[0-9a-f]{64}")
COMPRESS_MESSAGE = re.compile(r"\b(\d+) -> (\d+) bytes \(([+-])(\d+\.\d)%\)")
TEACHING_GATE = re.compile(
    r"clear-all|strip|scrub|sanitiz|remove metadata|removes metadata", re.IGNORECASE
)
# The base tape's prelude line (git show <base>:docs/demo/pdf-tooling.tape).
BASE_INSTALL_LINE = (
    "Type `export DEBIAN_FRONTEND=noninteractive && apt-get update -qq >/dev/null 2>&1 && "
    "apt-get install -y -qq python3-venv jq >/dev/null 2>&1 && python3 -m venv /opt/v && "
    "/opt/v/bin/pip install -q pdf-tooling==1.1.0 && echo INS''TALLED` Enter"
)


def _toolchain_violations(dockerfile: str, script: str) -> list[str]:
    out: list[str] = []
    lines = dockerfile.splitlines()
    froms = [ln for ln in lines if ln.startswith("FROM ")]
    if froms != [f"FROM {VHS_IMAGE}"]:
        out.append(f"FROM must be exactly 'FROM {VHS_IMAGE}', got {froms}")
    for ln in lines:
        refs = []
        if ln.startswith("FROM "):
            refs.append(ln.split()[1])
        m = re.search(r"COPY --from=(\S+)", ln)
        if m:
            refs.append(m.group(1))
        m = re.match(r"# syntax=(\S+)", ln)
        if m:
            refs.append(m.group(1))
        for ref in refs:
            if not DIGEST_RE.search(ref):
                out.append(f"image reference not digest-pinned: {ref}")
        if ln.startswith("ADD ") and re.search(r"https?://", ln) and not CHECKSUM_RE.search(ln):
            out.append(f"URL ADD without --checksum=sha256:<64 hex>: {ln}")
    for banned in ("apt-get", "apt ", "pip install", "curl "):
        if banned in dockerfile:
            out.append(f"Dockerfile contains {banned!r}")
    for needed in ("set -euo pipefail", "-f docs/demo/Dockerfile", "--platform linux/amd64"):
        if needed not in script:
            out.append(f"render script lacks {needed!r}")
    if "--entrypoint chown" not in script:
        out.append("render script lacks the '--entrypoint chown' hand-back")
    return out


def test_demo_render_toolchain_is_pinned() -> None:
    problems = _toolchain_violations(
        DOCKERFILE.read_text(encoding="utf-8"), RENDER.read_text(encoding="utf-8")
    )
    assert problems == []


def test_demo_render_toolchain_arm_can_fail() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    script = RENDER.read_text(encoding="utf-8")
    assert _toolchain_violations(dockerfile, script) == []
    unpinned = dockerfile.replace(f"@sha256:{VHS_DIGEST}", "", 1)
    assert unpinned != dockerfile
    assert _toolchain_violations(unpinned, script)
    no_checksum = CHECKSUM_RE.sub("", dockerfile)
    assert no_checksum != dockerfile
    assert _toolchain_violations(no_checksum, script)
    no_chown = "\n".join(ln for ln in script.splitlines() if "chown" not in ln)
    assert no_chown != script
    assert _toolchain_violations(dockerfile, no_chown)


def _tape_install_violations(tape: str) -> list[str]:
    out: list[str] = []
    if "uv sync --frozen" not in tape:
        out.append("the tape does not run 'uv sync --frozen'")
    for banned in ("pip install", "apt-get", "pdf-tooling=="):
        if banned in tape:
            out.append(f"the tape contains {banned!r}")
    header = "\n".join(ln for ln in tape.splitlines() if ln.startswith("#"))
    if VHS_DIGEST not in header:
        out.append("the tape header does not name the VHS image digest")
    outputs = re.findall(r"^Output (\S+)$", tape, flags=re.MULTILINE)
    if outputs != ["docs/demo/pdf-tooling.gif", "docs/demo/pdf-tooling.txt"]:
        out.append(f"Output lines must be the gif then the txt, got {outputs}")
    return out


def test_demo_tape_installs_the_tree() -> None:
    assert _tape_install_violations(TAPE.read_text(encoding="utf-8")) == []


def test_demo_tape_install_arm_can_fail() -> None:
    tape = TAPE.read_text(encoding="utf-8")
    lines = tape.splitlines()
    idx = next(
        i for i, ln in enumerate(lines) if "uv sync --frozen" in ln and ln.startswith("Type")
    )
    lines[idx] = BASE_INSTALL_LINE
    assert _tape_install_violations("\n".join(lines))


def _transcript_violations(text: str) -> list[str]:
    out: list[str] = []
    matches = COMPRESS_MESSAGE.findall(text)
    if not matches:
        out.append("no compress message row found")
    for before_s, after_s, sign, value in matches:
        before, after = int(before_s), int(after_s)
        if after >= before:
            out.append(f"compress did not shrink: {before} -> {after}")
        if sign != "-":
            out.append("sign + on a reduction")
        expected = f"{abs((after - before) / before * 100):.1f}"
        if value != expected:
            out.append(f"printed {value}% but the byte counts give {expected}%")
    if "1 page selected" not in text:
        out.append("missing '1 page selected'")
    if "1 pages selected" in text:
        out.append("contains '1 pages selected'")
    for name in ("chapter1.pdf", "chapter2.pdf"):
        if f"{name} -> small/{name} ok=true" not in text:
            out.append(f"missing the dry-run row for {name}")
    if TEACHING_GATE.search(text):
        out.append("transcript matches the teaching gate")
    for token in ("/home/", "/Users/", "/root/"):
        if token in text:
            out.append(f"transcript contains the host path token {token}")
    return out


def test_demo_transcript_compress_row_shows_a_reduction() -> None:
    assert _transcript_violations(TRANSCRIPT.read_text(encoding="utf-8")) == []


def test_demo_transcript_arm_can_fail() -> None:
    rows = (
        "chapter1.pdf -> small/chapter1.pdf ok=true\nchapter2.pdf -> small/chapter2.pdf ok=true\n"
    )
    good = "1 page selected\nbook.pdf  book-small.pdf  0  2259 -> 1259 bytes (-44.3%)\n" + rows
    assert _transcript_violations(good) == []
    wrong_sign = (
        "1 page selected\nbook.pdf  book-small.pdf  0  2549 -> 1259 bytes (+50.6%)\n" + rows
    )
    assert any("sign" in v for v in _transcript_violations(wrong_sign))
    arithmetic = (
        "1 page selected\nbook.pdf  book-small.pdf  0  2259 -> 1259 bytes (-50.6%)\n" + rows
    )
    assert any("byte counts" in v for v in _transcript_violations(arithmetic))
    plural = good.replace("1 page selected", "1 pages selected")
    assert any("pages selected" in v for v in _transcript_violations(plural))
