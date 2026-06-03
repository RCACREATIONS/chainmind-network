# IntelliChain Node - Windows Installer (PowerShell)
$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "IntelliChain Node Installer"

function Write-Header {
    Write-Host ""
    Write-Host "  ================================================" -ForegroundColor Cyan
    Write-Host "   IntelliChain Node -- Windows Installer" -ForegroundColor Cyan
    Write-Host "  ================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step($n, $msg) {
    Write-Host "  [$n] $msg" -ForegroundColor Yellow
}

function Write-OK($msg) {
    Write-Host "      OK  $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "      WARN $msg" -ForegroundColor DarkYellow
}

function Write-Fail($msg) {
    Write-Host "      ERR $msg" -ForegroundColor Red
}

function Download-File($url, $dest, $maxAttempts = 3) {
    # Try curl.exe first (Windows 10 1803+)
    $curlExe = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curlExe) {
        for ($i = 1; $i -le $maxAttempts; $i++) {
            if ($i -gt 1) { Write-Host "      Retry $i of $maxAttempts..." -ForegroundColor DarkYellow }
            & curl.exe -L --retry 5 --retry-delay 10 --retry-connrefused --max-time 300 --progress-bar -o $dest $url
            if ($LASTEXITCODE -eq 0 -and (Test-Path $dest)) { return $true }
            Start-Sleep -Seconds 5
        }
    }
    # Fallback: WebClient (faster than Invoke-WebRequest)
    for ($i = 1; $i -le $maxAttempts; $i++) {
        if ($i -gt 1) { Write-Host "      PowerShell retry $i of $maxAttempts..." -ForegroundColor DarkYellow }
        try {
            $wc = New-Object System.Net.WebClient
            $wc.DownloadFile($url, $dest)
            if (Test-Path $dest) { return $true }
        } catch {
            Write-Host "      Attempt $i failed: $($_.Exception.Message)" -ForegroundColor DarkYellow
            Start-Sleep -Seconds 5
        }
    }
    return $false
}

Write-Header

# ── Step 1: Python ─────────────────────────────────────────────────────────
Write-Step "1/4" "Checking Python..."
$pyver = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $pyver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) { break }
    } catch {}
}

if (-not $pyver) {
    Write-Fail "Python not found."
    Write-Host ""
    Write-Host "  Install Python 3.10+ from https://python.org" -ForegroundColor White
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor White
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}
Write-OK $pyver

# ── Step 2: Virtual environment + dependencies ─────────────────────────────
Write-Step "2/4" "Setting up virtual environment..."
if (-not (Test-Path ".venv")) {
    & python -m venv .venv 2>&1 | Out-Null
    Write-OK "Virtual environment created"
} else {
    Write-OK "Virtual environment already exists"
}

Write-Step "3/4" "Installing Python dependencies (with retry)..."
$pipOk = $false
for ($i = 1; $i -le 3; $i++) {
    if ($i -gt 1) { Write-Host "      Retry attempt $i of 3..." -ForegroundColor DarkYellow }
    & .venv\Scripts\python.exe -m pip install --no-cache-dir --prefer-binary --quiet -r requirements.txt 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $pipOk = $true; break }
    Start-Sleep -Seconds 5
}
if ($pipOk) {
    Write-OK "All dependencies installed"
} else {
    Write-Fail "Dependency install failed after 3 attempts. Check your internet connection."
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Step 4: Ollama ─────────────────────────────────────────────────────────
Write-Step "4/4" "Installing Ollama AI engine..."

$ollamaInstalled = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)
$ollamaInTools   = Test-Path "tools\ollama.exe"

if ($ollamaInstalled) {
    Write-OK "Ollama already installed system-wide"
} elseif ($ollamaInTools) {
    Write-OK "Ollama already present in tools folder"
} else {
    if (-not (Test-Path "tools")) { New-Item -ItemType Directory "tools" | Out-Null }

    Write-Host "      Downloading Ollama installer (~150MB) with retry logic..." -ForegroundColor Yellow
    $ollamaUrl   = "https://ollama.ai/download/OllamaSetup.exe"
    $ollamaDest  = "$env:TEMP\OllamaSetup.exe"

    $ok = Download-File -url $ollamaUrl -dest $ollamaDest -maxAttempts 3

    if ($ok) {
        Write-Host "      Running Ollama installer silently..." -ForegroundColor Yellow
        Start-Process -FilePath $ollamaDest -ArgumentList "/S" -Wait
        Start-Sleep -Seconds 3
        $nowInstalled = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)
        if ($nowInstalled) {
            Write-OK "Ollama installed and available in PATH"
        } else {
            Write-OK "Ollama installer ran. Open a new Command Prompt before running start.bat"
        }
    } else {
        Write-Warn "Auto-download failed. You can install Ollama manually:"
        Write-Host "      1. Go to https://ollama.ai/download" -ForegroundColor White
        Write-Host "      2. Download and run OllamaSetup.exe" -ForegroundColor White
        Write-Host "      3. Re-run this installer — it will skip this step" -ForegroundColor White
        Write-Host "      All other components are ready." -ForegroundColor Green
    }
}

# ── Data dir ───────────────────────────────────────────────────────────────
if (-not (Test-Path "data")) { New-Item -ItemType Directory "data" | Out-Null }

# ── Done ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "   Installation complete!" -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Pull smallest model :  start.bat model pull tinyllama" -ForegroundColor Cyan
Write-Host "    2. Start the node      :  start.bat node" -ForegroundColor Cyan
Write-Host "    3. Open dashboard      :  start.bat dashboard" -ForegroundColor Cyan
Write-Host ""
Read-Host "  Press Enter to exit"
