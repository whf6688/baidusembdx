[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataRoot = Join-Path $ProjectRoot "data\deploy"
$LogRoot = Join-Path $DataRoot "logs"
$ReleaseId = Get-Date -Format "yyyyMMdd-HHmmss"
$ArchiveName = "baidu-search-$ReleaseId.tar.gz"
$ArchivePath = Join-Path $DataRoot $ArchiveName
$LogPath = Join-Path $LogRoot "publish-$ReleaseId.log"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RemoteHelper = Join-Path $ProjectRoot "scripts\ecs_remote.py"
$RemoteArchive = "/tmp/$ArchiveName"
$RemotePublisher = "/tmp/publish-release.sh"
$GitSyncKey = Join-Path $ProjectRoot "data\git-sync\id_ed25519"
$GitSyncKnownHosts = Join-Path $ProjectRoot "data\git-sync\known_hosts"
$RemoteGitSyncKey = "/tmp/baidu-search-git-sync-$ReleaseId"
$RemoteGitSyncKnownHosts = "/tmp/baidu-search-git-known-hosts-$ReleaseId"
$TranscriptStarted = $false

function Write-Stage([string]$Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Message (exit code: $LASTEXITCODE)"
    }
}

New-Item -ItemType Directory -Path $DataRoot, $LogRoot -Force | Out-Null

try {
    Start-Transcript -Path $LogPath -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "Baidu Search Console - One-click publish" -ForegroundColor Green
    Write-Host "Target: https://www.pztxwx.cn"
    Write-Host "Release: $ReleaseId"

    if (-not $Yes) {
        $answer = Read-Host "Publish the current local version? Type YES to continue"
        if ($answer -cne "YES") {
            Write-Host "Publish cancelled."
            exit 0
        }
    }

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Local Python environment is missing: $Python"
    }
    if (-not (Test-Path -LiteralPath $RemoteHelper)) {
        throw "Server connection helper is missing: $RemoteHelper"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "data\ssh\baidu-search-ecs-ed25519"))) {
        throw "Aliyun SSH key is missing."
    }
    if (-not (Test-Path -LiteralPath $GitSyncKey) -or -not (Test-Path -LiteralPath $GitSyncKnownHosts)) {
        throw "Search project GitHub sync key is missing."
    }

    if (-not $SkipTests) {
        Write-Stage "Check backend"
        Push-Location $ProjectRoot
        try {
            & $Python -m pytest backend\tests -q
            Assert-LastExitCode "Backend checks failed"
        }
        finally {
            Pop-Location
        }

        Write-Stage "Check frontend"
        $Npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        Push-Location (Join-Path $ProjectRoot "frontend")
        try {
            if (-not (Test-Path -LiteralPath "node_modules")) {
                & $Npm install
                Assert-LastExitCode "Frontend dependency installation failed"
            }
            & $Npm run build
            Assert-LastExitCode "Frontend checks failed"
        }
        finally {
            Pop-Location
        }
    }

    Write-Stage "Create a secret-free release archive"
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    $Tar = (Get-Command tar.exe -ErrorAction Stop).Source
    $TarArgs = @(
        "-czf", $ArchivePath,
        "--exclude=.env", "--exclude=.env.*", "--exclude=deploy/.env.production",
        "--exclude=frontend/node_modules", "--exclude=frontend/dist",
        "--exclude=frontend/test-results", "--exclude=frontend/playwright-report",
        "--exclude=backend/.pytest_cache", "--exclude=backend/.ruff_cache",
        "--exclude=**/__pycache__", "--exclude=*.pyc", "--exclude=*.duckdb*",
        "-C", $ProjectRoot,
        "backend", "frontend", "packages", "deploy", "scripts", ".dockerignore", "README.md", "AGENTS.md"
    )
    & $Tar @TarArgs
    Assert-LastExitCode "Release archive creation failed"

    $Entries = & $Tar -tzf $ArchivePath
    Assert-LastExitCode "Release archive validation failed"
    $Forbidden = $Entries | Where-Object {
        $_ -match '(^|/)\.env($|\.)' -or
        $_ -match '(^|/)data/' -or
        $_ -match '(^|/)storage/' -or
        $_ -match 'htpasswd' -or
        $_ -match 'baidu-search-ecs-ed25519'
    }
    if ($Forbidden) {
        throw "Release archive contains forbidden files: $($Forbidden -join ', ')"
    }

    Write-Stage "Upload to Aliyun"
    & $Python $RemoteHelper put $ArchivePath $RemoteArchive
    Assert-LastExitCode "Release archive upload failed"
    & $Python $RemoteHelper put (Join-Path $ProjectRoot "deploy\publish-release.sh") $RemotePublisher
    Assert-LastExitCode "Remote publisher upload failed"
    & $Python $RemoteHelper put $GitSyncKey $RemoteGitSyncKey
    Assert-LastExitCode "GitHub sync key upload failed"
    & $Python $RemoteHelper put $GitSyncKnownHosts $RemoteGitSyncKnownHosts
    Assert-LastExitCode "GitHub known-hosts upload failed"
    $InstallGitSyncSecrets = "install -d -m 700 /www/baidu-search/secrets/git-sync /www/baidu-search/repository && install -m 600 $RemoteGitSyncKey /www/baidu-search/secrets/git-sync/id_ed25519 && install -m 644 $RemoteGitSyncKnownHosts /www/baidu-search/secrets/git-sync/known_hosts && rm -f $RemoteGitSyncKey $RemoteGitSyncKnownHosts"
    & $Python $RemoteHelper exec $InstallGitSyncSecrets
    Assert-LastExitCode "GitHub sync secret installation failed"

    Write-Stage "Back up and switch the online release"
    $RemoteCommand = "bash $RemotePublisher $RemoteArchive $ReleaseId"
    & $Python $RemoteHelper exec $RemoteCommand
    Assert-LastExitCode "Online publish failed; the server attempted to restore the previous release"

    Write-Stage "Final health check"
    $Health = Invoke-WebRequest `
        -Uri "https://www.pztxwx.cn/api/v1/health" `
        -UseBasicParsing `
        -TimeoutSec 30
    if ($Health.StatusCode -ne 200) {
        throw "Online health check failed: HTTP $($Health.StatusCode)"
    }

    Remove-Item -LiteralPath $ArchivePath -Force
    Write-Host ""
    Write-Host "Publish succeeded: https://www.pztxwx.cn" -ForegroundColor Green
    Write-Host "Log: $LogPath"
}
catch {
    Write-Host ""
    Write-Host "Publish failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $LogPath"
    exit 1
}
finally {
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}
