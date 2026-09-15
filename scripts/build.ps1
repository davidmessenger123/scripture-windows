# Build a one-folder Windows build with PyInstaller.
# Run from the repository root in a PowerShell prompt.
Write-Host "Note: run this on Windows (it is the target platform)."

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
    --noconfirm `
    --clean `
    --name Scripture `
    --onefile `
    --windowed `
    --add-data "src/scripture/qml;scripture/qml" `
    --hidden-import PySide6.QtQml `
    src\scripture\__main__.py

Write-Host "Built dist\Scripture.exe"