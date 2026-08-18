"""Config-flow regression tests for helper creation."""

from __future__ import annotations

import asyncio
from types import MappingProxyType, SimpleNamespace

from homeassistant.config_entries import ConfigSubentry

from custom_components.dtmf_code import config_flow as config_flow_module
from custom_components.dtmf_code.config_flow import DTMFCodeConfigFlow
from custom_components.dtmf_code.const import (
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
    CONF_CLEAR_KEY,
    CONF_CODE,
    CONF_CODE_CONFIRM,
    CONF_CODE_HASH,
    CONF_GATEWAY_ENTRY_ID,
    CONF_HASH_SALT,
    CONF_INPUT_TIMEOUT,
    CONF_LOCKOUT_SECONDS,
    CONF_MAX_ATTEMPTS,
    CONF_NAME,
    CONF_NUMBER_MODE,
    CONF_SUBMIT_KEY,
    DOMAIN,
    NUMBER_MODE_ALLOW_ALL,
    REOLINK_DOMAIN,
    SUBENTRY_TYPE_CODE,
)


class FakeConfigEntries:
    """Minimal config-entry manager for flow tests."""

    def __init__(self, gateways, collector=None) -> None:
        self.gateways = gateways if isinstance(gateways, list) else [gateways]
        self.collector = collector
        self.updates = []

    def async_entries(self, domain):
        if domain == REOLINK_DOMAIN:
            return self.gateways
        if domain == DOMAIN and self.collector is not None:
            return [self.collector]
        return []

    def async_update_entry(self, entry, **kwargs):
        self.updates.append((entry, kwargs))
        return True


class FakeHass:
    """Minimal Home Assistant surface required by the flow."""

    def __init__(self, config_entries) -> None:
        self.config_entries = config_entries

    async def async_add_executor_job(self, target, *args):
        await asyncio.sleep(0)
        return target(*args)


class FakeCollector:
    """Small ConfigEntry-compatible collector."""

    def __init__(self, gateway, profile) -> None:
        self.entry_id = "collector-1"
        self.unique_id = gateway.unique_id
        self.title = "DTMF Code - Front Door"
        self.data = MappingProxyType(
            {
                CONF_GATEWAY_ENTRY_ID: gateway.entry_id,
                CONF_HASH_SALT: "test-salt",
                CONF_SUBMIT_KEY: "#",
                CONF_CLEAR_KEY: "*",
                CONF_INPUT_TIMEOUT: 10,
                CONF_MAX_ATTEMPTS: 5,
                CONF_LOCKOUT_SECONDS: 60,
            }
        )
        self.subentries = MappingProxyType({profile.subentry_id: profile})

    def get_subentries_of_type(self, subentry_type):
        assert subentry_type == SUBENTRY_TYPE_CODE
        return list(self.subentries.values())


def _gateway(number=1):
    return SimpleNamespace(
        entry_id=f"gateway-{number}",
        unique_id=f"12345678-1234-5678-9234-56781234567{number}",
        title=f"Front Door {number}",
    )


def _existing_profile():
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
        title="Main",
        unique_id="profile-main",
    )


def _shared_input(gateway_entry_id):
    return {
        CONF_GATEWAY_ENTRY_ID: gateway_entry_id,
        CONF_SUBMIT_KEY: "#",
        CONF_CLEAR_KEY: "*",
        CONF_INPUT_TIMEOUT: 10,
        CONF_MAX_ATTEMPTS: 5,
        CONF_LOCKOUT_SECONDS: 60,
    }


def test_single_gateway_is_still_selectable_on_first_page():
    async def run_test() -> None:
        gateway = _gateway()
        flow = DTMFCodeConfigFlow()
        flow.hass = FakeHass(FakeConfigEntries(gateway))

        result = await flow.async_step_user()

        assert result["step_id"] == "user"
        fields = {marker.schema for marker in result["data_schema"].schema}
        assert fields == {
            CONF_GATEWAY_ENTRY_ID,
            CONF_SUBMIT_KEY,
            CONF_CLEAR_KEY,
            CONF_INPUT_TIMEOUT,
            CONF_MAX_ATTEMPTS,
            CONF_LOCKOUT_SECONDS,
        }

    asyncio.run(run_test())


def test_multiple_gateways_can_select_the_second_gateway():
    async def run_test() -> None:
        first_gateway = _gateway(1)
        second_gateway = _gateway(2)
        flow = DTMFCodeConfigFlow()
        flow.hass = FakeHass(FakeConfigEntries([first_gateway, second_gateway]))

        initial = await flow.async_step_user()
        assert initial["step_id"] == "user"

        result = await flow.async_step_user(_shared_input(second_gateway.entry_id))

        assert result["step_id"] == "code"
        assert flow._gateway_entry is second_gateway

    asyncio.run(run_test())


def test_second_helper_adds_profile_with_one_atomic_entry_update(monkeypatch):
    async def run_test() -> None:
        gateway = _gateway()
        collector = FakeCollector(gateway, _existing_profile())
        config_entries = FakeConfigEntries(gateway, collector)
        flow = DTMFCodeConfigFlow()
        flow.hass = FakeHass(config_entries)
        flow._gateway_entry = gateway
        flow._collector_entry = collector
        flow._shared_settings = {
            CONF_SUBMIT_KEY: "#",
            CONF_CLEAR_KEY: "*",
            CONF_INPUT_TIMEOUT: 10,
            CONF_MAX_ATTEMPTS: 5,
            CONF_LOCKOUT_SECONDS: 60,
        }
        monkeypatch.setattr(
            config_flow_module,
            "hash_code",
            lambda code, _salt: f"hash:{code}",
        )

        result = await flow.async_step_code(
            {
                CONF_NAME: "Garage",
                CONF_CODE: "5678",
                CONF_CODE_CONFIRM: "5678",
                CONF_NUMBER_MODE: NUMBER_MODE_ALLOW_ALL,
                CONF_ALLOWED_NUMBERS: [],
                CONF_CALL_DIRECTIONS: ["outgoing"],
            }
        )

        assert result["reason"] == "code_profile_added"
        assert result["description_placeholders"] == {"name": "Garage"}
        assert len(config_entries.updates) == 1
        entry, update = config_entries.updates[0]
        assert entry is collector
        assert len(update["subentries"]) == 2
        assert update["data"][CONF_SUBMIT_KEY] == "#"
        assert update["data"][CONF_CLEAR_KEY] == "*"

    asyncio.run(run_test())
