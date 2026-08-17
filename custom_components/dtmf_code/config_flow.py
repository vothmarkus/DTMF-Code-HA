"""Config and code-subentry flows for DTMF Code."""

from __future__ import annotations

import hmac
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    FlowType,
    SubentryFlowContext,
    SubentryFlowResult,
)
from homeassistant.core import callback
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


class DTMFCodeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a DTMF event source and its shared input policy."""

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the repeatable child configurations."""
        return {SUBENTRY_TYPE_CODE: CodeSubentryFlowHandler}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select one Reolink gateway and create its code collector."""
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
                await self.async_set_unique_id(gateway_entry.unique_id)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_GATEWAY_ENTRY_ID: gateway_entry.entry_id,
                    CONF_INSTANCE_ID: gateway_entry.unique_id,
                    CONF_HASH_SALT: new_hash_salt(),
                    **self._global_settings(user_input),
                }
                return self.async_create_entry(
                    title=f"DTMF Code - {gateway_entry.title}", data=data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._gateway_schema(gateways, user_input),
            errors=errors,
        )

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Open the first code-profile flow immediately after setup."""
        subentry_result = await self.hass.config_entries.subentries.async_init(
            (result["result"].entry_id, SUBENTRY_TYPE_CODE),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        result["next_flow"] = (
            FlowType.CONFIG_SUBENTRIES_FLOW,
            subentry_result["flow_id"],
        )
        return result

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
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=self._global_settings(user_input),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._global_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    def _available_gateways(self) -> dict[str, ConfigEntry]:
        return {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries(REOLINK_DOMAIN)
            if entry.unique_id
        }

    @staticmethod
    def _global_settings(user_input: dict[str, Any]) -> dict[str, str | int]:
        return {
            CONF_SUBMIT_KEY: str(user_input[CONF_SUBMIT_KEY]),
            CONF_CLEAR_KEY: str(user_input[CONF_CLEAR_KEY]),
            CONF_INPUT_TIMEOUT: int(user_input[CONF_INPUT_TIMEOUT]),
            CONF_MAX_ATTEMPTS: int(user_input[CONF_MAX_ATTEMPTS]),
            CONF_LOCKOUT_SECONDS: int(user_input[CONF_LOCKOUT_SECONDS]),
        }

    def _gateway_schema(
        self,
        gateways: dict[str, ConfigEntry],
        defaults: dict[str, Any] | None,
    ) -> vol.Schema:
        values = defaults or {}
        gateway_options = [
            {"value": entry_id, "label": entry.title} for entry_id, entry in gateways.items()
        ]
        gateway_default = values.get(CONF_GATEWAY_ENTRY_ID, gateway_options[0]["value"])
        base = self._global_schema(values).schema
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

    @staticmethod
    def _global_schema(defaults: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_SUBMIT_KEY,
                    default=defaults.get(CONF_SUBMIT_KEY, DEFAULT_SUBMIT_KEY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(CONTROL_KEYS), mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_CLEAR_KEY,
                    default=defaults.get(CONF_CLEAR_KEY, DEFAULT_CLEAR_KEY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(CONTROL_KEYS), mode=SelectSelectorMode.DROPDOWN
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
                    NumberSelectorConfig(min=1, max=10, step=1, mode=NumberSelectorMode.BOX)
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


class CodeSubentryFlowHandler(ConfigSubentryFlow):
    """Create and reconfigure named code profiles."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add one named code profile."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, title, error = await self._async_validate_profile(user_input)
            if error is None:
                return self.async_create_entry(
                    title=title,
                    data=data,
                    unique_id=str(uuid4()),
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self._profile_schema(user_input, code_required=True),
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
        defaults = {
            CONF_NAME: subentry.title,
            CONF_NUMBER_MODE: subentry.data[CONF_NUMBER_MODE],
            CONF_ALLOWED_NUMBERS: list(subentry.data[CONF_ALLOWED_NUMBERS]),
            CONF_CALL_DIRECTIONS: list(subentry.data[CONF_CALL_DIRECTIONS]),
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            data, title, error = await self._async_validate_profile(user_input, existing=subentry)
            if error is None:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=title,
                    data=data,
                )
            errors["base"] = error
            defaults.update(user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._profile_schema(defaults, code_required=False),
            errors=errors,
            description_placeholders={
                "min_length": str(CODE_MIN_LENGTH),
                "max_length": str(CODE_MAX_LENGTH),
            },
        )

    async def _async_validate_profile(
        self,
        user_input: dict[str, Any],
        existing: ConfigSubentry | None = None,
    ) -> tuple[dict[str, Any], str, str | None]:
        entry = self._get_entry()
        title = str(user_input[CONF_NAME]).strip()
        if not title or len(title) > 64:
            return {}, title, "invalid_name"
        for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_CODE):
            if existing is not None and subentry.subentry_id == existing.subentry_id:
                continue
            if hmac.compare_digest(subentry.title.casefold(), title.casefold()):
                return {}, title, "duplicate_name"

        code = str(user_input.get(CONF_CODE, ""))
        confirmation = str(user_input.get(CONF_CODE_CONFIRM, ""))
        if existing is None or code or confirmation:
            if not valid_code(code):
                return {}, title, "invalid_code"
            if not hmac.compare_digest(code, confirmation):
                return {}, title, "code_mismatch"
            code_hash = await self.hass.async_add_executor_job(
                hash_code, code, str(entry.data[CONF_HASH_SALT])
            )
            for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_CODE):
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

    @staticmethod
    def _profile_schema(defaults: dict[str, Any] | None, *, code_required: bool) -> vol.Schema:
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
