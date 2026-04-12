# Rain Radar

Home Assistant custom integration that detects precipitation near your location using the [RainViewer](https://www.rainviewer.com/api.html) public radar API.

---

## How it works

Every 5 minutes the integration fetches the latest radar frame from RainViewer, downloads the relevant map tiles for your area, and scans each pixel inside your configured radius. Pixel colour is mapped to radar reflectivity (dBZ) to determine whether rain is present, how intense it is, and — over time — whether a storm cell is approaching.

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

Each entry creates one device with six entities.

| Entity | Type | Unit | Description |
|--------|------|------|-------------|
| Rain detected | `binary_sensor` | on/off | ON when rain is found inside the radius |
| Nearest precipitation | `sensor` | km | Distance to the closest rain pixel |
| Nearest precipitation bearing | `sensor` | ° | Compass bearing to the closest rain (0° = N, 90° = E, …) |
| Storm approach speed | `sensor` | km/h | Speed at which the storm is closing in (see below) |
| Rain ETA | `sensor` | min | Estimated minutes until rain reaches your position |
| Maximum intensity | `sensor` | dBZ | Highest reflectivity value found inside the radius |

Sensors that have no meaningful value return **unknown**: the distance/bearing/intensity sensors when no rain is detected, and the approach/ETA sensors when no confirmed approach is in progress.

---

## Storm approach detection

The approach speed and ETA sensors use a rolling window of the last **6 updates (~30 minutes)** to detect whether a storm is genuinely closing in. A value is published only when **all four conditions** are met simultaneously:

1. At least **3 samples** are available in the window (15 minutes of data).
2. The **distance trend is negative** — linear regression over the window confirms the storm is getting closer.
3. The inferred speed is **≥ 1 km/h** — filters out sub-pixel jitter from the radar tile resolution.
4. The **bearing is consistent** across samples (circular standard deviation < 30°) — this ensures the integration is tracking the *same storm cell*, not a new one that appeared from a different direction.

When rain disappears entirely, the history is cleared so stale bearings never bias a future detection.

> The ETA sensor shows **0** when rain is already overhead (distance = 0 km). It shows **unknown** when the storm is not approaching or there is not yet enough history.

---

## Device tracker mode

When a `device_tracker` entity is selected, the coordinator reads the tracker's `latitude` and `longitude` attributes at every update. This means the monitored circle automatically follows wherever the device is.

If the tracker is unavailable or has no GPS fix, the update is skipped and Home Assistant marks the entities as unavailable until the next successful fetch.

---

## Automation examples

### Alert when rain is approaching

```yaml
automation:
  - alias: "Storm approaching alert"
    trigger:
      - platform: state
        entity_id: sensor.rain_radar_rain_eta
    condition:
      - condition: template
        value_template: "{{ states('sensor.rain_radar_rain_eta') not in ['unknown', 'unavailable'] }}"
      - condition: numeric_state
        entity_id: sensor.rain_radar_rain_eta
        below: 30
    action:
      - service: notify.mobile_app
        data:
          title: "Rain in {{ states('sensor.rain_radar_rain_eta') | int }} minutes"
          message: >
            Storm approaching from {{ states('sensor.rain_radar_nearest_precipitation_bearing') }}°
            at {{ states('sensor.rain_radar_approach_speed') }} km/h,
            currently {{ states('sensor.rain_radar_nearest_precipitation') }} km away.
```

### Alert when rain is detected nearby

```yaml
automation:
  - alias: "Rain nearby alert"
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
- The approach sensors need **15 minutes** of continuous rain detection before they can produce a value.
- RainViewer coverage varies by region; areas without radar stations will show no data.
