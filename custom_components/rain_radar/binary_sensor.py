"""Binary sensor: rain detected within radius."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_RADIUS, DOMAIN
from .coordinator import RainRadarCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor from a config entry."""
    coordinator: RainRadarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainDetectedBinarySensor(coordinator, entry)])


class RainDetectedBinarySensor(
    CoordinatorEntity[RainRadarCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON when rain is detected within the search radius."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_has_entity_name = True
    _attr_translation_key = "rain_detected"

    def __init__(
        self, coordinator: RainRadarCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_rain_detected"
        radius = entry.options.get(CONF_RADIUS) or entry.data.get(CONF_RADIUS)
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="RainViewer",
            model=f"Radar scan r={radius} km",
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.is_raining
