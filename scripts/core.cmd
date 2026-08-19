@echo off
rem Mantiene vivo el core de Vibi en esta maquina, fuera de Docker.
rem
rem Corre aqui y no en un contenedor a proposito: `agy` se lanza donde se lanza
rem el core, asi que teniendolo nativo sus herramientas propias --run_command,
rem view_file, list_dir-- son tu disco de verdad y no hace falta el servidor MCP
rem `pc` que antes cruzaba la frontera. Medido el 19/08/2026: el mismo turno
rem paso de 38 s a 5 s, y dejo de equivocarse en la version de Windows.
rem
rem Mismo bucle que agente-nodo.cmd y por lo mismo: uvicorn no se reinicia solo
rem si el proceso muere del todo. La espera evita llenar el disco de logs cuando
rem lo que falla es la configuracion.
setlocal
set "RAIZ=%~dp0.."
set "LOGDIR=%LOCALAPPDATA%\Vibi"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

cd /d "%RAIZ%" || exit /b 1

rem El entorno propio del core. Se crea con:
rem   python -m venv .venv-host
rem   .venv-host\Scripts\python -m pip install -r requirements.txt
set "PY=%RAIZ%\.venv-host\Scripts\python.exe"
if not exist "%PY%" (
    echo [%date% %time%] falta %PY%: crea el entorno antes>> "%LOGDIR%\core.log"
    exit /b 1
)

rem Solo localhost. Para llegar desde el movil se entra por Tailscale, igual que
rem antes: no se expone a la red de casa.
:bucle
echo [%date% %time%] arrancando core>> "%LOGDIR%\core.log"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%LOGDIR%\core.log" 2>&1
echo [%date% %time%] el core termino; reintento en 15s>> "%LOGDIR%\core.log"
timeout /t 15 /nobreak >nul
goto bucle
