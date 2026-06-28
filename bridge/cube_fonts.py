#!/usr/bin/env python3
"""
Font bitmap data for Yeelight Cube Smart Lamp Lite (20×5 matrix).

Subset of the "basic" font from yeelight-cube-lite Home Assistant integration
(https://github.com/Max-src/yeelight-cube-lite, MIT licensed).

Pixel index: row * 20 + col
  Row 0 (bottom): indices 0-19
  Row 1:          indices 20-39
  Row 2:          indices 40-59
  Row 3:          indices 60-79
  Row 4 (top):    indices 80-99

Each character occupies 3 columns with a 1-column gap before the next char.
Characters wider than 3 columns (M, W) use 5 columns.

Characters included: A-Z, 0-9, !
"""

TOTAL_COLUMNS = 20
TOTAL_ROWS = 5
TOTAL_PIXELS = 100

# Character widths (columns): most are 3, M and W are 5
CHAR_WIDTHS = {
    "A": 3, "B": 3, "C": 3, "D": 3, "E": 3, "F": 3, "G": 3, "H": 3,
    "I": 3, "J": 3, "K": 3, "L": 3, "M": 5, "N": 3, "O": 3, "P": 3,
    "Q": 3, "R": 3, "S": 3, "T": 3, "U": 3, "V": 3, "W": 5, "X": 3,
    "Y": 3, "Z": 3,
    "0": 3, "1": 3, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 3,
    "8": 3, "9": 3,
    "!": 1, " ": 1,
}

# Font bitmap: each character maps to a list of pixel indices (0-99)
# where LEDs should be lit. Characters are 3-wide (5-wide for M, W).
# Source: yeelight-cube-lite FONT_MAPS["basic"], MIT licensed.
BASIC_FONT = {
    "A": [0, 20, 40, 60, 81, 41, 62, 42, 22, 2],
    "B": [0, 20, 40, 60, 80, 81, 41, 1, 62, 22],
    "C": [1, 2, 20, 40, 60, 81, 82],
    "D": [0, 1, 20, 40, 60, 80, 81, 62, 42, 22],
    "E": [0, 1, 2, 20, 40, 41, 60, 80, 81, 82],
    "F": [0, 20, 40, 41, 60, 80, 81, 82],
    "G": [1, 2, 20, 22, 40, 42, 60, 81, 82],
    "H": [0, 2, 20, 22, 40, 41, 42, 60, 62, 80, 82],
    "I": [0, 1, 2, 21, 41, 61, 80, 81, 82],
    "J": [1, 20, 22, 42, 62, 82],
    "K": [0, 2, 20, 22, 40, 41, 60, 62, 80, 82],
    "L": [0, 1, 2, 20, 40, 60, 80],
    "M": [0, 20, 40, 60, 80, 81, 62, 42, 22, 2, 83, 64, 44, 24, 4],
    "N": [0, 20, 40, 60, 80, 81, 62, 42, 22, 2],
    "O": [1, 20, 22, 40, 42, 60, 62, 81, 0, 2, 80, 82],
    "P": [0, 20, 40, 41, 60, 62, 80, 81],
    "Q": [1, 2, 20, 22, 40, 42, 60, 62, 81],
    "R": [0, 2, 20, 22, 40, 41, 60, 62, 80, 81],
    "S": [0, 1, 22, 42, 41, 40, 60, 81, 82],
    "T": [1, 21, 41, 61, 80, 81, 82],
    "U": [1, 2, 20, 22, 40, 42, 60, 62, 80, 82],
    "V": [1, 20, 22, 40, 42, 60, 62, 80, 82],
    "W": [1, 3, 4, 20, 22, 24, 40, 42, 44, 60, 62, 64, 80, 82, 84],
    "X": [0, 2, 20, 22, 41, 60, 62, 80, 82],
    "Y": [1, 21, 41, 60, 62, 80, 82],
    "Z": [0, 1, 2, 20, 41, 62, 80, 81, 82],
    "0": [1, 20, 22, 40, 42, 60, 62, 81, 0, 2, 80, 82],
    "1": [0, 1, 2, 21, 41, 61, 81, 80],
    "2": [0, 1, 2, 20, 41, 62, 80, 81, 82, 42, 40],
    "3": [0, 1, 22, 41, 62, 80, 81, 2, 42, 82],
    "4": [2, 22, 40, 41, 42, 60, 62, 80, 82],
    "5": [0, 1, 22, 40, 41, 60, 80, 81, 82, 2, 42],
    "6": [1, 20, 22, 40, 41, 60, 81, 82, 80, 42, 0, 2],
    "7": [1, 21, 41, 62, 80, 81, 82],
    "8": [1, 20, 22, 41, 60, 62, 81, 0, 2, 80, 82, 40, 42],
    "9": [0, 1, 22, 41, 42, 60, 62, 81, 80, 82, 40, 2],
    "!": [0, 40, 60, 80],
    " ": [],
}


def get_char_width(ch: str) -> int:
    """Return the column width of a character in the basic font."""
    return CHAR_WIDTHS.get(ch.upper(), 3)


def get_char_pixels(ch: str) -> list:
    """Return list of pixel indices (0-99) for a character in basic font."""
    return BASIC_FONT.get(ch.upper(), [])


def render_text_to_pixels(text: str, offset_col: int = 0) -> list:
    """Convert text to a flat list of (pixel_index, is_lit) for the given column offset.

    Returns list of pixel indices where LEDs should be on, shifted by offset_col.
    Characters are rendered with 1-column spacing between them.
    """
    lit_pixels = []
    x_cursor = offset_col

    for ch in text.upper():
        char_pixels = get_char_pixels(ch)
        char_width = get_char_width(ch)

        for p in char_pixels:
            row = p // 20
            col = p % 20
            new_col = col + x_cursor
            if 0 <= new_col < TOTAL_COLUMNS:
                lit_pixels.append(row * 20 + new_col)

        x_cursor += char_width + 1  # char width + 1 column gap

    return lit_pixels


def layout_text_centered(text: str) -> list:
    """Center text on the 20×5 matrix. Returns list of pixel indices to light.

    Calculates total text width (sum of char widths + gaps between chars),
    then offsets to center on the 20-column display.
    """
    total_width = sum(get_char_width(c) for c in text.upper()) + (len(text) - 1)
    offset = max(0, (TOTAL_COLUMNS - total_width) // 2)
    return render_text_to_pixels(text, offset)
