"""DataUpdateCoordinator for Rain Radar."""
from __future__ import annotations

import asyncio
import colorsys
import io
import logging
import math
from collections import deque
from dataclasses import dataclass
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ALPHA_THRESHOLD,
    APPROACH_HISTORY_MAXLEN,
    APPROACH_HISTORY_MIN_POINTS,
    DBZ_COLOR_REFERENCES,
    MAX_BEARING_STD_DEG,
    MIN_APPROACH_SPEED_KMH,
    RAINVIEWER_API_URL,
    TILE_SIZE,
    TILE_URL,
    UPDATE_INTERVAL_MINUTES,
    ZOOM_MAX,
    ZOOM_MIN,
)

_LOGGER = logging.getLogger(__name__)

# Each history entry: (utc_datetime, distance_km, bearing_deg | None)
_HistoryEntry = tuple  # (datetime, float, float | None)


@dataclass
class RainRadarData:
    """Processed result from one radar scan."""

    is_raining: bool
    nearest_distance_km: float | None    # None when no rain detected
    nearest_bearing_deg: float | None    # degrees from N clockwise; None when no rain
    max_intensity_dbz: float | None      # None when no rain detected
    approach_speed_kmh: float | None     # None = not approaching / insufficient data
    eta_minutes: float | None            # None = same; 0.0 = rain already overhead


# ---------------------------------------------------------------------------
# Tile / projection helpers
# ---------------------------------------------------------------------------

def _calculate_zoom(lat: float, radius_km: float) -> int:
    """Pick a zoom level so the radius spans roughly 60 pixels."""
    lat_rad = math.radians(lat)
    km_per_pixel_target = radius_km / 60.0
    circumference_at_lat = 40_075.0 * math.cos(lat_rad)
    zoom_float = math.log2(circumference_at_lat / (km_per_pixel_target * TILE_SIZE))
    return max(ZOOM_MIN, min(ZOOM_MAX, round(zoom_float)))


def _km_per_pixel(lat: float, zoom: int) -> float:
    """Ground distance (km) per pixel at the given latitude and zoom level."""
    return 40_075.0 * math.cos(math.radians(lat)) / (2 ** zoom * TILE_SIZE)


def _lat_lon_to_global_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Convert lat/lon to fractional global pixel coordinates (origin = top-left)."""
    n = 2 ** zoom * TILE_SIZE
    gx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return gx, gy


def _global_pixel_to_lat_lon(gx: float, gy: float, zoom: int) -> tuple[float, float]:
    """Inverse of _lat_lon_to_global_pixel."""
    n = 2 ** zoom * TILE_SIZE
    lon = gx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * gy / n))))
    return lat, lon


def _geodetic_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from (lat1, lon1) to (lat2, lon2), degrees from N clockwise."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x = math.sin(Δλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _tiles_in_bounding_box(
    lat: float, lon: float, radius_km: float, zoom: int
) -> list[tuple[int, int]]:
    """Return all (tile_x, tile_y) pairs that overlap the bounding box of the circle."""
    delta_lat = radius_km / 111.0
    delta_lon = radius_km / (111.0 * math.cos(math.radians(lat)))

    corners = [
        (lat + delta_lat, lon - delta_lon),
        (lat - delta_lat, lon + delta_lon),
    ]
    tile_coords = []
    for clat, clon in corners:
        clat = max(-85.0511, min(85.0511, clat))
        n = 2 ** zoom
        tx = int((clon + 180.0) / 360.0 * n)
        lat_rad = math.radians(clat)
        ty = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        tile_coords.append((tx, ty))

    min_tx = min(tile_coords[0][0], tile_coords[1][0])
    max_tx = max(tile_coords[0][0], tile_coords[1][0])
    min_ty = min(tile_coords[0][1], tile_coords[1][1])
    max_ty = max(tile_coords[0][1], tile_coords[1][1])

    return [
        (tx, ty)
        for tx in range(min_tx, max_tx + 1)
        for ty in range(min_ty, max_ty + 1)
    ]


# ---------------------------------------------------------------------------
# Color → dBZ
# ---------------------------------------------------------------------------

def _rgb_to_dbz(r: int, g: int, b: int) -> float:
    """Estimate radar reflectivity (dBZ) from an RGBA pixel's RGB components."""
    best_dbz = 0.0
    best_dist = float("inf")
    for ref_r, ref_g, ref_b, ref_dbz in DBZ_COLOR_REFERENCES:
        dist = (r - ref_r) ** 2 + (g - ref_g) ** 2 + (b - ref_b) ** 2
        if dist < best_dist:
            best_dist = dist
            best_dbz = float(ref_dbz)
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.15 or s < 0.15:
        return 0.0
    return best_dbz


# ---------------------------------------------------------------------------
# Approach trend helpers
# ---------------------------------------------------------------------------

def _linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares slope of (xs, ys). Returns None if degenerate."""
    n = len(xs)
    if n < 2:
        return None
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    if abs(denom) < 1e-9:
        return None
    return (n * sxy - sx * sy) / denom


def _circular_std_deg(bearings: list[float]) -> float:
    """Circular standard deviation of bearing angles (degrees), handling wrap-around.

    Uses the Yamartino / Fisher formula:  σ = sqrt(−2·ln R)
    where R is the mean resultant length of the unit vectors.
    Returns 180.0 (maximum dispersion) when bearings are empty or evenly spread.
    """
    if not bearings:
        return 180.0
    rads = [math.radians(b) for b in bearings]
    sin_m = sum(math.sin(r) for r in rads) / len(rads)
    cos_m = sum(math.cos(r) for r in rads) / len(rads)
    R = math.sqrt(sin_m ** 2 + cos_m ** 2)
    if R < 1e-9:
        return 180.0
    return math.degrees(math.sqrt(-2.0 * math.log(R)))


def _compute_approach(
    history: deque,
    current_distance: float,
) -> tuple[float | None, float | None]:
    """Compute approach speed (km/h) and ETA (minutes).

    Returns (None, None) unless ALL of the following hold:
      1. ≥ APPROACH_HISTORY_MIN_POINTS samples in the window.
      2. Linear slope of distances is negative (storm getting closer).
      3. Inferred speed ≥ MIN_APPROACH_SPEED_KMH (not pixel-level noise).
      4. Circular std-dev of bearings < MAX_BEARING_STD_DEG — ensures we are
         tracking the *same* cell, not a new one appearing from another direction.

    Returns (speed_kmh, 0.0) when rain is already overhead (distance == 0).
    """
    if len(history) < APPROACH_HISTORY_MIN_POINTS:
        return None, None

    t0 = history[0][0].timestamp()
    xs = [(ts.timestamp() - t0) for ts, _, _ in history]   # seconds elapsed
    ys = [d for _, d, _ in history]                        # distances in km

    # Condition 1+2: negative distance trend
    slope = _linear_slope(xs, ys)   # km / second (negative = approaching)
    if slope is None or slope >= 0:
        return None, None

    # Condition 3: minimum speed
    approach_speed_kmh = abs(slope) * 3600.0
    if approach_speed_kmh < MIN_APPROACH_SPEED_KMH:
        return None, None

    # Condition 4: bearing consistency
    # Only use entries where distance > 0 (bearing is undefined at distance = 0)
    valid_bearings = [b for _, d, b in history if b is not None and d > 0.0]
    if len(valid_bearings) >= APPROACH_HISTORY_MIN_POINTS:
        std = _circular_std_deg(valid_bearings)
        if std > MAX_BEARING_STD_DEG:
            _LOGGER.debug(
                "Approach trend rejected: bearing circular std=%.1f° > threshold %.1f°"
                " — likely a different storm cell",
                std, MAX_BEARING_STD_DEG,
            )
            return None, None

    # All conditions satisfied
    if current_distance == 0.0:
        return round(approach_speed_kmh, 1), 0.0

    eta_min = current_distance / abs(slope) / 60.0
    return round(approach_speed_kmh, 1), round(eta_min, 0)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

# Return type from _analyse_tile:
# (rain_found, nearest_dist_km, nearest_gx, nearest_gy, max_dbz)
_TileResult = tuple[bool, float | None, float | None, float | None, float | None]


class RainRadarCoordinator(DataUpdateCoordinator[RainRadarData]):
    """Fetch and analyse radar tiles every UPDATE_INTERVAL_MINUTES minutes."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        device_tracker_entity_id: str | None = None,
        radius_km: int,
        min_intensity_dbz: int,
    ) -> None:
        if device_tracker_entity_id:
            name = f"Rain Radar → {device_tracker_entity_id}"
        else:
            name = f"Rain Radar ({latitude:.2f}, {longitude:.2f})"

        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._fixed_lat = latitude
        self._fixed_lon = longitude
        self._device_tracker_entity_id = device_tracker_entity_id
        self.radius_km = radius_km
        self.min_intensity_dbz = min_intensity_dbz

        # Exposed for entity display; updated each cycle in tracker mode
        self.latitude: float = latitude or 0.0
        self.longitude: float = longitude or 0.0

        # Rolling history for approach trend: (utc_datetime, distance_km, bearing_deg|None)
        self._distance_history: deque[_HistoryEntry] = deque(
            maxlen=APPROACH_HISTORY_MAXLEN
        )

    # ------------------------------------------------------------------
    # Position resolution
    # ------------------------------------------------------------------

    def _resolve_position(self) -> tuple[float, float]:
        """Return (lat, lon) either from fixed config or from the tracker entity."""
        if self._device_tracker_entity_id is None:
            return self._fixed_lat, self._fixed_lon  # type: ignore[return-value]

        state = self.hass.states.get(self._device_tracker_entity_id)
        if state is None or state.state == "unavailable":
            raise UpdateFailed(
                f"Device tracker {self._device_tracker_entity_id!r} is unavailable"
            )
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        if lat is None or lon is None:
            raise UpdateFailed(
                f"Device tracker {self._device_tracker_entity_id!r} has no GPS coordinates. "
                "Make sure location tracking is enabled on the device."
            )
        return float(lat), float(lon)

    # ------------------------------------------------------------------
    # Tile analysis (runs in executor thread — PIL / CPU)
    # ------------------------------------------------------------------

    @staticmethod
    def _analyse_tile(
        tile_bytes: bytes,
        tile_x: int,
        tile_y: int,
        zoom: int,
        cx_global: float,
        cy_global: float,
        radius_km: float,
        kpp: float,
        min_intensity_dbz: float,
        radius_px: float,
    ) -> _TileResult:
        """Scan one tile PNG.

        Returns (rain_found, nearest_dist_km, nearest_gx, nearest_gy, max_dbz).
        nearest_gx/gy are global pixel coordinates of the closest qualifying rain
        pixel — used by the caller to compute the geodetic bearing.
        """
        from PIL import Image  # noqa: PLC0415

        img = Image.open(io.BytesIO(tile_bytes)).convert("RGBA")
        pixels = img.load()

        tile_px_origin_x = tile_x * TILE_SIZE
        tile_px_origin_y = tile_y * TILE_SIZE

        local_cx = cx_global - tile_px_origin_x
        local_cy = cy_global - tile_px_origin_y

        px_min = max(0, int(local_cx - radius_px) - 1)
        px_max = min(TILE_SIZE - 1, int(local_cx + radius_px) + 1)
        py_min = max(0, int(local_cy - radius_px) - 1)
        py_max = min(TILE_SIZE - 1, int(local_cy + radius_px) + 1)

        if px_min > px_max or py_min > py_max:
            return False, None, None, None, None

        rain_found = False
        nearest_dist: float | None = None
        nearest_gx: float | None = None
        nearest_gy: float | None = None
        max_dbz: float | None = None

        for py in range(py_min, py_max + 1):
            for px in range(px_min, px_max + 1):
                gpx = tile_px_origin_x + px
                gpy = tile_px_origin_y + py
                dpx = gpx - cx_global
                dpy = gpy - cy_global
                dist_km = math.sqrt(dpx * dpx + dpy * dpy) * kpp
                # Sub-pixel clamp: distance within one pixel width → rain is overhead
                if dist_km < kpp:
                    dist_km = 0.0

                if dist_km > radius_km:
                    continue

                r, g, b, a = pixels[px, py]
                if a < ALPHA_THRESHOLD:
                    continue

                dbz = _rgb_to_dbz(r, g, b)
                if dbz < min_intensity_dbz:
                    continue

                rain_found = True
                if nearest_dist is None or dist_km < nearest_dist:
                    nearest_dist = dist_km
                    nearest_gx = float(gpx)
                    nearest_gy = float(gpy)
                if max_dbz is None or dbz > max_dbz:
                    max_dbz = dbz

        return rain_found, nearest_dist, nearest_gx, nearest_gy, max_dbz

    # ------------------------------------------------------------------
    # Main update method
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> RainRadarData:
        """Fetch the latest radar tile(s) and analyse them."""
        # 1. Resolve current position
        lat, lon = self._resolve_position()
        self.latitude = lat
        self.longitude = lon

        session = async_get_clientsession(self.hass)

        # 2. Fetch the weather-maps index
        try:
            async with asyncio.timeout(15):
                async with session.get(RAINVIEWER_API_URL) as resp:
                    resp.raise_for_status()
                    maps_data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Cannot reach RainViewer API: {err}") from err

        past_frames: list[dict] = maps_data.get("radar", {}).get("past", [])
        if not past_frames:
            raise UpdateFailed("RainViewer returned no radar frames")

        radar_path: str = past_frames[-1]["path"]
        _LOGGER.debug("Using radar frame: %s", radar_path)

        # 3. Projection constants
        zoom = _calculate_zoom(lat, self.radius_km)
        kpp = _km_per_pixel(lat, zoom)
        radius_px = self.radius_km / kpp
        cx_global, cy_global = _lat_lon_to_global_pixel(lat, lon, zoom)
        tiles = _tiles_in_bounding_box(lat, lon, self.radius_km, zoom)
        _LOGGER.debug(
            "zoom=%d  kpp=%.3f km/px  radius_px=%.1f  tiles=%d",
            zoom, kpp, radius_px, len(tiles),
        )

        # 4. Download + analyse each tile concurrently
        async def _fetch_and_analyse(tile_x: int, tile_y: int) -> _TileResult:
            url = TILE_URL.format(path=radar_path, zoom=zoom, x=tile_x, y=tile_y)
            try:
                async with asyncio.timeout(10):
                    async with session.get(url) as resp:
                        resp.raise_for_status()
                        tile_bytes = await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Failed to download tile %d/%d: %s", tile_x, tile_y, err)
                return False, None, None, None, None

            return await self.hass.async_add_executor_job(
                self._analyse_tile,
                tile_bytes, tile_x, tile_y, zoom,
                cx_global, cy_global,
                self.radius_km, kpp,
                float(self.min_intensity_dbz), radius_px,
            )

        results = await asyncio.gather(
            *[_fetch_and_analyse(tx, ty) for tx, ty in tiles]
        )

        # 5. Merge results
        is_raining = False
        nearest_dist: float | None = None
        nearest_gx: float | None = None
        nearest_gy: float | None = None
        max_dbz: float | None = None

        for rain_found, dist, rgx, rgy, dbz in results:
            if not rain_found:
                continue
            is_raining = True
            if dist is not None and (nearest_dist is None or dist < nearest_dist):
                nearest_dist = dist
                nearest_gx = rgx
                nearest_gy = rgy
            if dbz is not None and (max_dbz is None or dbz > max_dbz):
                max_dbz = dbz

        # 6. Compute geodetic bearing to nearest rain pixel
        bearing: float | None = None
        if nearest_gx is not None and nearest_gy is not None:
            rain_lat, rain_lon = _global_pixel_to_lat_lon(nearest_gx, nearest_gy, zoom)
            bearing = _geodetic_bearing(lat, lon, rain_lat, rain_lon)

        # 7. Update rolling history
        #    - Append when rain is present (distance may be 0 if overhead)
        #    - Clear when rain disappears entirely so stale data doesn't bias future trends
        if nearest_dist is not None:
            self._distance_history.append((dt_util.utcnow(), nearest_dist, bearing))
        else:
            if self._distance_history:
                _LOGGER.debug("Rain gone — clearing approach history")
            self._distance_history.clear()

        # 8. Compute approach trend (distance + bearing consistency check)
        approach_speed, eta_min = _compute_approach(
            self._distance_history,
            nearest_dist if nearest_dist is not None else 0.0,
        )

        _LOGGER.debug(
            "Scan complete: raining=%s  nearest=%.1f km  bearing=%.0f°  "
            "max=%.0f dBZ  approach=%.1f km/h  eta=%.0f min",
            is_raining,
            nearest_dist if nearest_dist is not None else -1,
            bearing if bearing is not None else -1,
            max_dbz if max_dbz is not None else -1,
            approach_speed if approach_speed is not None else -1,
            eta_min if eta_min is not None else -1,
        )
        return RainRadarData(
            is_raining=is_raining,
            nearest_distance_km=nearest_dist,
            nearest_bearing_deg=bearing,
            max_intensity_dbz=max_dbz,
            approach_speed_kmh=approach_speed,
            eta_minutes=eta_min,
        )
