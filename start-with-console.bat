@echo off
REM For troubleshooting: runs the app in this window, so you can see everything it prints.
REM Quit the tray version first (right-click the icon near the clock, Quit).
cd /d "%~dp0"
title VersiDen (close this window to stop it)
python app.py --open
echo.
echo The app has stopped. Press any key to close this window.
pause >nul
