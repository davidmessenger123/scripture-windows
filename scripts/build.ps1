# Build a one-file Windows build with PyInstaller.
# Run from the repository root in a PowerShell prompt.
Write-Host "Note: run this on Windows (it is the target platform)."
Write-Host "For a ready-to-send installer, use scripts\build-installer.ps1 instead."

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (-not (Test-Path "assets\app.ico")) {
    python scripts\make_icon.py
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --name Scripture `
    --onefile `
    --windowed `
    --icon assets\app.ico `
    --add-data "src\scripture\qml;scripture\qml" `
    --paths src `
    --hidden-import PySide6.QtQml `
    src\scripture\__main__.py

Write-Host "Built dist\Scripture.exe"