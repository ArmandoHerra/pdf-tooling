"""PDF-155 -- `meta get` / `info` report a present XMP packet instead of ``null``.

THE DEFECT (ledger ``9658d886b8``, ``874a9bd303``; ``99dbb7ff96`` is pinned, not
fixed). On two shapes where a ``/Root /Metadata`` packet exists, ``meta get``
and ``info`` reported ``xmp: null`` (or an all-empty ``xmp``) with
``warnings: []``: an unparseable packet, and a valid packet whose only
``rdf:Description`` has a non-empty ``rdf:about``.

THE RULE (D6). ``xmp`` is ``None`` when the document carries no XMP packet,
**or** when a packet is present but its fields could not be parsed or read; in
the second case ``warnings`` carries exactly one entry beginning
``XMP packet present but its fields are not reported``. ``xmp: null`` with no
such warning means "no packet" and nothing else.

THE ORACLE. ``pikepdf.open(F, password=...).Root.Metadata.read_bytes()``,
independent of pypdf. Every cell is a subprocess (``registry.run_cli``) with the
fixture passed as a RELATIVE operand and ``cwd`` = the fixture directory, so the
``path`` field and every byte literal are host-independent.

BASE LITERALS. ``BASE_SHA`` is the sha256 of stdout for each pinned cell,
recorded at Validation step 0 on the recorded base (``71f9f2a``, PDF-155 step 0,
2026-10-29), with relative operands. AC5/AC6/AC8 are pins, not detectors: they
pass at the base by design.

The module imports no symbol that PDF-155 adds, so it collects at the base and
its detector nodes fail there on behaviour.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import warnings
import xml.dom.minidom
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import REPO_ROOT, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

RDF: Final[str] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC: Final[str] = "http://purl.org/dc/elements/1.1/"
PDFNS: Final[str] = "http://ns.adobe.com/pdf/1.3/"
UUID_ABOUT: Final[str] = "uuid:6ec119a7-1f2a-4c2b-9e2e-0123456789ab"

USER: Final[str] = "user-pw-155"
OWNER: Final[str] = "owner-pw-155"

#: The D3 literal -- written out here, never imported from the product.
W1: Final[str] = (
    "XMP packet present but its fields are not reported: "
    "the XMP packet is not well-formed XML (--xmp shows the raw packet)"
)
W_UNREADABLE: Final[str] = (
    "XMP packet present but its fields are not reported: the XMP packet could not be read"
)
W_PREFIX: Final[str] = "XMP packet present but its fields are not reported"

GOLDEN_SHA: Final[dict[str, str]] = {
    "tests/golden/envelope_keys.json": (
        "07bb654bb4fd43b3d98316ae6283b882caefb9fcee6525d1dbc7fb43051dd4f5"
    ),
    "tests/golden/meta_get.json": (
        "e6121586bfc12c16a6943714b078ea43c90fe8e085e596c2bdbf3c8a89e49099"
    ),
}

META_GET_KEYS: Final[list[str]] = [
    "disagreements",
    "dry_run",
    "duration_ms",
    "exit_code",
    "info",
    "path",
    "residual_surfaces",
    "schema_version",
    "verb",
    "warnings",
    "xmp",
    "xmp_raw",
]
INFO_KEYS: Final[list[str]] = [
    "documents",
    "dry_run",
    "duration_ms",
    "exit_code",
    "items",
    "schema_version",
    "verb",
    "warnings",
]

# --------------------------------------------------------------------------- #
# The commands
# --------------------------------------------------------------------------- #

#: ``(label, verb, --xmp, format)``
MG: Final[tuple[tuple[str, str, bool, str], ...]] = (
    ("meta get -o json", "meta get", False, "json"),
    ("meta get --xmp -o json", "meta get", True, "json"),
    ("meta get -o ndjson", "meta get", False, "ndjson"),
    ("meta get --xmp -o ndjson", "meta get", True, "ndjson"),
    ("meta get -o table", "meta get", False, "table"),
)
IN: Final[tuple[tuple[str, str, bool, str], ...]] = (
    ("info -o json", "info", False, "json"),
    ("info -o ndjson", "info", False, "ndjson"),
)
MALFORMED: Final[tuple[str, ...]] = ("unparseable", "unbound_prefix")
EU: Final[tuple[str, ...]] = (
    "unparseable.aes6",
    "unparseable.aes4",
    "unparseable.nometa",
    "unparseable.rc4nometa",
)
#: The expected ``/Encrypt`` shape of each EU fixture: ``(R, /EncryptMetadata)``.
EU_SHAPE: Final[dict[str, tuple[int, str | None]]] = {
    "unparseable.aes6": (6, None),
    "unparseable.aes4": (4, None),
    "unparseable.nometa": (6, "false"),
    "unparseable.rc4nometa": (4, "false"),
}
ENCRYPTED: Final[tuple[str, ...]] = (
    "good.aes",
    "xmp_bearing.aes",
    "good.rc4",
    "xmp_bearing.rc4",
    "good.nometa",
    *EU,
)
PLAIN: Final[tuple[str, ...]] = (
    "good",
    "uuid_about",
    "unparseable",
    "unbound_prefix",
    "multi_desc",
    "conflict_uuid_first",
    "conflict_uuid_last",
    "xmp_bearing",
    "single_page",
)
NEEDS_PW: Final[frozenset[str]] = frozenset(ENCRYPTED)

# --------------------------------------------------------------------------- #
# Base literals (sha256 of stdout, relative operands) -- see the module docstring
# --------------------------------------------------------------------------- #

BASE_SHA: Final[dict[str, str]] = {
    "good :: meta get -o json": "f676e1a80ea9d487d0f1928ca6b376e7560fc31a3f656d9e51fb92e318538c8a",
    "good :: meta get --xmp -o json": (
        "1d9a93368fee77ebb5006b2e6961fde710e1520028897b52b2d563c5c1cfb72c"
    ),
    "good :: meta get -o ndjson": (
        "3f10cfa1f77e62d26d8c5a3b115ca9850675770ca7e7cccac4e099db0c2f2d48"
    ),
    "good :: meta get --xmp -o ndjson": (
        "f1b5d9bba82788ae84a28cb19ea28fbcdf16a84639f7c209977c41b949158e6a"
    ),
    "good :: meta get -o table": "b49199c60047345f9cc5e22dcc910f9611168169917a7c6d736747b6234b190c",
    "good :: info -o json": "b842054faebca53f4fe9c7ee45c93b78fd547e64e8e82a8dac4b97a623dc0a43",
    "good :: info -o ndjson": "715565ae5e662ee5d0607b729bc81c2baeaced6ad1d6e16f70240724e9b47e49",
    "multi_desc :: meta get -o json": (
        "44d593ed7ac3fd8833dfeca3dace50f67901434ef6d359be8943b3e5bdacddf8"
    ),
    "multi_desc :: meta get --xmp -o json": (
        "bae58e97d6bdacc1152bf9cb75b33656bfa9850b7bfe5210ccbe351fa04d38b7"
    ),
    "multi_desc :: meta get -o ndjson": (
        "24d82d4446c8df7e0526691c7ee659f3b57dfb65e1aa09952fec6b95a615ebad"
    ),
    "multi_desc :: meta get --xmp -o ndjson": (
        "2185fe1892600cb550b50ffba9233c2c2f4e41f7a5a8e8da19c498b892a2bac5"
    ),
    "multi_desc :: meta get -o table": (
        "be0a351cdc2dcf59e6171f0e2408b75bbd0a9c800e8d176fa16ed41152d7f51e"
    ),
    "multi_desc :: info -o json": (
        "0511642ef914da356ae70264f77f22b35c5aa56ca1a097ee07c3371a997eafde"
    ),
    "multi_desc :: info -o ndjson": (
        "d5c06ff09a9e216cbdcc7e20c245127daf6b5370930ba732fe984e12ebea55b7"
    ),
    "conflict_uuid_first :: meta get -o json": (
        "37828789b63cb02ff5cefb563fe6388cd1802b93649752d287b84908831e8dec"
    ),
    "conflict_uuid_first :: meta get --xmp -o json": (
        "ad114848f3c321a18040dd8edc80a91ed2131b14692529460e8e819b0b27e214"
    ),
    "conflict_uuid_first :: meta get -o ndjson": (
        "5e35075f9a31afa52dbef810dd6a1110c50d686469926476e94dae6586ee9652"
    ),
    "conflict_uuid_first :: meta get --xmp -o ndjson": (
        "6451086e8db28c82f02e0f581adc64926106164c41103f76064549e5cfe5267b"
    ),
    "conflict_uuid_first :: meta get -o table": (
        "f9d6da178cf28206a503f2e5ae0f327b2c49fe7dfcc65429ae682e9df44233ca"
    ),
    "conflict_uuid_first :: info -o json": (
        "34102ddd4ae9e3166d2d0e56002711d7e8007987b1823f215042c35e540222e1"
    ),
    "conflict_uuid_first :: info -o ndjson": (
        "a86e3bdb9777ccf1a55fe08e5d6f8f2eef5d1cc312b05a5b37552a6521101641"
    ),
    "conflict_uuid_last :: meta get -o json": (
        "9e0282fefeac81e7b9407d1720e955f10eedd973eb1f4fab44c789391c4e8721"
    ),
    "conflict_uuid_last :: meta get --xmp -o json": (
        "baaa9d32c747ac99caf712d347ce43f5c655c458e145207d0327b87f05a0e387"
    ),
    "conflict_uuid_last :: meta get -o ndjson": (
        "eeb17f1d397ce876629b11546492bcb5bf5069a74011413c3585a488395cd7d5"
    ),
    "conflict_uuid_last :: meta get --xmp -o ndjson": (
        "2a6b9ed2789ab4192d60b93e34f0cd62bcd08e59a6eeb1484c81d5554fdb899f"
    ),
    "conflict_uuid_last :: meta get -o table": (
        "a81b681c6a7990caa19fd71855d6b3c0a05b97349772d6d124e82026b8a73c29"
    ),
    "conflict_uuid_last :: info -o json": (
        "c86d8b5b0823635543a06eba852e16cd8cd47b5aa991ba5f165bf3ad5dfa694e"
    ),
    "conflict_uuid_last :: info -o ndjson": (
        "969102bc481ad8de2595d8f5279b3c4bff2d0c6ab4f388b14d7b3ffb8ccc6452"
    ),
    "xmp_bearing :: meta get -o json": (
        "5f766673b2462f210f9168220028cdcaf661a20c900fe4e9e5a0c4bef6f9c360"
    ),
    "xmp_bearing :: meta get --xmp -o json": (
        "bc489b281d6608ec24e61dfbbe8e78fc92ba9852b8b497e0393faadc5bdd5e20"
    ),
    "xmp_bearing :: meta get -o ndjson": (
        "71bbd3db490014068bf722cfb601854a3bb7a8c1971b032ea71665b71c6f7e36"
    ),
    "xmp_bearing :: meta get --xmp -o ndjson": (
        "0c4e7cd99f7c37f141cb003733c7b4d838027a9b4ce5a282e3b4472047674ca6"
    ),
    "xmp_bearing :: meta get -o table": (
        "e1ea86a511b30a6584521b1cff2cb4d447be30a288d374946edde2d289cbe399"
    ),
    "xmp_bearing :: info -o json": (
        "246100191f6487d952ecbe8a7db8f6f9d6e9cf65ab637a4a0c065673fa70539c"
    ),
    "xmp_bearing :: info -o ndjson": (
        "62c5e98ad535831730f09ecd9a138ea2745a760922e72c656844fcd69e0044d6"
    ),
    "single_page :: meta get -o json": (
        "a85dc2884449cd869ca1e4b1c7c7c3a54aad8eff6096054ec443fa08bfa9dae8"
    ),
    "single_page :: meta get --xmp -o json": (
        "a85dc2884449cd869ca1e4b1c7c7c3a54aad8eff6096054ec443fa08bfa9dae8"
    ),
    "single_page :: meta get -o ndjson": (
        "374477a346588519c2bf1b9cb8d72d6595c9676fd4f50a68ba189f3e4a6facbd"
    ),
    "single_page :: meta get --xmp -o ndjson": (
        "374477a346588519c2bf1b9cb8d72d6595c9676fd4f50a68ba189f3e4a6facbd"
    ),
    "single_page :: meta get -o table": (
        "d7605d84ecd69da5f760b6d4b7170dac6e3927f227b1e78e53c6003727a5da18"
    ),
    "single_page :: info -o json": (
        "b90c179daeecf4d2134bc631cd231516d7dc9dc6c1a4118d6951050363941429"
    ),
    "single_page :: info -o ndjson": (
        "c9ba64c630fc92c6d47b102e73e5e30c5565eccb8a34c12cb00d351005f3c1b0"
    ),
    "unparseable :: meta get -o table": (
        "38e234b49248a684387cf06123035557553c5eab0ff8a9c25a358a1b79bd4f93"
    ),
    "unbound_prefix :: meta get -o table": (
        "4e55e8fe6468d922750bda40a8c80c456ea43151f94f2f656075ae674eb9dc28"
    ),
    "uuid_about :: info -o json": (
        "4e6b553eeeeef6c77b05fb20114280a54280b626d8ced2327c7578dbec53757b"
    ),
    "uuid_about :: info -o ndjson": (
        "a7af028ef3759059b03f2431e6eb5e29dac9cfa848d21acdd2c884ec91f259b2"
    ),
    "good.aes :: meta get -o json": (
        "e01d90bb3221fa204cd0c2e3135b9848624086f17c62343713e6b0195c24d918"
    ),
    "good.aes :: meta get --xmp -o json": (
        "29b8f03e7eecc5e2e49f2b60a3eafa62d432bf5b488656a679d79aa50b996827"
    ),
    "good.aes :: meta get -o ndjson": (
        "9a89e438d1dd172058dff655af95271e97fb9dd01ea1e27d5c4db5e1b6f58bd8"
    ),
    "good.aes :: meta get --xmp -o ndjson": (
        "c72c816c436bb8cb1c57d1ad5fd767c7165c7c75ab4f8c7bcfb88c390e05f1a4"
    ),
    "good.aes :: meta get -o table": (
        "60362aca58e6fe338112c7132d1250f9ef6eef4e2f822e10661779a6a50c4cc6"
    ),
    "good.aes :: info -o json": "8adc83b3fdb052e6399efcf8c8211cc2912ff2c50c8f8e8d481d7e34f8e41b1b",
    "good.aes :: info -o ndjson": (
        "c00cfcc5b44a4f5a37ca6cb8f22f5eefe5e3c4d9b94e5d814f978eac5e0f9a00"
    ),
    "xmp_bearing.aes :: meta get -o json": (
        "783074413e94ce15cad8155e172804e6e1292fdf07f031fa164e6040fcd0d9a4"
    ),
    "xmp_bearing.aes :: meta get --xmp -o json": (
        "9156d070aea0a1eaa91167acddf80a5d6421614aa9f041c743091505c96d5660"
    ),
    "xmp_bearing.aes :: meta get -o ndjson": (
        "fce6848e72945a878b1c95240e02d3e312970ed500ff3ed3a92edc86f3aecfec"
    ),
    "xmp_bearing.aes :: meta get --xmp -o ndjson": (
        "7d8c7632e173861181b45db0e0ac00f8f04f7c23fa7c71ba2867884082ae81c3"
    ),
    "xmp_bearing.aes :: meta get -o table": (
        "d663ebdab571698cb64ed929b68534b58b6b993b944e1bce54fde9f50fef2c47"
    ),
    "xmp_bearing.aes :: info -o json": (
        "f40c38b6708ebca0285ee3e4ba91ba0a40361717d9b6e2401d26d5f7fd1a7ff3"
    ),
    "xmp_bearing.aes :: info -o ndjson": (
        "f721b1e87e7e3408c3ec2435ac417a539d0134a11a70eb1a742b18a81dd2f8f3"
    ),
    "good.rc4 :: meta get -o json": (
        "6e5c6ea7899abf6a34cf4f386a4b939bfb641987db7ac75be27585b12d7df0df"
    ),
    "good.rc4 :: meta get --xmp -o json": (
        "6cd758d09f1c5a167a91c0ad8ffb0a827ecbcc7bbabc70489d6372ff7db6128e"
    ),
    "good.rc4 :: meta get -o ndjson": (
        "e5faad9cfef94046d18000bc30c6dc9760c8bec8539bea5650b3f49c3c1d74d4"
    ),
    "good.rc4 :: meta get --xmp -o ndjson": (
        "87e07a4ee3f396a6ee721b3bbf135800b69050dd2836d9e1b0bc7a84747fea14"
    ),
    "good.rc4 :: meta get -o table": (
        "223e8d00f24558e572825cc3328d48804dbedef94ed29e2ddb49f1b63fbafbb7"
    ),
    "good.rc4 :: info -o json": "4963f0cb753617c352b4e9e87fae0ba2143e3769e15c67dd3180ad97b8a354b4",
    "good.rc4 :: info -o ndjson": (
        "0395aafa4939a03eb390aab4d26d6c6a0017f62a31265c42926a298b572729bd"
    ),
    "xmp_bearing.rc4 :: meta get -o json": (
        "cbce76bfc48c60a517b06d9408d554842b5e971c7e0efafe80f42bb91cfaed62"
    ),
    "xmp_bearing.rc4 :: meta get --xmp -o json": (
        "68d8788cd7caaaf7bc84539c46e67877aa425d8fab6c0e591d99268fd5fa1d1e"
    ),
    "xmp_bearing.rc4 :: meta get -o ndjson": (
        "9f0f665644dbee94b809ea60f0103df8592bd0eb6d3a955406d6ffb5bf763c9c"
    ),
    "xmp_bearing.rc4 :: meta get --xmp -o ndjson": (
        "15c9c33d594d1a99fbfc79599587a74ce3745aaedee40de00cc73d0db8b83834"
    ),
    "xmp_bearing.rc4 :: meta get -o table": (
        "c5c23d4af6952b779b2abee8ec898f2f9a4e68809e0368862193ac2b477b3d44"
    ),
    "xmp_bearing.rc4 :: info -o json": (
        "78c3528fdeceb749ee0bf73780f7523e5e42cb36b8a65d5e3324bafc76e21e79"
    ),
    "xmp_bearing.rc4 :: info -o ndjson": (
        "6f0dc24bbbaf33dc2199aed7fabcccf93281f7790041ea2ac270961f3ad72898"
    ),
    "good.nometa :: meta get -o json": (
        "a6f956805c458aac6e87a93c3cb37accb7f813e28997469e342cd9001f3b9000"
    ),
    "good.nometa :: meta get --xmp -o json": (
        "4c34b0da00aff88794b2c3e6e6d71a9479c3910116f0fad0a4dece7a39aa259b"
    ),
    "good.nometa :: meta get -o ndjson": (
        "3699425d38fc94787732e708d7f3538b8461877c82673d2b95e09fc05a142fed"
    ),
    "good.nometa :: meta get --xmp -o ndjson": (
        "e18fd00ab544fcb713baaa0c8c34ec33a131701da4a6a7d89a8484bc10ad9b82"
    ),
    "good.nometa :: meta get -o table": (
        "2a3ed11c56244cc9ec3650bd48d225c7e14d6667636712483ea5a7e12c71e7ad"
    ),
    "good.nometa :: info -o json": (
        "e379dcb7bb1a6cf261456d3e7c8b84b351349394fb330a485a73dead3f84eb18"
    ),
    "good.nometa :: info -o ndjson": (
        "47fae918e85e97201d11b9b42620e05e27074b0f44056f83237dbd49f70704ee"
    ),
}

#: ``(dry rc, real rc)`` per exit-table row at the base, both verbs.
BASE_EXIT_PAIRS: Final[dict[str, tuple[int, int]]] = {
    "meta get truncated": (1, 1),
    "info truncated": (1, 1),
}

#: sha256 of each write-side function's source segment at ``e83c743`` and at the
#: recorded base (equal: PDF-151/152/154/156 did not touch these functions).
WRITE_SIDE: Final[tuple[str, ...]] = (
    "write_metadata",
    "_rewrite_xmp_packet",
    "_edit_and_verify",
    "_xmp_over",
    "_descriptions",
    "_true_metadata_packet",
    "_encrypt_metadata_is_false",
)
WRITE_SIDE_SHA: Final[dict[str, str]] = {
    "write_metadata": ("009eaf0408aaee2957066b91886755460f2b3bd33de40f6bd636d5413fb9cf69"),
    "_rewrite_xmp_packet": ("51274d87a41a2fd0fb15ba6786527227dc588be4a180579f892b9b9e052b2a3d"),
    "_edit_and_verify": ("e72280e73782c3084b80c581af8701ca7f0cf0fe68855d1310a7da17767ebb81"),
    "_xmp_over": ("a6478b87f44279c118ef6dd18f539bfaca370f0d4de2ce4692ef3dd7d4488d88"),
    "_descriptions": ("3924dd9cb19f6beb9ba159efbfeeb6b1d786f64daefff90f08d8ade75b5914f6"),
    "_true_metadata_packet": ("99a452073fe430caf14e51401ae22bd16bd86c09ed5754e15f36725de043eca8"),
    "_encrypt_metadata_is_false": (
        "f936146ecbd114ccd2e0d44e0411cce87b3b0957a33319fe491133e83a4b4a21"
    ),
}

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_PROLOG: Final[str] = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    f'<rdf:RDF xmlns:rdf="{RDF}">\n'
)
_EPILOG: Final[str] = '</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>'
_TITLE: Final[str] = (
    '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">XMP Title</rdf:li></rdf:Alt></dc:title>'
)
_PRODUCER: Final[str] = "<pdf:Producer>XMP Producer</pdf:Producer>"


def _description(
    about: str, content: str, decls: str = f'xmlns:dc="{DC}" xmlns:pdf="{PDFNS}"'
) -> str:
    return f'<rdf:Description rdf:about="{about}" {decls}>{content}</rdf:Description>\n'


def _packet(body: str) -> bytes:
    return (_PROLOG + body + _EPILOG).encode("utf-8")


def _title_of(text: str) -> str:
    return f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{text}</rdf:li></rdf:Alt></dc:title>'


def packets() -> dict[str, bytes]:
    good = _packet(_description("", _TITLE + _PRODUCER))
    unbound = _packet(_description("", _TITLE + _PRODUCER, f'xmlns:pdf="{PDFNS}"'))
    author = "<dc:creator><rdf:Seq><rdf:li>Multi Author</rdf:li></rdf:Seq></dc:creator>"
    keywords = "<pdf:Keywords>multi, keywords</pdf:Keywords>"
    # Every property is readable at the base (the `about=""` Description holds
    # them all); the two `uuid:` Descriptions only repeat values, so normalising
    # the abouts must leave every reported field unchanged.
    multi = _packet(
        _description("uuid:aaa", _TITLE + _PRODUCER)
        + _description("", _TITLE + author + keywords + _PRODUCER)
        + _description("uuid:bbb", keywords)
    )
    # CONFLICTING values across Descriptions: the base reads the `about=""` one
    # ("E ..."), whatever the order; normalising every about would not.
    uuid_side = _description(
        "uuid:aaa", _title_of("U Title") + "<pdf:Producer>U Producer</pdf:Producer>"
    )
    empty_side = _description("", _title_of("E Title") + "<pdf:Producer>E Producer</pdf:Producer>")
    return {
        "conflict_uuid_first": _packet(uuid_side + empty_side),
        "conflict_uuid_last": _packet(empty_side + uuid_side),
        "good": good,
        "uuid_about": _packet(_description(UUID_ABOUT, _TITLE + _PRODUCER)),
        "unparseable": good.replace(b"</x:xmpmeta>", b""),
        "unbound_prefix": unbound,
        "multi_desc": multi,
    }


def _with_packet(single_page: Path, dest: Path, packet: bytes) -> None:
    with pikepdf.Pdf.open(single_page) as pdf:
        pdf.docinfo["/Title"] = "Info Title"
        pdf.Root.Metadata = pdf.make_stream(packet)
        pdf.Root.Metadata["/Type"] = pikepdf.Name.Metadata
        pdf.Root.Metadata["/Subtype"] = pikepdf.Name.XML
        pdf.save(dest, fix_metadata_version=False)


def build_world(root: Path, single_page: Path, xmp_bearing: Path) -> None:
    """Every fixture of the module, into *root*, with its two password files."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "user.pw").write_text(USER + "\n")
    (root / "owner.pw").write_text(OWNER + "\n")
    (root / "wrong.pw").write_text("not-the-password\n")
    for name in ("user.pw", "owner.pw", "wrong.pw"):
        (root / name).chmod(0o600)
    (root / "single_page.pdf").write_bytes(single_page.read_bytes())
    (root / "xmp_bearing.pdf").write_bytes(xmp_bearing.read_bytes())
    for name, packet in packets().items():
        _with_packet(single_page, root / f"{name}.pdf", packet)

    def encrypt(src: str, dest: str, *extra: str) -> None:
        proc = run_cli(
            "encrypt",
            src,
            "--owner-password-file",
            "owner.pw",
            "--user-password-file",
            "user.pw",
            "-O",
            dest,
            *extra,
            stdin="",
            cwd=root,
        )
        assert proc.returncode == 0, proc.stderr

    for base in ("good", "xmp_bearing"):
        encrypt(f"{base}.pdf", f"{base}.aes.pdf")
        encrypt(f"{base}.pdf", f"{base}.rc4.pdf", "--legacy")
    with pikepdf.Pdf.open(root / "good.pdf") as pdf:
        pdf.save(
            root / "good.nometa.pdf",
            encryption=pikepdf.Encryption(owner=OWNER, user=USER, R=6, metadata=False),
        )
    shapes: dict[str, pikepdf.Encryption] = {
        "aes6": pikepdf.Encryption(owner=OWNER, user=USER, R=6),
        "aes4": pikepdf.Encryption(owner=OWNER, user=USER, R=4, aes=True),
        "nometa": pikepdf.Encryption(owner=OWNER, user=USER, R=6, metadata=False),
        "rc4nometa": pikepdf.Encryption(owner=OWNER, user=USER, R=4, aes=False, metadata=False),
    }
    for suffix, encryption in shapes.items():
        with pikepdf.Pdf.open(root / "unparseable.pdf") as pdf:
            pdf.save(
                root / f"unparseable.{suffix}.pdf",
                fix_metadata_version=False,
                encryption=encryption,
            )
    data = (root / "good.pdf").read_bytes()
    (root / "corrupt.pdf").write_bytes(data[: len(data) // 2])
    (root / "adir").mkdir(exist_ok=True)


@pytest.fixture(scope="module")
def world(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pdf155")
    build_world(root, corpus.path("single_page"), corpus.path("xmp_bearing"))
    return root


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cell:
    rc: int
    out: str
    err: str
    fmt: str
    verb: str

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.out.encode("utf-8")).hexdigest()

    def doc(self) -> dict[str, Any]:
        """The parsed envelope; for ``info`` the first document is ``info_doc``."""
        if self.fmt == "table":
            raise AssertionError("a table cell has no parsed document")
        text = self.out if self.fmt == "json" else self.out.splitlines()[0]
        parsed: dict[str, Any] = json.loads(text)
        return parsed

    def info_doc(self) -> dict[str, Any]:
        doc = self.doc()
        if self.fmt == "json":
            first: dict[str, Any] = doc["documents"][0]
            return first
        return doc


_CACHE: dict[tuple[Any, ...], Cell] = {}


def run(
    root: Path,
    verb: str,
    operand: str,
    *,
    fmt: str,
    xmp: bool = False,
    pw: bool | None = None,
    dry: bool = False,
    pwfile: str = "user.pw",
) -> Cell:
    stem = operand.removesuffix(".pdf").split("/")[-1]
    use_pw = (stem in NEEDS_PW) if pw is None else pw
    key = (str(root), verb, operand, fmt, xmp, use_pw, dry, pwfile)
    if key in _CACHE:
        return _CACHE[key]
    args = [verb]
    if dry:
        args.append("--dry-run")
    args.append(operand)
    if xmp:
        args.append("--xmp")
    if use_pw:
        args += ["--password-file", pwfile]
    args += ["-o", fmt]
    proc: subprocess.CompletedProcess[str] = run_cli(*args, stdin="", cwd=root)
    cell = Cell(proc.returncode, proc.stdout, proc.stderr, fmt, verb)
    _CACHE[key] = cell
    return cell


def cmd(root: Path, fixture: str, command: tuple[str, str, bool, str], **kw: Any) -> Cell:
    _label, verb, xmp, fmt = command
    return run(root, verb, f"{fixture}.pdf", fmt=fmt, xmp=xmp, **kw)


def _open(root: Path, fixture: str) -> pikepdf.Pdf:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "a password was provided but none was needed"
        return pikepdf.Pdf.open(root / f"{fixture}.pdf", password=USER)


def oracle_bytes(root: Path, fixture: str) -> bytes | None:
    with _open(root, fixture) as pdf:
        meta = pdf.Root.get("/Metadata")
        if meta is None:
            return None
        return bytes(meta.read_bytes())


def oracle_text(root: Path, fixture: str) -> str:
    data = oracle_bytes(root, fixture)
    assert data is not None, f"{fixture}: the oracle finds no /Root /Metadata"
    return data.decode("utf-8", errors="replace")


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_sha(fixture: str, label: str) -> str:
    key = f"{fixture} :: {label}"
    assert key in BASE_SHA, f"no recorded base literal for {key}"
    return BASE_SHA[key]


def _assert_ok(cell: Cell, what: str) -> None:
    assert cell.rc == 0, f"{what}: rc {cell.rc}, stderr {cell.err!r}"
    if cell.fmt != "table":
        assert cell.doc()["schema_version"] == 1, what


def _xmp_of(cell: Cell) -> Any:
    return cell.doc()["xmp"] if cell.verb == "meta get" else cell.info_doc()["xmp"]


def _all(fixtures: tuple[str, ...], commands: tuple[Any, ...]) -> list[tuple[str, Any]]:
    return [(f, c) for f in fixtures for c in commands]


def _ids(pairs: list[tuple[str, Any]]) -> list[str]:
    return [f"{f}|{c[0]}" for f, c in pairs]


# --------------------------------------------------------------------------- #
# AC2 -- an unparseable packet is reported as present (meta get)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("fixture", "command"), _all(MALFORMED, MG), ids=_ids(_all(MALFORMED, MG)))
def test_ac2_unparseable_packet_is_reported_present(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, fixture, command)
    label, _verb, with_xmp, fmt = command
    _assert_ok(cell, f"{fixture} {label}")
    if fmt == "table":
        assert cell.sha == _base_sha(fixture, label), f"{fixture} {label}: table stdout moved"
    else:
        doc = cell.doc()
        assert doc["xmp"] is None
        assert doc["warnings"] == [W1]
        assert doc["disagreements"] == []
        if with_xmp:
            assert doc["xmp_raw"] == oracle_text(world, fixture)
        else:
            assert doc["xmp_raw"] is None
    assert cell.err == f"warning: {W1}\n", f"{fixture} {label}: stderr {cell.err!r}"


# --------------------------------------------------------------------------- #
# AC3 -- info reports an unparseable packet's text
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("fixture", "command"), _all(MALFORMED, IN), ids=_ids(_all(MALFORMED, IN)))
def test_ac3_info_reports_unparseable_packet_text(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, fixture, command)
    _assert_ok(cell, f"{fixture} {command[0]}")
    assert cell.info_doc()["xmp"] == oracle_text(world, fixture)
    if cell.fmt == "json":
        assert cell.doc()["warnings"] == []
    assert cell.err == ""


# --------------------------------------------------------------------------- #
# AC4 -- a non-empty rdf:about is read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", MG, ids=[c[0] for c in MG])
def test_ac4_non_empty_about_is_read(world: Path, command: tuple[str, str, bool, str]) -> None:
    before = _sha_file(world / "uuid_about.pdf")
    cell = cmd(world, "uuid_about", command)
    control = cmd(world, "good", command)
    label, _verb, with_xmp, fmt = command
    _assert_ok(cell, f"uuid_about {label}")
    assert cell.err == "" and control.err == ""
    if fmt == "table":
        # `path:` is the only line that may differ from the `good` control.
        assert cell.out.splitlines()[1:] == control.out.splitlines()[1:]
        assert "x-default" in cell.out and "XMP Title" in cell.out
    else:
        doc, ref = cell.doc(), control.doc()
        assert doc["xmp"]["title"] == {"x-default": "XMP Title"}
        assert doc["xmp"]["producer"] == "XMP Producer"
        assert doc["xmp"] == ref["xmp"]
        assert doc["disagreements"] == ref["disagreements"]
        assert doc["warnings"] == []
        if with_xmp:
            assert doc["xmp_raw"] == oracle_text(world, "uuid_about")
            assert 'rdf:about="uuid:6ec119a7-' in doc["xmp_raw"]
    assert _sha_file(world / "uuid_about.pdf") == before


@pytest.mark.parametrize("command", IN, ids=[c[0] for c in IN])
def test_ac4_info_on_uuid_about_is_byte_identical_to_base(
    world: Path, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, "uuid_about", command)
    assert cell.sha == _base_sha("uuid_about", command[0])


# --------------------------------------------------------------------------- #
# AC5 -- shapes that were already correct are byte-identical
# --------------------------------------------------------------------------- #

_AC5 = _all(
    ("good", "multi_desc", "conflict_uuid_first", "conflict_uuid_last", "xmp_bearing"), (*MG, *IN)
)


@pytest.mark.parametrize("fixture", ["conflict_uuid_first", "conflict_uuid_last"])
def test_ac5_conflicting_descriptions_read_the_empty_about_one(world: Path, fixture: str) -> None:
    doc = run(world, "meta get", f"{fixture}.pdf", fmt="json").doc()
    assert doc["xmp"]["title"] == {"x-default": "E Title"}
    assert doc["xmp"]["producer"] == "E Producer"
    assert doc["warnings"] == []


@pytest.mark.parametrize(("fixture", "command"), _AC5, ids=_ids(_AC5))
def test_ac5_correct_shapes_byte_identical(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, fixture, command)
    _assert_ok(cell, f"{fixture} {command[0]}")
    assert cell.sha == _base_sha(fixture, command[0])
    assert cell.err == ""


@pytest.mark.parametrize("fixture", ["good", "unparseable"])
@pytest.mark.parametrize("verb", ["meta get", "info"])
def test_ac5_alias_arm_path_is_reported_as_given(world: Path, fixture: str, verb: str) -> None:
    link = world / "link"
    if not link.exists():
        link.symlink_to(world, target_is_directory=True)
    direct = run(world, verb, f"{fixture}.pdf", fmt="json", xmp=verb == "meta get")
    aliased = run(world, verb, f"link/{fixture}.pdf", fmt="json", xmp=verb == "meta get")
    assert direct.rc == aliased.rc == 0

    def strip(cell: Cell) -> dict[str, Any]:
        doc = cell.doc()
        if verb == "info":
            doc = dict(doc["documents"][0])
        return {k: v for k, v in doc.items() if k != "path"}

    def path_of(cell: Cell) -> str:
        doc = cell.doc()
        return str(doc["documents"][0]["path"] if verb == "info" else doc["path"])

    assert strip(direct) == strip(aliased)
    assert path_of(aliased) == f"link/{fixture}.pdf"
    assert path_of(direct) == f"{fixture}.pdf"


# --------------------------------------------------------------------------- #
# AC6 -- every encrypted arm is pinned (99dbb7ff96 does not reproduce)
# --------------------------------------------------------------------------- #

_AC6_FIXTURES = ("good.aes", "xmp_bearing.aes", "good.rc4", "xmp_bearing.rc4", "good.nometa")
_AC6 = _all(_AC6_FIXTURES, (*MG, *IN))


@pytest.mark.parametrize(("fixture", "command"), _AC6, ids=_ids(_AC6))
def test_ac6_encrypted_arms_pinned(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, fixture, command)
    _assert_ok(cell, f"{fixture} {command[0]}")
    assert cell.sha == _base_sha(fixture, command[0])
    assert cell.err == "", f"{fixture} {command[0]}: stderr {cell.err!r}"
    assert "padding" not in cell.err
    if cell.fmt != "table":
        assert _xmp_of(cell) is not None
        if command[2]:
            assert cell.doc()["xmp_raw"] == oracle_text(world, fixture)


# --------------------------------------------------------------------------- #
# AC7 -- an encrypted unparseable packet is never mis-reported
# --------------------------------------------------------------------------- #


def _unparseable_precondition(root: Path, fixture: str) -> None:
    text = oracle_text(root, fixture)
    for name, parse in (
        ("minidom", xml.dom.minidom.parseString),
        ("etree", ET.fromstring),
    ):
        try:
            parse(text.encode("utf-8"))
        except Exception:
            continue
        raise AssertionError(f"{fixture}: the packet PARSES under {name}; the fixture is repaired")
    with _open(root, fixture) as pdf:
        encrypt = pdf.trailer["/Encrypt"]
        want_r, want_em = EU_SHAPE[fixture]
        assert int(encrypt["/R"]) == want_r, f"{fixture}: /R is {encrypt['/R']}, built {want_r}"
        got_em = encrypt.get("/EncryptMetadata")
        got = None if got_em is None else str(bool(got_em)).lower()
        assert got == want_em, f"{fixture}: /EncryptMetadata is {got}, built {want_em}"


BRANCHES: dict[str, str] = {}


def test_ac7_encrypted_unparseable_never_misreported(world: Path) -> None:
    for fixture in EU:
        _unparseable_precondition(world, fixture)
    for fixture in EU:
        expect = oracle_text(world, fixture)
        for command in MG:
            cell = cmd(world, fixture, command)
            label, _verb, with_xmp, fmt = command
            where = f"{fixture} {label}"
            _assert_ok(cell, where)
            if fmt == "table":
                assert cell.err in (f"warning: {W1}\n", f"warning: {W_UNREADABLE}\n"), where
                continue
            doc = cell.doc()
            assert doc["xmp"] is None, where
            assert doc["warnings"] in ([W1], [W_UNREADABLE]), f"{where}: {doc['warnings']!r}"
            if doc["warnings"] == [W1]:
                BRANCHES[fixture] = "i"
                assert doc["xmp_raw"] == (expect if with_xmp else None), where
            else:
                BRANCHES[fixture] = "ii"
                assert doc["xmp_raw"] is None, where
            assert cell.err == f"warning: {doc['warnings'][0]}\n", f"{where}: {cell.err!r}"


# --------------------------------------------------------------------------- #
# AC8 -- the packet-less control is byte-identical
# --------------------------------------------------------------------------- #

_AC8 = _all(("single_page",), (*MG, *IN))


@pytest.mark.parametrize(("fixture", "command"), _AC8, ids=_ids(_AC8))
def test_ac8_packet_less_control_byte_identical(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    cell = cmd(world, fixture, command)
    _assert_ok(cell, f"{fixture} {command[0]}")
    assert cell.sha == _base_sha(fixture, command[0])
    assert cell.err == ""
    if cell.fmt != "table":
        assert _xmp_of(cell) is None
        if command[1] == "meta get":
            assert cell.doc()["warnings"] == []


# --------------------------------------------------------------------------- #
# AC9 -- null means absent: the invariant over the whole population
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", [*PLAIN, *ENCRYPTED])
def test_ac9_null_means_absent(world: Path, fixture: str) -> None:
    cell = run(world, "meta get", f"{fixture}.pdf", fmt="json")
    _assert_ok(cell, fixture)
    doc = cell.doc()
    flagged = any(w.startswith(W_PREFIX) for w in doc["warnings"])
    reads_absent = doc["xmp"] is None and not flagged
    assert reads_absent == (oracle_bytes(world, fixture) is None), (
        f"{fixture}: xmp={doc['xmp']!r} warnings={doc['warnings']!r}"
    )


# --------------------------------------------------------------------------- #
# AC10 -- frozen surface
# --------------------------------------------------------------------------- #


def test_ac10_frozen_surface(world: Path) -> None:
    for rel, want in GOLDEN_SHA.items():
        assert _sha_file(REPO_ROOT / rel) == want, rel
    cells = [
        *_all(("good", "uuid_about", "multi_desc", "xmp_bearing", "single_page"), MG),
        *_all(MALFORMED, MG),
        *_all(("good.aes", "good.rc4", "good.nometa"), MG),
        *_all(EU, MG),
    ]
    for fixture, command in cells:
        cell = cmd(world, fixture, command)
        if cell.fmt in ("json", "ndjson"):
            assert sorted(cell.doc()) == META_GET_KEYS, f"{fixture} {command[0]}"
    for fixture in (*MALFORMED, "uuid_about", "good", "single_page", "good.aes"):
        cell = cmd(world, fixture, IN[0])
        assert sorted(cell.doc()) == INFO_KEYS, fixture


# --------------------------------------------------------------------------- #
# AC11 -- the write side is unchanged
# --------------------------------------------------------------------------- #


def _function_sources(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name in WRITE_SIDE:
            segment = ast.get_source_segment(text, node)
            assert segment is not None
            found[node.name] = hashlib.sha256(segment.encode("utf-8")).hexdigest()
    return found


def test_ac11_write_side_unchanged(world: Path) -> None:
    sources = _function_sources(REPO_ROOT / "src/pdf_tooling/adapters/pypdf_structure.py")
    assert sorted(sources) == sorted(WRITE_SIDE)
    for name in WRITE_SIDE:
        assert sources[name] == WRITE_SIDE_SHA[name], f"{name}: the write side moved"
    out = world / "o.pdf"
    proc = run_cli(
        "meta set",
        "uuid_about.pdf",
        "--title",
        "New",
        "-O",
        "o.pdf",
        "-f",
        "-o",
        "json",
        stdin="",
        cwd=world,
    )
    assert proc.returncode == 0, proc.stderr
    message = (
        "ok (XMP packet left unchanged: the XMP packet describes a non-empty rdf:about; /Info only)"
    )
    reported = message in proc.stdout
    assert reported, proc.stdout
    after = run_cli("meta get", "o.pdf", "-o", "json", stdin="", cwd=world)
    assert after.returncode == 0, after.stderr
    doc = json.loads(after.stdout)
    assert doc["info"]["Title"] == "New"
    assert doc["xmp"]["title"] == {"x-default": "XMP Title"}
    assert any(d["field"] == "title" for d in doc["disagreements"])
    out.unlink()


# --------------------------------------------------------------------------- #
# AC12 -- the (dry, real) matrix
# --------------------------------------------------------------------------- #

_ROWS: Final[tuple[tuple[str, str, bool | None, str], ...]] = (
    # (row, operand, password?, password file)
    ("ok", "good.pdf", None, "user.pw"),
    ("missing", "nope.pdf", None, "user.pw"),
    ("directory", "adir", None, "user.pw"),
    ("truncated", "corrupt.pdf", None, "user.pw"),
    ("aes_no_password", "good.aes.pdf", False, "user.pw"),
    ("aes_wrong_password", "good.aes.pdf", True, "wrong.pw"),
    ("aes_correct_password", "good.aes.pdf", True, "user.pw"),
)
_EXPECT_PAIRS: Final[dict[str, tuple[int, int]]] = {
    "ok": (0, 0),
    "missing": (4, 4),
    "directory": (2, 2),
    "aes_no_password": (6, 6),
    "aes_wrong_password": (6, 6),
    "aes_correct_password": (0, 0),
}


def _scrub(doc: Any) -> Any:
    if isinstance(doc, dict):
        return {k: _scrub(v) for k, v in doc.items() if k not in ("dry_run", "duration_ms")}
    if isinstance(doc, list):
        return [_scrub(v) for v in doc]
    return doc


@pytest.mark.parametrize("verb", ["meta get", "info"])
@pytest.mark.parametrize("row", _ROWS, ids=[r[0] for r in _ROWS])
def test_ac12_exit_table_dry_real(
    world: Path, verb: str, row: tuple[str, str, bool | None, str]
) -> None:
    name, operand, pw, pwfile = row
    dry = run(world, verb, operand, fmt="json", pw=pw, dry=True, pwfile=pwfile)
    real = run(world, verb, operand, fmt="json", pw=pw, dry=False, pwfile=pwfile)
    pair = (dry.rc, real.rc)
    want = _EXPECT_PAIRS.get(name, BASE_EXIT_PAIRS.get(f"{verb} {name}"))
    assert want is not None, f"no recorded base pair for {verb} {name}"
    assert pair == want, f"{verb} {name}: {pair} != base {want}"
    assert dry.err == real.err
    assert _scrub(json.loads(dry.out)) == _scrub(json.loads(real.out))
    if "error" in json.loads(real.out):
        assert dry.out == real.out, f"{verb} {name}: a top-level error envelope differs by mode"


_AC12_FIXTURES: Final[tuple[str, ...]] = (*MALFORMED, "uuid_about", "single_page", "good.aes")
_AC12 = _all(_AC12_FIXTURES, (*MG[:4], *IN))


@pytest.mark.parametrize(("fixture", "command"), _AC12, ids=_ids(_AC12))
def test_ac12_dry_real_matrix(
    world: Path, fixture: str, command: tuple[str, str, bool, str]
) -> None:
    dry = cmd(world, fixture, command, dry=True)
    real = cmd(world, fixture, command, dry=False)
    assert dry.rc == real.rc == 0
    assert dry.err == real.err
    d, r = dry.doc(), real.doc()
    if command[1] == "meta get":
        assert d["dry_run"] is True and r["dry_run"] is False
        for key in ("warnings", "xmp", "xmp_raw", "disagreements"):
            assert d[key] == r[key], f"{fixture} {command[0]}: {key}"
    assert _scrub(d) == _scrub(r)


def test_ac12_decisive_arm_dry_run_still_reads_the_packet(world: Path) -> None:
    cell = run(world, "meta get", "unparseable.pdf", fmt="json", xmp=True, dry=True)
    doc = cell.doc()
    assert doc["dry_run"] is True
    assert doc["xmp_raw"] == oracle_text(world, "unparseable")
    assert doc["warnings"] == [W1]
    assert cell.err == f"warning: {W1}\n"
