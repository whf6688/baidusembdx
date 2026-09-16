$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$drive = "S:"

if (-not (Test-Path "$drive\")) {
    subst $drive $projectRoot
}

try {
    Push-Location "$drive\"
    docker compose down
}
finally {
    Pop-Location
    subst $drive /d | Out-Null
}

Write-Host "Project stopped. Persistent data on E: was retained."
