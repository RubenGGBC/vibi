@echo off
rem Mantiene vivo el agente de nodo de Morgana en esta maquina.
rem
rem El agente ya se reconecta solo si se cae la red (backoff en client.py); este
rem bucle es para lo otro: que el proceso muera del todo. Espera entre intentos
rem para que un fallo de configuracion no llene el disco de logs en un minuto.
setlocal
set "RAIZ=%~dp0.."
set "LOGDIR=%LOCALAPPDATA%\Morgana"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

cd /d "%RAIZ%\agent" || exit /b 1

:bucle
echo [%date% %time%] arrancando agente>> "%LOGDIR%\agente.log"
python -m morgana_node >> "%LOGDIR%\agente.log" 2>&1
echo [%date% %time%] el agente termino; reintento en 15s>> "%LOGDIR%\agente.log"
timeout /t 15 /nobreak >nul
goto bucle
