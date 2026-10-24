# Launch a scaffold.   .\run.ps1 mise | bench | sight   [-Engine litert|ollama] [-Dual] [-Port 8000]
#   -Dual  : run the always-on watcher on a second model (Gemma 4 E2B on CPU; -WatchBackend npu for the Intel NPU)
#   -Phone : serve HTTPS to the local network for an iPhone (setup page with QR on port 8080, app on 8443)
param(
  [string]$App = "mise",
  [string]$Engine = "litert",
  [switch]$Dual,
  [switch]$Phone,
  [string]$WatchBackend = "cpu",
  [int]$Port = 0
)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = "1"
$env:APP = $App
$env:GEMMA_ENGINE = $Engine
if ($Phone) { $env:PHONE = "1"; if (-not $Port) { $Port = 8443 } } else { Remove-Item Env:PHONE -ErrorAction SilentlyContinue; if (-not $Port) { $Port = 8000 } }
$env:PORT = "$Port"
if ($Dual) {
  if ($WatchBackend -eq "npu") { $env:GEMMA_WATCH_MODEL = "$root\models\gemma-4-E2B-it_intel_LNL.litertlm" }
  else { $env:GEMMA_WATCH_MODEL = "$root\models\gemma-4-E2B-it.litertlm" }
  $env:GEMMA_WATCH_BACKEND = $WatchBackend
} else {
  Remove-Item Env:GEMMA_WATCH_MODEL -ErrorAction SilentlyContinue
}
$env:OPEN_BROWSER = "1"   # the server opens the page once models are warmed up
& "$root\.venv\Scripts\python.exe" -m core.server $App
