"""AC3 — ``Secret`` cannot be printed, serialized or pickled.

The cheapest tests in PDF-13 and the ones that kill the whole leak class:
**every** path in `PLAN.md` §5.7's threat model is repr-driven — log
formatting, the JSON encoder, traceback frame locals, ``%s`` interpolation —
so a type that cannot be rendered cannot travel down any of them.

Each rendering is asserted twice: once that it EQUALS the placeholder, and
once that it does not CONTAIN the sentinel. The second assertion is the one
that would survive somebody "improving" the placeholder into
``f"<redacted len={len(value)}>"``.
"""

from __future__ import annotations

import json
import pickle

import pytest

from pdf_toolkit.secret import REDACTED, Secret, SecretClearedError

PW_SENTINEL = "Sentinel-PW-7f3a91c4e85b4d02"
PW_SENTINEL_UNICODE = "Señal-PW-Ünïcøde-7f3a91c4"


@pytest.mark.parametrize("value", [PW_SENTINEL, PW_SENTINEL_UNICODE])
def test_ac3_every_rendering_is_the_placeholder_and_carries_no_value(value: str) -> None:
    secret = Secret(value, source="file:/tmp/pw")
    renderings = {
        "repr()": repr(secret),
        "str()": str(secret),
        "f-string": f"{secret}",
        "str.format": "{}".format(secret),  # noqa: UP032 - the point IS the format path
        "%s": "%s" % secret,  # noqa: UP031 - the point IS the old interpolation path
        "format() with a spec": format(secret, ">40"),
        "f-string with a spec": f"{secret:>40}",
    }
    for label, rendered in renderings.items():
        assert rendered == REDACTED, f"{label} did not redact"
        assert value not in rendered, f"{label} leaked the value"


def test_ac3_a_format_spec_cannot_transform_its_way_toward_the_value() -> None:
    """``__format__`` ignores the spec on purpose: padding or truncating a
    redacted marker is harmless, but honouring a spec at all is the first step
    toward honouring one that reveals."""
    secret = Secret(PW_SENTINEL, source="prompt")
    assert f"{secret:.4}" == REDACTED
    assert f"{secret:^80}" == REDACTED


def test_ac3_json_refuses_to_serialize_a_secret() -> None:
    with pytest.raises(TypeError):
        json.dumps(Secret(PW_SENTINEL, source="prompt"))


def test_ac3_json_refuses_a_secret_nested_in_a_payload() -> None:
    """The realistic shape: a secret that slipped into an ``OperationPlan``'s
    ``options`` dict. The encoder must refuse the whole payload rather than
    render the value."""
    with pytest.raises(TypeError):
        json.dumps({"options": {"password": Secret(PW_SENTINEL, source="prompt")}})


def test_ac3_pickle_refuses_a_secret() -> None:
    with pytest.raises(TypeError):
        pickle.dumps(Secret(PW_SENTINEL, source="prompt"))


def test_ac3_clear_zeroes_the_buffer_and_reveal_then_raises() -> None:
    secret = Secret(PW_SENTINEL, source="stdin")
    assert secret.reveal() == PW_SENTINEL
    secret.clear()
    assert secret.cleared is True
    with pytest.raises(SecretClearedError):
        secret.reveal()


def test_ac3_reveal_round_trips_unicode() -> None:
    assert Secret(PW_SENTINEL_UNICODE, source="prompt").reveal() == PW_SENTINEL_UNICODE


def test_ac3_bytes_and_str_construct_the_same_secret() -> None:
    assert Secret(PW_SENTINEL, source="a") == Secret(PW_SENTINEL.encode(), source="b")


def test_ac3_equality_is_by_value_and_notimplemented_for_anything_else() -> None:
    assert Secret("a", source="x") == Secret("a", source="y")
    assert Secret("a", source="x") != Secret("b", source="x")
    assert Secret("a", source="x").__eq__("a") is NotImplemented
    assert Secret("a", source="x") != "a"


def test_ac3_a_cleared_secret_never_compares_equal() -> None:
    cleared = Secret("a", source="x")
    cleared.clear()
    assert cleared != Secret("a", source="x")


def test_ac3_a_secret_is_unhashable_so_it_cannot_land_in_a_printable_set() -> None:
    with pytest.raises(TypeError):
        {Secret("a", source="x")}  # noqa: B018 - constructing the set IS the assertion


def test_ac3_the_source_label_is_the_one_thing_that_is_safe_to_read() -> None:
    secret = Secret(PW_SENTINEL, source="env:PDF_TOOLKIT_PASSWORD")
    assert secret.source == "env:PDF_TOOLKIT_PASSWORD"
    assert PW_SENTINEL not in secret.source
