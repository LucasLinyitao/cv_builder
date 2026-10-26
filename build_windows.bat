@echo off
rem ============================================================
rem  CV Builder - build the Windows desktop app
rem    build_windows.bat                  -> uses your installed MiKTeX/TeX Live (xelatex)
rem    build_windows.bat --with-tectonic  -> also bundles Tectonic + offline package cache
rem  Needs Python 3.11 or 3.12 (python.org). Output: dist\CV Builder\CV Builder.exe
rem  The window stays open at the end so you can read any error message.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title CV Builder - build

echo %~dp0 | findstr /i /c:"\Temp\" >nul
if not errorlevel 1 (
  echo [!] This looks like a temporary folder - did you run the .bat from inside the zip?
  echo     Extract the whole zip to a normal folder first, then run it again.
  echo.
  pause
  exit /b 1
)

echo Building CV Builder - this takes a few minutes the first time.
echo.
call :run %*
if exist "dist\CV Builder\CV Builder.exe" (
  echo.
  echo [ok] Built: dist\CV Builder\CV Builder.exe
  echo      Zip the whole "CV Builder" folder to share it.
) else (
  echo.
  echo [FAILED] No exe was produced. Read the messages above (scroll up) and send them to me.
)
echo.
pause
exit /b 0

:run
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [x] Python not found. Install Python 3.11 or 3.12 from https://www.python.org/downloads/
  echo     and tick "Add python.exe to PATH" in the installer, then run this again.
  exit /b 1
)
echo Using: %PY%
%PY% --version
if exist "dist\CV Builder\CV Builder.exe" del /q "dist\CV Builder\CV Builder.exe" >nul 2>nul

if not exist ".venv\Scripts\python.exe" (
  echo --- Creating virtual environment ---
  %PY% -m venv .venv
  if errorlevel 1 ( echo [x] Could not create the virtual environment. & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

echo --- Installing dependencies (needs internet the first time) ---
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo [x] pip install failed - check your internet connection. & exit /b 1 )

if /i "%~1"=="--with-tectonic" (
  call :tectonic
  if errorlevel 1 exit /b 1
) else (
  if exist vendor\tectonic rmdir /s /q vendor\tectonic
  if exist build_cache rmdir /s /q build_cache
)

echo --- Building the app ---
"%VPY%" -m PyInstaller build_app.spec --noconfirm --clean
if errorlevel 1 ( echo [x] PyInstaller failed. & exit /b 1 )
exit /b 0

:tectonic
echo --- Bundling Tectonic ---
if not exist vendor\tectonic\tectonic.exe (
  if not exist vendor\tectonic mkdir vendor\tectonic
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing 'https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%%400.15.0/tectonic-0.15.0-x86_64-pc-windows-msvc.zip' -OutFile vendor\tectonic.zip; Expand-Archive -Force vendor\tectonic.zip vendor\tectonic; Remove-Item vendor\tectonic.zip"
)
if not exist vendor\tectonic\tectonic.exe (
  echo [x] tectonic.exe download failed. & exit /b 1
)
"%VPY%" tools\make_warm_tex.py build_cache\warm\warm.tex
if errorlevel 1 exit /b 1
set "TECTONIC_CACHE_DIR=%CD%\build_cache\tectonic_cache"
vendor\tectonic\tectonic.exe -X compile --keep-logs --outdir build_cache\warm build_cache\warm\warm.tex
if errorlevel 1 ( echo [x] Tectonic test compile failed - needs internet on this machine. & exit /b 1 )
echo --- Tectonic ready ---
exit /b 0
