# Creates a double-clickable "Mise" shortcut on the Desktop and in the Start Menu (Windows).
#   powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
# The shortcut runs .venv\Scripts\pythonw.exe -m core.launcher (no terminal window).
# Safe to re-run: existing shortcuts are overwritten.
$ErrorActionPreference = 'Stop'

$Root    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python  = Join-Path $Root '.venv\Scripts\python.exe'
$Pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Png     = Join-Path $Root 'web\icons\icon-512.png'
$Ico     = Join-Path $Root 'web\icons\mise.ico'

if (-not (Test-Path $Pythonw)) {
    Write-Host "Could not find $Pythonw. Create the venv first (see README: py -3.12 -m venv .venv)." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Png)) {
    Write-Host "Could not find $Png." -ForegroundColor Red
    exit 1
}

# 1. Multi-size .ico from the 512px app icon (uses the venv's Pillow).
$code = "import sys; from PIL import Image; Image.open(sys.argv[1]).convert('RGBA').save(sys.argv[2], format='ICO', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])"
& $Python -c $code $Png $Ico
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Ico)) {
    Write-Host "Failed to create $Ico" -ForegroundColor Red
    exit 1
}
Write-Host "Icon:     $Ico"

# 2. Shortcuts on the Desktop and in Start Menu > Programs.
$Shell = New-Object -ComObject WScript.Shell
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mise.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Mise.lnk')
)
foreach ($Lnk in $Targets) {
    $Dir = Split-Path $Lnk -Parent
    if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Path $Dir -Force | Out-Null }
    if (Test-Path $Lnk) { Remove-Item $Lnk -Force }
    $s = $Shell.CreateShortcut($Lnk)
    $s.TargetPath       = $Pythonw
    $s.Arguments        = '-m core.launcher'
    $s.WorkingDirectory = $Root
    $s.IconLocation     = "$Ico,0"
    $s.Description      = 'Mise: your offline sous-chef'
    $s.WindowStyle      = 1
    $s.Save()
    Write-Host "Shortcut: $Lnk"
}

Write-Host ""
Write-Host "Done. Double-click 'Mise' on your Desktop or in the Start Menu to start Mise." -ForegroundColor Green
