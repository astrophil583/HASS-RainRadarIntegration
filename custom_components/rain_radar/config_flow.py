"""Config flow for Rain Radar integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DEVICE_TRACKER,
    CONF_LOCATION_MODE,
    CONF_MIN_INTENSITY,
    CONF_RADIUS,
    DEFAULT_MIN_INTENSITY,
    DEFAULT_RADIUS,
    DOMAIN,
    LOCATION_MODE_FIXED,
    LOCATION_MODE_TRACKER,
    RAINVIEWER_API_URL,
)

_LOGGER = logging.getLogger(__name__)

_RADIUS_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1, max=500))
_INTENSITY_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=0, max=70))


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------

def _mode_schema(default: str = LOCATION_MODE_FIXED) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LOCATION_MODE, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=LOCATION_MODE_FIXED, label="Fixed position"),
                        SelectOptionDict(value=LOCATION_MODE_TRACKER, label="Device tracker"),
                    ],
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
    )


def _fixed_schema(defaults: dict[str, Any], hass: HomeAssistant) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LATITUDE,
                default=defaults.get(CONF_LATITUDE, hass.config.latitude),
            ): cv.latitude,
            vol.Required(
                CONF_LONGITUDE,
                default=defaults.get(CONF_LONGITUDE, hass.config.longitude),
            ): cv.longitude,
            vol.Required(
                CONF_RADIUS, default=defaults.get(CONF_RADIUS, DEFAULT_RADIUS)
            ): _RADIUS_VALIDATOR,
            vol.Required(
                CONF_MIN_INTENSITY,
                default=defaults.get(CONF_MIN_INTENSITY, DEFAULT_MIN_INTENSITY),
            ): _INTENSITY_VALIDATOR,
        }
    )


def _tracker_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_TRACKER,
                default=defaults.get(CONF_DEVICE_TRACKER, vol.UNDEFINED),
            ): EntitySelector(EntitySelectorConfig(domain="device_tracker")),
            vol.Required(
                CONF_RADIUS, default=defaults.get(CONF_RADIUS, DEFAULT_RADIUS)
            ): _RADIUS_VALIDATOR,
            vol.Required(
                CONF_MIN_INTENSITY,
                default=defaults.get(CONF_MIN_INTENSITY, DEFAULT_MIN_INTENSITY),
            ): _INTENSITY_VALIDATOR,
        }
    )


# ---------------------------------------------------------------------------
# API validation helper
# ---------------------------------------------------------------------------

async def _validate_api(hass: HomeAssistant) -> str | None:
    """Return an error key if the RainViewer API is unreachable, else None."""
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(10):
            async with session.get(RAINVIEWER_API_URL) as resp:
                data = await resp.json(content_type=None)
                if not data.get("radar", {}).get("past"):
                    return "no_radar_data"
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error while validating RainViewer API")
        return "unknown"
    return None


def _tracker_has_gps(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return an error key if the tracker entity has no usable GPS coordinates."""
    state = hass.states.get(entity_id)
    if state is None or state.state == "unavailable":
        return "tracker_unavailable"
    if (
        state.attributes.get("latitude") is None
        or state.attributes.get("longitude") is None
    ):
        return "tracker_no_gps"
    return None


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class RainRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rain Radar.

    Step 1 (user)   – choose location mode (fixed / device tracker).
    Step 2a (fixed) – enter lat, lon, radius, intensity.
    Step 2b (tracker) – pick a device_tracker entity, radius, intensity.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._location_mode: str = LOCATION_MODE_FIXED

    # ------------------------------------------------------------------
    # Step 1: choose location mode
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._location_mode = user_input[CONF_LOCATION_MODE]
            if self._location_mode == LOCATION_MODE_TRACKER:
                return await self.async_step_tracker()
            return await self.async_step_fixed()

        return self.async_show_form(
            step_id="user",
            data_schema=_mode_schema(),
        )

    # ------------------------------------------------------------------
    # Step 2a: fixed position
    # ------------------------------------------------------------------

    async def async_step_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]

            await self.async_set_unique_id(f"fixed_{lat:.4f}_{lon:.4f}")
            self._abort_if_unique_id_configured()

            error = await _validate_api(self.hass)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Rain Radar ({lat:.2f}, {lon:.2f})",
                    data={CONF_LOCATION_MODE: LOCATION_MODE_FIXED, **user_input},
                )

        return self.async_show_form(
            step_id="fixed",
            data_schema=_fixed_schema(user_input or {}, self.hass),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2b: device tracker
    # ------------------------------------------------------------------

    async def async_step_tracker(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            entity_id: str = user_input[CONF_DEVICE_TRACKER]

            gps_error = _tracker_has_gps(self.hass, entity_id)
            if gps_error:
                errors[CONF_DEVICE_TRACKER] = gps_error
            else:
                await self.async_set_unique_id(f"tracker_{entity_id}")
                self._abort_if_unique_id_configured()

                api_error = await _validate_api(self.hass)
                if api_error:
                    errors["base"] = api_error
                else:
                    return self.async_create_entry(
                        title=f"Rain Radar → {entity_id}",
                        data={CONF_LOCATION_MODE: LOCATION_MODE_TRACKER, **user_input},
                    )

        return self.async_show_form(
            step_id="tracker",
            data_schema=_tracker_schema(user_input or {}),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Options flow factory
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> RainRadarOptionsFlow:
        return RainRadarOptionsFlow(config_entry)


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

class RainRadarOptionsFlow(config_entries.OptionsFlow):
    """Allow editing radius/intensity (and position for fixed mode, tracker for tracker mode)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        config = {**self._entry.data, **self._entry.options}
        mode = config.get(CONF_LOCATION_MODE, LOCATION_MODE_FIXED)

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        if mode == LOCATION_MODE_TRACKER:
            schema = _tracker_schema(config)
        else:
            schema = _fixed_schema(config, self.hass)

        return self.async_show_form(step_id="init", data_schema=schema)
