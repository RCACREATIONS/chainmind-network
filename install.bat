@echo off
if "%~1"=="RUNNING" goto :main
cmd /k "%~f0" RUNNING
exit /b

:main
setlocal enabledelayedexpansion
title ChainMind Network Installer
cd /d "%~dp0"

echo.
echo  ================================================
echo   ChainMind Network - Full Auto Installer
echo  ================================================
echo.

:: STEP 1: Python
echo  [1/5] Checking Python...
set PYTHON_EXE=
for %%e in (python python3) do (
    if "!PYTHON_EXE!"=="" (
        where %%e >nul 2>&1
        if !errorlevel! equ 0 set PYTHON_EXE=%%e
    )
)

if "!PYTHON_EXE!"=="" (
    echo        Python not found. Downloading Python 3.12...
    curl.exe -L --retry 3 --retry-delay 5 --max-time 120 -o "%TEMP%\python-setup.exe" "https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe"
    if !errorlevel! neq 0 (
        echo  ERROR: Could not download Python. Check your internet connection.
        goto :fail
    )
    "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    if !errorlevel! neq 0 (
        echo  ERROR: Python install failed.
        goto :fail
    )
    for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%p;%PATH%"
    set PYTHON_EXE=python
    echo        Python 3.12 installed.
) else (
    for /f "tokens=2" %%v in ('!PYTHON_EXE! --version 2^>^&1') do echo        Found: Python %%v
)

:: STEP 2: Virtual environment
echo.
echo  [2/5] Creating virtual environment...
if exist .venv (
    echo        Already exists.
) else (
    !PYTHON_EXE! -m venv .venv
    if !errorlevel! neq 0 (
        echo  ERROR: Could not create virtual environment.
        goto :fail
    )
    echo        Created.
)

:: STEP 3: Python dependencies (with retry)
echo.
echo  [3/5] Installing Python dependencies...
set PIP_OK=0
for /l %%i in (1,1,3) do (
    if !PIP_OK! equ 0 (
        if %%i gtr 1 echo        Retry attempt %%i of 3...
        .venv\Scripts\python.exe -m pip install --no-cache-dir --prefer-binary --quiet -r requirements.txt
        if !errorlevel! equ 0 set PIP_OK=1
    )
)
if !PIP_OK! equ 0 (
    echo  ERROR: Dependency install failed after 3 attempts.
    goto :fail
)
echo        Done.

:: STEP 4: Ollama - full system installer
echo.
echo  [4/5] Installing Ollama AI engine...
call :install_ollama
echo.

:: STEP 5: System hardware check
echo  [5/5] Detecting your hardware...
.venv\Scripts\python.exe -c "from node.system_check import get_system_info,system_summary,get_tier_for_system; i=get_system_info(); print('       ' + system_summary(i)); print('       Recommended tier: ' + get_tier_for_system(i).upper())"
if %errorlevel% neq 0 (
    echo        System check skipped.
)

if not exist data mkdir data

echo.
echo  ================================================
echo   Installation complete!
echo  ================================================
echo.
echo   Your hardware info is shown above.
echo   Only models that fit your RAM will be shown.
echo.
echo   NEXT STEPS - open a new Command Prompt window
echo   in this folder and run:
echo.
echo     start.bat model pull tinyllama
echo     start.bat all
echo.
goto :done

:: ── Ollama installation subroutine ──────────────────────────────────────────
:install_ollama

:: If ollama is system-wide, we're done
where ollama >nul 2>&1
if !errorlevel! equ 0 (
    echo        Ollama already installed system-wide.
    goto :eof
)

:: Remove stale CLI-only binary from old installs — it is NOT the full Ollama
if exist tools\ollama.exe (
    echo        Removing old incomplete Ollama binary...
    del /f /q tools\ollama.exe >nul 2>&1
)

echo        Downloading Ollama full installer (~150MB)...
echo        This installs Ollama as a proper Windows service with all dependencies.
echo.

set OLLAMA_SETUP=%TEMP%\OllamaSetup.exe
set OLLAMA_URL=https://ollama.ai/download/OllamaSetup.exe
set OLLAMA_OK=0

:: Try curl.exe first (Windows 10 1803+)
where curl.exe >nul 2>&1
if !errorlevel! equ 0 (
    curl.exe -L --retry 5 --retry-delay 10 --retry-connrefused --max-time 600 --progress-bar -o "!OLLAMA_SETUP!" "!OLLAMA_URL!"
    if !errorlevel! equ 0 if exist "!OLLAMA_SETUP!" set OLLAMA_OK=1
)

:: Fallback: PowerShell WebClient
if !OLLAMA_OK! equ 0 (
    echo        Trying PowerShell fallback...
    powershell -NoProfile -Command "$c=New-Object System.Net.WebClient; $c.DownloadFile('!OLLAMA_URL!','!OLLAMA_SETUP!')"
    if exist "!OLLAMA_SETUP!" set OLLAMA_OK=1
)

if !OLLAMA_OK! equ 0 (
    echo.
    echo   [WARNING] Ollama download failed. Please install manually:
    echo     1. Go to https://ollama.ai/download
    echo     2. Download and run OllamaSetup.exe
    echo     3. Open a new Command Prompt then run: start.bat model pull tinyllama
    echo.
    goto :eof
)

echo.
echo        Running Ollama installer silently...
"!OLLAMA_SETUP!" /S
timeout /t 8 >nul

:: Refresh PATH from registry so ollama is visible in this session
for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\")+\";\"+ [Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%p"

where ollama >nul 2>&1
if !errorlevel! equ 0 (
    echo        Ollama installed successfully - ready to use.
) else (
    echo        Ollama installed. Open a NEW Command Prompt before running start.bat.
    echo        (Windows needs a fresh terminal to see the updated PATH.)
)
goto :eof

:fail
echo.
echo  Installation failed - see error above.
echo.

:done
echo  This window will stay open. Press Ctrl+C or type EXIT to close.
