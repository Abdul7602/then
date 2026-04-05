@echo off
title Then — Personal Wisdom Companion

echo.
echo  ⚔️  Then is starting...
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ✗ Python not found.
    echo.
    echo  Please install Python from https://python.org/downloads
    echo  Make sure to tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

:: Open browser after 2 seconds
start "" timeout /t 2 /nobreak >nul & start "" "http://localhost:3000"

:: Start the server
echo  ✓ Server running at http://localhost:3000
echo  ✓ Opening your browser...
echo.
echo  Press Ctrl+C to stop Then.
echo.
python server.py

pause
