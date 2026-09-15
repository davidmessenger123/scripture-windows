# Build dist\Scripture.exe (PyInstaller) then an Inno Setup installer.
# Run from the repository root in a PowerShell prompt on Windows.
#
#   .\scripts\build-installer.ps1                 # version defaults to 0.1.0
#   .\scripts\build-installer.ps1 -AppVersion 1.0.0
#
# Prerequisites:
#   * Python 3.9+  (python must be on PATH)
#   * Inno Setup 6 (https://jrsoftware.org/isinfo.php)
#
param([string]$AppVersion = "0.1.0")

Write-Host "=== Scripture installer build v$AppVersion ===" -ForegroundColor Cyan

# -- Step 1: ensure icon exists ------------------------------------------
Write-Host "`n[1/4] Installing Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# -- Step 2: ensure icon exists ------------------------------------------
Write-Host "`n[2/4] Generating app icon..."
if (-not (Test-Path "assets\app.ico")) {
    python scripts\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed" }
} else {
    Write-Host "  assets\app.ico exists, skipping."
}

# -- Step 3: build onefile exe -------------------------------------------
Write-Host "`n[3/4] Building dist\Scripture.exe (PyInstaller)..."
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

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "  dist\Scripture.exe built."

# -- Step 4: locate Inno Setup 6 -----------------------------------------
Write-Host "`n[4/4] Locating Inno Setup 6..."
$isccPaths = @(
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
$iscc = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host ""
    throw ("Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php`n" +
           "and try again, or add ISCC.exe to PATH.")
}
Write-Host "  ISCC: $iscc"

# -- Step 5: compile installer -------------------------------------------
Write-Host "`n[5/5] Building dist\Scripture-Setup-$AppVersion.exe (Inno Setup)..."
& $iscc /DAppVersion=$AppVersion installer\scripture.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "`nDone." -ForegroundColor Green
Write-Host "  dist\Scripture.exe                    (portable onefile build)"
Write-Host "  dist\Scripture-Setup-$AppVersion.exe   (per-user installer)"