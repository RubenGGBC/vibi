# Agente de nodo

Convierte una máquina tuya (el PC main, el MacBook) en un **nodo** que Morgana
puede consultar. Se ejecuta **fuera de Docker**, con tu usuario del sistema:
por eso ve tu disco real y no solo el volumen del contenedor.

El agente abre la conexión hacia Morgana y la mantiene. No escucha en ningún
puerto, así que no hay nada que abrir en el router.

## Instalación

```bash
cd agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m morgana_node registrar --url https://mi-pc.mi-tailnet.ts.net
```

Te pedirá tu usuario y contraseña de Morgana **una sola vez**. Lo que queda en
disco (`~/.morgana/node.json`, permisos `0600`) es un token propio de este nodo,
no tu contraseña. Si pierdes el portátil, revocas ese nodo desde Morgana y el
resto de tus dispositivos siguen funcionando.

Opciones del alta:

| Opción | Por defecto |
|---|---|
| `--nombre` | el hostname del equipo |
| `--proyectos` | `~/proyectos` |
| `--usuario` | se pregunta por consola |

El nombre es lo que dirás en voz alta ("en el MacBook..."), así que ponle uno
que uses de verdad. Debe ser único entre tus dispositivos activos.

## Arrancar

```bash
.venv/bin/python -m morgana_node
```

Se reconecta solo si se cae la red o reinicias Morgana. Para que arranque con
el sistema, envuélvelo en un `systemd --user` (Linux) o un `launchd` (macOS).

### Arranque automático en Windows

En `scripts/` hay dos envoltorios: `agente-nodo.cmd` mantiene el proceso vivo
(el agente ya se reconecta solo si se cae la red; el bucle es por si el proceso
muere del todo) y `agente-nodo.vbs` lo lanza **sin ventana de consola**. Los
logs van a `%LOCALAPPDATA%\Morgana\agente.log`.

Para registrar la tarea desde PowerShell:

```powershell
$vbs = "C:\ruta\a\morgana\scripts\agente-nodo.vbs"
$accion = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$disparador = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Morgana - agente de nodo" `
  -Action $accion -Trigger $disparador -Settings $ajustes -Force
```

Va **sin elevar**: el agente no debe correr como administrador, porque entonces
cualquier comando que ejecute tendría permisos de administrador. Y sin límite de
duración (`ExecutionTimeLimit 0`), o Windows lo mataría a los tres días.

El companion de escritorio es un proceso **distinto** y tiene su propio
autostart: uno pone la cara y la voz, el otro obedece las órdenes. Tener uno no
implica tener el otro.

## Qué puede hacer un nodo

- `ping` — responde que está encendido, con su hostname y plataforma.
- `projects.list` — enumera las carpetas de la raíz de proyectos configurada.
  Solo viajan nombres: las rutas absolutas se quedan en la máquina.
- `files.search` — busca archivos por patrón y devuelve sus rutas. No lee nada.
- `browser.open` — abre una dirección `http`/`https` en el navegador. Cualquier
  otro esquema (`file:`, `javascript:`) se rechaza.
- `open.path` — abre un archivo o carpeta con su aplicación, como un doble clic.
- `shell.run` — **ejecuta un comando de terminal**. Lee el apartado siguiente.

Las capacidades son funciones escritas a mano en `capabilities.py`: el agente
rechaza cualquier cosa que no esté en ese diccionario.

## Qué significa tener `shell.run` encendido

Este agente corre **con tu usuario del sistema**. Un comando que ejecute aquí
puede hacer lo mismo que tú desde una terminal: leer tus documentos, tus llaves
SSH, tu correo local. No hay sandbox.

El agente **no filtra comandos por su contenido**, y es deliberado: bash es un
lenguaje completo y cualquier lista negra se evade con `echo ... | sh`. Filtrar
daría una sensación de seguridad que no se corresponde con la realidad.

Lo que sí hay:

- **El servidor decide qué se ejecuta solo y qué te pregunta antes.** Los
  comandos de solo lectura pasan; los que escriben, borran o salen a la red
  esperan tu visto bueno en la PWA. Y si Morgana ha leído un archivo o un
  resultado web en ese turno, **cualquier** comando te pregunta — porque ahí es
  donde entra una inyección de prompt, y tu clic es lo único que un texto
  malicioso no puede falsificar.
- **Interruptor por máquina.** Desde Dispositivos puedes apagar la ejecución en
  un nodo concreto sin revocarlo: seguirá contestando pings y listando
  proyectos, pero no ejecutará nada.
- **Kill switch.** Apaga la ejecución en todas tus máquinas a la vez y cancela
  lo que estuviera esperando aprobación.
- **Límites.** Un comando se corta a los 60 segundos (600 como máximo), su
  salida se trunca, y `stdin` está cerrado: lo que pregunte algo por consola
  falla al instante en vez de quedarse colgado.
- **Registro.** Cada orden queda en `node_orders` con su comando, su riesgo y
  quién la aprobó.

Si una máquina te da respeto —la del trabajo, un servidor compartido— déjale la
ejecución apagada. Sigue siendo un nodo útil.
