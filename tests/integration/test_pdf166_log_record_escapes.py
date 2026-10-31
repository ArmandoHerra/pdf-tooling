"""PDF-166 -- log records reach stderr with no terminal control bytes (CWE-150, B-538).

The end-to-end matrix: every measured route (the ``--password-file`` warnings, ``doctor
--strict``'s stray name, the ``-vv`` DEBUG records, the unknown-``/Encrypt`` record) is driven
as a real process with captured BYTES (``registry.run_cli`` is ``text=True`` and would hide a
bare CR), plus the frozen surfaces: ``-o json`` / ``-o ndjson`` stdout, the written file and
PDF-157's own lowercase lines.

A **record** is a stderr line starting with ``DEBUG: `` .. ``CRITICAL: ``; any other stderr
line is a non-record line. Fixtures are built here with ``pikepdf``/the stdlib/the product's
own ``create`` verb, so no binary is committed. ``ENC`` is RC4-128 with a fixed ``/ID``
(``metadata=False`` is required by pikepdf for non-AES), so two builds are sha-equal.

STEP-0 (measured at base c8b6e11, 2026-10-31, CPython 3.14.7, before any ``src/`` edit)::

    ENC_SHA256 determinism      two builds equal
    unknown-/Encrypt fixture    see UNKNOWN_ENCRYPT_REACHED below
    volatile in decrypt out.pdf trailer /ID second string (two runs 2.2 s apart differ there
                                and nowhere else); masked by pdf_fingerprint
    doctor stdout               host-dependent (engines present, their versions/details), so
                                the in-suite literal freeze hashes the host-independent keys
                                only; the full doctor bytes are A/B'd across trees outside
                                the suite (Validation step 7)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.safety.tempnames import TEMP_PREFIX  # noqa: E402
from registry import console_script, run_cli_with_pty  # noqa: E402

PW = "pw\x1b[31m\x07\u009b.txt"
PWG = "pwg\x1b[31m\x07\u009b.txt"
BAD = "bad\x1b[31m\x07\u009b.pdf"
BADENC = "benc\x1b[31m\x07\u009b.pdf"
STRAY = TEMP_PREFIX + "x\x1b[31m\x07\u009b.tmp"
EVIL_PDF_NAME = "unk\x1b[31m\x07\u009b.pdf"
NOPE = "nope\x1b[31m\x07.pdf"

SHOWN_PW = "pw\\x1b[31m\\x07\\x9b.txt"
SHOWN_PWG = "pwg\\x1b[31m\\x07\\x9b.txt"
SHOWN_STRAY = TEMP_PREFIX + "x\\x1b[31m\\x07\\x9b.tmp"
SHOWN_BAD = "bad\\x1b[31m\\x07\\x9b.pdf"
SHOWN_UNK = "unk\\x1b[31m\\x07\\x9b.pdf"

#: The pikepdf-built ENC (user = owner = "secret", RC4-128, fixed /ID), recorded at base.
ENC_SHA256 = "497863937543d61cab7462d3120eb5a5c6506a5f5b306373b4748dcce1ee9902"
LEVEL_PREFIXES = (b"DEBUG: ", b"INFO: ", b"WARNING: ", b"ERROR: ", b"CRITICAL: ")


# --------------------------------------------------------------------------- fixtures


def build_enc_pdf(path: Path) -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(
        path,
        encryption=pikepdf.Encryption(
            user="secret", owner="secret", R=4, aes=False, metadata=False
        ),
        static_id=True,
    )


def build_unknown_encrypt_pdf(path: Path) -> None:
    """One page plus a trailer /Encrypt (/V 2 /R 3 /Length 56) that no known algorithm matches.

    No real crypto is needed: the adapter logs the unrecognised dictionary before it tries
    ``decrypt("")``, and the run then ends 6.
    """
    zeros = "<" + "00" * 32 + ">"
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
        (f"<< /Filter /Standard /V 2 /R 3 /Length 56 /O {zeros} /U {zeros} /P -4 >>").encode(
            "ascii"
        ),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R /Encrypt 4 0 R "
        "/ID [<00112233445566778899AABBCCDDEEFF> <00112233445566778899AABBCCDDEEFF>] >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(bytes(out))


class World:
    """One scratch world: ``work`` (the cwd of every run) and a scrubbed environment."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.work = root / "work"
        self.work.mkdir()
        scratch = root / "scratch"
        self.env = dict(os.environ)
        for key, sub in (
            ("HOME", "home"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("TMPDIR", "tmp"),
        ):
            (scratch / sub).mkdir(parents=True, exist_ok=True)
            self.env[key] = str(scratch / sub)
        self.env.pop("PDF_TOOLING_PASSWORD", None)

    def run(
        self, argv: list[str], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - argv is the product's own console script
            [*console_script(), *argv],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd or self.work,
            env=self.env,
            check=False,
            timeout=120,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    (w.work / "ok.txt").write_bytes(b"hello page one\n")
    created = w.run(["create", "ok.txt", "-O", "ok.pdf", "-o", "json"])
    assert created.returncode == 0, created.stderr
    build_enc_pdf(w.work / "enc.pdf")
    (w.work / "good.pw").write_bytes(b"secret\n")
    (w.work / "good.pw").chmod(0o600)
    for name, body in ((PW, b"x\ny\n"), (PWG, b"secret\nextra\n")):
        (w.work / name).write_bytes(body)
        (w.work / name).chmod(0o644)
    (w.work / BAD).write_bytes(b"not a pdf at all")
    (w.work / BADENC).write_bytes((w.work / "enc.pdf").read_bytes())
    return w


# --------------------------------------------------------------------------- helpers


def count_f_ml(data: bytes) -> int:
    """F_ml: every byte 0x00-0x1F except TAB and LF, DEL, and each UTF-8 C1 pair."""
    c0 = sum(1 for byte in data if (byte < 0x20 and byte not in (0x09, 0x0A)) or byte == 0x7F)
    return c0 + len(re.findall(rb"\xc2[\x80-\x9f]", data))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def records_of(stderr: bytes) -> list[bytes]:
    return [line for line in stderr.split(b"\n") if line.startswith(LEVEL_PREFIXES)]


def non_records_of(stderr: bytes) -> list[bytes]:
    return [line for line in stderr.split(b"\n") if line and not line.startswith(LEVEL_PREFIXES)]


def raw_records(stderr: bytes) -> int:
    return sum(1 for line in records_of(stderr) if count_f_ml(line) > 0)


def warnings_of(stderr: bytes) -> list[bytes]:
    return [line for line in records_of(stderr) if line.startswith(b"WARNING: ")]


def _shows(line: bytes, shown: str) -> bool:
    """True when *line* carries *shown* as ASCII text (never an operand pin, B-073)."""
    return shown.encode("ascii") in line


VERBS = {
    "info": ["info", "enc.pdf"],
    "metaget": ["meta", "get", "enc.pdf"],
    "decrypt": ["decrypt", "enc.pdf", "-O", "out.pdf"],
}
VFLAGS = {"d0": [], "v": ["-v"], "vv": ["-vv"]}
RC_FOR = {PW: 6, PWG: 0}


def run_enc(
    w: World,
    verb: str,
    pwfile: str,
    level: str,
    *,
    fmt: str = "json",
    extra: list[str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    argv = [*VFLAGS[level], *VERBS[verb], "--password-file", pwfile, "-o", fmt, *(extra or [])]
    proc = w.run(argv)
    (w.work / "out.pdf").unlink(missing_ok=True)
    return proc


# --------------------------------------------------------------------------- Group B


def test_fixture_builders_are_deterministic_and_open(world: World, tmp_path: Path) -> None:
    again = tmp_path / "again.pdf"
    build_enc_pdf(again)
    assert sha(again.read_bytes()) == sha((world.work / "enc.pdf").read_bytes()) == ENC_SHA256
    proc = world.run(["info", "enc.pdf", "--password-file", "good.pw", "-o", "json"])
    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)["documents"][0]
    assert document["encrypted"] is True
    assert document["ok"] is True
    assert warnings_of(proc.stderr) == []


def test_ac4_password_file_records_are_escaped(world: World) -> None:
    raw = 0
    shown_all: list[bool] = []
    for verb in VERBS:
        for pwfile, shown in ((PW, SHOWN_PW), (PWG, SHOWN_PWG)):
            for level in ("d0", "v"):
                proc = run_enc(world, verb, pwfile, level)
                assert proc.returncode == RC_FOR[pwfile], (verb, pwfile, level, proc.stderr)
                warns = warnings_of(proc.stderr)
                assert len(warns) == 2, (verb, pwfile, level)  # guard: base 2, after 2
                shown_all.extend(_shows(line, shown) for line in warns)
                raw += raw_records(proc.stderr)
    assert raw == 0  # base: 24
    assert all(shown_all) and len(shown_all) == 24

    # (b) guards: the file is never read for an unencrypted input; a good file is silent.
    for verb in ("info", "meta get", "decrypt"):
        argv = [*verb.split(), "ok.pdf", "--password-file", PW, "-o", "json"]
        if verb == "decrypt":
            argv += ["-O", "out.pdf"]
        proc = world.run(argv)
        (world.work / "out.pdf").unlink(missing_ok=True)
        assert records_of(proc.stderr) == [], verb
    proc = world.run(["info", "enc.pdf", "--password-file", "good.pw", "-o", "json"])
    assert warnings_of(proc.stderr) == []

    # (c) pty: what a terminal receives.
    result = run_cli_with_pty(
        "info", "enc.pdf", "--password-file", PWG, "-o", "json",
        pty_stream="stderr", cwd=world.work, env=world.env,
    )  # fmt: skip
    assert result.returncode == 0
    for point in ("\x1b", "\x07", "\x7f", "\x9b"):
        assert point not in result.stderr, point

    # (d) dry run: records are a function of what the verb reads, not of the escape.
    dry = world.run(
        ["decrypt", "enc.pdf", "--password-file", PWG, "-O", "d.pdf", "--dry-run", "-o", "json"]
    )
    assert dry.returncode == 0
    assert raw_records(dry.stderr) == 0
    assert len(records_of(dry.stderr)) == DRY_RUN_RECORDS


#: ``decrypt --dry-run`` never reads the password file: 0 records at base and after.
DRY_RUN_RECORDS = 0


def _doctor_world(w: World) -> Path:
    root = w.root / "doctor"
    root.mkdir()
    (root / STRAY).write_bytes(b"")
    return root


def test_ac5_doctor_strict_stray_record_is_escaped(world: World) -> None:
    root = _doctor_world(world)
    proc = world.run(["doctor", "--strict", "-o", "json"], cwd=root)
    envelope = json.loads(proc.stdout)
    assert proc.returncode == envelope["exit_code"]
    unavailable = [row for row in envelope["ports"] if not row["available"]]
    warns = warnings_of(proc.stderr)
    assert len(warns) == 1
    assert len(records_of(proc.stderr)) == 1 + (1 if unavailable else 0)
    assert raw_records(proc.stderr) == 0  # base: 1
    assert _shows(warns[0], SHOWN_STRAY)
    # Oracle: the JSON is lossless.
    assert any(entry.endswith(STRAY) for entry in envelope["stray_temp_files"])
    # Guard: without --strict nothing is logged.
    plain = world.run(["doctor", "-o", "json"], cwd=root)
    assert records_of(plain.stderr) == []


def test_ac6_debug_records_naming_paths_are_escaped(world: World) -> None:
    runs: dict[str, subprocess.CompletedProcess[bytes]] = {}
    runs["info-bad"] = world.run(["-vv", "info", BAD, "-o", "table"])
    runs["info-badenc"] = world.run(
        ["-vv", "info", BADENC, "--password-file", "good.pw", "-o", "json"]
    )
    for verb in VERBS:
        for pwfile in (PW, PWG):
            key = f"{verb}-{'pw' if pwfile == PW else 'pwg'}"
            runs[key] = run_enc(world, verb, pwfile, "vv")
    assert len(runs) == 8
    raw = 0
    for key, proc in runs.items():
        rc, count = EXPECTED_VV[key]
        assert proc.returncode == rc, key
        assert len(records_of(proc.stderr)) == count, key
        raw += raw_records(proc.stderr)
    assert raw == 0  # base: 26
    bad_errors = [
        line for line in runs["info-bad"].stderr.split(b"\n") if line.startswith(b"error: ")
    ]
    assert len(bad_errors) == 1
    assert count_f_ml(bad_errors[0]) == 0
    assert non_records_of(runs["info-bad"].stderr) == bad_errors


#: (rc, records) per -vv cell, recorded at base c8b6e11: the record count must not move.
EXPECTED_VV: dict[str, tuple[int, int]] = {
    "info-bad": (1, 5),
    "info-badenc": (0, 4),
    "info-pw": (6, 6),
    "info-pwg": (0, 6),
    "metaget-pw": (6, 5),
    "metaget-pwg": (0, 5),
    "decrypt-pw": (6, 5),
    "decrypt-pwg": (0, 5),
}


#: Step 0 at base: ``info`` on the constructed fixture reaches the record (rc 6, one WARNING
#: naming the unrecognised dictionary), so AC7(b) is counted, not demoted.
UNKNOWN_ENCRYPT_REACHED = True


def test_ac7b_unknown_encrypt_fixture_record_is_escaped(world: World) -> None:
    build_unknown_encrypt_pdf(world.work / EVIL_PDF_NAME)
    proc = world.run(["info", EVIL_PDF_NAME, "-o", "json"])
    hits = [
        line for line in records_of(proc.stderr) if b"unrecognised encryption dictionary" in line
    ]
    assert proc.returncode == UNKNOWN_ENCRYPT_RC
    assert len(hits) == (1 if UNKNOWN_ENCRYPT_REACHED else 0)
    assert raw_records(proc.stderr) == 0  # base: the reached record is raw
    if UNKNOWN_ENCRYPT_REACHED:
        assert _shows(hits[0], SHOWN_UNK)


UNKNOWN_ENCRYPT_RC = 6


# --------------------------------------------------------------------------- Group C

#: Recorded at base c8b6e11 (main after cycle 11 waves 1, 1b, 2), 2026-10-31, CPython 3.14.7,
#: before any src/ edit. Two consecutive base runs of all nine outputs were byte-identical after
#: ``normalize`` (``duration_ms``, lock-pinned engine ``version`` strings, the scratch root).
#: ``doctor_strict_json`` hashes only its host-independent keys (see ``_doctor_projection``);
#: its return code is host-dependent too, and is compared with the envelope's own exit_code.
FROZEN_SHA256 = {
    "info_enc_pwg_json": "4c41ae245fe0ffb5012901f9359ff18c82160f5c3ea66612491fc382cb8fc296",
    "info_enc_pwg_ndjson": "d7172f0f1ea284e851859cb02dc14b0ce37fd8fa000a9fc2b650d61e9c4cc0e7",
    "info_enc_pw_json": "6c98818b79891fb5f2984588bcac4b961846c8dca3fdcc2755f37520aa942351",
    "metaget_enc_pwg_json": "c37fae9c63c71aca21906ec305982b4d15a3e270bf74249613702d1b7dff5708",
    "decrypt_enc_pwg_json": "453d869fe79ef9ceda2987180cf6bcc0ec108584b71eb02e4f8b3d277bc68b16",
    "decrypt_enc_pwg_ndjson": "d8b4fef01bda636d0674c69439dad64c5121f5187369b2071494dde0547398c7",
    "info_badenc_json": "eb615f6b8d3c5a3c1ca471efb1998e4528f9dc82de2c5bb5b89416ef6bf6f7f9",
    "doctor_strict_json": "72e0f3f1ed46dd7a872a1ebfc3ff67c052c382c4a7f897f3fc03a3a0846225f0",
    "info_bad_json": "dcca0d1cc9b04594fd38585cb34ccb21ce7baa32d8c230470dc88c374872adf2",
}
FROZEN_RC = {
    "info_enc_pwg_json": 0,
    "info_enc_pwg_ndjson": 0,
    "info_enc_pw_json": 6,
    "metaget_enc_pwg_json": 0,
    "decrypt_enc_pwg_json": 0,
    "decrypt_enc_pwg_ndjson": 0,
    "info_badenc_json": 0,
    "info_bad_json": 1,
}
#: pdf_fingerprint of ``decrypt``'s out.pdf: the only run-varying field is the trailer /ID
#: second string (two runs 2.2 s apart differ there and nowhere else), masked.
DECRYPT_FINGERPRINT = "cafcdab3609ca3e0d4f61fd20be75e98e43142480b7bb500f6645dff82ef75ac"


def normalize(data: bytes, root: Path | None = None) -> bytes:
    data = re.sub(rb'"duration_ms": [0-9.]+', b'"duration_ms": 0', data)
    data = re.sub(rb'"version": "[^"]*"', b'"version": "X"', data)
    if root is not None:
        data = data.replace(os.fsencode(str(root)), b"<ROOT>")
    return data


def _doctor_projection(stdout: bytes, root: Path) -> bytes:
    """The host-independent keys of doctor's envelope (engines present vary by machine)."""
    envelope = json.loads(normalize(stdout, root))
    keep = {k: envelope[k] for k in ("schema_version", "verb", "dry_run", "strict")}
    keep["stray_temp_files"] = envelope["stray_temp_files"]
    return json.dumps(keep, sort_keys=True, ensure_ascii=True).encode("ascii")


def pdf_fingerprint(path: Path) -> str:
    """sha256 of a parsed form: page count, decoded page content, object structure, trailer.

    The one time-derived field (the trailer /ID second string) is replaced by a placeholder.
    """
    parts: list[str] = []
    with pikepdf.open(path) as pdf:
        parts.append(f"pages={len(pdf.pages)}")
        for page in pdf.pages:
            contents = page.obj.get("/Contents")
            streams = list(contents) if isinstance(contents, pikepdf.Array) else [contents]
            data = b"".join(s.read_bytes() for s in streams if s is not None)
            parts.append("content=" + sha(data))
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream):
                parts.append("stream:" + ",".join(sorted(str(k) for k in obj.stream_dict.keys())))
            elif isinstance(obj, pikepdf.Dictionary):
                parts.append("dict:" + ",".join(sorted(str(k) for k in obj.keys())))
            else:
                parts.append(type(obj).__name__)
        parts.append("trailer:" + ",".join(sorted(str(k) for k in pdf.trailer.keys())))
        ids = pdf.trailer.get("/ID")
        if ids is not None:
            parts.append("id0=" + bytes(ids[0]).hex())
            parts.append("id1=<masked>")
    return sha("\n".join(parts).encode("utf-8"))


def _members(
    w: World, level: str, root: Path
) -> tuple[dict[str, subprocess.CompletedProcess[bytes]], dict[str, str]]:
    """The nine frozen outputs at one verbosity, plus the fingerprint of each written file."""
    vf = VFLAGS[level]
    procs: dict[str, subprocess.CompletedProcess[bytes]] = {}
    prints: dict[str, str] = {}
    pwg = ["--password-file", PWG]
    argvs: list[tuple[str, list[str], Path | None]] = [
        ("info_enc_pwg_json", ["info", "enc.pdf", *pwg, "-o", "json"], None),
        ("info_enc_pwg_ndjson", ["info", "enc.pdf", *pwg, "-o", "ndjson"], None),
        ("info_enc_pw_json", ["info", "enc.pdf", "--password-file", PW, "-o", "json"], None),
        ("metaget_enc_pwg_json", ["meta", "get", "enc.pdf", *pwg, "-o", "json"], None),
        ("decrypt_enc_pwg_json", ["decrypt", "enc.pdf", *pwg, "-O", "out.pdf", "-o", "json"], None),
        (
            "decrypt_enc_pwg_ndjson",
            ["decrypt", "enc.pdf", *pwg, "-O", "out.pdf", "-o", "ndjson"],
            None,
        ),
        ("info_badenc_json", ["info", BADENC, "--password-file", "good.pw", "-o", "json"], None),
        ("doctor_strict_json", ["doctor", "--strict", "-o", "json"], root),
        ("info_bad_json", ["info", BAD, "-o", "json"], None),
    ]
    for name, argv, cwd in argvs:
        procs[name] = w.run([*vf, *argv], cwd=cwd)
        written = w.work / "out.pdf"
        if written.exists():
            prints[name] = pdf_fingerprint(written)
            written.unlink()
    return procs, prints


def _norm(name: str, stdout: bytes, root: Path) -> bytes:
    """What the literal freeze hashes (doctor: its host-independent keys only)."""
    if name == "doctor_strict_json":
        return _doctor_projection(stdout, root)
    return normalize(stdout, root)


def test_ac8_stdout_is_byte_unchanged(world: World) -> None:
    root = _doctor_world(world)
    levels = {level: _members(world, level, root) for level in VFLAGS}
    base_procs, base_prints = levels["d0"]
    assert len(base_procs) == 9

    # (i) verbosity invariance, on the full normalised bytes (doctor: whole envelope).
    for name, proc in base_procs.items():
        for level in ("v", "vv"):
            other = levels[level][0][name]
            assert normalize(other.stdout, root) == normalize(proc.stdout, root), (name, level)

    # (ii) literal freeze.
    assert set(FROZEN_SHA256) == set(base_procs)
    assert set(FROZEN_RC) == set(base_procs) - {"doctor_strict_json"}
    doctor_exit = json.loads(base_procs["doctor_strict_json"].stdout)["exit_code"]
    assert base_procs["doctor_strict_json"].returncode == doctor_exit
    for name, proc in base_procs.items():
        if name in FROZEN_RC:
            assert proc.returncode == FROZEN_RC[name], name
        assert sha(_norm(name, proc.stdout, root)) == FROZEN_SHA256[name], name

    # (iii) the written file, time-masked: equal at every verbosity and across runs 2 s apart.
    assert set(base_prints) == {"decrypt_enc_pwg_json", "decrypt_enc_pwg_ndjson"}
    for level in ("v", "vv"):
        assert levels[level][1] == base_prints
    assert set(base_prints.values()) == {DECRYPT_FINGERPRINT}
    time.sleep(2.1)
    again = world.run(["decrypt", "enc.pdf", "--password-file", PWG, "-O", "out.pdf", "-o", "json"])
    assert again.returncode == 0
    assert pdf_fingerprint(world.work / "out.pdf") == DECRYPT_FINGERPRINT

    # (iv) oracle: the JSON that carried a hostile name still carries it raw.
    doctor = json.loads(base_procs["doctor_strict_json"].stdout)
    assert any(entry.endswith(STRAY) for entry in doctor["stray_temp_files"])
    bad = json.loads(base_procs["info_bad_json"].stdout)
    assert bad["documents"][0]["path"] == BAD


NOPE_STDERR = b"error: no such file (nope\\x1b[31m\\x07.pdf)\n"


def test_ac9_pdf157_lines_are_unchanged_and_not_double_escaped(world: World) -> None:
    proc = world.run(["info", NOPE, "-o", "table"])
    assert proc.returncode == 4
    assert proc.stderr == NOPE_STDERR

    proc = world.run(["-vv", "info", BAD, "-o", "table"])
    errors = [line for line in proc.stderr.split(b"\n") if line.startswith(b"error: ")]
    assert len(errors) == 1
    assert errors[0].count(SHOWN_BAD.encode("ascii")) == 1
    for line in proc.stderr.split(b"\n"):
        for doubled in (b"\\\\x1b", b"\\\\x07", b"\\\\x9b"):
            assert doubled not in line
