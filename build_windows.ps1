<#
.SYNOPSIS
  Construye el ejecutable .exe en Windows usando PyInstaller.
.DESCRIPTION
  Crea un virtualenv, instala dependencias y compila autoclick_gui.py a .exe.
  El resultado se copia a artifact/autoclicker-windows.exe.
.Uso
  powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "=== Versión de Python ===" -ForegroundColor Cyan
python -V

# Crear carpeta targets si no existe
if (!(Test-Path targets)) { New-Item -ItemType Directory targets | Out-Null }

# Virtualenv
if (!(Test-Path .venv)) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1

Write-Host "=== Instalando dependencias ===" -ForegroundColor Cyan
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install pyinstaller==6.11.1

Write-Host "=== Compilando GUI (autoclick_gui.py) ===" -ForegroundColor Cyan
pyinstaller --clean --noconfirm --onefile --windowed `
    --add-data "targets;targets" `
    --hidden-import positions_clicker `
    --name "kantana" `
    autoclick_gui.py 2>&1 | Tee-Object -FilePath pyinstaller-windows.log

# También compilar versión headless (CLI)
Write-Host "=== Compilando CLI (autoclick_image.py) ===" -ForegroundColor Cyan
pyinstaller --clean --noconfirm --onefile --console `
    --add-data "targets;targets" `
    --name "kantana-cli" `
    autoclick_image.py 2>&1 | Tee-Object -FilePath pyinstaller-windows-cli.log

# Preparar artifact
if (!(Test-Path artifact)) { New-Item -ItemType Directory artifact | Out-Null }
if (Test-Path .\dist\kantana.exe) { Copy-Item -Path .\dist\kantana.exe -Destination .\artifact\kantana-windows.exe -Force }
if (Test-Path .\dist\kantana-cli.exe) { Copy-Item -Path .\dist\kantana-cli.exe -Destination .\artifact\kantana-cli-windows.exe -Force }
if (Test-Path targets) { Copy-Item -Path .\targets -Destination .\artifact\targets -Recurse -Force }

Write-Host "=== Compilación finalizada ===" -ForegroundColor Green
Write-Host "GUI: .\artifact\kantana-windows.exe" -ForegroundColor Green
Write-Host "CLI: .\artifact\kantana-cli-windows.exe" -ForegroundColor Green
