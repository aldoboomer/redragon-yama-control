"""Efectos de iluminación: qué controles usa cada uno y su vista previa en pantalla.

Qué parámetros respeta cada efecto viene de la tabla de OpenRGB para este
mismo chip (EVision). «Estrellas lentas» y «Cruce» no están en esa tabla y
se asumen iguales a sus parientes.

La vista previa es una aproximación dibujada por el programa: el teclado
hace su propia animación. Nunca se manda nada al teclado mientras se anima.
"""
from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass

from . import layout

CUSTOM = 0x14


@dataclass(frozen=True)
class Effect:
    code: int
    name: str
    speed: bool = False
    color: bool = False
    random: bool = False
    direction: str | None = None   # "lr" (horizontal) o "ud" (vertical)
    hint: str = ""


EFFECTS = [
    Effect(CUSTOM, "Personalizado (color por tecla)", hint="Pinta cada tecla abajo. Solo usa el brillo."),
    Effect(0x06, "Fijo", color=True, random=True),
    Effect(0x05, "Respiración", speed=True, color=True, random=True),
    Effect(0x04, "Ciclo de colores", speed=True, hint="Siempre recorre todos los colores."),
    Effect(0x01, "Ola corta", True, True, True, "lr"),
    Effect(0x02, "Ola larga", True, True, True, "lr"),
    Effect(0x03, "Rueda de color", True, True, True, "lr"),
    Effect(0x0C, "Arcoíris vertical", True, True, True, "ud"),
    Effect(0x12, "Arcoíris circular", hint="Siempre multicolor; solo usa el brillo."),
    Effect(0x07, "Reactivo: se enciende al pulsar", True, True, True,
           hint="En la vista previa se simulan pulsaciones al azar."),
    Effect(0x08, "Reactivo: onda al pulsar", True, True, True,
           hint="En la vista previa se simulan pulsaciones al azar."),
    Effect(0x09, "Reactivo: línea al pulsar", True, True, True,
           hint="En la vista previa se simulan pulsaciones al azar."),
    Effect(0x0A, "Estrellas rápidas", True, True, True),
    Effect(0x0F, "Estrellas lentas", True, True, True),
    Effect(0x0B, "Flores", True, True, True),
    Effect(0x0D, "Huracán", True, True, True),
    Effect(0x0E, "Acumular", True, True, True,
           hint="Las teclas que pulsas quedan encendidas; en la vista previa se simulan."),
    Effect(0x10, "Ida y vuelta", color=True, random=True),
    Effect(0x11, "Cruce", True, True, True),
]
BY_CODE = {e.code: e for e in EFFECTS}
BY_NAME = {e.name: e for e in EFFECTS}

DIRECTIONS = {
    "lr": [(0x00, "Izquierda → derecha"), (0xFF, "Derecha → izquierda")],
    "ud": [(0x00, "Abajo → arriba"), (0xFF, "Arriba → abajo")],
}

BLACK = (0, 0, 0)


def hue(h: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))


class Preview:
    """Calcula el color de cada tecla dibujada para un instante t (segundos)."""

    def __init__(self):
        self.centers = [(x + w / 2, y + h / 2) for _, x, y, w, h, _ in layout.KEYS]
        self.cx = layout.WIDTH_UNITS / 2
        self.cy = layout.HEIGHT_UNITS / 2
        rnd = random.Random(7)
        self.seeds = [rnd.random() for _ in self.centers]
        self.presses: list[tuple[float, int, float]] = []   # (t0, tecla, tono)
        self._next_press = 0.0
        self._accum_reset = 0.0
        self._rnd = random.Random()

    def _simulate_presses(self, t: float, sp: float, keep: float):
        if t >= self._next_press:
            self.presses.append((t, self._rnd.randrange(len(self.centers)), self._rnd.random()))
            self._next_press = t + 0.55 / sp
        self.presses = [p for p in self.presses if t - p[0] < keep]

    def frame(self, t: float, code: int, color, random_on: bool, speed_ui: int,
              direction: int, brightness: int, custom_leds) -> list[tuple[int, int, int]]:
        sp = 0.35 + speed_ui * 0.3          # 0 (lenta) … 5 (rápida)
        sign = 1 if direction == 0 else -1
        W, H = layout.WIDTH_UNITS, layout.HEIGHT_UNITS
        out = []

        def paint(k: float, h: float):
            return scale(hue(h) if random_on else color, k)

        if code in (0x07, 0x08, 0x09):
            self._simulate_presses(t, sp, 2.5 / sp + 1)
        elif code == 0x0E:
            if t - self._accum_reset > 12 / sp:
                self.presses, self._accum_reset = [], t
            self._simulate_presses(t, sp * 2, 1e9)

        lit = {}
        if code == 0x0E:
            for _, key, h in self.presses:
                lit[key] = h

        for i, ((x, y), (_, _, _, _, _, leds)) in enumerate(zip(self.centers, layout.KEYS)):
            if code == CUSTOM:
                c = custom_leds[leds[0]]
            elif code == 0x06:
                c = hue(x / W) if random_on else color
            elif code == 0x05:
                k = (1 - math.cos(2 * math.pi * t * sp * 0.35)) / 2
                c = paint(k, t * 0.05)
            elif code == 0x04:
                c = hue(t * sp * 0.08)
            elif code in (0x01, 0x02):
                period = 2.5 if code == 0x01 else 1.0
                phase = x / W * period - sign * t * sp * 0.25
                c = hue(phase) if random_on else scale(color, (1 + math.sin(2 * math.pi * phase)) / 2)
            elif code == 0x03:
                ang = math.atan2(y - self.cy, x - self.cx) / (2 * math.pi)
                phase = ang - sign * t * sp * 0.2
                c = hue(phase) if random_on else scale(color, (1 + math.sin(2 * math.pi * phase)) / 2)
            elif code == 0x0C:
                phase = y / H + sign * t * sp * 0.25
                c = hue(phase) if random_on else scale(color, (1 + math.sin(2 * math.pi * phase)) / 2)
            elif code == 0x12:
                d = math.hypot(x - self.cx, (y - self.cy) * 1.6) / W
                c = hue(d * 2 - t * 0.3)
            elif code == 0x07:
                k, h = 0.0, 0.0
                for t0, key, hh in self.presses:
                    if key == i:
                        kk = 1 - (t - t0) * sp / 2.5
                        if kk > k:
                            k, h = kk, hh
                c = paint(k, h)
            elif code in (0x08, 0x09):
                k, h = 0.0, 0.0
                for t0, key, hh in self.presses:
                    kx, ky = self.centers[key]
                    r = (t - t0) * sp * 5
                    fade = max(0.0, 1 - (t - t0) * sp / 2.5)
                    if code == 0x08:
                        dist = math.hypot(x - kx, (y - ky) * 1.2)
                    else:
                        dist = abs(x - kx) if abs(y - ky) < 0.5 else 1e9
                    kk = max(0.0, 1 - abs(dist - r) / 0.9) * fade
                    if kk > k:
                        k, h = kk, hh
                c = paint(k, h)
            elif code in (0x0A, 0x0F):
                f = sp * (0.6 if code == 0x0A else 0.22)
                s = self.seeds[i]
                k = max(0.0, math.sin(2 * math.pi * (t * f * (0.6 + s) + s * 7))) ** 6
                c = paint(k, s + math.floor(t * f + s))
            elif code == 0x0B:
                s = self.seeds[i]
                cycle = t * sp * 0.15 + s * 5
                k = max(0.0, math.sin(math.pi * (cycle % 1))) ** 2
                c = paint(k, s * 3 + math.floor(cycle) * 0.37)
            elif code == 0x0D:
                ang = math.atan2(y - self.cy, x - self.cx) / (2 * math.pi)
                dist = math.hypot(x - self.cx, y - self.cy) / W
                phase = ang * 2 - dist * 3 - t * sp * 0.3
                c = hue(phase) if random_on else scale(color, (1 + math.sin(2 * math.pi * phase)) / 2)
            elif code == 0x0E:
                c = paint(1.0, lit[i]) if i in lit else BLACK
            elif code == 0x10:
                pos = W * (0.5 + 0.5 * math.sin(t * 1.2))
                c = paint(1 - abs(x - pos) / 2.5, x / W)
            elif code == 0x11:
                pos = (t * sp * 4) % (W + 4) - 2
                k = max(1 - abs(x - pos) / 1.5, 1 - abs(x - (W - pos)) / 1.5)
                c = paint(k, x / W)
            else:
                c = color
            out.append(scale(c, brightness / 4))
        return out
