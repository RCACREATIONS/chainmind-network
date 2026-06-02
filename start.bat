@echo off
setlocal enabledelayedexpansion
title ChainMind Network

if not exist .venv\Scripts\python.exe (
    echo.
    echo  Virtual environment not found. Run install.bat first.
    echo.
    pause & exit /b 1
)

:: Find ollama — system PATH first (OllamaSetup installs it there)
set OLLAMA_EXE=
where ollama >nul 2>&1
if %errorlevel% equ 0 set OLLAMA_EXE=ollama

set CMD=%1

if "%CMD%"=="node" (
    echo  Starting Ollama in background...
    if not "!OLLAMA_EXE!"=="" (
        start /b "" "!OLLAMA_EXE!" serve >nul 2>&1
        timeout /t 3 >nul
    ) else (
        echo  [WARNING] Ollama not found. Run install.bat to install it.
    )
    echo  Starting ChainMind node...
    .venv\Scripts\python.exe -m node.cli node start
    pause
    goto :eof
)

if "%CMD%"=="dashboard" (
    .venv\Scripts\python.exe -m node.cli dashboard
    goto :eof
)

if "%CMD%"=="all" (
    echo  Starting Ollama in background...
    if not "!OLLAMA_EXE!"=="" (
        start /b "" "!OLLAMA_EXE!" serve >nul 2>&1
        timeout /t 3 >nul
    ) else (
        echo  [WARNING] Ollama not found. Run install.bat to install it.
    )
    echo  Starting node in background...
    start "ChainMind Node" .venv\Scripts\python.exe -m node.cli node start
    timeout /t 3 >nul
    echo  Opening dashboard...
    .venv\Scripts\python.exe -m node.cli dashboard
    goto :eof
)

if "%CMD%"=="status" (
    .venv\Scripts\python.exe -m node.cli node status
    pause
    goto :eof
)

if "%CMD%"=="model" (
    .venv\Scripts\python.exe -m node.cli model %2 %3 %4 %5
    pause
    goto :eof
)

if "%CMD%"=="network" (
    .venv\Scripts\python.exe -m node.cli network %2 %3 %4 %5
    pause
    goto :eof
)

if "%CMD%"=="ask" (
    .venv\Scripts\python.exe -m node.cli ask %2 %3 %4 %5
    pause
    goto :eof
)

if "%CMD%"=="leaderboard" (
    .venv\Scripts\python.exe -m node.cli leaderboard
    pause
    goto :eof
)

echo.
echo   ChainMind Network
echo.
echo   Usage: start.bat ^<command^>
echo.
echo   Node:
echo     node              Start the AI node server
echo     dashboard         Open the web dashboard
echo     all               Start node + dashboard together
echo     status            Show node status and stats
echo.
echo   Models:
echo     model list        List installed models
echo     model catalog     Browse models by size
echo     model pull NAME   Download a model (e.g. tinyllama)
echo     model delete NAME Remove a model
echo.
echo   Network:
echo     network status    Show peers and network info
echo     network connect URL   Connect to a peer node
echo     network peers     List all known peers
echo.
echo   Queries:
echo     ask "PROMPT"          One-shot inference
echo     ask "PROMPT" --network   Route via peer network
echo     leaderboard           Show IQ token leaderboard
echo.
echo   Quick start:
echo     start.bat model pull tinyllama
echo     start.bat all
echo.
pause
