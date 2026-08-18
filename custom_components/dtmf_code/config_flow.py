"""Config, options and code-subentry flows for DTMF Code."""

from __future__ import annotations

import hmac
import logging
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CALL_DIRECTION_OUTGOING,
    CALL_DIRECTIONS,
    CODE_MAX_LENGTH,
    CODE_MIN_LENGTH,
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
    CONF_CLEAR_KEY,
    CONF_CODE,
    CONF_CODE_CONFIRM,
    CONF_CODE_HASH,
    CONF_GATEWAY_ENTRY_ID,
    CONF_HASH_SALT,
    CONF_INPUT_TIMEOUT,
    CONF_INSTANCE_ID,
    CONF_LOCKOUT_SECONDS,
    CONF_MAX_ATTEMPTS,
    CONF_NAME,
    CONF_NUMBER_MODE,
    CONF_SUBMIT_KEY,
    CONTROL_KEYS,
    DEFAULT_CLEAR_KEY,
    DEFAULT_INPUT_TIMEOUT,
    DEFAULT_LOCKOUT_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_SUBMIT_KEY,
    DOMAIN,
    NUMBER_MODE_ALLOW_ALL,
    NUMBER_MODE_ALLOW_LIST,
    NUMBER_MODES,
    REOLINK_DOMAIN,
    SUBENTRY_TYPE_CODE,
)
from .security import hash_code, new_hash_salt, normalize_remote_number, valid_code

_LOGGER = logging.getLogger(__name__)

_SHARED_KEYS = (
    CONF_SUBMIT_KEY,
    CONF_CLEAR_KEY,
    CONF_INPUT_TIMEOUT,
    CONF_MAX_ATTEMPTS,
    CONF_LOCKOUT_SECONDS,
)
_REQUIRED_PROFILE_KEYS = (
    CONF_CODE_HASH,
    CONF_NUMBER_MODE,
    CONF_ALLOWED_NUMBERS,
    CONF_CALL_DIRECTIONS,
)


class DTMFCodeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one shared DTMF collector and repeatable code profiles."""

    VERSION = 1
    MINOR_VERSION = 5

    def __init__(self) -> None:
        """Initialize one helper creation flow."""
        self._gateway_entry: ConfigEntry | None = None
        self._collector_entry: ConfigEntry | None = None
        self._shared_settings: dict[str, str | int] | None = None
        self._new_hash_salt: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DTMFCodeOptionsFlow:
        """Return the options flow used by Home Assistant's Helpers page."""
        return DTMFCodeOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the repeatable child configurations."""
        return {SUBENTRY_TYPE_CODE: CodeSubentryFlowHandler}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select the gateway and configure settings shared by all its codes."""
        gateways = self._available_gateways()
        if not gateways:
            return self.async_abort(reason="no_gateways")

        errors: dict[str, str] = {}
        if user_input is not None:
            gateway_entry = gateways.get(str(user_input[CONF_GATEWAY_ENTRY_ID]))
            if gateway_entry is None or gateway_entry.unique_id is None:
                errors["base"] = "gateway_not_found"
            elif user_input[CONF_SUBMIT_KEY] == user_input[CONF_CLEAR_KEY]:
                errors["base"] = "control_keys_equal"
            else:
                self._select_gateway(gateway_entry)
                self._shared_settings = _global_settings(user_input)
                if self._collector_entry is None:
                    self._new_hash_salt = new_hash_salt()
                else:
                    self._update_existing_shared_settings(self._collector_entry)
                return await self.async_step_code()

        defaults = user_input or self._initial_user_defaults(gateways)
        return self.async_show_form(
            step_id="user",
            data_schema=self._gateway_schema(gateways, defaults),
            errors=errors,
        )

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create one code profile and its own event entity."""
        if self._gateway_entry is None or self._shared_settings is None:
            return await self.async_step_user()

        collector = self._collector_for_gateway(self._gateway_entry)
        self._collector_entry = collector
        if collector is not None:
            stored_error = _stored_configuration_error(collector)
            if stored_error is not None:
                return self.async_abort(reason=stored_error)
            hash_salt = str(collector.data[CONF_HASH_SALT])
        else:
            hash_salt = self._new_hash_salt or new_hash_salt()
        self._new_hash_salt = hash_salt

        errors: dict[str, str] = {}
        if user_input is not None:
            subentries = (
                collector.get_subentries_of_type(SUBENTRY_TYPE_CODE)
                if collector is not None
                else []
            )
            data, title, error = await _async_validate_profile(
                self.hass,
                hash_salt,
                subentries,
                user_input,
            )
            if error is None:
                if collector is not None:
                    self._add_profile_to_existing_collector(collector, data, title)
                    return self.async_abort(
                        reason="code_profile_added",
                        description_placeholders={"name": title},
                    )

                gateway = self._gateway_entry
                if gateway.unique_id is None:
                    return self.async_abort(reason="gateway_not_found")
                await self.async_set_unique_id(gateway.unique_id)
                self._abort_if_unique_id_configured()
                parent_data = {
                    CONF_GATEWAY_ENTRY_ID: gateway.entry_id,
                    CONF_INSTANCE_ID: gateway.unique_id,
                    CONF_HASH_SALT: hash_salt,
                    **self._shared_settings,
                }
                return self.async_create_entry(
                    title=f"DTMF Code - {gateway.title}",
                    data=parent_data,
                    subentries=[
                        {
                            "data": data,
                            "subentry_type": SUBENTRY_TYPE_CODE,
                            "title": title,
                            "unique_id": str(uuid4()),
                        }
                    ],
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="code",
            data_schema=_profile_schema(user_input, code_required=True),
            errors=errors,
            description_placeholders={
                "min_length": str(CODE_MIN_LENGTH),
                "max_length": str(CODE_MAX_LENGTH),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update shared keypad behavior without changing gateway identity."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_SUBMIT_KEY] == user_input[CONF_CLEAR_KEY]:
                errors["base"] = "control_keys_equal"
            else:
                await self.async_set_unique_id(entry.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_and_abort(
                    entry,
                    data_updates=_global_settings(user_input),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_global_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    def _select_gateway(self, gateway_entry: ConfigEntry) -> None:
        """Remember a gateway and its existing collector, if any."""
        self._gateway_entry = gateway_entry
        self._collector_entry = self._collector_for_gateway(gateway_entry)

    def _collector_for_gateway(self, gateway_entry: ConfigEntry) -> ConfigEntry | None:
        """Return the single collector already attached to this gateway."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_GATEWAY_ENTRY_ID) == gateway_entry.entry_id:
                return entry
            if gateway_entry.unique_id and entry.unique_id == gateway_entry.unique_id:
                return entry
        return None

    def _available_gateways(self) -> dict[str, ConfigEntry]:
        """Return selectable Reolink SIP Gateway config entries."""
        return {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries(REOLINK_DOMAIN)
            if entry.unique_id
        }

    def _initial_user_defaults(self, gateways: dict[str, ConfigEntry]) -> dict[str, Any]:
        """Use the first gateway and its existing shared settings as defaults."""
        first_entry_id = next(iter(gateways))
        first_gateway = gateways[first_entry_id]
        collector = self._collector_for_gateway(first_gateway)
        defaults = dict(collector.data) if collector is not None else {}
        defaults[CONF_GATEWAY_ENTRY_ID] = first_entry_id
        return defaults

    def _update_existing_shared_settings(self, collector: ConfigEntry) -> None:
        """Persist changed shared settings before opening the profile page."""
        if self._shared_settings is None:
            raise RuntimeError("shared DTMF settings are not initialized")

        updated_data = {**dict(collector.data), **self._shared_settings}
        if updated_data != dict(collector.data):
            self.hass.config_entries.async_update_entry(collector, data=updated_data)

    def _add_profile_to_existing_collector(
        self,
        collector: ConfigEntry,
        profile_data: dict[str, Any],
        title: str,
    ) -> None:
        """Add one code profile through Home Assistant's public subentry API."""
        subentry = ConfigSubentry(
            data=MappingProxyType(profile_data),
            subentry_type=SUBENTRY_TYPE_CODE,
            title=title,
            unique_id=str(uuid4()),
        )
        self.hass.config_entries.async_add_subentry(collector, subentry)

    def _gateway_schema(
        self,
        gateways: dict[str, ConfigEntry],
        defaults: dict[str, Any],
    ) -> vol.Schema:
        """Build the first page: gateway plus shared keypad settings."""
        gateway_options = [
            {"value": entry_id, "label": entry.title} for entry_id, entry in gateways.items()
        ]
        gateway_default = defaults.get(CONF_GATEWAY_ENTRY_ID, gateway_options[0]["value"])
        base = _global_schema(defaults).schema
        return vol.Schema(
            {
                vol.Required(CONF_GATEWAY_ENTRY_ID, default=gateway_default): SelectSelector(
                    SelectSelectorConfig(
                        options=gateway_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                **base,
            }
        )


class DTMFCodeOptionsFlow(OptionsFlow):
    """Edit shared DTMF keypad settings from the Helpers page."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle helper settings."""
        entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_SUBMIT_KEY] == user_input[CONF_CLEAR_KEY]:
                errors["base"] = "control_keys_equal"
            else:
                updated_data = {**dict(entry.data), **_global_settings(user_input)}
                self.hass.config_entries.async_update_entry(entry, data=updated_data)
                # Keep the options object unchanged. Shared settings intentionally
                # remain in ConfigEntry.data for backward compatibility.
                return self.async_create_entry(data=dict(entry.options))

        return self.async_show_form(
            step_id="init",
            data_schema=_global_schema(user_input or dict(entry.data)),
            errors=errors,
        )


class CodeSubentryFlowHandler(ConfigSubentryFlow):
    """Create and reconfigure named code profiles from the integration page."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add one named code profile."""
        entry = self._get_entry()
        stored_error = _stored_configuration_error(entry)
        if stored_error is not None:
            return self.async_abort(reason=stored_error)

        errors: dict[str, str] = {}
        if user_input is not None:
            data, title, error = await _async_validate_profile(
                self.hass,
                str(entry.data[CONF_HASH_SALT]),
                entry.get_subentries_of_type(SUBENTRY_TYPE_CODE),
                user_input,
            )
            if error is None:
                return self.async_create_entry(
                    title=title,
                    data=data,
                    unique_id=str(uuid4()),
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_profile_schema(user_input, code_required=True),
            errors=errors,
            description_placeholders={
                "min_length": str(CODE_MIN_LENGTH),
                "max_length": str(CODE_MAX_LENGTH),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change profile policy and optionally replace its code."""
        subentry = self._get_reconfigure_subentry()
        entry = self._get_entry()
        stored_error = _stored_configuration_error(entry)
        if stored_error is not None:
            return self.async_abort(reason=stored_error)

        defaults = {
            CONF_NAME: subentry.title,
            CONF_NUMBER_MODE: subentry.data[CONF_NUMBER_MODE],
            CONF_ALLOWED_NUMBERS: list(subentry.data[CONF_ALLOWED_NUMBERS]),
            CONF_CALL_DIRECTIONS: list(subentry.data[CONF_CALL_DIRECTIONS]),
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            data, title, error = await _async_validate_profile(
                self.hass,
                str(entry.data[CONF_HASH_SALT]),
                entry.get_subentries_of_type(SUBENTRY_TYPE_CODE),
                user_input,
                existing=subentry,
            )
            if error is None:
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=title,
                    data=data,
                )
            errors["base"] = error
            defaults.update(user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_profile_schema(defaults, code_required=False),
            errors=errors,
            description_placeholders={
                "min_length": str(CODE_MIN_LENGTH),
                "max_length": str(CODE_MAX_LENGTH),
            },
        )


def _stored_configuration_error(entry: ConfigEntry) -> str | None:
    """Return an abort reason instead of raising on an incompatible stored entry."""
    for key in (CONF_INSTANCE_ID, CONF_HASH_SALT, *_SHARED_KEYS):
        if key not in entry.data:
            _LOGGER.error(
                "Stored DTMF Code entry %s is missing required key %s",
                entry.entry_id,
                key,
            )
            return "stored_configuration_invalid"

    hash_salt = entry.data.get(CONF_HASH_SALT)
    if not isinstance(hash_salt, str) or not hash_salt:
        _LOGGER.error("Stored DTMF Code entry %s has an invalid hash salt", entry.entry_id)
        return "stored_configuration_invalid"

    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_CODE):
        missing = [key for key in _REQUIRED_PROFILE_KEYS if key not in subentry.data]
        if missing:
            _LOGGER.error(
                "Stored DTMF Code profile %s is missing required keys: %s",
                subentry.subentry_id,
                ", ".join(missing),
            )
            return "stored_configuration_invalid"

    return None


async def _async_validate_profile(
    hass: HomeAssistant,
    hash_salt: str,
    subentries: list[ConfigSubentry],
    user_input: dict[str, Any],
    existing: ConfigSubentry | None = None,
) -> tuple[dict[str, Any], str, str | None]:
    """Validate and normalize one code profile."""
    title = str(user_input[CONF_NAME]).strip()
    if not title or len(title) > 64:
        return {}, title, "invalid_name"
    for subentry in subentries:
        if existing is not None and subentry.subentry_id == existing.subentry_id:
            continue
        # Profile names are human-readable Unicode labels, not secrets.  A
        # normal case-insensitive Unicode comparison is both correct and safe;
        # hmac.compare_digest(str, str) deliberately rejects non-ASCII text.
        if subentry.title.casefold() == title.casefold():
            return {}, title, "duplicate_name"

    code = str(user_input.get(CONF_CODE, ""))
    confirmation = str(user_input.get(CONF_CODE_CONFIRM, ""))
    if existing is None or code or confirmation:
        if not valid_code(code):
            return {}, title, "invalid_code"
        # This is input validation in an authenticated configuration flow, not
        # a secret verification boundary. A regular comparison also handles a
        # mistyped non-ASCII confirmation without raising TypeError.
        if code != confirmation:
            return {}, title, "code_mismatch"
        try:
            code_hash = await hass.async_add_executor_job(hash_code, code, hash_salt)
        except (TypeError, ValueError):
            _LOGGER.exception("Stored DTMF Code hash salt is invalid")
            return {}, title, "stored_configuration_invalid"
        for subentry in subentries:
            if existing is not None and subentry.subentry_id == existing.subentry_id:
                continue
            if hmac.compare_digest(str(subentry.data[CONF_CODE_HASH]), code_hash):
                return {}, title, "duplicate_code"
    else:
        code_hash = str(existing.data[CONF_CODE_HASH])

    number_mode = str(user_input[CONF_NUMBER_MODE])
    if number_mode not in NUMBER_MODES:
        return {}, title, "invalid_number_mode"
    normalized_numbers: list[str] = []
    for raw_number in user_input.get(CONF_ALLOWED_NUMBERS, []):
        normalized = normalize_remote_number(str(raw_number))
        if not normalized:
            return {}, title, "invalid_number"
        if normalized not in normalized_numbers:
            normalized_numbers.append(normalized)
    if number_mode == NUMBER_MODE_ALLOW_LIST and not normalized_numbers:
        return {}, title, "numbers_required"
    if number_mode == NUMBER_MODE_ALLOW_ALL:
        normalized_numbers.clear()

    directions = [str(value) for value in user_input[CONF_CALL_DIRECTIONS]]
    if not directions or any(value not in CALL_DIRECTIONS for value in directions):
        return {}, title, "directions_required"

    return (
        {
            CONF_CODE_HASH: code_hash,
            CONF_NUMBER_MODE: number_mode,
            CONF_ALLOWED_NUMBERS: normalized_numbers,
            CONF_CALL_DIRECTIONS: list(dict.fromkeys(directions)),
        },
        title,
        None,
    )


def _global_settings(user_input: dict[str, Any]) -> dict[str, str | int]:
    """Normalize settings shared by all code profiles."""
    return {
        CONF_SUBMIT_KEY: str(user_input[CONF_SUBMIT_KEY]),
        CONF_CLEAR_KEY: str(user_input[CONF_CLEAR_KEY]),
        CONF_INPUT_TIMEOUT: int(user_input[CONF_INPUT_TIMEOUT]),
        CONF_MAX_ATTEMPTS: int(user_input[CONF_MAX_ATTEMPTS]),
        CONF_LOCKOUT_SECONDS: int(user_input[CONF_LOCKOUT_SECONDS]),
    }


def _global_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the shared keypad-settings schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SUBMIT_KEY,
                default=defaults.get(CONF_SUBMIT_KEY, DEFAULT_SUBMIT_KEY),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(CONTROL_KEYS),
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_CLEAR_KEY,
                default=defaults.get(CONF_CLEAR_KEY, DEFAULT_CLEAR_KEY),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(CONTROL_KEYS),
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_INPUT_TIMEOUT,
                default=defaults.get(CONF_INPUT_TIMEOUT, DEFAULT_INPUT_TIMEOUT),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=3,
                    max=60,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                CONF_MAX_ATTEMPTS,
                default=defaults.get(CONF_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=10,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_LOCKOUT_SECONDS,
                default=defaults.get(CONF_LOCKOUT_SECONDS, DEFAULT_LOCKOUT_SECONDS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=10,
                    max=3600,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
    )


def _profile_schema(defaults: dict[str, Any] | None, *, code_required: bool) -> vol.Schema:
    """Build the code-profile schema shared by both flow entry points."""
    values = defaults or {}
    schema: dict[vol.Marker, Any] = {
        vol.Required(CONF_NAME, default=values.get(CONF_NAME, "")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        )
    }
    password_selector = TextSelector(
        TextSelectorConfig(
            type=TextSelectorType.PASSWORD,
            autocomplete="new-password",
        )
    )
    if code_required:
        schema[vol.Required(CONF_CODE)] = password_selector
        schema[vol.Required(CONF_CODE_CONFIRM)] = password_selector
    else:
        schema[vol.Optional(CONF_CODE)] = password_selector
        schema[vol.Optional(CONF_CODE_CONFIRM)] = password_selector

    schema.update(
        {
            vol.Required(
                CONF_NUMBER_MODE,
                default=values.get(CONF_NUMBER_MODE, NUMBER_MODE_ALLOW_LIST),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(NUMBER_MODES),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="number_mode",
                )
            ),
            vol.Optional(
                CONF_ALLOWED_NUMBERS,
                default=values.get(CONF_ALLOWED_NUMBERS, []),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEL, multiple=True)),
            vol.Required(
                CONF_CALL_DIRECTIONS,
                default=values.get(CONF_CALL_DIRECTIONS, [CALL_DIRECTION_OUTGOING]),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(CALL_DIRECTIONS),
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="call_direction",
                )
            ),
        }
    )
    return vol.Schema(schema)