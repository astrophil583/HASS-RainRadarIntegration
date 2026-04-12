# Rain Radar

Home Assistant custom integration that detects precipitation near your location using the [RainViewer](https://www.rainviewer.com/api.html) public radar API.

---

## How it works

Every 5 minutes the integration fetches the latest radar frame from RainViewer, downloads the relevant map tiles for your area, and scans each pixel inside your configured radius. Pixel colour is mapped to radar reflectivity (dBZ) to determine whether rain is present and how intense it is.

---

## Installation

1. Copy the `custom_components/rain_radar` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add integration** and search for **Rain Radar**.

**Requirement:** [Pillow](https://pypi.org/project/Pillow/) ≥ 9.0.0 (installed automatically by HA).

---

## Setup

### Step 1 — choose a location mode

| Mode | Description |
|------|-------------|
| **Fixed position** | Monitor a static set of coordinates |
| **Device tracker** | Follow a mobile device; coordinates are read live each update |

### Step 2 — configure the area

| Option | Default | Range | Notes |
|--------|---------|-------|-------|
| Latitude / Longitude | HA location | — | Fixed mode only |
| Device tracker | — | — | Tracker mode only; must have GPS attributes |
| Search radius | 50 km | 1–500 km | Circle around the position to scan |
| Min intensity | 10 dBZ | 0–70 dBZ | Pixels below this threshold are ignored |

> **Intensity reference:** 10 dBZ ≈ drizzle · 30 dBZ ≈ moderate rain · 45 dBZ ≈ heavy rain

All options can be changed later via **Configure** in the integration card without reinstalling.

---

## Entities

Each entry creates one device with four entities.

| Entity | Type | Unit | Description |
|--------|------|------|-------------|
| Rain detected | `binary_sensor` | on/off | ON when rain is found inside the radius |
| Nearest precipitation | `sensor` | km | Distance to the closest rain pixel |
| Nearest precipitation bearing | `sensor` | ° | Compass bearing to the closest rain (0° = N, 90° = E, …) |
| Maximum intensity | `sensor` | dBZ | Highest reflectivity value found inside the radius |

The three numeric sensors return **unknown** when no rain is detected.

---

## Device tracker mode

When a `device_tracker` entity is selected, the coordinator reads the tracker's `latitude` and `longitude` attributes at every update. This means the monitored circle automatically follows wherever the device is.

If the tracker is unavailable or has no GPS fix, the update is skipped and Home Assistant marks the entities as unavailable until the next successful fetch.

---

## Automation example

```yaml
automation:
  - alias: "Rain approaching alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.rain_radar_rain_detected
        to: "on"
    condition:
      - condition: numeric_state
        entity_id: sensor.rain_radar_nearest_precipitation
        below: 20
    action:
      - service: notify.mobile_app
        data:
          title: "Rain incoming"
          message: >
            Rain detected {{ states('sensor.rain_radar_nearest_precipitation') }} km away
            (bearing {{ states('sensor.rain_radar_nearest_precipitation_bearing') }}°),
            intensity {{ states('sensor.rain_radar_max_intensity') }} dBZ.
```

---

## Limitations

- Radar data is updated by RainViewer roughly every 10 minutes; the 5-minute poll interval ensures you always have the latest available frame.
- Pixel-to-dBZ colour mapping is approximate; the RainViewer palette is matched via nearest-colour lookup.
- At very small radii (< 5 km) the tile zoom may not have sufficient resolution to detect small cells.
- RainViewer coverage varies by region; areas without radar stations will show no data.
