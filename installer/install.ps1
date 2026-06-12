# ChainMind Node — Windows PowerShell installer
# One-command install (run as any user, no admin needed):
#
#   iwr https://chainmind.com.ng/install.ps1 | iex
#
# Or with explicit version:
#   iwr https://chainmind.com.ng/install.ps1 -UseBasicParsing | Invoke-Expression
#
# What it does:
#   1. Downloads the latest ChainMind-Node-windows-x64.exe from GitHub Releases
#   2. Installs it to %LOCALAPPDATA%\ChainMind
#   3. Adds the install dir to the user PATH (no admin required)
#   4. Creates a desktop shortcut
#   5. Launches ChainMind Node

param(
    [string]$InstallDir = "$env:LOCALAPPDATA\ChainMind",
    [string]$ManifestUrl = "https://chainmind.com.ng/api/release/latest.json",
    [string]$ManifestMirror = "https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json",
    [switch]$NoLaunch,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

# ── Banner ────────────────────────────────────────────────────────────────────
function Write-Banner {
    Write-Host ""
    Write-Host "  ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗███╗   ███╗██╗███╗   ██╗██████╗" -ForegroundColor Magenta
    Write-Host " ██╔════╝██║  ██║██╔══██╗██║████╗  ██║████╗ ████║██║████╗  ██║██╔══██╗" -ForegroundColor Magenta
    Write-Host " ██║     ███████║███████║██║██╔██╗ ██║██╔████╔██║██║██╔██╗ ██║██║  ██║" -ForegroundColor Magenta
    Write-Host " ╚██████╗██║  ██║██║  ██║██║██║ ╚████║██║ ╚═╝ ██║██║██║ ╚████║██████╔╝" -ForegroundColor Magenta
    Write-Host "  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝" -ForegroundColor Magenta
    Write-Host "  Decentralised AI Network — Node Installer" -ForegroundColor Cyan
    Write-Host ""
}

# ── Fetch manifest ────────────────────────────────────────────────────────────
function Get-Manifest {
    foreach ($url in @($ManifestUrl, $ManifestMirror)) {
        try {
            $resp = Invoke-RestMethod -Uri $url -TimeoutSec 10 -ErrorAction Stop
            return $resp
        } catch {
            Write-Host "  ↻ Trying mirror…" -ForegroundColor Yellow
        }
    }
    throw "Could not fetch release manifest from any server."
}

# ── Progress download ─────────────────────────────────────────────────────────
function Get-FileWithProgress {
    param([string]$Url, [string]$Dest)
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "ChainMind-Installer/1.0")
    $done = $false
    Register-ObjectEvent $wc DownloadProgressChanged -Action {
        $pct = $Event.SourceArgs.ProgressPercentage
        $mb  = [math]::Round($Event.SourceArgs.BytesReceived / 1MB, 1)
        Write-Host -NoNewline "`r  Downloading… $pct% ($mb MB)" -ForegroundColor Cyan
    } | Out-Null
    Register-ObjectEvent $wc DownloadFileCompleted -Action { $script:done = $true } | Out-Null
    $wc.DownloadFileAsync([Uri]$Url, $Dest)
    while (-not $done) { Start-Sleep -Milliseconds 100 }
    Write-Host ""
}

# ── SHA-256 verify ────────────────────────────────────────────────────────────
function Test-Checksum {
    param([string]$File, [string]$Expected)
    if (-not $Expected -or $Expected -eq "REPLACE_WITH_SHA256_AFTER_BUILD") { return $true }
    $actual = (Get-FileHash -Path $File -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $Expected.ToLower()) {
        Write-Host "  ✗ Checksum mismatch!" -ForegroundColor Red
        Write-Host "    Expected : $Expected"
        Write-Host "    Got      : $actual"
        return $false
    }
    return $true
}

# ── Add to PATH ───────────────────────────────────────────────────────────────
function Add-ToUserPath {
    param([string]$Dir)
    $current = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($current -notlike "*$Dir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$current;$Dir", "User")
        $env:PATH = "$env:PATH;$Dir"
        Write-Host "  ✔ Added to PATH: $Dir" -ForegroundColor Green
    }
}

# ── Create desktop shortcut ───────────────────────────────────────────────────
function New-DesktopShortcut {
    param([string]$ExePath)
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk     = "$desktop\ChainMind Node.lnk"
    $shell   = New-Object -ComObject WScript.Shell
    $s       = $shell.CreateShortcut($lnk)
    $s.TargetPath       = $ExePath
    $s.WorkingDirectory = Split-Path $ExePath
    $s.Description      = "ChainMind Node — Decentralised AI Network"
    $s.Save()
    Write-Host "  ✔ Desktop shortcut created" -ForegroundColor Green
}

# ── Main ──────────────────────────────────────────────────────────────────────
Write-Banner

Write-Host "  Install directory : $InstallDir" -ForegroundColor Gray
Write-Host ""

# 1. Fetch manifest
Write-Host "  Fetching latest release info…" -ForegroundColor Cyan
$manifest = Get-Manifest
$version  = $manifest.version
$url      = $manifest.assets.windows_x64
$checksum = $manifest.checksums.windows_x64

Write-Host "  Latest version : $version" -ForegroundColor Green
Write-Host "  Binary URL     : $url" -ForegroundColor Gray
Write-Host ""

# 2. Create install dir
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$exeDest = "$InstallDir\ChainMind-Node.exe"

# 3. Download
Get-FileWithProgress -Url $url -Dest $exeDest

# 4. Verify checksum
if (-not (Test-Checksum -File $exeDest -Expected $checksum)) {
    Remove-Item $exeDest -Force
    throw "Download verification failed. Installation aborted."
}
Write-Host "  ✔ Checksum verified" -ForegroundColor Green

# 5. Write VERSION
Set-Content -Path "$InstallDir\VERSION" -Value $version

# 6. PATH
Add-ToUserPath -Dir $InstallDir

# 7. Desktop shortcut
if (-not $NoShortcut) {
    New-DesktopShortcut -ExePath $exeDest
}

Write-Host ""
Write-Host "  ✔ ChainMind Node v$version installed successfully!" -ForegroundColor Green
Write-Host "  Run it any time with: ChainMind-Node" -ForegroundColor Cyan
Write-Host ""

# 8. Launch
if (-not $NoLaunch) {
    Write-Host "  Launching ChainMind Node…" -ForegroundColor Cyan
    Start-Process $exeDest
}
