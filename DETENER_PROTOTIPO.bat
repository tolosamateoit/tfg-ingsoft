@echo off
cd /d "%~dp0"
where docker >nul 2>&1
if errorlevel 1 (
  echo No se encontro Docker Desktop.
  pause
  exit /b 1
)
docker compose down
if errorlevel 1 (
  echo No se pudieron detener los servicios. Compruebe que Docker Desktop este iniciado.
  pause
  exit /b 1
)
echo Prototipo detenido.
pause
