@echo off
title CNC Quote logs
cd /d "%~dp0"
echo Last lines from the app (close this window when done):
echo.
docker compose logs --tail 80 app
pause
