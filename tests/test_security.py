"""Tests for code storage and exact remote-number normalization."""

from __future__ import annotations

import pytest

from custom_components.dtmf_code.security import (
    hash_code,
    hashes_equal,
    new_hash_salt,
    normalize_remote_number,
    valid_code,
)


def test_code_hash_is_salted_and_does_not_contain_plaintext():
    first_salt = new_hash_salt()
    second_salt = new_hash_salt()

    first = hash_code("1234", first_salt)
    same = hash_code("1234", first_salt)
    second = hash_code("1234", second_salt)

    assert hashes_equal(first, same)
    assert not hashes_equal(first, second)
    assert "1234" not in first
    assert first.startswith("pbkdf2_sha256$240000$")


@pytest.mark.parametrize("code", ["0000", "1234", "123456789012"])
def test_valid_code_accepts_only_supported_numeric_codes(code):
    assert valid_code(code)


@pytest.mark.parametrize(
    "code", ["", "123", "1234567890123", "12#4", "+1234", "\uff11\uff12\uff13\uff14"]
)
def test_valid_code_rejects_unsupported_codes(code):
    assert not valid_code(code)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("sip:+49 170-123456@example.org", "+49170123456"),
        ('"Door" <sips:%2B49 (170) 123456@example.org;user=phone>', "+49170123456"),
        ("tel:**620;phone-context=example.org", "**620"),
        ("SIP:Alice@EXAMPLE.ORG", "alice"),
        ("  +49/170.123456  ", "+49170123456"),
        ("", ""),
    ],
)
def test_normalize_remote_number(raw, normalized):
    assert normalize_remote_number(raw) == normalized


def test_number_comparison_cannot_match_by_suffix():
    allowed = {normalize_remote_number("+49170123456")}
    assert normalize_remote_number("0170123456") not in allowed
