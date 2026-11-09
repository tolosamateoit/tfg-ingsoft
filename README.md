1. Instale Docker Desktop para Windows y reinicie la computadora si se lo solicita.
2. Abra Docker Desktop y espere hasta que indique que esta listo.
3. Descomprima el proyecto completo y haga doble clic en INICIAR_PROTOTIPO.bat.
4. Espere: la primera vez se cargan las imagenes incluidas y puede tardar varios minutos.
   La aplicacion se abrira en el navegador. Si no se abre, visite http://127.0.0.1:5173/.
5. Para finalizar, haga doble clic en DETENER_PROTOTIPO.bat.

Es necesaria una conexion a Internet. Mantenga todos los archivos del paquete en su lugar.
Si aparece un error: 
-compruebe que Docker Desktop este iniciado y que ningun otro programa use los puertos 5173 o 8001


-Pruebe ejecutar DETENER_PROTOTIPO.bat como administrador, y luego INICIAR_PROTOTIPO.bat como administrador


-Pruebe desactivar el antivirus


-------------------------

En caso de tener problemas con docker, se adjunta un instructivo diferente.



1. REQUISITOS PREVIOS

Instalar Python y Node.js (incluye npm).

Python: https://www.python.org/downloads/
Node.js: https://nodejs.org/

Durante la instalación de Python, seleccionar la opción "Add Python to PATH".


2. INICIAR EL BACKEND

Abrir una terminal PowerShell dentro de la carpeta "backend" y ejecutar los siguientes comandos en orden.

Crear el entorno virtual:

python -m venv .venv

Instalar las dependencias:

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Iniciar el backend:

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001

Mantener esta terminal abierta mientras se utiliza el prototipo.


3. INICIAR EL FRONTEND

Abrir una segunda terminal PowerShell dentro de la carpeta "frontend" y ejecutar los siguientes comandos en orden.

Instalar las dependencias:

npm ci

Iniciar el frontend:

npm run dev

Mantener esta terminal abierta mientras se utiliza el prototipo.


4. ACCEDER AL PROTOTIPO

Abrir un navegador web e ingresar a la siguiente dirección:

http://localhost:5173

El frontend se conectará automáticamente al backend y este utilizará la base de datos alojada en Supabase.


5. DETENER EL PROTOTIPO

Para detener la ejecución, presionar Ctrl + C en ambas terminales.


6. EJECUCIONES POSTERIORES

Una vez instaladas las dependencias, no es necesario repetir su instalación.

Para volver a utilizar el prototipo, ejecutar únicamente:

Backend (desde la carpeta "backend"):

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001

Frontend (desde la carpeta "frontend"):

npm run dev

Finalmente, acceder a http://localhost:5173.