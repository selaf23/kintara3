#!/usr/bin/env python3
"""
Herramienta simple para registrar posiciones de pantalla y hacer clics en ellas.

Flujo:
 1) Registrar posiciones moviendo el ratón al punto y pulsando Enter (modo CLI) o
    usar la GUI para añadir posiciones.
 2) Guardar las posiciones en `targets/positions.json` (opcional).
 3) Ejecutar el bucle de clics: F6 para iniciar/detener, Esc para salir (modo CLI),
    o usar los botones Iniciar/Detener en la GUI.

Opciones de seguridad:
 - Por defecto se ejecuta en modo simulado (no hace clics reales).
 - Pasa --real para permitir clics reales (se muestra cuenta regresiva).

Uso rápido:
  python positions_clicker.py        # interactivo (CLI)
  python positions_clicker.py --gui  # GUI para gestionar posiciones y clics
"""

import argparse
import json
import os
import random
import threading
import time

import pyautogui
from pynput import keyboard

# Optional GUI support
try:
    import queue
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:
    tk = None
    queue = None

TARGETS_DIR = os.path.join(os.path.dirname(__file__), "targets")
POSITIONS_FILE = os.path.join(TARGETS_DIR, "positions.json")

pyautogui.FAILSAFE = True

clicking = False
running = True
last_click_times = {}


def ensure_targets_dir():
    os.makedirs(TARGETS_DIR, exist_ok=True)


def load_positions():
    if not os.path.exists(POSITIONS_FILE):
        return {}
    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_positions(positions: dict):
    ensure_targets_dir()
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] No se pudo guardar positions.json: {e}")


def record_positions_interactive():
    print("Registrar posiciones. Mueve el ratón a la posición deseada y pulsa Enter.")
    print("Escribe 'done' y pulsa Enter cuando hayas terminado.")
    positions = {}
    idx = 1
    while True:
        s = input(
            f"Registrar posición #{idx} (Enter para capturar / 'done' para terminar): "
        ).strip()
        if s.lower() == "done":
            break
        pos = pyautogui.position()
        name = input(
            f"Nombre para la posición #{idx} (por defecto pos_{idx}): "
        ).strip()
        if not name:
            name = f"pos_{idx}"
        positions[name] = {
            "x": pos.x,
            "y": pos.y,
            "click_cooldown": 1.0,
            "jitter": 0,
            "button": "left",
            "enabled": True,
        }
        print(f"Registrada {name} -> ({pos.x},{pos.y})")
        idx += 1
    return positions


def on_press(key):
    global clicking, running
    try:
        if key == keyboard.Key.f6:
            clicking = not clicking
            state = "INICIADO" if clicking else "DETENIDO"
            print(f"[Autoclicker] {state}")
        elif key == keyboard.Key.esc:
            print("[Autoclicker] Saliendo...")
            running = False
            return False
    except Exception:
        pass


def click_loop(
    positions_list, global_interval, simulate, order_mode="secuencial", log_fn=print, max_loops=0
):
    global running, clicking, last_click_times
    log_fn(
        "Hilo de clics iniciado. Usa el botón Iniciar/Detener o F6 para controlar, Esc para salir (CLI)."
    )
    loop_count = 0
    last_clicked = None
    while running:
        if clicking:
            loop_count += 1
            if max_loops > 0 and loop_count > max_loops:
                log_fn(f"[INFO] Límite de {max_loops} bucle(s) alcanzado. Deteniendo.")
                clicking = False
                running = False
                break
            now = time.time()
            log_fn(
                f"[BUCLE {loop_count}] Ejecutando {len(positions_list)} posiciones (modo={order_mode})"
            )
            # Construir lista de posiciones habilitadas
            entries = [
                (n, info)
                for n, info in positions_list.items()
                if info.get("enabled", True)
            ]
            if not entries:
                time.sleep(0.1)
                continue
            names = [n for n, _ in entries]
            mode = str(order_mode).lower() if order_mode else "secuencial"
            if mode == "aleatorio":
                names_iter = list(names)
                random.shuffle(names_iter)
            elif mode == "evitar_consecutivo":
                names_iter = list(names)
                random.shuffle(names_iter)
                if (
                    last_clicked is not None
                    and len(names_iter) > 1
                    and names_iter[0] == last_clicked
                ):
                    names_iter[0], names_iter[1] = names_iter[1], names_iter[0]
            else:
                names_iter = names
            for name in names_iter:
                info = positions_list.get(name, {})
                if not info:
                    continue
                x = int(info.get("x", 0))
                y = int(info.get("y", 0))
                cooldown = float(info.get("click_cooldown", global_interval))
                jitter = int(info.get("jitter", 0))
                button = info.get("button", "left")
                last = last_click_times.get((name, x, y), 0)
                if now - last < cooldown:
                    continue
                jx = 0
                jy = 0
                if jitter:
                    jx = random.randint(-jitter, jitter)
                    jy = random.randint(-jitter, jitter)
                tx, ty = x + jx, y + jy
                if simulate:
                    log_fn(
                        f"[SIMULADO] CLIC {name} en ({tx},{ty}) (cooldown={cooldown}s)"
                    )
                    last_clicked = name
                else:
                    try:
                        pyautogui.click(tx, ty, button=button)
                        log_fn(f"[CLIC] {name} en ({tx},{ty}) (boton={button})")
                        last_clicked = name
                    except Exception as e:
                        log_fn(f"[ERROR] No se pudo clicar {name} en ({tx},{ty}): {e}")
                last_click_times[(name, x, y)] = time.time()
                time.sleep(float(info.get("click_delay", 0.05)))
            # pausa entre pasadas
            time.sleep(global_interval)
        else:
            time.sleep(0.1)
    log_fn("Hilo de clics detenido")


def main():
    parser = argparse.ArgumentParser(
        description="Registrar posiciones y clicarlas en secuencia"
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Permite clics reales (por defecto simulado)",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Iniciar automáticamente el clic (riesgoso)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Intervalo por defecto entre pasadas (s)",
    )
    parser.add_argument(
        "--countdown", type=int, default=3, help="Cuenta regresiva antes de iniciar (s)"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Abrir interfaz gráfica para controlar posiciones y clics",
    )
    parser.add_argument(
        "--randomize",
        action="store_true",
        help="(deprecated) Ejecutar las posiciones en orden aleatorio cada pasada",
    )
    parser.add_argument(
        "--order-mode",
        choices=("secuencial", "aleatorio", "evitar_consecutivo"),
        default="secuencial",
        help="Modo de orden de posiciones: 'secuencial', 'aleatorio' (por pasada), 'evitar_consecutivo' (evita repetir la misma posición al inicio de la pasada)",
    )
    parser.add_argument(
        "--max-loops",
        type=int,
        default=0,
        help="Número máximo de bucles antes de detenerse (0 = infinito, por defecto)",
    )
    args = parser.parse_args()

    simulate = not args.real

    ensure_targets_dir()

    # Modo GUI
    if args.gui:
        if tk is None:
            print(
                "Tkinter no está disponible en este entorno; no se puede iniciar la GUI"
            )
            return

        positions = {}
        if os.path.exists(POSITIONS_FILE):
            # Cargar posiciones existentes sin preguntar para la GUI
            positions = load_positions()

        log_q = queue.Queue()

        def enqueue_log(s):
            try:
                log_q.put(s)
            except Exception:
                pass

        def poll_log(text_widget):
            try:
                while not log_q.empty():
                    text_widget.insert("end", log_q.get() + "\n")
                    text_widget.see("end")
                text_widget.after(200, lambda: poll_log(text_widget))
            except Exception:
                pass

        root = tk.Tk()
        root.title("Gestor de posiciones — GUI")
        root.geometry("760x420")

        left = tk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=8)
        tk.Label(left, text="Posiciones").pack()
        lb = tk.Listbox(left, width=30, height=20)
        lb.pack()

        lbl_cursor = tk.Label(left, text="Cursor: (0,0)")
        lbl_cursor.pack(pady=6)

        def update_cursor():
            p = pyautogui.position()
            try:
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
            enqueue_log(f"Añadida {name} -> ({p.x},{p.y})")

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
            enqueue_log(f"Añadida {name} -> ({x},{y})")

        tk.Button(left, text="Agregar posición (cursor)", command=add_current).pack(
            pady=4
        )
        tk.Button(left, text="Agregar manual", command=add_manual).pack(pady=4)

        # Grabación con la tecla 's' (global si pynput está disponible, local si no)
        recording_state = {"enabled": False, "listener": None}
        lbl_record = tk.Label(left, text="Grabación S: OFF")
        lbl_record.pack(pady=4)

        def toggle_recording_mode():
            if recording_state["enabled"]:
                recording_state["enabled"] = False
                try:
                    if recording_state.get("listener"):
                        recording_state["listener"].stop()
                        recording_state["listener"] = None
                except Exception:
                    pass
                try:
                    root.unbind("<KeyPress-s>")
                except Exception:
                    pass
                btn_record.config(text="Grabar con S")
                lbl_record.config(text="Grabación S: OFF")
                enqueue_log("[INFO] Grabación con S detenida")
            else:
                recording_state["enabled"] = True
                try:
                    # listener global
                    def on_press_rec(key):
                        try:
                            if getattr(key, "char", None) and key.char.lower() == "s":
                                root.after(0, add_current)
                        except Exception:
                            pass

                    rec_listener = keyboard.Listener(on_press=on_press_rec)
                    rec_listener.daemon = True
                    rec_listener.start()
                    recording_state["listener"] = rec_listener
                except Exception:
                    # fallback local binding
                    root.bind("<KeyPress-s>", lambda e: add_current())
                btn_record.config(text="Detener grabación")
                lbl_record.config(text="Grabación S: ON")
                enqueue_log(
                    "[INFO] Grabación con S iniciada: presiona 's' para grabar posiciones"
                )

        btn_record = tk.Button(left, text="Grabar con S", command=toggle_recording_mode)
        btn_record.pack(pady=4)

        def remove_selected():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if messagebox.askyesno("Eliminar", f"Eliminar {name}?"):
                positions.pop(name, None)
                populate_list()
                enqueue_log(f"Eliminada {name}")

        tk.Button(left, text="Eliminar seleccionado", command=remove_selected).pack(
            pady=4
        )

        def save_positions_ui():
            save_positions(positions)
            enqueue_log(f"Guardadas {len(positions)} posiciones")

        tk.Button(left, text="Guardar posiciones", command=save_positions_ui).pack(
            pady=4
        )

        right = tk.Frame(root)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        ctrl = tk.Frame(right)
        ctrl.pack(fill=tk.X)
        tk.Label(ctrl, text="Intervalo (s):").grid(row=0, column=0)
        interval_var = tk.DoubleVar(value=args.interval)
        tk.Entry(ctrl, textvariable=interval_var, width=6).grid(row=0, column=1)
        sim_var = tk.BooleanVar(value=simulate)
        tk.Checkbutton(ctrl, text="Simular", variable=sim_var).grid(
            row=0, column=2, padx=8
        )
        tk.Label(ctrl, text="Cuenta regresiva: ").grid(row=1, column=0)
        count_var = tk.IntVar(value=args.countdown)
        tk.Entry(ctrl, textvariable=count_var, width=6).grid(row=1, column=1)
        tk.Label(ctrl, text="Máx. bucles (0=inf):").grid(row=2, column=0, sticky=tk.W)
        max_loops_var = tk.IntVar(value=args.max_loops)
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
        order_mode_var = tk.StringVar(value="secuencial")
        ttk.Combobox(
            ctrl,
            textvariable=order_mode_var,
            values=("secuencial", "aleatorio", "evitar_consecutivo"),
            width=26,
        ).grid(row=1, column=5, padx=8)

        # Contador de bucle
        loop_count = [0]
        lbl_loop = tk.Label(ctrl, text="Bucle: 0/∞")
        lbl_loop.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=4)

        def update_loop_label():
            max_l = max_loops_var.get()
            max_str = str(max_l) if max_l > 0 else "∞"
            lbl_loop.config(text=f"Bucle: {loop_count[0]}/{max_str}")
            root.after(500, update_loop_label)
        update_loop_label()

        log_text = tk.Text(right)
        log_text.pack(fill=tk.BOTH, expand=True)

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
                        max_l = max_loops_var.get()
                        if max_l > 0 and loop_count[0] > max_l:
                            enqueue_log(f"[INFO] Límite de {max_l} bucle(s) alcanzado. Deteniendo.")
                            running_flag[0] = False
                            stop_event.set()
                            break
                        max_str = str(max_l) if max_l > 0 else "∞"
                        root.after(
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

                    mode = order_mode_var.get() if order_mode_var else "secuencial"
                    if mode == "aleatorio":
                        names_iter = list(active_names)
                        random.shuffle(names_iter)
                    elif mode == "evitar_consecutivo":
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
                        if now - last < cooldown:
                            continue
                        jx = 0
                        jy = 0
                        if jitter:
                            jx = random.randint(-jitter, jitter)
                            jy = random.randint(-jitter, jitter)
                        tx, ty = x + jx, y + jy
                        if bool(sim_var.get()):
                            enqueue_log(
                                f"[SIMULADO] CLIC {name} en ({tx},{ty}) (cooldown={cooldown}s)"
                            )
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

        def poll_log_main():
            try:
                while not log_q.empty():
                    log_text.insert("end", log_q.get() + "\n")
                    log_text.see("end")
                # También se puede imprimir en consola y/o escribir a fichero
                root.after(200, poll_log_main)
            except Exception:
                pass

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
                    if n <= 0:
                        running_flag[0] = True
                        stop_event.clear()
                        thread = threading.Thread(target=pos_click_loop, daemon=True)
                        thread.start()
                        enqueue_log("Hilo de clics lanzado")
                        return
                    enqueue_log(f"Iniciando en {n}...")
                    root.after(1000, lambda: do_start_after(n - 1))

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
            root.mainloop()
        finally:
            try:
                if "recording_state" in locals() and recording_state.get("listener"):
                    try:
                        recording_state["listener"].stop()
                    except Exception:
                        pass
            except Exception:
                pass
        return

    # Modo CLI / interactivo
    positions = {}
    if os.path.exists(POSITIONS_FILE):
        s = input("Se encontró positions.json. ¿Cargarla? [Y/n]: ").strip().lower()
        if s == "" or s == "y" or s == "s":
            positions = load_positions()
        else:
            positions = record_positions_interactive()
    else:
        positions = record_positions_interactive()

    if not positions:
        print("No se registraron posiciones. Saliendo.")
        return

    s = input("¿Guardar posiciones en targets/positions.json? [Y/n]: ").strip().lower()
    if s == "" or s == "y" or s == "s":
        save_positions(positions)
        print(f"Guardadas {len(positions)} posiciones en {POSITIONS_FILE}")

    print(f"Posiciones: {positions}")
    print(f"Modo: {'SIMULADO' if simulate else 'REAL'}")

    if args.max_loops == 0:
        s = input("¿Cuántos bucles quieres ejecutar? (Enter = infinito): ").strip()
        if s:
            try:
                args.max_loops = max(0, int(s))
            except ValueError:
                args.max_loops = 0
        if args.max_loops > 0:
            print(f"Se ejecutarán {args.max_loops} bucle(s) máximo.")
        else:
            print("Modo infinito (se detiene con F6 o Esc).")

    if not simulate:
        print(
            "ADVERTENCIA: se habilitarán clics reales. Asegúrate de que el cursor esté en una zona segura."
        )
        print(f"Iniciando en {args.countdown} segundos...")
        time.sleep(args.countdown)

    # Start background thread
    # Determinar modo de orden (compatibilidad con --randomize)
    order_mode = args.order_mode
    if args.randomize:
        order_mode = "aleatorio"

    t = threading.Thread(
        target=click_loop,
        args=(positions, args.interval, simulate, order_mode, print, args.max_loops),
        daemon=True,
    )
    t.start()

    # Keyboard listener (F6 to toggle, Esc to exit)
    with keyboard.Listener(on_press=on_press) as listener:
        if args.auto_start:
            global clicking
            clicking = True
            print("Autostart activado: comenzando a clicar")
        listener.join()

    # Clean shutdown
    running = False
    t.join(timeout=1)


if __name__ == "__main__":
    main()
