@echo off
setlocal
cd /d "%~dp0"
set "errorDocker=0"

where docker >nul 2>&1
if errorlevel 1 (
  echo No se encontro Docker Desktop.
) else (
  call docker compose down
  if errorlevel 1 (
    echo No se pudieron detener los servicios Docker. Compruebe que Docker Desktop este iniciado.
    set "errorDocker=1"
  )
)

echo.
echo Verificando puertos 8001 y 5173...

powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $patron = '^\s*TCP\s+\S+:(8001|5173)\s+\S+\s+(LISTENING|ESCUCHANDO)\s+(\d+)\s*$'; function Escuchas { $lineas = @(netstat -ano -p TCP); if ($LASTEXITCODE -ne 0) { throw 'No se pudieron consultar los puertos.' }; foreach ($linea in $lineas) { if ($linea -match $patron) { [PSCustomObject]@{ Puerto = $Matches[1]; Proceso = [int]$Matches[3] } } } }; function CerrarArbol([int]$idProceso, $tabla, $visitados) { if (-not $visitados.Add($idProceso)) { return }; foreach ($hijo in $tabla) { if ($hijo.ParentProcessId -eq $idProceso) { CerrarArbol ([int]$hijo.ProcessId) $tabla $visitados } }; $activo = Get-Process -Id $idProceso -ErrorAction SilentlyContinue; if ($activo) { Write-Host ('Cerrando PID ' + $idProceso + ' (' + $activo.ProcessName + ')'); Stop-Process -Id $idProceso -Force -ErrorAction Stop } }; try { for ($intento = 0; $intento -lt 5; $intento++) { $ocupados = @(Escuchas); if ($ocupados.Count -eq 0) { break }; $tabla = @(Get-CimInstance Win32_Process); $visitados = New-Object 'System.Collections.Generic.HashSet[int]'; foreach ($proceso in $ocupados) { CerrarArbol $proceso.Proceso $tabla $visitados }; Start-Sleep -Milliseconds 500 }; $restantes = @(Escuchas); if ($restantes.Count -gt 0) { $restantes | ForEach-Object { Write-Host ('Puerto ' + $_.Puerto + ' aun ocupado por PID ' + $_.Proceso) }; exit 1 }; foreach ($puerto in @(8001, 5173)) { $socket = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $puerto); try { $socket.ExclusiveAddressUse = $true; $socket.Start() } finally { $socket.Stop() } }; Write-Host 'Puertos 8001 y 5173 libres y comprobados.' } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
  echo No se pudieron liberar todos los puertos. Revise el detalle indicado arriba.
  pause
  exit /b 1
)

echo.
if "%errorDocker%"=="1" (
  echo Los puertos estan libres, pero Docker informo un error al detener los servicios.
  pause
  exit /b 1
)
echo Prototipo detenido y puertos liberados.
pause
exit /b 0
