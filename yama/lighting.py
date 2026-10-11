"""Pestaña de iluminación: efectos, pintura por tecla, diseños y vista previa."""
from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk

from . import device, layout
from .effects import BY_CODE, BY_NAME, CUSTOM, DIRECTIONS, EFFECTS, Preview
from .theme import APP_DIR, BG, FIELD, MUTED, hex_color, parse_hex, text_color

UNIT = 38
PAD = 8
UNDO_LIMIT = 60
FRAME_MS = 40
PRESETS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (255, 200, 0),
           (0, 255, 255), (255, 0, 255), (255, 80, 0)]
DESIGNS_FILE = APP_DIR / "disenos.json"


class KeyboardView(tk.Canvas):
    """Teclado latinoamericano dibujado. Pincel, rectángulo y gotero (clic derecho)."""

    def __init__(self, master, tab: "LightingTab"):
        super().__init__(master, width=layout.WIDTH_UNITS * UNIT + 2 * PAD,
                         height=layout.HEIGHT_UNITS * UNIT + 2 * PAD, bg=BG, highlightthickness=0)
        self.tab = tab
        self.items = []  # (rect, text, leds, bbox)
        for label, x, y, w, h, leds in layout.KEYS:
            x0, y0 = PAD + x * UNIT, PAD + y * UNIT
            bbox = (x0 + 2, y0 + 2, x0 + w * UNIT - 2, y0 + h * UNIT - 2)
            rect = self.create_rectangle(*bbox, fill="#000000", outline="#555", width=1)
            text = self.create_text(x0 + w * UNIT / 2, y0 + h * UNIT / 2, text=label,
                                    font=("Segoe UI", 8), justify="center")
            self.items.append((rect, text, leds, bbox))
        self._drag_start = None
        self._band = None
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Button-3>", self._eyedrop)

    def _key_at(self, x, y):
        for _, _, leds, (x0, y0, x1, y1) in self.items:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return leds
        return None

    def _press(self, e):
        self.tab.begin_edit()
        if self.tab.tool.get() == "rect":
            self._drag_start = (e.x, e.y)
            self._band = self.create_rectangle(e.x, e.y, e.x, e.y, outline="#ffffff", dash=(4, 3))
        else:
            leds = self._key_at(e.x, e.y)
            if leds:
                self.tab.paint(leds, record=False)

    def _motion(self, e):
        if self._band is not None:
            self.coords(self._band, *self._drag_start, e.x, e.y)
        elif self.tab.tool.get() == "brush":
            leds = self._key_at(e.x, e.y)
            if leds:
                self.tab.paint(leds, record=False)

    def _release(self, e):
        if self._band is None:
            return
        ax, ay = self._drag_start
        x0, x1, y0, y1 = min(ax, e.x), max(ax, e.x), min(ay, e.y), max(ay, e.y)
        self.delete(self._band)
        self._band = None
        leds = [led for _, _, ls, (kx0, ky0, kx1, ky1) in self.items
                if kx0 < x1 and kx1 > x0 and ky0 < y1 and ky1 > y0 for led in ls]
        if leds:
            self.tab.paint(leds, record=False)

    def _eyedrop(self, e):
        leds = self._key_at(e.x, e.y)
        if leds:
            self.tab.set_brush(self.tab.current_colors()[leds[0]])

    def show_keys(self, key_colors):
        for (rect, text, _, _), rgb in zip(self.items, key_colors):
            self.itemconfigure(rect, fill=hex_color(rgb))
            self.itemconfigure(text, fill=text_color(rgb))


class LightingTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.brush = (255, 0, 0)
        self.color_b = (0, 0, 255)
        self.effect_color = (255, 0, 0)
        self.recent: list[tuple[int, int, int]] = []
        self.undo_stack = [[] for _ in range(device.PROFILES)]
        self.redo_stack = [[] for _ in range(device.PROFILES)]
        self.preview = Preview()
        self.t0 = time.monotonic()

        self._build_effect_row()
        self._build_paint_rows()
        self.kb_view = KeyboardView(self, self)
        self.kb_view.pack(pady=6)
        self._build_bottom_row()

        top = self.winfo_toplevel()
        top.bind("<Control-z>", lambda e: self._shortcut(self.undo), add="+")
        top.bind("<Control-y>", lambda e: self._shortcut(self.redo), add="+")
        self.after(FRAME_MS, self._tick)

    # --- construcción -----------------------------------------------------

    def _build_effect_row(self):
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Efecto").grid(row=0, column=0, sticky="w")
        self.mode_box = ttk.Combobox(row, state="readonly", width=32, values=[e.name for e in EFFECTS])
        self.mode_box.grid(row=1, column=0, sticky="w", padx=(0, 16))
        self.mode_box.bind("<<ComboboxSelected>>", lambda e: self._update_controls())

        ttk.Label(row, text="Brillo").grid(row=0, column=1, sticky="w")
        self.bright = tk.IntVar(value=4)
        ttk.Scale(row, from_=0, to=4, variable=self.bright, length=110,
                  command=lambda v: self.bright.set(round(float(v)))).grid(row=1, column=1, padx=(0, 16))

        self.speed_label = ttk.Label(row, text="Velocidad")
        self.speed_label.grid(row=0, column=2, sticky="w")
        self.speed = tk.IntVar(value=3)
        self.speed_scale = ttk.Scale(row, from_=0, to=5, variable=self.speed, length=110,
                                     command=lambda v: self.speed.set(round(float(v))))
        self.speed_scale.grid(row=1, column=2, padx=(0, 16))

        self.dir_label = ttk.Label(row, text="Dirección")
        self.dir_label.grid(row=0, column=3, sticky="w")
        self.dir_box = ttk.Combobox(row, state="readonly", width=20)
        self.dir_box.grid(row=1, column=3, sticky="w", padx=(0, 16))

        self.color_label = ttk.Label(row, text="Color del efecto")
        self.color_label.grid(row=0, column=4, sticky="w")
        cell = ttk.Frame(row)
        cell.grid(row=1, column=4, sticky="w")
        self.effect_swatch = tk.Button(cell, width=4, relief="flat", command=self._pick_effect_color)
        self.effect_swatch.pack(side="left")
        self.random_var = tk.BooleanVar()
        self.random_check = ttk.Checkbutton(cell, text="Multicolor", variable=self.random_var)
        self.random_check.pack(side="left", padx=6)

        self.hint = ttk.Label(self, text="", foreground=MUTED)
        self.hint.pack(anchor="w", pady=(4, 0))

    def _build_paint_rows(self):
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 2))
        ttk.Label(row, text="Pincel").pack(side="left")
        self.brush_swatch = tk.Button(row, width=4, relief="flat", command=self._pick_brush)
        self.brush_swatch.pack(side="left", padx=(6, 4))
        self.hex_var = tk.StringVar()
        hex_entry = ttk.Entry(row, textvariable=self.hex_var, width=9)
        hex_entry.pack(side="left")
        hex_entry.bind("<Return>", lambda e: self._hex_entered())
        hex_entry.bind("<FocusOut>", lambda e: self._hex_entered())
        for rgb in PRESETS:
            tk.Button(row, width=2, relief="flat", bg=hex_color(rgb),
                      command=lambda c=rgb: self.set_brush(c)).pack(side="left", padx=1)
        ttk.Label(row, text="Recientes").pack(side="left", padx=(12, 4))
        self.recent_buttons = []
        for i in range(8):
            b = tk.Button(row, width=2, relief="flat", bg=FIELD, command=lambda i=i: self._use_recent(i))
            b.pack(side="left", padx=1)
            self.recent_buttons.append(b)
        ttk.Label(row, text="(clic derecho en una tecla = tomar su color)", foreground=MUTED).pack(
            side="left", padx=8)

        row = ttk.Frame(self)
        row.pack(fill="x", pady=2)
        self.tool = tk.StringVar(value="brush")
        ttk.Radiobutton(row, text="Pincel", value="brush", variable=self.tool).pack(side="left")
        ttk.Radiobutton(row, text="Rectángulo", value="rect", variable=self.tool).pack(side="left", padx=(4, 12))
        for name, leds in layout.GROUPS.items():
            ttk.Button(row, text=name, command=lambda l=leds: self.paint(l)).pack(side="left", padx=1)
        ttk.Button(row, text="Todo", command=lambda: self.paint(layout.ALL_LEDS)).pack(side="left", padx=1)
        ttk.Button(row, text="Apagar todo", command=self._clear).pack(side="left", padx=1)

        row = ttk.Frame(self)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Degradado del pincel a").pack(side="left")
        self.b_swatch = tk.Button(row, width=4, relief="flat", bg=hex_color(self.color_b), command=self._pick_b)
        self.b_swatch.pack(side="left", padx=6)
        ttk.Button(row, text="↔ Horizontal", command=lambda: self._gradient(0)).pack(side="left", padx=1)
        ttk.Button(row, text="↕ Vertical", command=lambda: self._gradient(1)).pack(side="left", padx=1)
        ttk.Button(row, text="Rehacer", command=self.redo).pack(side="right")
        ttk.Button(row, text="Deshacer", command=self.undo).pack(side="right", padx=4)
        self.set_brush(self.brush, remember=False)

    def _build_bottom_row(self):
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Diseños").pack(side="left")
        self.design_box = ttk.Combobox(row, state="readonly", width=20)
        self.design_box.pack(side="left", padx=4)
        ttk.Button(row, text="Cargar", command=self._load_design).pack(side="left")
        ttk.Button(row, text="Guardar como…", command=self._save_design).pack(side="left", padx=2)
        ttk.Button(row, text="Borrar", command=self._delete_design).pack(side="left")

        ttk.Label(row, text="Copiar a").pack(side="left", padx=(16, 4))
        self.copy_box = ttk.Combobox(row, state="readonly", width=4)
        self.copy_box.pack(side="left")
        ttk.Button(row, text="Copiar perfil", command=self._copy_profile).pack(side="left", padx=4)

        ttk.Button(row, text="Aplicar al teclado", style="Accent.TButton",
                   command=self.apply).pack(side="right")
        self.animate = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Vista previa animada", variable=self.animate,
                        command=self._redraw).pack(side="right", padx=12)
        self._refresh_designs()

    # --- estado ----------------------------------------------------------------

    @property
    def profile(self) -> int:
        return self.app.profile.get()

    def current_colors(self):
        return self.app.colors[self.profile]

    def current_effect(self):
        return BY_NAME.get(self.mode_box.get(), EFFECTS[0])

    def current_direction(self) -> int:
        eff = self.current_effect()
        for value, name in DIRECTIONS.get(eff.direction or "lr", []):
            if name == self.dir_box.get():
                return value
        return 0

    def params(self) -> dict:
        eff = self.current_effect()
        return dict(mode=eff.code, brightness=self.bright.get(), speed=5 - self.speed.get(),
                    direction=self.current_direction(),
                    random=int(self.random_var.get() or eff.code == 0x12), color=self.effect_color)

    def show(self):
        """Carga en los controles lo leído del teclado para el perfil elegido."""
        light = self.app.lighting[self.profile]
        if light:
            eff = BY_CODE.get(light["mode"], EFFECTS[0])
            self.mode_box.set(eff.name)
            self.bright.set(min(light["brightness"], 4))
            self.speed.set(5 - min(light["speed"], 5))
            self.random_var.set(bool(light["random"]))
            self.effect_color = light["color"]
            self._update_controls(direction=light["direction"])
        else:
            self.mode_box.set(EFFECTS[0].name)
            self._update_controls()
        self.copy_box.configure(values=[f"P{p + 1}" for p in range(device.PROFILES) if p != self.profile])
        self.copy_box.set("")
        self._redraw()

    def _update_controls(self, direction=None):
        eff = self.current_effect()
        enable = lambda widgets, on: [w.state(["!disabled"] if on else ["disabled"]) for w in widgets]
        enable([self.speed_label, self.speed_scale], eff.speed)
        enable([self.dir_label, self.dir_box], eff.direction is not None)
        enable([self.color_label], eff.color)
        enable([self.random_check], eff.random)
        self.effect_swatch.configure(state="normal" if eff.color else "disabled",
                                     bg=hex_color(self.effect_color) if eff.color else FIELD)
        options = DIRECTIONS.get(eff.direction or "", [])
        self.dir_box.configure(values=[name for _, name in options])
        if options:
            current = direction if direction is not None else self.current_direction()
            self.dir_box.set(next((n for v, n in options if v == current), options[0][1]))
        else:
            self.dir_box.set("")
        unused = [n for n, used in (("velocidad", eff.speed), ("dirección", eff.direction),
                                    ("color", eff.color)) if not used]
        text = eff.hint
        if unused and eff.code != CUSTOM:
            text = (text + " " if text else "") + "No usa: " + ", ".join(unused) + "."
        self.hint.configure(text=text)
        self._redraw()

    # --- pintura -----------------------------------------------------------------

    def begin_edit(self):
        """Guarda el estado para Deshacer y pasa a Personalizado si hace falta."""
        p = self.profile
        self.undo_stack[p].append(list(self.app.colors[p]))
        del self.undo_stack[p][:-UNDO_LIMIT]
        self.redo_stack[p].clear()
        if self.current_effect().code != CUSTOM:
            self.mode_box.set(BY_CODE[CUSTOM].name)
            self._update_controls()
            self.app.status.set("Cambié el efecto a Personalizado para poder pintar tecla por tecla.")

    def paint(self, leds, record=True, color=None):
        if record:
            self.begin_edit()
        colors = self.current_colors()
        for led in leds:
            colors[led] = color or self.brush
        self._redraw()

    def _clear(self):
        self.begin_edit()
        self.app.colors[self.profile] = [(0, 0, 0)] * device.LED_COUNT
        self._redraw()

    def _gradient(self, axis: int):
        self.begin_edit()
        colors = self.current_colors()
        span = layout.WIDTH_UNITS if axis == 0 else layout.HEIGHT_UNITS
        for _, x, y, w, h, leds in layout.KEYS:
            t = ((x + w / 2) if axis == 0 else (y + h / 2)) / span
            mix = tuple(int(a + (b - a) * t) for a, b in zip(self.brush, self.color_b))
            for led in leds:
                colors[led] = mix
        self._redraw()

    def undo(self):
        p = self.profile
        if self.undo_stack[p]:
            self.redo_stack[p].append(list(self.app.colors[p]))
            self.app.colors[p] = self.undo_stack[p].pop()
            self._redraw()

    def redo(self):
        p = self.profile
        if self.redo_stack[p]:
            self.undo_stack[p].append(list(self.app.colors[p]))
            self.app.colors[p] = self.redo_stack[p].pop()
            self._redraw()

    def _shortcut(self, action):
        focus = self.focus_get()
        if self.winfo_ismapped() and not isinstance(focus, (tk.Entry, ttk.Entry)):
            action()

    # --- colores -----------------------------------------------------------------

    def set_brush(self, rgb, remember=True):
        self.brush = tuple(rgb)
        self.brush_swatch.configure(bg=hex_color(self.brush))
        self.hex_var.set(hex_color(self.brush))
        if remember:
            if self.brush in self.recent:
                self.recent.remove(self.brush)
            self.recent.insert(0, self.brush)
            del self.recent[8:]
            for i, b in enumerate(self.recent_buttons):
                b.configure(bg=hex_color(self.recent[i]) if i < len(self.recent) else FIELD)

    def _use_recent(self, i):
        if i < len(self.recent):
            self.set_brush(self.recent[i])

    def _hex_entered(self):
        rgb = parse_hex(self.hex_var.get())
        if rgb:
            self.set_brush(rgb)
        else:
            self.hex_var.set(hex_color(self.brush))

    def _pick_brush(self):
        rgb, _ = colorchooser.askcolor(hex_color(self.brush), parent=self)
        if rgb:
            self.set_brush(tuple(int(v) for v in rgb))

    def _pick_b(self):
        rgb, _ = colorchooser.askcolor(hex_color(self.color_b), parent=self)
        if rgb:
            self.color_b = tuple(int(v) for v in rgb)
            self.b_swatch.configure(bg=hex_color(self.color_b))

    def _pick_effect_color(self):
        rgb, _ = colorchooser.askcolor(hex_color(self.effect_color), parent=self)
        if rgb:
            self.effect_color = tuple(int(v) for v in rgb)
            self.effect_swatch.configure(bg=hex_color(self.effect_color))

    # --- diseños y perfiles ------------------------------------------------------

    def _designs(self) -> dict:
        try:
            return json.loads(DESIGNS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _refresh_designs(self, select=None):
        names = sorted(self._designs())
        self.design_box.configure(values=names)
        self.design_box.set(select or (names[0] if names else ""))

    def _save_design(self):
        name = simpledialog.askstring("Guardar diseño", "Nombre del diseño:", parent=self,
                                      initialvalue=self.design_box.get())
        if not name:
            return
        designs = self._designs()
        if name in designs and not messagebox.askyesno("Guardar diseño", f"¿Reemplazar «{name}»?"):
            return
        params = self.params()
        designs[name] = {"effect": {**params, "color": list(params["color"])},
                         "colors": [list(c) for c in self.current_colors()]}
        APP_DIR.mkdir(parents=True, exist_ok=True)
        DESIGNS_FILE.write_text(json.dumps(designs, indent=1, ensure_ascii=False), encoding="utf-8")
        self._refresh_designs(select=name)
        self.app.status.set(f"Diseño «{name}» guardado en este PC.")

    def _load_design(self):
        design = self._designs().get(self.design_box.get())
        if not design:
            return
        self.begin_edit()
        self.app.colors[self.profile] = [tuple(c) for c in design["colors"]]
        eff = dict(design["effect"])
        eff["color"] = tuple(eff["color"])
        self.app.lighting[self.profile] = eff
        self.show()
        self.app.status.set(f"Diseño «{self.design_box.get()}» cargado. Falta «Aplicar al teclado».")

    def _delete_design(self):
        name = self.design_box.get()
        designs = self._designs()
        if name in designs and messagebox.askyesno("Borrar diseño", f"¿Borrar «{name}»?"):
            del designs[name]
            DESIGNS_FILE.write_text(json.dumps(designs, indent=1, ensure_ascii=False), encoding="utf-8")
            self._refresh_designs()

    def _copy_profile(self):
        target = self.copy_box.get()
        if not target:
            return
        q = int(target[1:]) - 1
        if not messagebox.askyesno("Copiar perfil", f"¿Copiar la iluminación de P{self.profile + 1} a {target} "
                                                    "y guardarla en el teclado?"):
            return
        params, colors = self.params(), list(self.current_colors())

        def write(kb):
            kb.write_colors(q, colors)
            kb.write_lighting(q, **params)

        if self.app.with_keyboard(write, f"Iluminación de P{self.profile + 1} copiada a {target}."):
            self.app.lighting[q] = params
            self.app.colors[q] = colors

    def apply(self):
        p, params = self.profile, self.params()

        def write(kb):
            if params["mode"] == CUSTOM:
                kb.write_colors(p, self.current_colors())
            kb.write_lighting(p, **params)

        if self.app.with_keyboard(write, f"Iluminación aplicada en P{p + 1}."):
            self.app.lighting[p] = params

    # --- dibujo ------------------------------------------------------------------

    def _frame_colors(self, animated: bool):
        eff = self.current_effect()
        if eff.code == CUSTOM or not animated:
            if eff.code == CUSTOM:
                leds = self.current_colors()
                return [leds[k[5][0]] for k in layout.KEYS]
            base = self.effect_color if eff.color else (90, 90, 90)
            return [base] * len(layout.KEYS)
        p = self.params()
        return self.preview.frame(time.monotonic() - self.t0, eff.code, self.effect_color,
                                  bool(p["random"]), self.speed.get(), p["direction"],
                                  self.bright.get(), self.current_colors())

    def _redraw(self):
        self.kb_view.show_keys(self._frame_colors(self.animate.get()))

    def _tick(self):
        if self.winfo_ismapped() and self.animate.get() and self.current_effect().code != CUSTOM:
            self._redraw()
        self.after(FRAME_MS, self._tick)
