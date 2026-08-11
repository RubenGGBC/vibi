@echo off
rem Mantiene vivo el agente de nodo de Vibi en esta maquina.
rem
rem El agente ya se reconecta solo si se cae la red (backoff en client.py); este
rem bucle es para lo otro: que el proceso muera del todo. Espera entre intentos
rem para que un fallo de configuracion no llene el disco de logs en un minuto.
setlocal
set "RAIZ=%~dp0.."
set "LOGDIR=%LOCALAPPDATA%\Vibi"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem Donde esta npx, que hace falta para abrir el navegador con el que Vibi
rem navega en tu pantalla. Solo es necesario si la version de Node activa no
rem trae npm: con nvm pasa. Descomenta y ajusta la ruta.
rem set "VIBI_NPX=%LOCALAPPDATA%\nvm\v24.3.0\npx.cmd"

cd /d "%RAIZ%\agent" || exit /b 1

:bucle
echo [%date% %time%] arrancando agente>> "%LOGDIR%\agente.log"
python -m vibi_node >> "%LOGDIR%\agente.log" 2>&1
echo [%date% %time%] el agente termino; reintento en 15s>> "%LOGDIR%\agente.log"
timeout /t 15 /nobreak >nul
goto bucle
