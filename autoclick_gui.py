#!/usr/bin/env python3
"""
Interfaz gráfica para el autoclicker basado en imágenes.

Características:
- GUI con Tkinter para añadir/eliminar imágenes objetivo (se copian a `targets/`).
- Editar opciones por objetivo (intervalo de clic, confianza, jitter, botón, habilitado).
- Controles globales: intervalo de escaneo, modo simulado, cuenta regresiva, Iniciar/Detener.
- Bucle de escaneo en segundo plano reutiliza la misma lógica que el script CLI.
- Por seguridad: el modo simulado viene activado por defecto. Desactívalo solo
  si sabes lo que haces y has concedido los permisos necesarios (macOS).

También soporta modo sin GUI para demostraciones: `--nogui --simulate --demo`.
"""

import argparse
import glob
import json
import os
import random
import shutil
import sys
import threading
import time
from typing import Any, Dict, List

# Importar módulos de GUI cuando se vaya a usar la interfaz
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    tk = None  # type: ignore

import queue
import subprocess

import pyautogui

# Atajos globales (opcional)
try:
    from pynput import keyboard as pkb

    HAVE_PYNPUT = True
except Exception:
    pkb = None
    HAVE_PYNPUT = False

# OpenCV opcional
try:
    import cv2  # noqa: F401

    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

# Valores por defecto
DEFAULT_TARGETS_DIR = "targets"
DEFAULT_SCAN_INTERVAL = 0.5
DEFAULT_CLICK_DELAY = 0.05
DEFAULT_CONFIDENCE = 0.85
DEFAULT_JITTER = 3
DEFAULT_CLICK_COOLDOWN = 1.0
DEFAULT_BUTTON = "left"

pyautogui.FAILSAFE = True


def exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resolve_targets_dir(cli_path: str | None) -> str:
    if cli_path:
        return os.path.abspath(cli_path)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cand = os.path.join(meipass, DEFAULT_TARGETS_DIR)
            if os.path.isdir(cand):
                return cand
    return os.path.join(exe_dir(), DEFAULT_TARGETS_DIR)


def ensure_targets_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def list_target_images(targets_dir: str) -> List[str]:
    if not os.path.isdir(targets_dir):
        return []
    exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif")
    paths: List[str] = []
    for e in exts:
        paths.extend(glob.glob(os.path.join(targets_dir, e)))
    return sorted(paths)


def load_targets_config(targets_dir: str) -> Dict[str, Any]:
    cfg_path = os.path.join(targets_dir, "config.json")
    if not os.path.exists(cfg_path):
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            print(
                f"[AVISO] config.json tiene un formato inesperado (se esperaba un objeto) — se ignorará"
            )
            return {}
    except Exception as e:
        print(f"[AVISO] Error al leer config.json: {e}")
        return {}


def save_targets_config(targets_dir: str, cfg: Dict[str, Any]) -> None:
    cfg_path = os.path.join(targets_dir, "config.json")
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] No se pudo escribir config.json: {e}")


def get_target_setting(img_path: str, cfg: Dict[str, Any], key: str, default: Any):
    basename = os.path.basename(img_path)
    entry = cfg.get(basename) or cfg.get(img_path) or {}
    return entry.get(key, default)


def _enhance_small_template(tpl_gray, min_size=20):
    h, w = tpl_gray.shape[:2]
    if h < min_size or w < min_size:
        scale = max(min_size / w, min_size / h, 1.0)
        if scale > 1.0:
            nw, nh = int(w * scale), int(h * scale)
            tpl_gray = cv2.resize(tpl_gray, (nw, nh), interpolation=cv2.INTER_CUBIC)
    return tpl_gray


def locate_all(
    img_path: str, confidence: float, simulate: bool = False, demo: bool = False
):
    """Localiza coincidencias en pantalla.

    Estrategia:
    - Si `simulate` -> no coincidencias (salvo demo)
    - Primero intenta `pyautogui.locateAllOnScreen` (rápido)
    - Si no hay resultados y OpenCV está disponible, realiza un matching multi-escala
      con `cv2.matchTemplate` (más robusto en casos de escala/dpi distinta).
    - Mejorado para detectar imágenes pequeñas con escalas agresivas y upscaling.
    """
    if simulate:
        if demo:
            return [(100, 100, 20, 20)]
        return []

    try:
        if HAVE_CV2:
            try:
                return list(
                    pyautogui.locateAllOnScreen(img_path, confidence=confidence)
                )
            except Exception:
                pass
        else:
            try:
                return list(pyautogui.locateAllOnScreen(img_path))
            except Exception:
                return []
    except Exception:
        pass

    if not HAVE_CV2:
        return []

    try:
        import cv2
        import numpy as np

        tpl = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if tpl is None:
            tpl = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
        if tpl is None:
            print(f"[AVISO] No se pudo leer la imagen objetivo: {img_path}")
            return []

        screen_pil = pyautogui.screenshot()
        screen = cv2.cvtColor(np.array(screen_pil), cv2.COLOR_RGB2BGR)
        screen_h, screen_w = screen.shape[:2]

        tpl_color = tpl
        if tpl_color.ndim == 3 and tpl_color.shape[2] == 4:
            tpl_color = cv2.cvtColor(tpl_color, cv2.COLOR_BGRA2BGR)

        tpl_gray = cv2.cvtColor(tpl_color, cv2.COLOR_BGR2GRAY)
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

        th, tw = tpl_gray.shape[:2]
        is_small = tw < 32 or th < 32

        tpl_enhanced = _enhance_small_template(tpl_gray, min_size=24)
        eh, ew = tpl_enhanced.shape[:2]

        boxes = []
        scores = []

        if is_small:
            scales = np.linspace(0.3, 3.0, 25)
        else:
            scales = np.linspace(0.4, 2.2, 16)

        for scale in scales:
            nw = int(ew * scale)
            nh = int(eh * scale)
            if nw < 8 or nh < 8 or nw > screen_w or nh > screen_h:
                continue
            try:
                interp = cv2.INTER_CUBIC if scale > 1.2 else cv2.INTER_AREA if scale < 0.8 else cv2.INTER_LINEAR
                tpl_resized = cv2.resize(tpl_enhanced, (nw, nh), interpolation=interp)
            except Exception:
                continue

            res = cv2.matchTemplate(screen_gray, tpl_resized, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= float(confidence))
            for py_y, px_x in zip(*loc):
                score = float(res[py_y, px_x])
                scale_correction = ew / tw if is_small else 1.0
                orig_w = int(nw / scale_correction) if is_small else nw
                orig_h = int(nh / scale_correction) if is_small else nh
                boxes.append((int(px_x), int(py_y), int(nw), int(nh)))
                scores.append(score)

        if not boxes:
            return []

        def _nms(boxes, scores, iou_thresh=0.25):
            x1 = np.array([b[0] for b in boxes], dtype=float)
            y1 = np.array([b[1] for b in boxes], dtype=float)
            x2 = x1 + np.array([b[2] for b in boxes], dtype=float)
            y2 = y1 + np.array([b[3] for b in boxes], dtype=float)

            areas = (x2 - x1 + 1) * (y2 - y1 + 1)
            order = np.argsort(scores)[::-1]
            keep = []
            while order.size > 0:
                i = order[0]
                keep.append(i)
                xx1 = np.maximum(x1[i], x1[order[1:]])
                yy1 = np.maximum(y1[i], y1[order[1:]])
                xx2 = np.minimum(x2[i], x2[order[1:]])
                yy2 = np.minimum(y2[i], y2[order[1:]])

                w = np.maximum(0.0, xx2 - xx1 + 1)
                h = np.maximum(0.0, yy2 - yy1 + 1)
                inter = w * h
                ovr = inter / (areas[i] + areas[order[1:]] - inter)

                inds = np.where(ovr <= iou_thresh)[0]
                order = order[inds + 1]
            return keep

        keep_idx = _nms(boxes, np.array(scores), iou_thresh=0.25)
        filtered = [boxes[i] for i in keep_idx]
        return filtered
    except Exception as e:
        print(f"[AVISO] Fallback OpenCV locate falló para {img_path}: {e}")
        return []


def center_of(box) -> tuple[int, int]:
    try:
        return int(box.x + box.width / 2), int(box.y + box.height / 2)
    except Exception:
        try:
            cx, cy = pyautogui.center(box)
            return int(cx), int(cy)
        except Exception:
            return int(box[0] + box[2] / 2), int(box[1] + box[3] / 2)


class Scanner:
    """Lógica de escaneo en segundo plano reutilizable."""

    def __init__(
        self,
        targets_dir: str,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        default_confidence: float = DEFAULT_CONFIDENCE,
        default_jitter: int = DEFAULT_JITTER,
        default_click_delay: float = DEFAULT_CLICK_DELAY,
        default_click_cooldown: float = DEFAULT_CLICK_COOLDOWN,
        default_button: str = DEFAULT_BUTTON,
        simulate: bool = True,
        demo: bool = False,
        log_fn=None,
    ):
        self.targets_dir = targets_dir
        ensure_targets_dir(self.targets_dir)
        self.scan_interval = scan_interval
        self.default_confidence = default_confidence
        self.default_jitter = default_jitter
        self.default_click_delay = default_click_delay
        self.default_click_cooldown = default_click_cooldown
        self.default_button = default_button
        self.simulate = simulate
        self.demo = demo
        self.log_fn = log_fn or (lambda s: print(s))

        self.running = False
        self.thread = None
        self.last_click_times: Dict[tuple, float] = {}

    def log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_fn(f"[{ts}] {msg}")

    def find_and_click_once(
        self, target_images: List[str], cfg: Dict[str, Any], scan_idx: int | None = None
    ):
        now = time.time()
        for img in target_images:
            confidence = get_target_setting(
                img, cfg, "confidence", self.default_confidence
            )
            matches = locate_all(
                img, confidence, simulate=self.simulate, demo=self.demo
            )
            basename = os.path.basename(img)
            if matches:
                self.log(
                    f"[BUCLE {scan_idx}] ENCONTRADO {basename}: {len(matches)} coincidencia(s) (conf={confidence})"
                )
            else:
                self.log(
                    f"[BUCLE {scan_idx}] NO_ENCONTRADO {basename} (conf={confidence})"
                )
                continue

            for m in matches:
                cx, cy = center_of(m)
                key = (basename, cx, cy)

                click_cooldown = get_target_setting(
                    img, cfg, "click_cooldown", self.default_click_cooldown
                )
                jitter = get_target_setting(img, cfg, "jitter", self.default_jitter)
                click_delay = get_target_setting(
                    img, cfg, "click_delay", self.default_click_delay
                )
                button = get_target_setting(img, cfg, "button", self.default_button)
                enabled = get_target_setting(img, cfg, "enabled", True)

                if not enabled:
                    continue

                last = self.last_click_times.get(key, 0)
                if now - last < float(click_cooldown):
                    continue

                jx = random.randint(-int(jitter), int(jitter)) if jitter else 0
                jy = random.randint(-int(jitter), int(jitter)) if jitter else 0
                tx, ty = cx + jx, cy + jy

                if self.simulate:
                    self.log(
                        f"[SIMULADO] CLIC {basename} en ({tx},{ty}) (cooldown={click_cooldown}s, conf={confidence})"
                    )
                else:
                    try:
                        # Mover cursor primero para mayor fiabilidad
                        try:
                            pyautogui.moveTo(tx, ty, duration=0.05)
                            time.sleep(0.02)
                        except Exception:
                            pass
                        # Click real
                        pyautogui.mouseDown(button=button)
                        pyautogui.mouseUp(button=button)

                        # Verificar posición después del movimiento
                        try:
                            p_after = pyautogui.position()
                            if abs(p_after.x - tx) > 8 or abs(p_after.y - ty) > 8:
                                self.log(
                                    f"[WARN] El cursor no quedó en la posición esperada: ({p_after.x},{p_after.y}) vs ({tx},{ty})"
                                )
                        except Exception:
                            pass

                        self.log(
                            f"[CLIC] {basename} en ({tx},{ty}) (boton={button}, conf={confidence})"
                        )
                    except Exception as e:
                        self.log(
                            f"[ERROR] No se pudo clicar {basename} en ({tx},{ty}): {e}"
                        )

                self.last_click_times[key] = time.time()
                time.sleep(float(click_delay))

    def scan_loop(self):
        self.log("Hilo de escaneo iniciado")
        self.scan_count = 0
        while self.running:
            self.scan_count += 1
            cfg = load_targets_config(self.targets_dir)
            imgs = list_target_images(self.targets_dir)
            if not imgs and not self.demo:
                self.log(f"No se encontraron imágenes objetivo en {self.targets_dir}")
            else:
                self.log(f"[BUCLE {self.scan_count}] Escaneo de {len(imgs)} imagen(es)")
                self.find_and_click_once(imgs, cfg, scan_idx=self.scan_count)
            time.sleep(self.scan_interval)
        self.log("Hilo de escaneo detenido")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self.scan_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
            self.thread = None


# Implementación de la GUI
class AutoclickGUI:
    def __init__(self, targets_dir: str):
        if tk is None:
            raise RuntimeError("Tkinter no está disponible en este entorno de Python")

        self.targets_dir = resolve_targets_dir(targets_dir)
        ensure_targets_dir(self.targets_dir)

        self.root = tk.Tk()
        self.root.title("Autoclicker por imágenes — GUI")
        self.root.geometry("900x600")

        # Variables
        self.scan_interval_var = tk.DoubleVar(value=DEFAULT_SCAN_INTERVAL)
        self.simulate_var = tk.BooleanVar(value=True)
        self.countdown_var = tk.IntVar(value=3)

        # Variables del objetivo seleccionado
        self.sel_enabled = tk.BooleanVar(value=True)
        self.sel_click_interval = tk.DoubleVar(value=DEFAULT_CLICK_COOLDOWN)
        self.sel_confidence = tk.DoubleVar(value=DEFAULT_CONFIDENCE)
        self.sel_jitter = tk.IntVar(value=DEFAULT_JITTER)
        self.sel_button = tk.StringVar(value=DEFAULT_BUTTON)
        self.sel_click_delay = tk.DoubleVar(value=DEFAULT_CLICK_DELAY)

        # Escáner
        self.scanner: Scanner | None = None

        # Construir UI
        self._build_ui()

        # Cola de log
        self._log_queue: List[str] = []
        self._poll_log()

        # Atajos de teclado (local y global)
        try:
            self._init_keyboard_listener()
        except Exception:
            # no interrumpe si pynput/teclas fallan
            self._log("[INFO] No se pudieron inicializar atajos de teclado globales")

        # Bind cerrar
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)

        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=0)

        lb_label = ttk.Label(left_frame, text="Objetivos (en targets/)")
        lb_label.pack(anchor=tk.W, pady=(0, 2))

        self.listbox = tk.Listbox(left_frame, width=38, height=20, font=("TkDefaultFont", 10))
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="Agregar imagen", command=self._add_image).pack(
            side=tk.LEFT
        )
        ttk.Button(
            btn_frame, text="Eliminar", command=self._remove_selected
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Actualizar", command=self._refresh_list).pack(
            side=tk.LEFT
        )

        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)

        settings_frame = tk.LabelFrame(
            right_frame, text="Configuración del objetivo", font=("TkDefaultFont", 10, "bold")
        )
        settings_frame.pack(fill=tk.X, pady=(0, 4))

        row = 0
        tk.Checkbutton(
            settings_frame, text="Habilitado", variable=self.sel_enabled
        ).grid(row=row, column=0, sticky=tk.W, columnspan=2)
        row += 1
        tk.Label(settings_frame, text="Intervalo entre clics (s)").grid(
            row=row, column=0, sticky=tk.W
        )
        tk.Entry(settings_frame, textvariable=self.sel_click_interval, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )
        row += 1
        tk.Label(settings_frame, text="Confianza (0-1)").grid(
            row=row, column=0, sticky=tk.W
        )
        tk.Entry(settings_frame, textvariable=self.sel_confidence, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )
        row += 1
        tk.Label(settings_frame, text="Jitter (px)").grid(
            row=row, column=0, sticky=tk.W
        )
        tk.Entry(settings_frame, textvariable=self.sel_jitter, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )
        row += 1
        tk.Label(settings_frame, text="Retardo entre clics (s)").grid(
            row=row, column=0, sticky=tk.W
        )
        tk.Entry(settings_frame, textvariable=self.sel_click_delay, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )
        row += 1
        tk.Label(settings_frame, text="Botón").grid(row=row, column=0, sticky=tk.W)
        ttk.Combobox(
            settings_frame,
            textvariable=self.sel_button,
            values=("left", "right", "middle"),
            width=6,
        ).grid(row=row, column=1, sticky=tk.W, padx=4)
        row += 1
        ttk.Button(
            settings_frame, text="Guardar objetivo", command=self._save_selected
        ).grid(row=row, column=0, columnspan=2, pady=4)

        preview_frame = tk.LabelFrame(
            right_frame, text="Vista previa", font=("TkDefaultFont", 10, "bold")
        )
        preview_frame.pack(fill=tk.X, pady=(0, 4))
        self.preview_canvas = tk.Canvas(preview_frame, width=120, height=90, bg="#f0f0f0", highlightthickness=0)
        self.preview_canvas.pack(side=tk.LEFT, padx=6, pady=4)
        self.preview_canvas.create_text(60, 45, text="Sin imagen", fill="#999", font=("TkDefaultFont", 8))
        self.preview_info = ttk.Label(preview_frame, text="Selecciona un objetivo", font=("TkDefaultFont", 8))
        self.preview_info.pack(side=tk.LEFT, padx=6)

        global_frame = tk.LabelFrame(
            right_frame, text="Controles globales", font=("TkDefaultFont", 10, "bold")
        )
        global_frame.pack(fill=tk.X, pady=(0, 4))

        tk.Label(global_frame, text="Intervalo de escaneo (s)").grid(
            row=0, column=0, sticky=tk.W
        )
        tk.Entry(global_frame, textvariable=self.scan_interval_var, width=6).grid(
            row=0, column=1, sticky=tk.W
        )
        tk.Checkbutton(
            global_frame, text="Simular (sin clics reales)", variable=self.simulate_var
        ).grid(row=0, column=2, padx=12)

        tk.Label(global_frame, text="Cuenta regresiva (s)").grid(
            row=1, column=0, sticky=tk.W
        )
        tk.Entry(global_frame, textvariable=self.countdown_var, width=6).grid(
            row=1, column=1, sticky=tk.W
        )

        ctrl_frame = ttk.Frame(global_frame)
        ctrl_frame.grid(row=2, column=0, columnspan=3, pady=6)
        self.start_btn = ttk.Button(ctrl_frame, text="Iniciar", command=self._start)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(ctrl_frame, text="Detener", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(ctrl_frame, text="Posiciones", command=self._open_positions).pack(
            side=tk.LEFT, padx=8
        )

        log_frame = tk.LabelFrame(
            right_frame, text="Registro", font=("TkDefaultFont", 10, "bold")
        )
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        self.log_text = tk.Text(log_frame, height=10, font=("TkFixedFont", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self.status_var = tk.StringVar(value="Listo")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        )
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._refresh_list()

    # Helpers de UI
    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        imgs = list_target_images(self.targets_dir)
        for p in imgs:
            self.listbox.insert(tk.END, os.path.basename(p))

    def _show_preview(self, name):
        self.preview_canvas.delete("all")
        w, h = 120, 90
        path = os.path.join(self.targets_dir, name)
        if not os.path.exists(path):
            self.preview_canvas.create_text(w//2, h//2, text="Archivo no encontrado", fill="#999", font=("TkDefaultFont", 8))
            self.preview_info.config(text="")
            return
        try:
            img = tk.PhotoImage(file=path)
            iw, ih = img.width(), img.height()
            scale = min(w/iw, h/ih, 1.0)
            if scale < 1.0:
                nw, nh = int(iw*scale), int(ih*scale)
                img = img.subsample(max(1, int(1/scale)))
            self.preview_canvas.config(width=min(w, iw), height=min(h, ih))
            self.preview_canvas.create_image(0, 0, anchor=tk.NW, image=img)
            self.preview_canvas.image = img
            self.preview_info.config(text=f"{iw}x{ih} px — {name}")
        except Exception:
            self.preview_canvas.create_text(w//2, h//2, text="Sin vista previa", fill="#999", font=("TkDefaultFont", 8))
            try:
                stat = os.stat(path)
                size_kb = stat.st_size / 1024
                self.preview_info.config(text=f"{size_kb:.0f} KB — {name}")
            except Exception:
                self.preview_info.config(text=name)

    def _on_select(self, evt=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.listbox.get(idx)
        self._show_preview(name)
        cfg = load_targets_config(self.targets_dir)
        entry = cfg.get(name, {})
        self.sel_enabled.set(bool(entry.get("enabled", True)))
        self.sel_click_interval.set(
            float(entry.get("click_cooldown", DEFAULT_CLICK_COOLDOWN))
        )
        self.sel_confidence.set(float(entry.get("confidence", DEFAULT_CONFIDENCE)))
        self.sel_jitter.set(int(entry.get("jitter", DEFAULT_JITTER)))
        self.sel_button.set(entry.get("button", DEFAULT_BUTTON))
        self.sel_click_delay.set(float(entry.get("click_delay", DEFAULT_CLICK_DELAY)))

    def _add_image(self):
        path = filedialog.askopenfilename(
            title="Selecciona la imagen a añadir",
            filetypes=[("Archivos de imagen", "*.png *.jpg *.jpeg *.bmp *.gif")],
        )
        if not path:
            return
        dest = os.path.join(self.targets_dir, os.path.basename(path))
        try:
            shutil.copy2(path, dest)
            cfg = load_targets_config(self.targets_dir)
            if os.path.basename(path) not in cfg:
                cfg[os.path.basename(path)] = {}
                save_targets_config(self.targets_dir, cfg)
            self._refresh_list()
            self._log(f"Añadida {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo añadir la imagen: {e}")

    def _remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.listbox.get(idx)
        if not messagebox.askyesno("Eliminar", f"¿Eliminar {name} de targets/?"):
            return
        try:
            os.remove(os.path.join(self.targets_dir, name))
        except Exception:
            pass
        cfg = load_targets_config(self.targets_dir)
        if name in cfg:
            cfg.pop(name, None)
            save_targets_config(self.targets_dir, cfg)
        self._refresh_list()
        self._log(f"Eliminada {name}")

    def _save_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Sin selección", "Selecciona primero un objetivo")
            return
        name = self.listbox.get(sel[0])
        cfg = load_targets_config(self.targets_dir)
        entry = cfg.get(name, {})
        entry["enabled"] = bool(self.sel_enabled.get())
        entry["click_cooldown"] = float(self.sel_click_interval.get())
        entry["confidence"] = float(self.sel_confidence.get())
        entry["jitter"] = int(self.sel_jitter.get())
        entry["button"] = str(self.sel_button.get())
        entry["click_delay"] = float(self.sel_click_delay.get())
        cfg[name] = entry
        save_targets_config(self.targets_dir, cfg)
        self._log(f"Configuración guardada para {name}")

    def _append_log(self, s: str):
        self._log_queue.append(s)

    def _poll_log(self):
        if self._log_queue:
            for s in self._log_queue:
                self.log_text.insert(tk.END, s + "\n")
            self.log_text.see(tk.END)
            self._log_queue.clear()
        self.root.after(200, self._poll_log)

    def _log(self, s: str):
        self._append_log(s)

    def _start(self):
        if self.scanner and self.scanner.running:
            messagebox.showinfo("Ya en ejecución", "El escáner ya está en ejecución")
            return
        simulate = bool(self.simulate_var.get())
        scanner = Scanner(
            self.targets_dir,
            scan_interval=float(self.scan_interval_var.get()),
            default_confidence=float(self.sel_confidence.get()),
            default_jitter=int(self.sel_jitter.get()),
            default_click_delay=float(self.sel_click_delay.get()),
            default_click_cooldown=float(self.sel_click_interval.get()),
            default_button=str(self.sel_button.get()),
            simulate=simulate,
            demo=False,
            log_fn=self._log,
        )
        self.scanner = scanner
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Iniciando escáner...")

        countdown = int(self.countdown_var.get() or 0)
        if countdown > 0:
            self._countdown_and_start(countdown)
        else:
            scanner.start()
            self.status_var.set("Escáner en ejecución")

    def _countdown_and_start(self, n: int):
        if n <= 0:
            if self.scanner:
                self.scanner.start()
                self.status_var.set("Escáner en ejecución")
            return
        self._log(f"Iniciando en {n}...")
        self.status_var.set(f"Iniciando en {n}...")
        self.root.after(1000, lambda: self._countdown_and_start(n - 1))

    def _stop(self):
        if self.scanner:
            self.scanner.stop()
            self._log("Escáner detenido")
            self.scanner = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Detenido")

    def _toggle_scan(self):
        """Alterna el escáner (Iniciar/Detener)."""
        if self.scanner and self.scanner.running:
            self._stop()
        else:
            self._start()

    def _init_keyboard_listener(self):
        """Configura atajos locales (cuando la ventana tiene foco) y un listener global opcional.

        - F6: alterna Iniciar/Detener
        - Esc: cierra la aplicación (con confirmación si el escáner está en ejecución)
        """
        try:
            # atajos locales dentro de la ventana
            self.root.bind_all("<F6>", lambda e: self._toggle_scan())
            self.root.bind_all("<Escape>", lambda e: self._on_close())
        except Exception:
            pass

        if pkb is None:
            self._log("[INFO] pynput no disponible: atajos globales deshabilitados")
            return

        try:

            def on_press(key):
                try:
                    if key == pkb.Key.f6:
                        # ejecutar en el hilo de la GUI
                        self.root.after(0, self._toggle_scan)
                    elif key == pkb.Key.esc:
                        self.root.after(0, self._on_close)
                except Exception as e:
                    self._log(f"[ERROR] Listener teclado: {e}")

            listener = pkb.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            self._kb_listener = listener
            self._log("[INFO] Atajos globales: F6 (toggle), Esc (salir) activos")
        except Exception as e:
            self._log(f"[ERROR] No se pudo iniciar listener de teclado global: {e}")

    def _open_positions(self):
        """Abrir el gestor de posiciones integrado en la misma aplicación."""
        try:
            self._start_positions_manager()
        except Exception as e:
            self._log(f"[ERROR] No se pudo abrir el gestor de posiciones: {e}")

    def _start_positions_manager(self):
        """Inicia una ventana para gestionar posiciones y lanzar clics.

        La ventana permite añadir/eliminar posiciones, guardar en targets/positions.json,
        iniciar/detener la secuencia de clics y ver un log en tiempo real.
        """
        ensure_targets_dir(self.targets_dir)
        positions_path = os.path.join(self.targets_dir, "positions.json")
        positions = {}
        if os.path.exists(positions_path):
            try:
                with open(positions_path, "r", encoding="utf-8") as f:
                    positions = json.load(f)
            except Exception:
                positions = {}

        if tk is None:
            messagebox.showerror(
                "Error",
                "Tkinter no está disponible: no se puede abrir gestor de posiciones",
            )
            self._log(
                "[ERROR] Tkinter no está disponible: no se puede abrir gestor de posiciones"
            )
            return

        win = tk.Toplevel(self.root)
        self._positions_win = win
        win.title("Gestor de posiciones")
        win.geometry("760x420")

        left = tk.Frame(win)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=8)
        tk.Label(left, text="Posiciones").pack()
        lb = tk.Listbox(left, width=30, height=20)
        lb.pack()

        lbl_cursor = tk.Label(left, text="Cursor: (0,0)")
        lbl_cursor.pack(pady=6)

        def update_cursor():
            try:
                p = pyautogui.position()
                lbl_cursor.config(text=f"Cursor: ({p.x},{p.y})")
            except Exception:
                lbl_cursor.config(text="Cursor: (error)")
            lbl_cursor.after(100, update_cursor)

        update_cursor()

        def populate_list():
            lb.delete(0, tk.END)
            for k in positions.keys():
                lb.insert(tk.END, k)

        def add_current():
            p = pyautogui.position()
            name = f"pos_{len(positions) + 1}"
            positions[name] = {
                "x": p.x,
                "y": p.y,
                "click_cooldown": 1.0,
                "jitter": 0,
                "button": "left",
                "enabled": True,
            }
            populate_list()
            self._log(f"Añadida {name} -> ({p.x},{p.y})")

        frm_manual = tk.Frame(left)
        frm_manual.pack(pady=6)
        tk.Label(frm_manual, text="X:").grid(row=0, column=0)
        ent_x = tk.Entry(frm_manual, width=6)
        ent_x.grid(row=0, column=1)
        tk.Label(frm_manual, text="Y:").grid(row=0, column=2)
        ent_y = tk.Entry(frm_manual, width=6)
        ent_y.grid(row=0, column=3)

        def add_manual():
            try:
                x = int(ent_x.get())
                y = int(ent_y.get())
            except Exception:
                messagebox.showerror("Error", "X e Y deben ser enteros")
                return
            name = f"pos_{len(positions) + 1}"
            positions[name] = {
                "x": x,
                "y": y,
                "click_cooldown": 1.0,
                "jitter": 0,
                "button": "left",
                "enabled": True,
            }
            populate_list()
            self._log(f"Añadida {name} -> ({x},{y})")

        tk.Button(left, text="Agregar manual", command=add_manual).pack(pady=4)
        tk.Button(left, text="Agregar posición (cursor)", command=add_current).pack(
            pady=4
        )

        # Grabación con la tecla 's' (global si pynput está disponible, local si no)
        recording_state = {"enabled": False, "listener": None}
        lbl_record = tk.Label(left, text="Grabación S: OFF")
        lbl_record.pack(pady=4)

        def toggle_recording_mode():
            if recording_state["enabled"]:
                # Detener grabación
                recording_state["enabled"] = False
                try:
                    if recording_state.get("listener"):
                        recording_state["listener"].stop()
                        recording_state["listener"] = None
                except Exception:
                    pass
                try:
                    win.unbind("<KeyPress-s>")
                except Exception:
                    pass
                toggle_btn.config(text="Grabar con S")
                lbl_record.config(text="Grabación S: OFF")
                enqueue_log("[INFO] Grabación con S detenida")
            else:
                # Iniciar grabación
                recording_state["enabled"] = True
                if pkb is not None:

                    def on_press_rec(key):
                        try:
                            if getattr(key, "char", None) and key.char.lower() == "s":
                                # Agregar posición en el hilo de la GUI
                                self.root.after(0, add_current)
                        except Exception:
                            pass

                    rec_listener = pkb.Listener(on_press=on_press_rec)
                    rec_listener.daemon = True
                    rec_listener.start()
                    recording_state["listener"] = rec_listener
                else:
                    # Fallback: binding local cuando la ventana tiene foco
                    win.bind("<KeyPress-s>", lambda e: add_current())
                toggle_btn.config(text="Detener grabación")
                lbl_record.config(text="Grabación S: ON")
                enqueue_log(
                    "[INFO] Grabación con S iniciada: presiona 's' para grabar posiciones"
                )

        toggle_btn = tk.Button(left, text="Grabar con S", command=toggle_recording_mode)
        toggle_btn.pack(pady=4)

        def remove_selected():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if not messagebox.askyesno("Eliminar", f"Eliminar {name} de la lista?"):
                return
            positions.pop(name, None)
            populate_list()
            self._log(f"Eliminada {name}")

        tk.Button(left, text="Eliminar seleccionado", command=remove_selected).pack(
            pady=4
        )

        def save_positions_local(pos):
            try:
                with open(positions_path, "w", encoding="utf-8") as f:
                    json.dump(pos, f, indent=2, ensure_ascii=False)
                self._log(f"Guardadas {len(pos)} posiciones en positions.json")
                messagebox.showinfo("Guardado", f"Guardadas {len(pos)} posiciones")
            except Exception as e:
                self._log(f"[ERROR] No se pudo guardar positions.json: {e}")
                messagebox.showerror("Error", f"No se pudo guardar: {e}")

        tk.Button(
            left,
            text="Guardar posiciones",
            command=lambda: save_positions_local(positions),
        ).pack(pady=4)

        right = tk.Frame(win)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        ctrl = tk.Frame(right)
        ctrl.pack(fill=tk.X)
        tk.Label(ctrl, text="Intervalo (s):").grid(row=0, column=0)
        interval_var = tk.DoubleVar(value=float(self.scan_interval_var.get()))
        tk.Entry(ctrl, textvariable=interval_var, width=6).grid(row=0, column=1)
        sim_var = tk.BooleanVar(value=bool(self.simulate_var.get()))
        tk.Checkbutton(ctrl, text="Simular", variable=sim_var).grid(
            row=0, column=2, padx=8
        )
        tk.Label(ctrl, text="Cuenta regresiva: ").grid(row=1, column=0)
        count_var = tk.IntVar(value=int(self.countdown_var.get()))
        tk.Entry(ctrl, textvariable=count_var, width=6).grid(row=1, column=1)
        tk.Label(ctrl, text="Máx. bucles (0=inf):").grid(row=2, column=0, sticky=tk.W)
        max_loops_var = tk.IntVar(value=0)
        tk.Entry(ctrl, textvariable=max_loops_var, width=6).grid(row=2, column=1, sticky=tk.W)

        # Retardo entre posiciones (global o por posición)
        tk.Label(ctrl, text="Retardo entre posiciones (s):").grid(
            row=0, column=3, sticky=tk.W
        )
        pos_delay_var = tk.DoubleVar(value=0.05)
        tk.Entry(ctrl, textvariable=pos_delay_var, width=6).grid(
            row=0, column=4, sticky=tk.W
        )
        use_global_delay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            ctrl, text="Usar retardo global", variable=use_global_delay_var
        ).grid(row=0, column=5, padx=8)

        def apply_global_delay_to_all():
            try:
                d = float(pos_delay_var.get())
            except Exception:
                messagebox.showerror("Error", "Retardo debe ser numérico")
                return
            for k in positions.keys():
                positions[k]["click_delay"] = float(d)
            enqueue_log(f"Aplicado retardo {d}s a {len(positions)} posiciones")

        tk.Button(ctrl, text="Aplicar a todas", command=apply_global_delay_to_all).grid(
            row=1, column=4, padx=4
        )

        # Modo de orden entre posiciones
        order_mode_var = tk.StringVar(value="Secuencial")
        ttk.Combobox(
            ctrl,
            textvariable=order_mode_var,
            values=(
                "Secuencial",
                "Aleatorio por pasada",
                "Evitar repetición consecutiva",
            ),
            width=26,
        ).grid(row=1, column=5, padx=8)

        # Contador de bucle
        loop_count = [0]
        max_lbl_str = tk.StringVar(value="∞")
        lbl_loop = tk.Label(ctrl, text="Bucle: 0/∞")
        lbl_loop.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=4)

        def refresh_max_label():
            ml = max_loops_var.get()
            max_lbl_str.set(str(ml) if ml > 0 else "∞")
            loop_count_val = loop_count[0] if loop_count else 0
            lbl_loop.config(text=f"Bucle: {loop_count_val}/{max_lbl_str.get()}")
            win.after(500, refresh_max_label)
        refresh_max_label()

        log_text = tk.Text(right)
        log_text.pack(fill=tk.BOTH, expand=True)

        # Usar una cola para pasar logs desde hilos al hilo de la GUI
        log_q = queue.Queue()

        def enqueue_log(s):
            try:
                log_q.put(s)
            except Exception:
                pass

        def poll_log_main():
            try:
                while not log_q.empty():
                    msg = log_q.get()
                    log_text.insert(tk.END, msg + "\n")
                    log_text.see(tk.END)
                    # también logear en la ventana principal
                    self._log(msg)
            except Exception:
                pass
            finally:
                win.after(200, poll_log_main)

        thread = None
        stop_event = threading.Event()
        running_flag = [False]
        last_clicked_name = [None]

        def pos_click_loop():
            last_clicks = {}
            while not stop_event.is_set():
                if running_flag[0]:
                    now = time.time()

                    # Incrementar contador de bucle y actualizar UI
                    try:
                        loop_count[0] += 1
                        ml = max_loops_var.get()
                        if ml > 0 and loop_count[0] > ml:
                            enqueue_log(f"[INFO] Límite de {ml} bucle(s) alcanzado. Deteniendo.")
                            running_flag[0] = False
                            stop_event.set()
                            break
                        max_str = str(ml) if ml > 0 else "∞"
                        win.after(
                            0, lambda: lbl_loop.config(text=f"Bucle: {loop_count[0]}/{max_str}")
                        )
                    except Exception:
                        pass

                    # Construir orden de iteración (posiciones habilitadas)
                    active_names = [
                        n
                        for n, info0 in positions.items()
                        if info0.get("enabled", True)
                    ]
                    if not active_names:
                        time.sleep(0.1)
                        continue

                    mode = order_mode_var.get() if order_mode_var else "Secuencial"
                    mode_key = str(mode).lower()
                    if mode_key in ("aleatorio", "aleatorio por pasada"):
                        names_iter = list(active_names)
                        random.shuffle(names_iter)
                    elif mode_key in (
                        "evitar repetición consecutiva",
                        "evitar_consecutivo",
                    ):
                        names_iter = list(active_names)
                        random.shuffle(names_iter)
                        try:
                            last_clicked = last_clicked_name[0]
                        except Exception:
                            last_clicked = None
                        if (
                            last_clicked is not None
                            and len(names_iter) > 1
                            and names_iter[0] == last_clicked
                        ):
                            # intercambiar con la siguiente para evitar repetición consecutiva
                            names_iter[0], names_iter[1] = names_iter[1], names_iter[0]
                    else:
                        names_iter = active_names

                    for name in names_iter:
                        info = positions.get(name, {})
                        if not info.get("enabled", True):
                            continue
                        x = int(info.get("x", 0))
                        y = int(info.get("y", 0))
                        cooldown = float(info.get("click_cooldown", interval_var.get()))
                        jitter = int(info.get("jitter", 0))
                        button = info.get("button", "left")
                        last = last_clicks.get((name, x, y), 0)
                        if time.time() - last < cooldown:
                            continue
                        jx = random.randint(-jitter, jitter) if jitter else 0
                        jy = random.randint(-jitter, jitter) if jitter else 0
                        tx, ty = x + jx, y + jy

                        if bool(sim_var.get()):
                            enqueue_log(
                                f"[SIMULADO] CLIC {name} en ({tx},{ty}) (cooldown={cooldown}s)"
                            )
                            # registrar la última posición clicada
                            try:
                                last_clicked_name[0] = name
                            except Exception:
                                pass
                        else:
                            try:
                                pyautogui.click(tx, ty, button=button)
                                enqueue_log(
                                    f"[CLIC] {name} en ({tx},{ty}) (boton={button})"
                                )
                                try:
                                    last_clicked_name[0] = name
                                except Exception:
                                    pass
                            except Exception as e:
                                enqueue_log(
                                    f"[ERROR] No se pudo clicar {name} en ({tx},{ty}): {e}"
                                )

                        last_clicks[(name, x, y)] = time.time()
                        # Retardo entre posiciones (global o por posición)
                        try:
                            if bool(use_global_delay_var.get()):
                                delay_between = float(pos_delay_var.get())
                            else:
                                delay_between = float(info.get("click_delay", 0.05))
                        except Exception:
                            delay_between = float(info.get("click_delay", 0.05))
                        time.sleep(delay_between)

                    time.sleep(float(interval_var.get()))
                else:
                    time.sleep(0.1)

            enqueue_log("Hilo de clics detenido")

        def start_clicking():
            nonlocal thread
            if thread and thread.is_alive():
                enqueue_log("Ya en ejecución")
                return
            if not bool(sim_var.get()):
                enqueue_log(
                    "ADVERTENCIA: se habilitarán clics reales. Preparando cuenta regresiva..."
                )

                def do_start_after(n):
                    nonlocal thread
                    if n <= 0:
                        running_flag[0] = True
                        stop_event.clear()
                        thread = threading.Thread(target=pos_click_loop, daemon=True)
                        thread.start()
                        enqueue_log("Hilo de clics lanzado")
                        return
                    enqueue_log(f"Iniciando en {n}...")
                    win.after(1000, lambda: do_start_after(n - 1))

                do_start_after(int(count_var.get()))
            else:
                running_flag[0] = True
                stop_event.clear()
                thread = threading.Thread(target=pos_click_loop, daemon=True)
                thread.start()
                enqueue_log("Hilo de clics lanzado")

        def stop_clicking():
            running_flag[0] = False
            stop_event.set()
            enqueue_log("Detenido por usuario")

        tk.Button(ctrl, text="Iniciar", command=start_clicking).grid(
            row=1, column=2, padx=8
        )
        tk.Button(ctrl, text="Detener", command=stop_clicking).grid(
            row=1, column=3, padx=8
        )

        populate_list()
        poll_log_main()

        try:
            # Exponer la ventana en self para que el listener global pueda inspeccionarla
            self._positions_win = win
        except Exception:
            pass

        # Atajos locales para control rápido desde el gestor de posiciones
        try:
            win.bind("<F6>", lambda e: toggle_local_scan())
            win.bind("<Escape>", lambda e: self._on_close())
        except Exception:
            pass

        def toggle_local_scan():
            # Actúa como los botones Iniciar/Detener del gestor
            if running_flag[0]:
                stop_clicking()
            else:
                start_clicking()

        enqueue_log(
            "[INFO] Atajos locales: F6 (toggle positions), Esc (cerrar gestor) activos"
        )

        # Mantener referencia hasta que la ventana se cierre
        try:
            win.mainloop()
        finally:
            try:
                # Si quedó un listener de grabación activo, detenerlo
                try:
                    if "recording_state" in locals() and recording_state.get(
                        "listener"
                    ):
                        try:
                            recording_state["listener"].stop()
                        except Exception:
                            pass
                except Exception:
                    pass
                self._positions_win = None
            except Exception:
                pass

    def _on_close(self):
        if self.scanner and self.scanner.running:
            if not messagebox.askyesno(
                "Salir", "El escáner está en ejecución. ¿Salir de todos modos?"
            ):
                return
        if self.scanner:
            self.scanner.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def run_headless(
    targets_dir: str, simulate: bool, demo: bool, duration: float, scan_interval: float
):
    targets_dir = resolve_targets_dir(targets_dir)
    scanner = Scanner(
        targets_dir,
        scan_interval=scan_interval,
        simulate=simulate,
        demo=demo,
        log_fn=lambda s: print(s),
    )
    scanner.start()
    try:
        if duration and duration > 0:
            time.sleep(duration)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("Interrumpido")
    finally:
        scanner.stop()


def main():
    parser = argparse.ArgumentParser(description="Autoclicker GUI / modo sin GUI")
    parser.add_argument(
        "--targets",
        help="Ruta a la carpeta targets (por defecto: targets junto al script)",
    )
    parser.add_argument(
        "--nogui", action="store_true", help="Ejecutar en modo headless (sin GUI)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simular los clics (sin clic real). En la GUI está activado por defecto",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo en headless: simular detección aun sin imágenes reales",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="Duración (s) para demo en headless; por defecto 2s",
    )
    parser.add_argument(
        "--scan-interval",
        type=float,
        default=DEFAULT_SCAN_INTERVAL,
        help="Intervalo de escaneo para modo headless",
    )

    args = parser.parse_args()

    targets_dir = resolve_targets_dir(args.targets)

    if args.nogui:
        simulate = bool(args.simulate) if args.simulate else True
        run_headless(
            targets_dir,
            simulate=simulate,
            demo=args.demo,
            duration=args.duration,
            scan_interval=args.scan_interval,
        )
        return

    app = AutoclickGUI(targets_dir)
    app.run()


if __name__ == "__main__":
    main()
