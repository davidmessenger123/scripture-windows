# Build a one-file Windows build with PyInstaller.
# Run from the repository root in a PowerShell prompt.
$ErrorActionPreference = "Stop"
Write-Host "Note: run this on Windows (it is the target platform)."
Write-Host "For a ready-to-send installer, use scripts\build-installer.ps1 instead."

python -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
python -m pip install --disable-pip-version-check --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw "editable install failed" }

if (-not (Test-Path "assets\app.ico")) {
    python scripts\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed" }
}

python -m PyInstaller --noconfirm --clean Scripture.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Built dist\Scripture.exe"