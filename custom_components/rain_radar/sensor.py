"""Sensors: nearest precipitation distance, bearing, and maximum radar intensity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_RADIUS, DOMAIN
from .coordinator import RainRadarCoordinator, RainRadarData


@dataclass(frozen=True, kw_only=True)
class RainRadarSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a value accessor."""

    value_fn: Callable[[RainRadarData], float | None]


SENSOR_DESCRIPTIONS: tuple[RainRadarSensorDescription, ...] = (
    RainRadarSensorDescription(
        key="nearest_precipitation",
        translation_key="nearest_precipitation",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.nearest_distance_km,
    ),
    RainRadarSensorDescription(
        key="nearest_bearing",
        translation_key="nearest_bearing",
        # SensorDeviceClass.WIND_DIRECTION is the standard HA class for compass bearings
        device_class=SensorDeviceClass.WIND_DIRECTION,
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.nearest_bearing_deg,
    ),
    RainRadarSensorDescription(
        key="max_intensity",
        translation_key="max_intensity",
        native_unit_of_measurement="dBZ",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.max_intensity_dbz,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rain Radar sensors from a config entry."""
    coordinator: RainRadarCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RainRadarSensor(coordinator, entry, description)
            for description in SENSOR_DESCRIPTIONS
        ]
    )


class RainRadarSensor(CoordinatorEntity[RainRadarCoordinator], SensorEntity):
    """A sensor that reports a single numeric value from the radar scan."""

    entity_description: RainRadarSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RainRadarCoordinator,
        entry: ConfigEntry,
        description: RainRadarSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        radius = entry.options.get(CONF_RADIUS) or entry.data.get(CONF_RADIUS)
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="RainViewer",
            model=f"Radar scan r={radius} km",
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor value, or None (→ 'unknown') when no rain is present."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
