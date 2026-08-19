@echo off
rem Deja Vibi en marcha: el core y el agente de nodo.
rem
rem Cada uno trae su propio bucle de reintento, asi que aqui solo se lanzan.
rem Van ocultos por los .vbs para no dejar dos ventanas negras abiertas.
setlocal
set "AQUI=%~dp0"
start "" wscript.exe "%AQUI%core.vbs"
start "" wscript.exe "%AQUI%agente-nodo.vbs"
