#!/usr/bin/env bash
# ============================================
# build_macos.sh — Compila kantana para macOS
# ============================================
# Uso:  chmod +x build_macos.sh && ./build_macos.sh
# Requiere: Python 3.10+, pip, Xcode CLT (opcional)
set -euo pipefail

echo "=== Versión de Python ==="
python3 -V

# Crear carpeta targets si no existe
mkdir -p targets

# Virtualenv
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "=== Instalando dependencias ==="
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install 'pyinstaller>=6.0'

echo "=== Compilando GUI (autoclick_gui.py) ==="
pyinstaller --clean --noconfirm --onefile --windowed \
    --add-data "targets:targets" \
    --hidden-import positions_clicker \
    --name "kantana" \
    autoclick_gui.py 2>&1 | tee pyinstaller-macos.log

echo "=== Compilando CLI (autoclick_image.py) ==="
pyinstaller --clean --noconfirm --onefile --console \
    --add-data "targets:targets" \
    --name "kantana-cli" \
    autoclick_image.py 2>&1 | tee pyinstaller-macos-cli.log

# Preparar artifact
mkdir -p artifact
if [ -f dist/kantana ]; then cp dist/kantana artifact/kantana-macos; fi
if [ -f dist/kantana-cli ]; then cp dist/kantana-cli artifact/kantana-cli-macos; fi
if [ -d targets ]; then cp -R targets artifact/targets; fi

echo "=== Compilación finalizada ==="
echo "GUI: artifact/kantana-macos"
echo "CLI: artifact/kantana-cli-macos"
