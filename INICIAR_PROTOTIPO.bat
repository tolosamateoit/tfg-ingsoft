@echo off
setlocal
cd /d "%~dp0"
where docker >nul 2>&1
if errorlevel 1 (
  echo No se encontro Docker. Instale Docker Desktop y vuelva a intentarlo.
  pause
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop no esta iniciado. Abralo, espere a que este listo e intente nuevamente.
  pause
  exit /b 1
)
if not exist "backend\.env" goto missing
if not exist "frontend\.env.development.local" goto missing
docker image inspect oliva-prototipo-backend:20261109 >nul 2>&1
if errorlevel 1 goto load_images
docker image inspect oliva-prototipo-frontend:20261109 >nul 2>&1
if errorlevel 1 goto load_images
goto start_services
:load_images
if not exist "imagenes_prototipo.tar" goto missing
echo Cargando las imagenes incluidas. Esto puede tardar varios minutos...
docker load -i "imagenes_prototipo.tar"
if errorlevel 1 (
  echo No se pudieron cargar las imagenes. Compruebe que el paquete este completo y que haya espacio libre.
  pause
  exit /b 1
)
docker image inspect oliva-prototipo-backend:20261109 >nul 2>&1
if errorlevel 1 goto missing_images
docker image inspect oliva-prototipo-frontend:20261109 >nul 2>&1
if errorlevel 1 goto missing_images
:start_services
echo Iniciando el prototipo...
docker compose up -d --no-build --pull never
if errorlevel 1 (
  echo No se pudieron iniciar los servicios. Compruebe Internet y que los puertos 5173 y 8001 esten libres.
  pause
  exit /b 1
)
echo Esperando la aplicacion y la conexion a la base de datos...
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 90;$i++){try {$a=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 3; $b=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/api/health/database' -TimeoutSec 8; if($a.StatusCode -eq 200 -and $b.StatusCode -eq 200){$ok=$true; break}} catch {}; Start-Sleep -Seconds 2}; if(-not $ok){exit 1}"
if errorlevel 1 (
  echo La aplicacion o la base de datos no respondieron. Compruebe Internet y vuelva a intentarlo.
  echo Para ver el detalle ejecute: docker compose logs
  pause
  exit /b 1
)
start "" "http://127.0.0.1:5173/"
echo El prototipo esta disponible en http://127.0.0.1:5173/
exit /b 0
:missing
echo Faltan archivos de configuracion. Vuelva a descargar el paquete completo.
pause
exit /b 1
:missing_images
echo El archivo de imagenes no contiene los servicios necesarios. Vuelva a descargar el paquete completo.
pause
exit /b 1
