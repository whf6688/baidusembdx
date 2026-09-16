$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path $projectRoot "data"
$dockerDiskOnC = Join-Path $env:LOCALAPPDATA "Docker\wsl\disk\docker_data.vhdx"

if ((Split-Path -Qualifier $projectRoot) -ne "E:") {
    throw "Project storage must remain on drive E:."
}

if (Test-Path -LiteralPath $dockerDiskOnC) {
    $target = Join-Path $dataRoot "DockerDesktopWSL"
    throw "Docker disk is still on C:. In Docker Desktop > Settings > Resources > Advanced, change Disk image location to: $target"
}

foreach ($name in @("postgres", "redis", "analytics", "storage", "DockerDesktopWSL")) {
    New-Item -ItemType Directory -Path (Join-Path $dataRoot $name) -Force | Out-Null
}

docker info --format "Docker Engine {{.ServerVersion}}" | Write-Host

$drive = "S:"
if (Test-Path "$drive\") {
    $existing = (Get-Item "$drive\").FullName
    if ($existing -ne "$drive\") {
        throw "$drive is already in use."
    }
} else {
    subst $drive $projectRoot
}

try {
    Push-Location "$drive\"
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose build or startup failed. Existing containers were left untouched."
    }
    docker compose ps
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose status check failed."
    }
}
finally {
    Pop-Location
    subst $drive /d | Out-Null
}

$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 3
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/health" -TimeoutSec 5
        if ($health.status -eq "ok") {
            Write-Host "Project started: http://127.0.0.1:8080"
            exit 0
        }
    } catch {
        # Services are still initializing.
    }
} while ((Get-Date) -lt $deadline)

throw "Containers started, but health check did not pass within 3 minutes. Run: docker compose logs api"
