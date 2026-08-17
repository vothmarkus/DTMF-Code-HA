"""DTMF Code integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import DTMFCodeManager

type DTMFCodeConfigEntry = ConfigEntry[DTMFCodeManager]

PLATFORMS = (Platform.EVENT,)


async def async_setup_entry(hass: HomeAssistant, entry: DTMFCodeConfigEntry) -> bool:
    """Set up DTMF Code from a config entry."""
    manager = DTMFCodeManager(hass, entry)
    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DTMFCodeConfigEntry) -> bool:
    """Unload DTMF Code and discard all transient input."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.stop()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: DTMFCodeConfigEntry) -> None:
    """Reload after settings or code profiles change."""
    await hass.config_entries.async_reload(entry.entry_id)
