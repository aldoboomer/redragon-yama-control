"""Ventana principal: iluminación, macros en G1–G12 y respaldos."""
from __future__ import annotations

import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import device, layout
from . import macros as mc
from .lighting import LightingTab
from .theme import APP_DIR, BG, FG, PANEL

FACTORY = "De fábrica"
# Con espera 0 el teclado se salta el evento (p. ej. Shift no alcanza a aplicarse).
MIN_DELAY_MS = 10


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Redragon Yama — control")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._style()

        self.profile = tk.IntVar(value=0)
        self.lighting = [None] * device.PROFILES
        self.colors = [[(0, 0, 0)] * device.LED_COUNT for _ in range(device.PROFILES)]
        self.macros: list[mc.Macro] = []
        self.assign = [{n: None for n in range(1, 13)} for _ in range(device.PROFILES)]
        self.recording = False
        self._insert_at = 0
        self.macro_limit = device.MACRO_AREA_LIMIT
        self._pressed = set()
        self._last_event_time = None

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Perfil:").pack(side="left")
        for p in range(device.PROFILES):
            ttk.Radiobutton(top, text=f"P{p + 1}", value=p, variable=self.profile,
                            command=self._profile_changed).pack(side="left", padx=4)
        ttk.Button(top, text="Leer del teclado", command=self.load_all).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.lighting_tab = LightingTab(nb, self)
        nb.add(self.lighting_tab, text="  Iluminación  ")
        nb.add(self._build_macros(nb), text="  Macros G1–G12  ")
        nb.add(self._build_backup(nb), text="  Respaldo  ")

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, padding=(10, 0, 10, 8)).pack(fill="x")

        self.after(100, self._startup)

    # --- utilidades ---------------------------------------------------------

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=FG, fieldbackground="#3a3c42")
        style.configure("TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=FG)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#3a3c42", foreground=FG, padding=(8, 4))
        style.map("TNotebook.Tab", background=[("selected", "#c62828")])
        style.configure("TButton", background="#3a3c42", foreground=FG)
        style.map("TButton", background=[("active", "#4a4d55")])
        style.configure("Accent.TButton", background="#c62828", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#e53935")])
        style.configure("Treeview", background="#232428", fieldbackground="#232428", foreground=FG)
        style.configure("TRadiobutton", background=PANEL, foreground=FG)
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        for widget in ("TLabel", "TCheckbutton", "TRadiobutton"):
            style.map(widget, foreground=[("disabled", "#6b6e75")], background=[("disabled", PANEL)])
        style.map("TCombobox", fieldbackground=[("readonly", "#3a3c42")], foreground=[("readonly", FG)],
                  selectbackground=[("readonly", "#3a3c42")], selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", "#232428")
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def with_keyboard(self, action, done_msg=None):
        try:
            with device.Yama() as kb, kb.session():
                result = action(kb)
        except device.KeyboardNotFound as e:
            messagebox.showerror("Teclado no encontrado", str(e))
            return None
        except (device.ProtocolError, ValueError, OSError) as e:
            messagebox.showerror("Error", str(e))
            return None
        if done_msg:
            self.status.set(done_msg)
        return result if result is not None else True

    def _startup(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        first = APP_DIR / "respaldo-inicial.json"
        if not first.exists():
            data = self.with_keyboard(lambda kb: kb.dump())
            if data:
                first.write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.load_all()

    def load_all(self):
        def read(kb):
            active = kb.read_active_profile()
            lighting = [kb.read_lighting(p) for p in range(device.PROFILES)]
            colors = [kb.read_colors(p) for p in range(device.PROFILES)]
            keymaps = [kb.read_keymap(p) for p in range(device.PROFILES)]
            blob = kb.read_macros_blob()
            return active, lighting, colors, keymaps, blob, kb.read_macro_limit()

        res = self.with_keyboard(read)
        if not res:
            return
        active, self.lighting, self.colors, keymaps, blob, self.macro_limit = res
        self.macros = mc.decode_blob(blob)
        for p, km in enumerate(keymaps):
            for n, idx in layout.G_KEY_INDEX.items():
                entry = km[idx * 3:idx * 3 + 3]
                is_macro = entry[0] == 0x05 and entry[1] == 0x01 and entry[2] < len(self.macros)
                self.assign[p][n] = entry[2] if is_macro else None
        self.profile.set(active)
        self._profile_changed()
        self._refresh_macro_list()
        self.status.set(f"Leído del teclado. Perfil activo: P{active + 1}.")

    def _profile_changed(self):
        self.lighting_tab.show()
        self._show_assignments()

    # --- macros -------------------------------------------------------------

    def _build_macros(self, parent):
        frame = ttk.Frame(parent, padding=10)

        left = ttk.Frame(frame)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(left, text="Macros guardadas").pack(anchor="w")
        self.macro_list = tk.Listbox(left, height=14, width=24, bg="#232428", fg=FG,
                                     selectbackground="#c62828", exportselection=False,
                                     highlightthickness=0, borderwidth=0)
        self.macro_list.pack(fill="y", expand=True)
        self.macro_list.bind("<<ListboxSelect>>", lambda e: self._show_macro())
        row = ttk.Frame(left)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Nueva", command=self._new_macro).pack(side="left")
        ttk.Button(row, text="Borrar", command=self._delete_macro).pack(side="left", padx=4)

        mid = ttk.Frame(frame)
        mid.grid(row=0, column=1, sticky="nsew")
        head = ttk.Frame(mid)
        head.pack(fill="x")
        ttk.Label(head, text="Nombre").pack(side="left")
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(head, textvariable=self.name_var, width=22)
        name_entry.pack(side="left", padx=6)
        name_entry.bind("<KeyRelease>", lambda e: self._rename_macro())
        ttk.Label(head, text="Repetir").pack(side="left", padx=(10, 0))
        self.repeat_var = tk.IntVar(value=1)
        ttk.Spinbox(head, from_=1, to=255, width=5, textvariable=self.repeat_var,
                    command=self._set_repeat).pack(side="left", padx=6)

        self.events_view = ttk.Treeview(mid, columns=("acc", "tecla", "espera"), show="headings", height=13)
        for col, title, width in (("acc", "Acción", 90), ("tecla", "Tecla", 140), ("espera", "Espera (ms)", 90)):
            self.events_view.heading(col, text=title)
            self.events_view.column(col, width=width, anchor="w")
        self.events_view.pack(fill="both", expand=True, pady=6)
        self.events_view.bind("<Double-1>", self._on_double_click)

        tools = ttk.Frame(mid)
        tools.pack(fill="x")
        self.rec_button = ttk.Button(tools, text="● Grabar", command=self._toggle_record)
        self.rec_button.pack(side="left")
        ttk.Button(tools, text="Escribir texto…", command=self._from_text).pack(side="left", padx=4)
        ttk.Button(tools, text="Cambiar tecla", command=self._edit_key).pack(side="left")
        ttk.Button(tools, text="Cambiar espera", command=self._edit_delay).pack(side="left", padx=4)
        ttk.Button(tools, text="Borrar tecla", command=self._delete_event).pack(side="left")
        ttk.Button(tools, text="Vaciar", command=self._clear_events).pack(side="left", padx=4)
        self.real_timing = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="Grabar tiempos reales", variable=self.real_timing).pack(side="left", padx=6)
        ttk.Label(mid, foreground="#a0a0a0", text=(
            "Doble clic en Tecla o Espera para corregir. Grabar y Escribir texto insertan después del "
            "evento seleccionado (sin selección, al final).")).pack(anchor="w", pady=(6, 0))
        self.memory_label = ttk.Label(mid, text="")
        self.memory_label.pack(anchor="w", pady=(2, 0))
        self.rec_hint = ttk.Label(mid, text="", foreground="#ff8a80")
        self.rec_hint.pack(anchor="w", pady=(4, 0))
        self.rec_sink = tk.Frame(mid, width=1, height=1, bg=PANEL, takefocus=1)
        self.rec_sink.pack()
        self.rec_sink.bind("<KeyPress>", self._rec_key)
        self.rec_sink.bind("<KeyRelease>", self._rec_key)

        right = ttk.Frame(frame)
        right.grid(row=0, column=2, sticky="n", padx=(12, 0))
        self.assign_title = ttk.Label(right, text="Teclas G")
        self.assign_title.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        self.g_boxes = {}
        for n in range(1, 13):
            r, c = (1, n - 1) if n <= 6 else (3, n - 7)
            ttk.Label(right, text=f"G{n}").grid(row=r, column=c, sticky="w", padx=2)
            box = ttk.Combobox(right, state="readonly", width=12)
            box.grid(row=r + 1, column=c, padx=2, pady=(0, 8))
            box.bind("<<ComboboxSelected>>", lambda e, n=n: self._set_assignment(n))
            self.g_boxes[n] = box
        ttk.Label(right, wraplength=560, justify="left",
                  text="«De fábrica» deja la G como viene: reproduce lo que grabes con la tecla Rec "
                       "del teclado. Las asignaciones son por perfil (P1, P2, P3).").grid(
            row=5, column=0, columnspan=6, sticky="w", pady=(4, 12))
        ttk.Button(right, text="Guardar macros en el teclado", style="Accent.TButton",
                   command=self.save_macros).grid(row=6, column=0, columnspan=6, sticky="e")
        return frame

    def _current_macro(self):
        sel = self.macro_list.curselection()
        return (sel[0], self.macros[sel[0]]) if sel else (None, None)

    def _refresh_macro_list(self, select=None):
        self.macro_list.delete(0, "end")
        for m in self.macros:
            self.macro_list.insert("end", m.name)
        if self.macros:
            idx = select if select is not None else 0
            self.macro_list.selection_set(min(idx, len(self.macros) - 1))
        self._show_macro()
        self._show_assignments()

    def _show_macro(self):
        _, m = self._current_macro()
        self.events_view.delete(*self.events_view.get_children())
        used = len(mc.encode_blob(self.macros))
        self.memory_label.configure(
            text=f"Memoria de macros: {used} de {self.macro_limit} bytes ({used * 100 // self.macro_limit}%)",
            foreground="#ff8a80" if used > self.macro_limit else FG)
        if not m:
            self.name_var.set("")
            return
        self.name_var.set(m.name)
        self.repeat_var.set(m.repeat)
        for i, ev in enumerate(m.events):
            self.events_view.insert("", "end", iid=str(i),
                                    values=("Presiona" if ev.down else "Suelta", ev.label(), ev.delay_ms))

    def _new_macro(self):
        names = {m.name for m in self.macros}
        n = 1
        while f"Macro {n}" in names:
            n += 1
        self.macros.append(mc.Macro(f"Macro {n}"))
        self._refresh_macro_list(select=len(self.macros) - 1)

    def _delete_macro(self):
        i, m = self._current_macro()
        if m is None or not messagebox.askyesno("Borrar macro", f"¿Borrar «{m.name}»?"):
            return
        del self.macros[i]
        for prof in self.assign:
            for n, idx in prof.items():
                if idx == i:
                    prof[n] = None
                elif idx is not None and idx > i:
                    prof[n] = idx - 1
        self._refresh_macro_list(select=max(i - 1, 0))

    def _rename_macro(self):
        i, m = self._current_macro()
        if m is not None and self.name_var.get().strip():
            m.name = self.name_var.get().strip()
            self.macro_list.delete(i)
            self.macro_list.insert(i, m.name)
            self.macro_list.selection_set(i)
            self._show_assignments()

    def _set_repeat(self):
        _, m = self._current_macro()
        if m is not None:
            m.repeat = max(1, min(int(self.repeat_var.get() or 1), 255))

    def _selected_rows(self):
        return sorted(int(x) for x in self.events_view.selection())

    def _insert_position(self, m):
        rows = self._selected_rows()
        return rows[-1] + 1 if rows else len(m.events)

    def _select_rows(self, rows):
        rows = [str(r) for r in rows]
        if rows:
            self.events_view.selection_set(rows)
            self.events_view.see(rows[-1])

    @staticmethod
    def _partner(events, i):
        """Índice del evento que cierra/abre la misma tecla (presiona ↔ suelta), o None."""
        ev = events[i]
        if ev.raw_kind != mc.TYPE_KEY:
            return None
        key = (ev.is_modifier, ev.code)
        rng = range(i + 1, len(events)) if ev.down else range(i - 1, -1, -1)
        for j in rng:
            other = events[j]
            if other.raw_kind == mc.TYPE_KEY and (other.is_modifier, other.code) == key:
                return j if other.down != ev.down else None
        return None

    def _on_double_click(self, event):
        row = self.events_view.identify_row(event.y)
        if not row:
            return
        self.events_view.selection_set(row)
        if self.events_view.identify_column(event.x) == "#3":
            self._edit_delay()
        else:
            self._edit_key()

    def _edit_delay(self):
        _, m = self._current_macro()
        rows = self._selected_rows()
        if m is None or not rows:
            return
        prompt = "Milisegundos de espera después del evento"
        prompt += " (se aplica a todos los seleccionados):" if len(rows) > 1 else ":"
        value = simpledialog.askinteger("Espera", prompt, initialvalue=m.events[rows[0]].delay_ms,
                                        minvalue=MIN_DELAY_MS, maxvalue=40950, parent=self)
        if value is not None:
            for r in rows:
                m.events[r].delay_ms = value // 10 * 10
            self._show_macro()
            self._select_rows(rows)

    def _edit_key(self):
        _, m = self._current_macro()
        rows = self._selected_rows()
        if m is None or len(rows) != 1:
            if rows:
                messagebox.showinfo("Cambiar tecla", "Selecciona un solo evento.")
            return
        i = rows[0]
        if m.events[i].raw_kind != mc.TYPE_KEY:
            return
        new = self._ask_key()
        if new is None:
            return
        # se cambian juntos el «presiona» y su «suelta» para no dejar teclas pegadas
        for j in (i, self._partner(m.events, i)):
            if j is not None:
                m.events[j].is_modifier, m.events[j].code = new
        self._show_macro()
        self._select_rows([i])

    def _ask_key(self):
        win = tk.Toplevel(self)
        win.title("Cambiar tecla")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        win.transient(self)
        ttk.Label(win, text="Presiona la tecla nueva…", padding=(30, 20)).pack()
        ttk.Button(win, text="Cancelar", takefocus=0, command=win.destroy).pack(pady=(0, 14))
        result = []

        def on_key(e):
            mapped = mc.tk_key_to_event(e.keysym, e.keycode)
            if mapped:
                result.append(mapped)
                win.destroy()
            return "break"

        win.bind("<KeyPress>", on_key)
        win.grab_set()
        win.focus_force()
        self.wait_window(win)
        return result[0] if result else None

    def _delete_event(self):
        _, m = self._current_macro()
        rows = set(self._selected_rows())
        if m is None or not rows:
            return
        for r in list(rows):  # borrar también su par para no dejar una tecla presionada
            partner = self._partner(m.events, r)
            if partner is not None:
                rows.add(partner)
        for r in sorted(rows, reverse=True):
            del m.events[r]
        self._show_macro()
        if m.events:
            self._select_rows([min(min(rows), len(m.events) - 1)])

    def _clear_events(self):
        _, m = self._current_macro()
        if m is not None:
            m.events.clear()
            self._show_macro()

    def _from_text(self):
        _, m = self._current_macro()
        if m is None:
            self._new_macro()
            _, m = self._current_macro()
        text = simpledialog.askstring("Escribir texto", "Texto que debe escribir la macro "
                                      "(usa \\n para Enter):", parent=self)
        if not text:
            return
        events, missing = mc.text_to_events(text.replace("\\n", "\n"))
        pos = self._insert_position(m)
        m.events[pos:pos] = events
        self._show_macro()
        self._select_rows(range(pos, pos + len(events)))
        if missing:
            messagebox.showwarning("Caracteres omitidos",
                                   "No encontré cómo escribir: " + " ".join(sorted(set(missing))))

    def _toggle_record(self):
        _, m = self._current_macro()
        if not self.recording and m is None:
            self._new_macro()
        self.recording = not self.recording
        self._pressed.clear()
        self._last_event_time = None
        if self.recording:
            _, m = self._current_macro()
            self._insert_at = self._insert_position(m)
            where = "al final" if self._insert_at == len(m.events) else f"después del evento {self._insert_at}"
            self.rec_button.configure(text="■ Detener")
            self.rec_hint.configure(text=f"Grabando ({where}): presiona las teclas "
                                         "(la tecla Windows abre el menú Inicio).")
            self.rec_sink.focus_set()
        else:
            self.rec_button.configure(text="● Grabar")
            self.rec_hint.configure(text="")
            self.focus_set()

    def _rec_key(self, event):
        if not self.recording:
            return "break"
        _, m = self._current_macro()
        mapped = mc.tk_key_to_event(event.keysym, event.keycode)
        if m is None or mapped is None:
            return "break"
        is_mod, code = mapped
        down = event.type == tk.EventType.KeyPress
        key = (is_mod, code)
        if down and key in self._pressed:      # repetición automática al mantener
            return "break"
        if not down and key not in self._pressed:
            return "break"
        (self._pressed.add if down else self._pressed.discard)(key)
        now = time.monotonic()
        if self._insert_at > 0 and self._last_event_time is not None:
            m.events[self._insert_at - 1].delay_ms = (max(MIN_DELAY_MS, min(int((now - self._last_event_time) * 1000), 40950) // 10 * 10)
                                     if self.real_timing.get() else 20)
        self._last_event_time = now
        m.events.insert(self._insert_at, mc.Event(is_mod, code, down, 20))
        self._insert_at += 1
        self._show_macro()
        self._select_rows([self._insert_at - 1])
        return "break"

    def _show_assignments(self):
        p = self.profile.get()
        self.assign_title.configure(text=f"Teclas G del perfil P{p + 1}")
        values = [FACTORY] + [f"{i + 1}. {m.name}" for i, m in enumerate(self.macros)]
        for n, box in self.g_boxes.items():
            box.configure(values=values)
            idx = self.assign[p][n]
            box.set(values[idx + 1] if idx is not None and idx < len(self.macros) else FACTORY)

    def _set_assignment(self, n):
        value = self.g_boxes[n].get()
        self.assign[self.profile.get()][n] = None if value == FACTORY else int(value.split(".")[0]) - 1

    def save_macros(self):
        if self.recording:
            self._toggle_record()
        empty = [m.name for m in self.macros if not m.events]
        if empty:
            messagebox.showerror("Macros vacías", "Estas macros no tienen eventos: " + ", ".join(empty))
            return
        def write(kb):
            limit = kb.read_macro_limit()
            blob = mc.encode_blob(self.macros)
            if len(blob) > limit:
                short = mc.encode_blob(self.macros, names=False)
                if len(short) > limit or not messagebox.askyesno(
                        "Falta espacio",
                        f"Las macros ocupan {len(blob)} de {limit} bytes. Sin guardar sus nombres "
                        f"ocupan {len(short)} y sí caben (al volver a leerlas se llamarán «Macro 1», "
                        "«Macro 2»…). ¿Guardarlas sin nombres?"):
                    raise ValueError(f"Las macros ocupan {len(blob)} bytes y el teclado admite {limit}. "
                                     "Acorta o borra alguna.")
                blob = short
            kb.write_macros_blob(blob)
            usage.append(f"{len(blob)} de {limit} bytes usados")
            for p in range(device.PROFILES):
                entries = {}
                for n, idx in layout.G_KEY_INDEX.items():
                    target = self.assign[p][n]
                    entries[idx] = (layout.g_macro_entry(target) if target is not None
                                    else layout.g_default_entry(n))
                kb.write_keymap_entries(p, entries)

        usage = []
        if self.with_keyboard(write):
            self.status.set(f"Macros guardadas en el teclado ({usage[0]}).")

    # --- respaldo -----------------------------------------------------------

    def _build_backup(self, parent):
        frame = ttk.Frame(parent, padding=16)
        ttk.Label(frame, wraplength=700, justify="left", text=(
            "Un respaldo guarda todo lo que hay en la memoria del teclado: efectos y colores de "
            "los 3 perfiles, macros y asignación de teclas.\n\n"
            f"La primera vez que abriste este programa se guardó uno automático en:\n{APP_DIR / 'respaldo-inicial.json'}"
        )).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=16)
        ttk.Button(row, text="Guardar respaldo…", command=self._save_backup).pack(side="left")
        ttk.Button(row, text="Restaurar respaldo…", command=self._restore_backup).pack(side="left", padx=8)
        return frame

    def _save_backup(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                            initialdir=APP_DIR, initialfile="respaldo-yama.json",
                                            filetypes=[("Respaldo", "*.json")])
        if not path:
            return
        data = self.with_keyboard(lambda kb: kb.dump())
        if data:
            Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")
            self.status.set(f"Respaldo guardado en {path}")

    def _restore_backup(self):
        path = filedialog.askopenfilename(parent=self, initialdir=APP_DIR, filetypes=[("Respaldo", "*.json")])
        if not path or not messagebox.askyesno("Restaurar", "Esto reemplaza todo lo que tiene el teclado. ¿Seguir?"):
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if self.with_keyboard(lambda kb: kb.restore(data), "Respaldo restaurado."):
            self.load_all()


def main():
    App().mainloop()
