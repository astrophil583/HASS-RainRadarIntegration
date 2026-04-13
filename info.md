Detects precipitation near your location (or a tracked device) using the RainViewer public radar API.

**Entities created per entry:**
- 🌧 **Rain detected** — binary sensor, ON when rain is found inside the radius
- 📏 **Nearest precipitation** — distance to the closest rain pixel (km)
- 🧭 **Nearest precipitation bearing** — compass direction to the closest rain (°)
- 💨 **Storm approach speed** — how fast the storm is closing in (km/h)
- ⏱ **Rain ETA** — estimated minutes until rain reaches your position
- 📡 **Maximum intensity** — highest radar reflectivity detected (dBZ)

**Location modes:** fixed coordinates or live device tracker.

For full documentation see the [README](https://github.com/astrophil583/HASS-RainRadarIntegration/blob/main/README.md).
