@echo off
title CNC Quote
cd /d "%~dp0"
echo.
echo  CNC Quote - starting on this computer
echo  ======================================
where docker >nul 2>nul
if errorlevel 1 (
  echo  Docker Desktop is not installed.
  echo  Install it from https://www.docker.com/products/docker-desktop/ , restart the PC, then run this again.
  pause & exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo  Docker Desktop is not running. Open Docker Desktop, wait until it says "Engine running",
  echo  then run this again.
  pause & exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "local\make-env.ps1"
echo.
echo  Building and starting. The FIRST start downloads and builds everything: 10-20 minutes.
echo  Later starts take under a minute.
echo.
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo  Something went wrong above. Run "Show logs.cmd" and send the last lines to your developer.
  pause & exit /b 1
)
echo.
echo  Waiting for the app to answer...
powershell -NoProfile -ExecutionPolicy Bypass -File "local\wait-for-app.ps1"
if errorlevel 1 (
  echo  The app did not answer in time. Run "Show logs.cmd" to see why.
  pause & exit /b 1
)
echo.
echo  CNC Quote is running:  http://localhost:8080
echo  To stop it, run "Stop CNC Quote.cmd". Your data is kept between runs.
start "" http://localhost:8080
timeout /t 8 >nul
