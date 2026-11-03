@echo off
REM kill-all.bat - stop StockOS dev servers and Ollama.
REM Frees ports 8000/3000 and releases VRAM so other LLMs can load.
setlocal

for %%P in (8000 3000) do (
  echo [port %%P]
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr LISTENING ^| findstr /C:":%%P "') do (
    echo   killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
  )
)

echo [ollama]
taskkill /F /IM ollama.exe >nul 2>&1
if errorlevel 1 (
  echo   ollama was not running
) else (
  echo   ollama stopped - VRAM freed
)

echo Done. Restart with: py run.py
