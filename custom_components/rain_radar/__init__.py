"""Rain Radar integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_TRACKER,
    CONF_LOCATION_MODE,
    CONF_MIN_INTENSITY,
    CONF_RADIUS,
    DEFAULT_MIN_INTENSITY,
    DEFAULT_RADIUS,
    DOMAIN,
    LOCATION_MODE_TRACKER,
)
from .coordinator import RainRadarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rain Radar from a config entry."""
    config = {**entry.data, **entry.options}

    shared_kwargs = dict(
        hass=hass,
        radius_km=config.get(CONF_RADIUS, DEFAULT_RADIUS),
        min_intensity_dbz=config.get(CONF_MIN_INTENSITY, DEFAULT_MIN_INTENSITY),
    )

    if config.get(CONF_LOCATION_MODE) == LOCATION_MODE_TRACKER:
        coordinator = RainRadarCoordinator(
            **shared_kwargs,
            device_tracker_entity_id=config[CONF_DEVICE_TRACKER],
        )
    else:
        coordinator = RainRadarCoordinator(
            **shared_kwargs,
            latitude=config[CONF_LATITUDE],
            longitude=config[CONF_LONGITUDE],
        )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
