"""Event entities for accepted codes and rejected submissions."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DTMFCodeConfigEntry
from .const import (
    CONF_INSTANCE_ID,
    EVENT_ACCEPTED,
    EVENT_LOCKED_OUT,
    EVENT_REJECTED,
    SUBENTRY_TYPE_CODE,
    code_signal,
    security_signal,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DTMFCodeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one result entity per code plus the security entity."""
    async_add_entities([DTMFSecurityEventEntity(entry)])
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_CODE):
        async_add_entities(
            [DTMFCodeEventEntity(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class DTMFCodeEventEntity(EventEntity):
    """Event entity fired only when this profile is accepted."""

    _attr_event_types: ClassVar[list[str]] = [EVENT_ACCEPTED]
    _attr_has_entity_name = True
    _attr_icon = "mdi:dialpad"

    def __init__(self, entry: DTMFCodeConfigEntry, subentry: ConfigSubentry) -> None:
        self._entry = entry
        self._profile_id = subentry.unique_id or subentry.subentry_id
        self.entity_description = EventEntityDescription(
            key=self._profile_id,
            translation_key="code",
            translation_placeholders={"name": subentry.title},
        )
        self._attr_unique_id = f"{entry.data[CONF_INSTANCE_ID]}_code_{self._profile_id}"

    async def async_added_to_hass(self) -> None:
        """Subscribe after the entity has been added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                code_signal(self._entry.entry_id, self._profile_id),
                self._async_handle_accepted,
            )
        )

    @callback
    def _async_handle_accepted(self, event_data: dict[str, Any]) -> None:
        self._trigger_event(EVENT_ACCEPTED, event_data)
        self.async_write_ha_state()


class DTMFSecurityEventEntity(EventEntity):
    """Shared event entity for failed attempts and lockouts."""

    _attr_event_types: ClassVar[list[str]] = [EVENT_REJECTED, EVENT_LOCKED_OUT]
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-lock-outline"

    def __init__(self, entry: DTMFCodeConfigEntry) -> None:
        self._entry = entry
        self.entity_description = EventEntityDescription(key="security", translation_key="security")
        self._attr_unique_id = f"{entry.data[CONF_INSTANCE_ID]}_security"

    async def async_added_to_hass(self) -> None:
        """Subscribe after the entity has been added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                security_signal(self._entry.entry_id),
                self._async_handle_security_event,
            )
        )

    @callback
    def _async_handle_security_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        self._trigger_event(event_type, event_data)
        self.async_write_ha_state()
