@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo.
echo  Mega Catalog Studio - Installer
echo  -------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo [!] Python not found. Install Python 3.11 or 3.12 from https://www.python.org/downloads/
  echo     and tick "Add python.exe to PATH" during setup.
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" || (echo [!] Python 3.10 or newer is required. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment...
  %PY% -m venv .venv || (echo [!] Could not create .venv & pause & exit /b 1)
)
set "VPY=.venv\Scripts\python.exe"
echo [2/4] Installing packages...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt || (echo [!] Package install failed. Check internet, VPN or set PIP_INDEX_URL to a mirror. & pause & exit /b 1)
echo [3/4] Installing rembg (optional)...
"%VPY%" -m pip install "rembg[cpu]" || echo [i] rembg was not installed. The built-in ONNX engine will be used instead.
echo [4/4] Downloading background-removal model isnet-general-use (~170 MB)...
"%VPY%" -c "from studio.images import ensure_model; ensure_model('isnet-general-use'); print('model ok')" || echo [i] Model download failed. It can be downloaded later from the app.
echo.
echo  Done. Double-click run.bat to start the studio.
echo  (Microsoft Edge is used for scraping. If you prefer Chromium, run install-chromium.bat)
pause
