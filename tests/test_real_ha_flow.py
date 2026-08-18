"""End-to-end config-flow tests using Home Assistant's real flow managers."""

from __future__ import annotations

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
    SubentryFlowContext,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dtmf_code.const import (
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
    CONF_CLEAR_KEY,
    CONF_CODE,
    CONF_CODE_CONFIRM,
    CONF_GATEWAY_ENTRY_ID,
    CONF_INPUT_TIMEOUT,
    CONF_INSTANCE_ID,
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


def _add_gateway(hass: HomeAssistant) -> MockConfigEntry:
    gateway = MockConfigEntry(
        domain=REOLINK_DOMAIN,
        title="Reolink SIP Gateway",
        unique_id="12345678-1234-5678-9234-567812345678",
        data={},
    )
    gateway.add_to_hass(hass)
    return gateway


def _settings_input(*, timeout: int = 10) -> dict[str, object]:
    return {
        CONF_SUBMIT_KEY: "#",
        CONF_CLEAR_KEY: "*",
        CONF_INPUT_TIMEOUT: timeout,
        CONF_MAX_ATTEMPTS: 5,
        CONF_LOCKOUT_SECONDS: 60,
    }


def _shared_input(gateway: MockConfigEntry) -> dict[str, object]:
    return {
        CONF_GATEWAY_ENTRY_ID: gateway.entry_id,
        **_settings_input(),
    }


def _profile_input(name: str, code: str) -> dict[str, object]:
    return {
        CONF_NAME: name,
        CONF_CODE: code,
        CONF_CODE_CONFIRM: code,
        CONF_NUMBER_MODE: NUMBER_MODE_ALLOW_ALL,
        CONF_ALLOWED_NUMBERS: [],
        CONF_CALL_DIRECTIONS: ["outgoing", "incoming"],
    }


async def _create_first_helper(hass: HomeAssistant, gateway: MockConfigEntry):
    first_page = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert first_page["type"] is FlowResultType.FORM
    assert first_page["step_id"] == "user"

    second_page = await hass.config_entries.flow.async_configure(
        first_page["flow_id"],
        _shared_input(gateway),
    )
    assert second_page["type"] is FlowResultType.FORM
    assert second_page["step_id"] == "code"

    created = await hass.config_entries.flow.async_configure(
        second_page["flow_id"],
        _profile_input("Main", "1234"),
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY

    await hass.async_block_till_done()
    entry = created["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_CODE)) == 1
    return entry


async def test_first_helper_creates_and_loads_in_real_home_assistant(
    hass: HomeAssistant,
) -> None:
    """The first helper must survive real config-entry creation and setup."""
    gateway = _add_gateway(hass)
    await _create_first_helper(hass, gateway)


async def test_helpers_page_options_flow_can_be_opened_and_saved(
    hass: HomeAssistant,
) -> None:
    """The Helpers page must have the options handler its frontend requires."""
    gateway = _add_gateway(hass)
    entry = await _create_first_helper(hass, gateway)

    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        _settings_input(timeout=15),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    await hass.async_block_till_done()
    assert entry.data[CONF_INPUT_TIMEOUT] == 15
    assert entry.state is ConfigEntryState.LOADED


async def test_existing_helper_reconfigure_flow_can_be_opened(
    hass: HomeAssistant,
) -> None:
    """The integration-page reconfigure flow must remain available."""
    gateway = _add_gateway(hass)
    entry = await _create_first_helper(hass, gateway)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_second_helper_creation_via_normal_helper_flow(
    hass: HomeAssistant,
) -> None:
    """Repeating Helper -> DTMF Code must add another profile."""
    gateway = _add_gateway(hass)
    entry = await _create_first_helper(hass, gateway)

    first_page = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    second_page = await hass.config_entries.flow.async_configure(
        first_page["flow_id"],
        _shared_input(gateway),
    )
    result = await hass.config_entries.flow.async_configure(
        second_page["flow_id"],
        _profile_input("Garage", "5678"),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "code_profile_added"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_CODE)) == 2


async def test_add_code_profile_via_real_subentry_flow(
    hass: HomeAssistant,
) -> None:
    """The 'Codeprofil hinzufügen' dialog must complete without an exception."""
    gateway = _add_gateway(hass)
    entry = await _create_first_helper(hass, gateway)

    form = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CODE),
        context=SubentryFlowContext(source=SOURCE_USER),
    )
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        form["flow_id"],
        _profile_input("Garage", "5678"),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_CODE)) == 2


async def test_incomplete_stored_entry_aborts_instead_of_unknown_error(
    hass: HomeAssistant,
) -> None:
    """Stored-data damage must produce a controlled error, not a backend exception."""
    gateway = _add_gateway(hass)
    broken = MockConfigEntry(
        domain=DOMAIN,
        title="DTMF Code - Reolink SIP Gateway",
        unique_id=gateway.unique_id,
        data={
            CONF_GATEWAY_ENTRY_ID: gateway.entry_id,
            CONF_INSTANCE_ID: gateway.unique_id,
            **_settings_input(),
        },
    )
    broken.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (broken.entry_id, SUBENTRY_TYPE_CODE),
        context=SubentryFlowContext(source=SOURCE_USER),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "stored_configuration_invalid"
