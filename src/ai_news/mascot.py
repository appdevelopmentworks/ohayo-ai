"""Nyusuke's faces: eyes and mouth per mood (viewBox 0 0 160 170), from docs/design/README.md."""

MOODS = {
    "normal": {"arcs": False, "r": 6, "lx": 64, "rx": 96, "ey": 74,
               "mouth": "M72 86 Q80 93 88 86", "mouth_fill": "none"},
    "surprised": {"arcs": False, "r": 8.5, "lx": 64, "rx": 96, "ey": 73,
                  "mouth": "M76 89 Q80 82 84 89 Q80 96 76 89 Z", "mouth_fill": "#FFFFFF"},
    "smile": {"arcs": True, "r": 6, "lx": 64, "rx": 96, "ey": 74,
              "mouth": "M70 84 Q80 97 90 84 Z", "mouth_fill": "#FFFFFF"},
    "think": {"arcs": False, "r": 5, "lx": 67, "rx": 99, "ey": 70,
              "mouth": "M74 89 L87 86", "mouth_fill": "none"},
}  # fmt: skip

# Which face goes with which AI weather.
WEATHER_MOODS = {"thunder": "surprised", "cloudy": "think", "sunny": "smile"}
