@echo off
REM ===== Verity — local test launcher (Windows). Double-click this file. =====
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)

if not exist .venv (
  echo Creating a local environment ^(first run only^)...
  %PY% -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing components ^(first run only, about 1-2 minutes^)...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q

set SEED_DEMO=1
echo.
echo =====================================================
echo   Verity v2 is starting on YOUR computer only.
echo   Open a browser at:   http://localhost:5000
echo   Sign in:  lead@verity.local   /   Verity2026
echo   Close this window ^(or Ctrl+C^) to stop.
echo =====================================================
echo.
start "" http://localhost:5000
python app.py
pause
