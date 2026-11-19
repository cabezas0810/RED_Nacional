"""Integración RED Movilidad (Santiago de Chile) para Home Assistant."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

PLATAFORMAS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATAFORMAS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return await hass.config_entries.async_unload_platforms(entry, PLATAFORMAS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Al borrar una entrada, se va también su aviso de líneas duplicadas."""
    ir.async_delete_issue(hass, DOMAIN, f"lineas_duplicadas_{entry.entry_id}")


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Recarga la entrada cuando se cambian sus opciones (línea/modo)."""
    await hass.config_entries.async_reload(entry.entry_id)
