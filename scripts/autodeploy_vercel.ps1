# Keep the Vercel site in lockstep with GitHub main until the Vercel GitHub app is installed.
# Polls origin/main; when web/ changed, deploys THAT commit from a clean worktree (never local edits).
#   powershell -ExecutionPolicy Bypass -File scripts\autodeploy_vercel.ps1 [-Interval 45]
param([int]$Interval = 45, [string]$Scope = "neelsirivaras-projects")
$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$wt = Join-Path $root ".deploy-worktree"
Set-Location $root
git fetch -q origin
if (-not (Test-Path $wt)) { git worktree add -f --detach $wt origin/main 2>&1 | Out-Null }
$link = Join-Path $root "web\.vercel\project.json"
function Deploy([string]$sha) {
  git -C $wt checkout -q --detach $sha
  New-Item -ItemType Directory -Force (Join-Path $wt "web\.vercel") | Out-Null
  Copy-Item $link (Join-Path $wt "web\.vercel\project.json") -Force
  $out = vercel deploy --cwd (Join-Path $wt "web") --prod --yes --scope $Scope 2>&1 | Out-String
  if ($out -match "Aliased\s+(\S+)") { "$(Get-Date -Format HH:mm:ss) deployed $($sha.Substring(0,7)) -> $($Matches[1])" }
  else { "$(Get-Date -Format HH:mm:ss) DEPLOY FAILED for $($sha.Substring(0,7)): $($out.Trim().Split("`n")[-1])" }
}
$last = (git rev-parse origin/main).Trim()
"$(Get-Date -Format HH:mm:ss) watching origin/main at $($last.Substring(0,7)) for web/ changes"
while ($true) {
  Start-Sleep $Interval
  git fetch -q origin 2>$null
  $new = (git rev-parse origin/main).Trim()
  if ($new -ne $last) {
    $changed = git diff --name-only $last $new -- web/
    if ($changed) { Deploy $new } else { "$(Get-Date -Format HH:mm:ss) main moved to $($new.Substring(0,7)) (no web/ changes, site already current)" }
    $last = $new
  }
}
