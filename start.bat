@echo off
REM Double-click to start the app in the background, with an icon near the clock.
REM Right-click that icon to open, restart or quit the app.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0tray.pyw"
  exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "%~dp0tray.pyw"
  exit /b
)
REM No windowless Python found: run with a window instead.
start "" python "%~dp0tray.pyw"
