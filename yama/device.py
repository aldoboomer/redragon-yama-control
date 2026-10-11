"""Comunicación USB con el Redragon K550RGB-1 (Yama), VID 320F / PID 5000.

Protocolo (descifrado del programa oficial y verificado en el teclado):
paquetes de 64 bytes por la colección HID vendor 0xFF1C/0x92.

    [0]    report id = 0x04
    [1:3]  checksum = suma de bytes [3:64], uint16 little-endian
    [3]    comando
    [4]    largo de los datos (máx. 0x38)
    [5:7]  offset uint16 little-endian
    [7]    0 (en la respuesta: 0xFF / 0xFE = error)
    [8:]   datos

Cada sesión de escritura va entre BEGIN (0x01) y END (0x02).

Ojo: los LEDs reciben el color en orden G, R, B. El programa de Redragon
manda R, G, B y por eso rojo y verde salen cambiados. Aquí se convierte
siempre en esta capa: el resto del código trabaja en RGB normal.
"""
from __future__ import annotations

import contextlib

import hid

VID, PID = 0x320F, 0x5000
USAGE_PAGE = 0xFF1C

CMD_BEGIN = 0x01
CMD_END = 0x02
CMD_READ_CAPABILITIES = 0x03
CMD_READ_CONFIG = 0x05
CMD_WRITE_CONFIG = 0x06
CMD_READ_KEYMAP = 0x07
CMD_WRITE_KEYMAP = 0x08
CMD_READ_MACROS = 0x09
CMD_WRITE_MACROS = 0x0A
CMD_READ_COLORS = 0x10
CMD_WRITE_COLORS = 0x11

CHUNK = 0x38
PROFILES = 3

CONFIG_STRIDE = 0x2A      # bloque de iluminación por perfil
KEYMAP_STRIDE = 0x200     # mapa de teclas por perfil
KEYMAP_SIZE = 0x1B0       # 144 entradas de 3 bytes
COLORS_STRIDE = 0x200     # colores "personalizado" por perfil
LED_COUNT = 144
COLORS_SIZE = LED_COUNT * 3

# Espacio para macros = byte 11 de las capacidades × 128 (así lo calcula el
# programa oficial). En el Yama vale 0x18 → 3072 bytes; se usa si no se puede leer.
MACRO_AREA_LIMIT = 0xC00


class KeyboardNotFound(Exception):
    pass


class ProtocolError(Exception):
    pass


def _packet(cmd: int, size: int = 0, offset: int = 0, data: bytes = b"") -> bytes:
    buf = bytearray(64)
    buf[0] = 0x04
    buf[3] = cmd
    buf[4] = size
    buf[5] = offset & 0xFF
    buf[6] = (offset >> 8) & 0xFF
    buf[8:8 + len(data)] = data
    checksum = sum(buf[3:]) & 0xFFFF
    buf[1] = checksum & 0xFF
    buf[2] = checksum >> 8
    return bytes(buf)


def rgb_to_device(rgb: tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    return bytes((g, r, b))


def device_to_rgb(raw: bytes) -> tuple[int, int, int]:
    g, r, b = raw[0], raw[1], raw[2]
    return (r, g, b)


class Yama:
    def __init__(self):
        path = None
        for info in hid.enumerate(VID, PID):
            if info["usage_page"] == USAGE_PAGE:
                path = info["path"]
                break
        if path is None:
            raise KeyboardNotFound(
                "No encontré el Redragon Yama (USB 320F:5000). "
                "¿Está conectado? Cierra el programa de Redragon si está abierto."
            )
        self._dev = hid.device()
        self._dev.open_path(path)

    def close(self):
        self._dev.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- transporte -------------------------------------------------------

    def _xfer(self, cmd: int, size: int = 0, offset: int = 0, data: bytes = b"") -> bytes:
        self._dev.write(_packet(cmd, size, offset, data))
        resp = bytes(self._dev.read(64, 1000))
        if len(resp) < 8:
            raise ProtocolError(f"El teclado no respondió al comando 0x{cmd:02X}")
        if resp[7] in (0xFF, 0xFE) or resp[3] != cmd:
            raise ProtocolError(f"El teclado rechazó el comando 0x{cmd:02X} (offset 0x{offset:X})")
        return resp

    @contextlib.contextmanager
    def session(self):
        self._xfer(CMD_BEGIN)
        try:
            yield self
        finally:
            self._xfer(CMD_END)

    def _read(self, cmd: int, total: int, base: int = 0) -> bytes:
        out = bytearray()
        for off in range(0, total, CHUNK):
            n = min(CHUNK, total - off)
            resp = self._xfer(cmd, n, base + off)
            out += resp[8:8 + n]
        return bytes(out)

    def _write(self, cmd: int, data: bytes, base: int = 0):
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            self._xfer(cmd, len(chunk), base + off, chunk)

    # --- iluminación ------------------------------------------------------

    def read_lighting(self, profile: int) -> dict:
        raw = self._read(CMD_READ_CONFIG, CONFIG_STRIDE, profile * CONFIG_STRIDE)
        return {
            "mode": raw[0],
            "brightness": raw[1],
            "speed": raw[2],
            "direction": raw[3],
            "random": raw[4],
            "color": device_to_rgb(raw[5:8]),
        }

    def read_active_profile(self) -> int:
        raw = self._read(CMD_READ_CONFIG, CONFIG_STRIDE * PROFILES)
        for p in range(PROFILES):
            if raw[p * CONFIG_STRIDE + 0x11] == 1:
                return p
        return 0

    def write_lighting(self, profile: int, mode: int, brightness: int, speed: int,
                       direction: int, random: int, color: tuple[int, int, int]):
        data = bytes((mode, brightness, speed, direction, random)) + rgb_to_device(color)
        self._write(CMD_WRITE_CONFIG, data, profile * CONFIG_STRIDE)

    def read_colors(self, profile: int) -> list[tuple[int, int, int]]:
        raw = self._read(CMD_READ_COLORS, COLORS_SIZE, profile * COLORS_STRIDE)
        return [device_to_rgb(raw[i * 3:i * 3 + 3]) for i in range(LED_COUNT)]

    def write_colors(self, profile: int, colors: list[tuple[int, int, int]]):
        data = b"".join(rgb_to_device(c) for c in colors)
        self._write(CMD_WRITE_COLORS, data, profile * COLORS_STRIDE)

    # --- teclas y macros --------------------------------------------------

    def read_keymap(self, profile: int) -> bytes:
        return self._read(CMD_READ_KEYMAP, KEYMAP_SIZE, profile * KEYMAP_STRIDE)

    def write_keymap_entries(self, profile: int, entries: dict[int, bytes]):
        """Escribe solo los bloques del mapa que contienen entradas cambiadas."""
        current = bytearray(self.read_keymap(profile))
        original = bytes(current)
        for idx, entry in entries.items():
            current[idx * 3:idx * 3 + 3] = entry
        for off in range(0, KEYMAP_SIZE, CHUNK):
            if current[off:off + CHUNK] != original[off:off + CHUNK]:
                self._write(CMD_WRITE_KEYMAP, bytes(current[off:off + CHUNK]),
                            profile * KEYMAP_STRIDE + off)

    def read_macro_limit(self) -> int:
        caps = self._xfer(CMD_READ_CAPABILITIES, 0x2C)[8:8 + 0x2C]
        return caps[11] * 128 or MACRO_AREA_LIMIT

    def read_macros_blob(self) -> bytes:
        head = self._read(CMD_READ_MACROS, 0x10)
        if head[:2] != b"\xaa\x55":
            return b""
        total = int.from_bytes(head[2:4], "little")
        if not 0x10 <= total <= self.read_macro_limit():
            return b""
        return self._read(CMD_READ_MACROS, total)

    def write_macros_blob(self, blob: bytes):
        limit = self.read_macro_limit()
        if len(blob) > limit:
            raise ValueError(
                f"Las macros ocupan {len(blob)} bytes y el teclado admite {limit}. "
                "Acorta o borra alguna."
            )
        self._write(CMD_WRITE_MACROS, blob)

    # --- respaldo ---------------------------------------------------------

    def dump(self) -> dict:
        return {
            "format": "yama-control/1",
            "config": self._read(CMD_READ_CONFIG, CONFIG_STRIDE * PROFILES).hex(),
            "keymaps": [self.read_keymap(p).hex() for p in range(PROFILES)],
            "colors": [self._read(CMD_READ_COLORS, COLORS_SIZE, p * COLORS_STRIDE).hex()
                       for p in range(PROFILES)],
            "macros": self.read_macros_blob().hex(),
        }

    def restore(self, data: dict):
        if data.get("format") != "yama-control/1":
            raise ValueError("Este archivo no es un respaldo de yama-control.")
        self._write(CMD_WRITE_CONFIG, bytes.fromhex(data["config"]))
        for p, km in enumerate(data["keymaps"]):
            self._write(CMD_WRITE_KEYMAP, bytes.fromhex(km), p * KEYMAP_STRIDE)
        for p, cols in enumerate(data["colors"]):
            self._write(CMD_WRITE_COLORS, bytes.fromhex(cols), p * COLORS_STRIDE)
        if data["macros"]:
            self.write_macros_blob(bytes.fromhex(data["macros"]))
