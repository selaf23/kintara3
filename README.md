# kantana

Autoclicker por imagenes — GUI y utilidades
==========================================

Este repositorio contiene una herramienta para detectar imágenes en pantalla y hacer clic sobre ellas automáticamente. Tiene:

- `autoclick_gui.py` — Interfaz gráfica (Tkinter) para añadir objetivos, configurar opciones por objetivo y controlar el autoclicker. Incluye un botón `Posiciones` que abre un gestor de posiciones (ver sección "Posiciones" más abajo).
- `positions_clicker.py` — Herramienta para registrar/gestionar posiciones y ejecutar clics por coordenadas (tiene modo CLI y GUI independiente).
- `autoclick_image.py` — Versión headless (sin GUI) para usar desde línea de comandos o empaquetar.
- `add_target.py` — Helper para copiar imágenes a `targets/` y registrar opciones por objetivo en `targets/config.json`.
- `build_windows.ps1` — Script PowerShell que ayuda a generar un `.exe` en Windows con PyInstaller (local).
- `run_safe.py` — Runner seguro que simula clics (no mueve el ratón) para pruebas.
- `.github/workflows/build-binaries.yml` — workflow de GitHub Actions que intenta construir binarios (opcional).

Estado recomendado
------------------
- Para distribuir un `.exe` de Windows lo más fiable es compilar localmente en una máquina Windows usando `build_windows.ps1` (o usar el workflow de Actions si prefieres CI).
- Para pruebas rápidas usa el modo simulado (`Simulate`) en la GUI o ejecuta `run_safe.py`.

Requisitos
----------
- Python 3.8+ (recomendado 3.11)
- `pip` para instalar dependencias (se incluye `requirements.txt`)
- En Windows: instala Python desde https://python.org para incluir Tcl/Tk (Tkinter)
- En macOS: concede permisos de Accessibility / Input Monitoring al intérprete o ejecutable para clics reales

Cómo preparar el entorno (recomendado)
-------------------------------------
Usa un virtualenv:

```bash
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Uso — Interfaz gráfica (recomendado)
-----------------------------------
1. Ejecuta la GUI:

```bash
python autoclick_gui.py
```

2. En la ventana puedes:
- `Agregar imagen` → selecciona una captura del botón/área objetivo; se copiará a `targets/`.
- Seleccionar un objetivo y presionar `Guardar objetivo` para ajustar:
  - `Intervalo entre clics` (segundos) — mínimo entre clics sobre ese objetivo (guardado como `click_cooldown`).
  - `Confianza (0-1)` — para matching con OpenCV si está instalado.
  - `Jitter` — variación aleatoria en píxeles para evitar clics idénticos.
  - `Retardo entre clics` — pausa entre clicks cuando hay varias coincidencias.
  - `Botón` — `left`, `right` o `middle`.
- Controles globales: `Intervalo de escaneo`, `Simular` (por defecto ON), `Cuenta regresiva`, `Iniciar` / `Detener`.

Uso — Modo headless / línea de comandos
---------------------------------------
- Demo simulado (no hace clics reales):

```bash
python autoclick_gui.py --nogui --simulate --demo --duration 5
```

- Ejecutar el autoclicker headless en modo real (usa `targets/`):

```bash
python autoclick_image.py --scan-interval 0.5 --confidence 0.85
```

- Script sencillo de autoclick en una posición fija (ejemplo):

```bash
python main.py
```

Añadir objetivos desde la CLI
----------------------------
Puedes copiar la imagen manualmente a `targets/` o usar `add_target.py` para copiar y fijar opciones:

```bash
python add_target.py /ruta/a/mi-boton.png --click-interval 2.5 --confidence 0.9 --jitter 3 --button left --enabled true
```

Esto actualizará `targets/config.json` con la entrada por `basename` del archivo.

Construir `.exe` en Windows (local)
-----------------------------------
En Windows, desde la raíz del repo ejecuta el helper PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

- El script crea un virtualenv, instala dependencias y ejecuta PyInstaller.
- El exe resultante quedará (si todo va bien) en `artifact\autoclicker-windows.exe`.
- Nota: `build_windows.ps1` crea `targets/` si no existe para evitar errores con `--add-data`.

Si quieres controlar todo manualmente en Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install pyinstaller==5.11
pyinstaller --clean --noconfirm --onefile --add-data "targets;targets" --name autoclicker autoclick_gui.py
```

Si falla al empaquetar la GUI por Tk/Tcl puedes probar empaquetar la versión headless:

```powershell
pyinstaller --clean --noconfirm --onefile --add-data "targets;targets" --name autoclicker autoclick_image.py
```

Construir en macOS
------------------
- Recomendado: crea venv, instala `requirements.txt` y ejecuta `python3 autoclick_gui.py`.
- Para empaquetar con PyInstaller en macOS:

```bash
pyinstaller --onefile --add-data "targets:targets" --name autoclicker autoclick_image.py
```

Permisos en macOS
-----------------
- Para hacer clics reales y monitorizar teclas globales debes dar permisos en:
  System Settings → Privacy & Security → Accessibility / Input Monitoring
  Añade el intérprete Python o el ejecutable final.

Solución de problemas rápida
----------------------------
- ERROR: `Unable to find '.../targets'` → crea la carpeta `targets` o añade al menos una imagen.
  ```powershell
  mkdir .\targets
  ```
- Si PyInstaller falla, revisa el log `pyinstaller-windows.log` (si usas el helper) o la salida de consola y pégala aquí para que la revise.
- Si la GUI no arranca: asegúrate de usar la distribución oficial de Python (python.org) para tener Tcl/Tk.
- Si el exe se queda bloqueado al arrancar: puede faltar Visual C++ Redistributable en Windows.

Distribución del exe
--------------------
- Evita subir binarios grandes a `main` del repo (ensucian el historial). Si deseas, crea una rama `binaries` o publica un Release y sube allí el `.exe`.
- Puedo añadir el `.exe` a la rama `binaries` si me facilitas el archivo o un enlace público de descarga.

CI / GitHub Actions
-------------------
- Hay un workflow en `.github/workflows/build-binaries.yml` que intenta construir binarios en runners Windows/macOS. Puede fallar por empaquetado de Tk/Tcl; el método local en Windows suele ser más fiable.

Si necesitas ayuda
------------------
- Si algo falla al ejecutar el build en Windows, copia/pega aquí la salida de `pyinstaller-windows.log` o la consola y lo depuro.
- Si quieres, te guío paso a paso mientras ejecutas el script en Windows.

---

Si quieres que actualice esto con más capturas o ejemplos concretos, dimelo y lo añado.# kintara3
