"""Colores de la interfaz y utilidades compartidas entre pestañas."""
import os
from pathlib import Path

BG, PANEL, FG, MUTED, ACCENT = "#1e1f22", "#2b2d31", "#e6e6e6", "#a0a0a0", "#c62828"
FIELD = "#3a3c42"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "yama-control"


def hex_color(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def parse_hex(text: str):
    """'#ff8000' o 'ff8000' → (255, 128, 0); None si no es válido."""
    text = text.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def text_color(rgb) -> str:
    r, g, b = rgb
    return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#ffffff"
