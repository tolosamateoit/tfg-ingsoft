@echo off
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo No se encontro Docker Desktop.
) else (
  docker compose down
  if errorlevel 1 (
    echo No se pudieron detener los servicios Docker. Compruebe que Docker Desktop este iniciado.
  )
)

echo.
echo Verificando puertos 8001 y 5173...

for %%P in (8001 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano -p TCP ^| findstr LISTENING') do (
    rem La comprobacion exacta del puerto se realiza en PowerShell.
  )
)

powershell -NoProfile -Command "$puertos = @(8001, 5173); foreach ($puerto in $puertos) { $procesos = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue; foreach ($p in $procesos) { $idProceso = $p.OwningProcess; if ($idProceso -gt 0) { Write-Host ('Deteniendo PID ' + $idProceso + ' del puerto ' + $puerto); Stop-Process -Id $idProceso -Force -ErrorAction SilentlyContinue } } }"

echo.
echo Prototipo detenido.
pause