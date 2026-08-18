"""Regression tests for Unicode-safe profile validation."""

from __future__ import annotations

import asyncio
from types import MappingProxyType

from homeassistant.config_entries import ConfigSubentry

from custom_components.dtmf_code import config_flow as config_flow_module
from custom_components.dtmf_code.config_flow import _async_validate_profile
from custom_components.dtmf_code.const import (
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
    CONF_CODE,
    CONF_CODE_CONFIRM,
    CONF_CODE_HASH,
    CONF_NAME,
    CONF_NUMBER_MODE,
    NUMBER_MODE_ALLOW_ALL,
    SUBENTRY_TYPE_CODE,
)


class FakeHass:
    """Minimal executor surface required by profile validation."""

    async def async_add_executor_job(self, target, *args):
        await asyncio.sleep(0)
        return target(*args)


def _profile(title: str = "Haustür") -> ConfigSubentry:
    return ConfigSubentry(
        data=MappingProxyType(
            {
                CONF_CODE_HASH: "hash:1234",
                CONF_NUMBER_MODE: NUMBER_MODE_ALLOW_ALL,
                CONF_ALLOWED_NUMBERS: [],
                CONF_CALL_DIRECTIONS: ["outgoing"],
            }
        ),
        subentry_type=SUBENTRY_TYPE_CODE,
        title=title,
        unique_id="profile-main",
    )


def _input(name: str, code: str = "1234567", confirmation: str | None = None):
    return {
        CONF_NAME: name,
        CONF_CODE: code,
        CONF_CODE_CONFIRM: code if confirmation is None else confirmation,
        CONF_NUMBER_MODE: NUMBER_MODE_ALLOW_ALL,
        CONF_ALLOWED_NUMBERS: [],
        CONF_CALL_DIRECTIONS: ["outgoing"],
    }


def test_existing_unicode_profile_name_allows_different_second_profile(monkeypatch):
    """An existing name such as 'Haustür' must not crash second-profile creation."""

    async def run_test() -> None:
        monkeypatch.setattr(
            config_flow_module,
            "hash_code",
            lambda code, _salt: f"hash:{code}",
        )

        data, title, error = await _async_validate_profile(
            FakeHass(),
            "test-salt",
            [_profile()],
            _input("testdtmf"),
        )

        assert error is None
        assert title == "testdtmf"
        assert data[CONF_CODE_HASH] == "hash:1234567"

    asyncio.run(run_test())


def test_unicode_profile_names_are_compared_case_insensitively():
    """Unicode labels still participate in duplicate-name detection."""

    async def run_test() -> None:
        _data, _title, error = await _async_validate_profile(
            FakeHass(),
            "test-salt",
            [_profile()],
            _input("HAUSTÜR"),
        )

        assert error == "duplicate_name"

    asyncio.run(run_test())


def test_non_ascii_code_confirmation_returns_validation_error_not_type_error():
    """A mistyped Unicode confirmation must not escape as a Python TypeError."""

    async def run_test() -> None:
        _data, _title, error = await _async_validate_profile(
            FakeHass(),
            "test-salt",
            [],
            _input("Garage", code="1234567", confirmation="12345ä7"),
        )

        assert error == "code_mismatch"

    asyncio.run(run_test())
