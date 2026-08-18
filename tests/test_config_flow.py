"""Config-flow regression tests for helper creation."""

from __future__ import annotations

import asyncio
import inspect
from types import MappingProxyType, SimpleNamespace

from homeassistant.config_entries import ConfigEntries, ConfigSubentry

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
    """Minimal config-entry manager with HA's relevant public API boundary."""

    def __init__(self, gateways, collector=None) -> None:
        self.gateways = gateways if isinstance(gateways, list) else [gateways]
        self.collector = collector
        self.updates = []
        self.added_subentries = []

    def async_entries(self, domain):
        if domain == REOLINK_DOMAIN:
            return self.gateways
        if domain == DOMAIN and self.collector is not None:
            return [self.collector]
        return []

    def async_update_entry(self, entry, *, data):
        """Mirror the relevant public API: no subentries keyword is accepted."""
        self.updates.append((entry, data))
        entry.data = MappingProxyType(data)
        return True

    def async_add_subentry(self, entry, subentry):
        """Mirror Home Assistant's supported subentry-add API."""
        self.added_subentries.append((entry, subentry))
        entry.subentries = MappingProxyType(
            {**dict(entry.subentries), subentry.subentry_id: subentry}
        )
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
        return [
            subentry
            for subentry in self.subentries.values()
            if subentry.subentry_type == subentry_type
        ]


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


def _shared_input(gateway_entry_id, *, timeout=10):
    return {
        CONF_GATEWAY_ENTRY_ID: gateway_entry_id,
        CONF_SUBMIT_KEY: "#",
        CONF_CLEAR_KEY: "*",
        CONF_INPUT_TIMEOUT: timeout,
        CONF_MAX_ATTEMPTS: 5,
        CONF_LOCKOUT_SECONDS: 60,
    }


def _profile_input():
    return {
        CONF_NAME: "Garage",
        CONF_CODE: "5678",
        CONF_CODE_CONFIRM: "5678",
        CONF_NUMBER_MODE: NUMBER_MODE_ALLOW_ALL,
        CONF_ALLOWED_NUMBERS: [],
        CONF_CALL_DIRECTIONS: ["outgoing"],
    }


def test_home_assistant_requires_async_add_subentry_for_subentries():
    """Lock the test double to the real HA 2026.8 public API contract."""
    update_parameters = inspect.signature(ConfigEntries.async_update_entry).parameters

    assert "data" in update_parameters
    assert "subentries" not in update_parameters
    assert hasattr(ConfigEntries, "async_add_subentry")


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


def test_second_helper_adds_profile_via_public_subentry_api(monkeypatch):
    """Exercise the exact page-1 -> page-2 -> OK path that failed in HA."""

    async def run_test() -> None:
        gateway = _gateway()
        collector = FakeCollector(gateway, _existing_profile())
        config_entries = FakeConfigEntries(gateway, collector)
        flow = DTMFCodeConfigFlow()
        flow.hass = FakeHass(config_entries)
        monkeypatch.setattr(
            config_flow_module,
            "hash_code",
            lambda code, _salt: f"hash:{code}",
        )

        page_two = await flow.async_step_user(_shared_input(gateway.entry_id))
        assert page_two["step_id"] == "code"
        assert config_entries.updates == []

        result = await flow.async_step_code(_profile_input())

        assert result["reason"] == "code_profile_added"
        assert result["description_placeholders"] == {"name": "Garage"}
        assert config_entries.updates == []
        assert len(config_entries.added_subentries) == 1
        entry, subentry = config_entries.added_subentries[0]
        assert entry is collector
        assert subentry.title == "Garage"
        assert len(collector.subentries) == 2

    asyncio.run(run_test())


def test_second_helper_updates_shared_settings_before_profile_page(monkeypatch):
    """Changed shared values are saved separately before the subentry is added."""

    async def run_test() -> None:
        gateway = _gateway()
        collector = FakeCollector(gateway, _existing_profile())
        config_entries = FakeConfigEntries(gateway, collector)
        flow = DTMFCodeConfigFlow()
        flow.hass = FakeHass(config_entries)
        monkeypatch.setattr(
            config_flow_module,
            "hash_code",
            lambda code, _salt: f"hash:{code}",
        )

        page_two = await flow.async_step_user(
            _shared_input(gateway.entry_id, timeout=15)
        )

        assert page_two["step_id"] == "code"
        assert len(config_entries.updates) == 1
        updated_entry, updated_data = config_entries.updates[0]
        assert updated_entry is collector
        assert updated_data[CONF_INPUT_TIMEOUT] == 15
        assert config_entries.added_subentries == []

        result = await flow.async_step_code(_profile_input())

        assert result["reason"] == "code_profile_added"
        assert len(config_entries.updates) == 1
        assert len(config_entries.added_subentries) == 1

    asyncio.run(run_test())
