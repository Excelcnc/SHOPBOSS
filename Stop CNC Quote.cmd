@echo off
cd /d "%~dp0"
echo Stopping CNC Quote (your data is kept)...
docker compose stop
timeout /t 4 >nul
