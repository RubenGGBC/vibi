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

## Qué puede hacer un nodo

De momento, dos cosas, y ninguna ejecuta comandos:

- `ping` — responde que está encendido, con su hostname y plataforma.
- `projects.list` — enumera las carpetas de la raíz de proyectos configurada.
  Solo viajan nombres: las rutas absolutas se quedan en la máquina.

Las capacidades son funciones escritas a mano en `capabilities.py`. Aunque el
servidor pidiera cualquier otra cosa, el agente rechaza lo que no esté en ese
diccionario.
