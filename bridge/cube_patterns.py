#!/usr/bin/env python3
"""
State → pixel art mappings for Yeelight Cube Smart Lamp Lite.

Maps each AI agent state to a text label, RGB color, and animation type.
Used by yeelight_cube_lite.py to render status on the 20×5 LED matrix.

Color semantics match the existing yeelight-vibe-bridge state color reference:
  - Blue family: thinking/reading/writing/fetching (active work)
  - Green: querying (context gathering)
  - Orange/amber: executing/waiting (caution/action)
  - Red: error (stop)
  - Warm white: success (done)

Animation types:
  - "solid": static display, no animation
  - "breathe": slow brightness pulse (for active work states)
  - "flash": rapid on/off blink (for network access)
  - "blink": periodic blink (for error)
  - "pulse_slow": slow pulse (for waiting)
"""

# ═══════════════ State Definitions ═══════════════

STATE_DEFS = {
    "idle": {
        "text": "IDLE",
        "rgb": (68, 136, 255),
        "animation": "solid",
        "brightness": 15,
        "label": "Ice blue idle",
    },
    "waiting": {
        "text": "WAIT",
        "rgb": (255, 140, 0),
        "animation": "pulse_slow",
        "brightness": 40,
        "label": "Waiting for user",
    },
    "success": {
        "text": "DONE",
        "rgb": (255, 240, 230),
        "animation": "solid",
        "brightness": 25,
        "label": "Task complete",
    },
    "error": {
        "text": "ERR!",
        "rgb": (255, 30, 30),
        "animation": "blink",
        "brightness": 50,
        "label": "Error stop",
    },
    "thinking": {
        "text": "THINK",
        "rgb": (0, 68, 255),
        "animation": "breathe",
        "brightness": 50,
        "label": "Thinking",
    },
    "reading": {
        "text": "READ",
        "rgb": (0, 200, 255),
        "animation": "breathe",
        "brightness": 50,
        "label": "Reading files",
    },
    "writing": {
        "text": "WRITE",
        "rgb": (255, 50, 120),
        "animation": "breathe",
        "brightness": 50,
        "label": "Writing editing",
    },
    "executing": {
        "text": "EXEC",
        "rgb": (220, 90, 0),
        "animation": "breathe",
        "brightness": 50,
        "label": "Executing command",
    },
    "querying": {
        "text": "QUERY",
        "rgb": (0, 160, 100),
        "animation": "breathe",
        "brightness": 50,
        "label": "Querying context",
    },
    "fetching": {
        "text": "FETCH",
        "rgb": (0, 100, 255),
        "animation": "flash",
        "brightness": 40,
        "label": "Accessing network",
    },
    "off": {
        "text": "",
        "rgb": (0, 0, 0),
        "animation": "solid",
        "brightness": 0,
        "label": "Off",
    },
}

# Alias names matching the existing relay's _ALIASES map
STATE_ALIASES = {
    "green": "idle",
    "orange": "waiting",
    "flash": "thinking",
    "context": "querying",
    "bash": "executing",
    "web": "fetching",
    "read": "reading",
    "write": "writing",
    "purple": "writing",
    "cyan": "reading",
}

# Priority ordering for multi-session coordination (lower = higher priority)
# Matches the existing relay's _PRIORITY map
STATE_PRIORITY = {
    "error": 0,
    "fetching": 1,
    "executing": 2,
    "writing": 3,
    "reading": 4,
    "querying": 5,
    "thinking": 6,
    "waiting": 7,
    "idle": 8,
    "success": 9,
    "off": 99,
}

# Animation configuration
ANIMATION_CONFIG = {
    "breathe": {
        "frames": 10,
        "cycle_ms": 2000,
        "brightness_curve": [100, 90, 70, 50, 30, 20, 20, 30, 50, 70, 90],
    },
    "flash": {
        "frames": 6,
        "cycle_ms": 900,
        "brightness_curve": [100, 60, 100, 60, 100, 60],
    },
    "blink": {
        "frames": 4,
        "cycle_ms": 1200,
        "brightness_curve": [100, 0, 100, 0],
    },
    "pulse_slow": {
        "frames": 10,
        "cycle_ms": 3000,
        "brightness_curve": [100, 90, 80, 70, 60, 60, 70, 80, 90, 100],
    },
}
