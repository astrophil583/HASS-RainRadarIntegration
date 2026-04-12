"""Constants for the Rain Radar integration."""

DOMAIN = "rain_radar"

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS = "radius"
CONF_MIN_INTENSITY = "min_intensity"
CONF_LOCATION_MODE = "location_mode"
CONF_DEVICE_TRACKER = "device_tracker"

LOCATION_MODE_FIXED = "fixed"
LOCATION_MODE_TRACKER = "tracker"

DEFAULT_RADIUS = 50        # km
DEFAULT_MIN_INTENSITY = 10  # dBZ (very light drizzle threshold)
UPDATE_INTERVAL_MINUTES = 5

TILE_SIZE = 256
ALPHA_THRESHOLD = 10  # pixels with alpha < this are treated as no-rain

RAINVIEWER_API_URL = "https://api.rainviewer.com/public/weather-maps.json"
# path, zoom, x, y
TILE_URL = "https://tilecache.rainviewer.com{path}/256/{zoom}/{x}/{y}/2/1_1.png"

# Minimum/maximum zoom levels for tile fetching
ZOOM_MIN = 4
ZOOM_MAX = 9

# Storm approach trend detection
APPROACH_HISTORY_MAXLEN = 6     # rolling window size (~30 min at 5-min intervals)
APPROACH_HISTORY_MIN_POINTS = 3 # samples needed before publishing a trend
MIN_APPROACH_SPEED_KMH = 1.0    # speeds below this are treated as pixel-level noise
MAX_BEARING_STD_DEG = 30.0      # max circular std-dev of bearings to confirm same cell

# Rough reference colors for RainViewer color scheme 2 → dBZ mapping.
# These RGB tuples represent the dominant hue bands in the palette.
# Nearest-hue matching is used at runtime (see coordinator.rgb_to_dbz).
DBZ_COLOR_REFERENCES = [
    # (R,   G,   B,  dBZ)
    (0,   255, 255,   5),   # cyan
    (0,   160, 255,  10),   # sky-blue
    (0,    64, 255,  15),   # blue
    (0,   200,   0,  20),   # green
    (0,   128,   0,  25),   # dark green
    (255, 255,   0,  30),   # yellow
    (255, 200,   0,  35),   # amber
    (255, 128,   0,  40),   # orange
    (255,   0,   0,  45),   # red
    (200,   0,   0,  50),   # dark red
    (255,   0, 255,  55),   # magenta
    (160,   0, 255,  60),   # purple
    (100,   0, 128,  65),   # dark purple
]
