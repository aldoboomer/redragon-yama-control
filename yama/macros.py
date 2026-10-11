"""Formato de macros en la memoria del teclado.

Bloque completo (comando 0x09 lee / 0x0A escribe desde el offset 0):

    u16 0x55AA | u16 largo total | u16 cantidad | u16 1 (incluye nombres) | 8 bytes 0
    u16 offset de cada macro
    por macro: u16 n_eventos | u8 repeticiones | u8 largo del nombre
               n_eventos × 4 bytes | nombre en UTF-16LE

Evento (4 bytes):
    u16  bits 0-11 espera en decenas de ms, bits 12-14 tipo (2 = teclado),
         bit 15 = tecla presionada (0 = soltada)
    u8   1 = modificador (siguiente byte es máscara) / 2 = tecla (código HID)
    u8   máscara o código HID
"""
from __future__ import annotations

import ctypes
import struct
import sys
import unicodedata
from dataclasses import dataclass, field

TYPE_KEY = 2

MOD_LCTRL, MOD_LSHIFT, MOD_LALT, MOD_LWIN = 0x01, 0x02, 0x04, 0x08
MOD_RCTRL, MOD_RSHIFT, MOD_RALT, MOD_RWIN = 0x10, 0x20, 0x40, 0x80

MOD_NAMES = {
    MOD_LCTRL: "Ctrl", MOD_LSHIFT: "Shift", MOD_LALT: "Alt", MOD_LWIN: "Win",
    MOD_RCTRL: "Ctrl der.", MOD_RSHIFT: "Shift der.", MOD_RALT: "AltGr", MOD_RWIN: "Win der.",
}

# Nombres según las teclas impresas en un teclado latinoamericano.
HID_NAMES = {
    **{0x04 + i: chr(ord("A") + i) for i in range(26)},
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5", 0x23: "6", 0x24: "7",
    0x25: "8", 0x26: "9", 0x27: "0",
    0x28: "Enter", 0x29: "Esc", 0x2A: "Retroceso", 0x2B: "Tab", 0x2C: "Espacio",
    0x2D: "' ?", 0x2E: "¿ ¡", 0x2F: "´ ¨", 0x30: "+ *", 0x31: "} ]", 0x32: "} ]",
    0x33: "Ñ", 0x34: "{ [", 0x35: "| °", 0x36: ", ;", 0x37: ". :", 0x38: "- _",
    0x39: "BloqMayús",
    **{0x3A + i: f"F{i + 1}" for i in range(12)},
    0x46: "ImpPnt", 0x47: "BloqDes", 0x48: "Pausa", 0x49: "Insert", 0x4A: "Inicio",
    0x4B: "RePág", 0x4C: "Supr", 0x4D: "Fin", 0x4E: "AvPág", 0x4F: "→", 0x50: "←",
    0x51: "↓", 0x52: "↑", 0x53: "BloqNum", 0x54: "Num /", 0x55: "Num *", 0x56: "Num -",
    0x57: "Num +", 0x58: "Num Intro",
    **{0x59 + i: f"Num {i + 1}" for i in range(9)},
    0x62: "Num 0", 0x63: "Num .", 0x64: "< >", 0x65: "Menú",
}

# Código de escaneo (set 1) → código HID. Las teclas extendidas llevan 0xE000.
SCAN_TO_HID = {
    0x01: 0x29, 0x0C: 0x2D, 0x0D: 0x2E, 0x0E: 0x2A, 0x0F: 0x2B,
    0x1A: 0x2F, 0x1B: 0x30, 0x1C: 0x28, 0x27: 0x33, 0x28: 0x34, 0x29: 0x35,
    0x2B: 0x31, 0x33: 0x36, 0x34: 0x37, 0x35: 0x38, 0x37: 0x55, 0x39: 0x2C,
    0x3A: 0x39, 0x45: 0x53, 0x46: 0x47, 0x47: 0x5F, 0x48: 0x60, 0x49: 0x61,
    0x4A: 0x56, 0x4B: 0x5C, 0x4C: 0x5D, 0x4D: 0x5E, 0x4E: 0x57, 0x4F: 0x59,
    0x50: 0x5A, 0x51: 0x5B, 0x52: 0x62, 0x53: 0x63, 0x56: 0x64, 0x57: 0x44,
    0x58: 0x45,
    0xE01C: 0x58, 0xE035: 0x54, 0xE037: 0x46, 0xE047: 0x4A, 0xE048: 0x52,
    0xE049: 0x4B, 0xE04B: 0x50, 0xE04D: 0x4F, 0xE04F: 0x4D, 0xE050: 0x51,
    0xE051: 0x4E, 0xE052: 0x49, 0xE053: 0x4C, 0xE05D: 0x65,
}
SCAN_TO_HID.update({0x02 + i: 0x1E + i for i in range(10)})                      # 1..0
SCAN_TO_HID.update({0x3B + i: 0x3A + i for i in range(10)})                      # F1..F10
SCAN_TO_HID.update(zip(range(0x10, 0x1A), (0x14, 0x1A, 0x08, 0x15, 0x17, 0x1C, 0x18, 0x0C, 0x12, 0x13)))
SCAN_TO_HID.update(zip(range(0x1E, 0x27), (0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F)))
SCAN_TO_HID.update(zip(range(0x2C, 0x33), (0x1D, 0x1B, 0x06, 0x19, 0x05, 0x11, 0x10)))

SCAN_TO_MOD = {
    0x1D: MOD_LCTRL, 0x2A: MOD_LSHIFT, 0x38: MOD_LALT, 0x36: MOD_RSHIFT,
    0xE01D: MOD_RCTRL, 0xE038: MOD_RALT, 0xE05B: MOD_LWIN, 0xE05C: MOD_RWIN,
}

VK_PAUSE = 0x13


@dataclass
class Event:
    is_modifier: bool
    code: int           # máscara de modificador o código HID
    down: bool
    delay_ms: int = 20  # espera DESPUÉS de este evento
    raw_kind: int = TYPE_KEY
    raw_b2: int | None = None  # para eventos que no son de teclado (se conservan tal cual)

    def label(self) -> str:
        if self.raw_kind != TYPE_KEY:
            return f"(evento tipo {self.raw_kind}, sin editar)"
        if self.is_modifier:
            return MOD_NAMES.get(self.code, f"Mod 0x{self.code:02X}")
        return HID_NAMES.get(self.code, f"Tecla 0x{self.code:02X}")


@dataclass
class Macro:
    name: str
    events: list[Event] = field(default_factory=list)
    repeat: int = 1


def _encode_event(ev: Event) -> bytes:
    word = min(max(ev.delay_ms, 0) // 10, 0xFFF) | (ev.raw_kind << 12) | (0x8000 if ev.down else 0)
    if ev.raw_kind != TYPE_KEY:
        return struct.pack("<HBB", word, ev.raw_b2 or 0, ev.code)
    return struct.pack("<HBB", word, 1 if ev.is_modifier else 2, ev.code)


def _decode_event(raw: bytes) -> Event:
    word, b2, b3 = struct.unpack("<HBB", raw)
    kind = (word >> 12) & 0x7
    ev = Event(is_modifier=(kind == TYPE_KEY and b2 == 1), code=b3, down=bool(word & 0x8000),
               delay_ms=(word & 0xFFF) * 10, raw_kind=kind)
    if kind != TYPE_KEY:
        ev.raw_b2 = b2
    return ev


def encode_blob(macros: list[Macro], names: bool = True) -> bytes:
    """names=False omite los nombres (2 bytes por letra), como hace el programa
    oficial cuando falta espacio; al leerlas se llaman «Macro N»."""
    table_end = 0x10 + 2 * len(macros)
    table, body = b"", b""
    for m in macros:
        table += struct.pack("<H", table_end + len(body))
        name = m.name[:255] if names else ""
        body += struct.pack("<HBB", len(m.events), max(1, min(m.repeat, 255)), len(name))
        body += b"".join(_encode_event(e) for e in m.events)
        body += name.encode("utf-16-le")
    total = table_end + len(body)
    return struct.pack("<HHHH", 0x55AA, total, len(macros), int(names)) + bytes(8) + table + body


def decode_blob(blob: bytes) -> list[Macro]:
    if len(blob) < 0x10 or blob[:2] != b"\xaa\x55":
        return []
    _, total, count, has_names = struct.unpack_from("<HHHH", blob, 0)
    macros = []
    for i in range(count):
        (off,) = struct.unpack_from("<H", blob, 0x10 + 2 * i)
        n_events, repeat, name_len = struct.unpack_from("<HBB", blob, off)
        pos = off + 4
        events = [_decode_event(blob[pos + 4 * k:pos + 4 * k + 4]) for k in range(n_events)]
        pos += 4 * n_events
        name = blob[pos:pos + 2 * name_len].decode("utf-16-le", "replace") if has_names else ""
        macros.append(Macro(name=name or f"Macro {i + 1}", events=events, repeat=repeat))
    return macros


# --- Windows: teclas virtuales → códigos HID ------------------------------

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.VkKeyScanW.restype = ctypes.c_short
    _user32.MapVirtualKeyW.restype = ctypes.c_uint

    def _vk_to_scan(vk: int) -> int:
        return _user32.MapVirtualKeyW(vk, 4)  # MAPVK_VK_TO_VSC_EX: incluye prefijo E0

    def _is_dead_key(vk: int, state: int) -> bool:
        """True si vk con ese estado (1 Shift, 2 Ctrl, 4 Alt) es una tecla muerta."""
        keys = (ctypes.c_ubyte * 256)()
        if state & 1:
            keys[0x10] = 0x80
        if state & 2:
            keys[0x11] = 0x80
        if state & 4:
            keys[0x12] = 0x80
        out = ctypes.create_unicode_buffer(8)
        layout = _user32.GetKeyboardLayout(0)
        res = _user32.ToUnicodeEx(vk, _vk_to_scan(vk), keys, out, 8, 0, layout)
        if res < 0:  # dejó la tecla muerta pendiente: la limpiamos con un espacio
            _user32.ToUnicodeEx(0x20, 0x39, (ctypes.c_ubyte * 256)(), out, 8, 0, layout)
            return True
        return False

    def _vk_scan(ch: str) -> int:
        return _user32.VkKeyScanW(ord(ch))
else:  # pragma: no cover - solo se usa en Windows
    def _vk_to_scan(vk): return 0
    def _is_dead_key(vk, state): return False
    def _vk_scan(ch): return -1


# Teclas que Tk entrega con nombre propio (sin depender del código virtual)
KEYSYM_TO_EVENT = {
    "Shift_L": (True, MOD_LSHIFT), "Shift_R": (True, MOD_RSHIFT),
    "Control_L": (True, MOD_LCTRL), "Control_R": (True, MOD_RCTRL),
    "Alt_L": (True, MOD_LALT), "Alt_R": (True, MOD_RALT),
    "Win_L": (True, MOD_LWIN), "Win_R": (True, MOD_RWIN),
    "Super_L": (True, MOD_LWIN), "Super_R": (True, MOD_RWIN),
    "App": (False, 0x65), "Pause": (False, 0x48),
    "Up": (False, 0x52), "Down": (False, 0x51), "Left": (False, 0x50), "Right": (False, 0x4F),
    "Home": (False, 0x4A), "End": (False, 0x4D), "Prior": (False, 0x4B), "Next": (False, 0x4E),
    "Insert": (False, 0x49), "Delete": (False, 0x4C), "Print": (False, 0x46),
    "KP_Enter": (False, 0x58), "KP_Divide": (False, 0x54), "Num_Lock": (False, 0x53),
}


def tk_key_to_event(keysym: str, keycode: int) -> tuple[bool, int] | None:
    """(es_modificador, código) para una tecla capturada en Tk, o None si no se reconoce."""
    if keysym in KEYSYM_TO_EVENT:
        return KEYSYM_TO_EVENT[keysym]
    if keycode == VK_PAUSE:
        return (False, 0x48)
    scan = _vk_to_scan(keycode)
    if scan in SCAN_TO_MOD:
        return (True, SCAN_TO_MOD[scan])
    if scan in SCAN_TO_HID:
        return (False, SCAN_TO_HID[scan])
    return None


def _keystroke(ch: str) -> list[tuple[int, int, bool]] | None:
    """[(mods, hid, es_tecla_muerta)] para producir el carácter con el layout actual."""
    res = _vk_scan(ch)
    if res == -1:
        return None
    vk, state = res & 0xFF, (res >> 8) & 0xFF
    mods = 0
    if state & 6 == 6:          # Ctrl+Alt = AltGr
        mods |= MOD_RALT
    else:
        if state & 2:
            mods |= MOD_LCTRL
        if state & 4:
            mods |= MOD_LALT
    if state & 1:
        mods |= MOD_LSHIFT
    hid = SCAN_TO_HID.get(_vk_to_scan(vk))
    if hid is None:
        return None
    return [(mods, hid, _is_dead_key(vk, state))]


_COMBINING_TO_SPACING = {"́": "´", "̈": "¨", "̀": "`", "̂": "^", "̃": "~"}


def text_to_events(text: str, delay_ms: int = 20) -> tuple[list[Event], list[str]]:
    """Convierte texto en pulsaciones según el layout de Windows activo.

    Devuelve (eventos, caracteres que no se pudieron escribir).
    """
    events: list[Event] = []
    missing: list[str] = []

    def press(mods: int, hid: int):
        for bit in (MOD_LSHIFT, MOD_LCTRL, MOD_LALT, MOD_RALT):
            if mods & bit:
                events.append(Event(True, bit, True, delay_ms))
        events.append(Event(False, hid, True, delay_ms))
        events.append(Event(False, hid, False, delay_ms))
        for bit in (MOD_RALT, MOD_LALT, MOD_LCTRL, MOD_LSHIFT):
            if mods & bit:
                events.append(Event(True, bit, False, delay_ms))

    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            press(0, 0x28)
            continue
        if ch == "\t":
            press(0, 0x2B)
            continue
        strokes = _keystroke(ch)
        if strokes is None:
            # á = tecla muerta ´ + a, ü = ¨ + u, etc.
            base, *marks = unicodedata.normalize("NFD", ch)
            if len(marks) == 1 and marks[0] in _COMBINING_TO_SPACING:
                dead = _keystroke(_COMBINING_TO_SPACING[marks[0]])
                letter = _keystroke(base)
                if dead and letter:
                    press(*dead[0][:2])
                    press(*letter[0][:2])
                    continue
            missing.append(ch)
            continue
        mods, hid, dead = strokes[0]
        press(mods, hid)
        if dead:  # el símbolo solo sale si después va un espacio
            press(0, 0x2C)
    return events, missing
