# Vibi con acceso al ordenador entero

Fecha: 2026-08-09

## El problema

Vibi tiene dos manos y ninguna alcanza el ordenador de verdad.

Dentro del contenedor, el motor agéntico trabaja con sus herramientas nativas
—leer, editar, buscar, bash— pero solo sobre `/srv/vibi/workspace`, la única
carpeta del anfitrión que monta `docker-compose.yml`. Es donde de verdad sabe
trabajar, y es una carpeta.

En la máquina, el agente de `agent/` sí corre con el usuario del sistema y desde
el 5 de agosto tiene shell libre. Pero es un mando a distancia, no un sitio donde
trabajar: una orden por vez, `NODE_RESULT_TIMEOUT_SECONDS` de espera antes de
que la conversación se rinda, salida cortada a 60 000 caracteres, y de archivos
solo `open.path`, `files.search` y las transferencias.

Así que pedirle a Vibi que mire una carpeta de Descargas, que arregle un
archivo de un repo cualquiera o que lance una compilación que tarda cinco
minutos son tres cosas que hoy no se pueden hacer.

## Qué se construye

Cada nodo sirve su propio disco y su propio intérprete de comandos por MCP. El
motor se conecta a ese servidor igual que ya se conecta al de Playwright, y ve
las herramientas del ordenador como herramientas suyas.

La forma ya está probada aquí: `browser_mcp.py` levanta un servidor MCP en la
máquina del usuario y `agy` habla con él por `serverUrl`. Esto es lo mismo con
otro contenido, y por el mismo motivo: lo que hay que tocar está en el
ordenador, no en el contenedor.

Se descartaron dos alternativas:

- **Montar el disco como volumen de Docker.** Solo llegaría al anfitrión, y
  Vibi tiene que alcanzar también el MacBook. Además el contenedor es Linux:
  ni ejecuta un `.exe` ni ve las rutas con la forma que el usuario escribe.
- **Sacar el motor de Docker y correrlo en el nodo.** Es la vía más potente y la
  más cara: mover el eje del sistema, un login de `agy` por máquina, y quedarse
  sin chat cuando el ordenador está apagado.

## Piezas

### `agent/vibi_node/fs_scope.py`

Resuelve una ruta y decide si las herramientas de archivos pueden tocarla.

La raíz es el disco entero. Lo que queda fuera es una lista corta de sitios
donde vive el material sensible: `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.gemini`,
`~/.claude`, `~/.vibi`, los `.env`, los `*.pem` y `*.key`. Ampliable con
`VIBI_FS_EXCLUIR`.

Dos cosas que no son evidentes y que el módulo tiene que dejar escritas:

- **Resuelve enlaces antes de comparar.** Un symlink o una junction que apunte
  a `~/.ssh` salta una lista que compare cadenas.
- **No se aplica al intérprete de comandos.** El shell del nodo ya llega a esos
  sitios y filtrarlo sería teatro; la exclusión es un recordatorio de que ahí no
  hay nada que Vibi necesite, no una barrera de seguridad.

### `agent/vibi_node/system_fs.py`

Las operaciones de archivo, como funciones normales para poder probarlas sin
levantar nada: `listar`, `leer`, `escribir`, `editar`, `buscar`.

`editar` hace sustitución exacta de un fragmento por otro. Es la que decide si
esto se puede usar: sin ella, cambiar una línea de un archivo de mil obliga a
reescribirlo entero, y el modelo se inventa lo que no vuelve a mirar.

### `agent/vibi_node/system_shell.py`

`ejecutar` para lo que termina pronto, y `lanzar` / `salida` / `parar` para lo
que no. Un trabajo lanzado devuelve un identificador y sigue corriendo mientras
la conversación continúa; su salida se consulta cuando interese.

En Windows el intérprete es PowerShell (`pwsh` si está instalado, si no
`powershell.exe`). El `shell.run` que ya existe usa `subprocess(shell=True)`,
que ahí es `cmd.exe`: para llamar a esto ejecución nativa hace falta lo que la
máquina usa de verdad.

### `agent/vibi_node/system_mcp.py`

El servidor. FastMCP sobre uvicorn, en un hilo del proceso del agente, con
transporte HTTP con streaming, que es lo que habla `agy`.

Escucha en `127.0.0.1`. No hace falta más cuando el contenedor vive en esta
misma máquina: `host.docker.internal` es una dirección virtual de Docker
Desktop, la conexión entra como local y el puerto no se ve desde la red. Está
medido con el navegador.

**Con el nodo en otra máquina eso no vale, y aquí sí hay credencial.** El
servidor de Playwright se dejó sin ella porque solo escucha en localhost; este
sirve el disco entero, así que lleva un secreto en la ruta: escucha en
`/<token>/mcp` y lo demás es un 404. Va en la ruta y no en una cabecera porque
`agy` declara los servidores remotos con `serverUrl` a secas, y no está
comprobado que admita cabeceras; una URL la traga cualquier cliente MCP.

El secreto lo genera el agente al arrancar el servidor y viaja al servidor de
Vibi en el resultado de la capacidad, que ya va por un canal autenticado.
Nunca se escribe en disco: si el agente se reinicia, se genera otro y la
siguiente sesión lo aprende.

A diferencia del navegador, este servidor **no** sobrevive al agente. Ahí había
una ventana abierta que el usuario estaba mirando y que costaba minutos
recuperar; aquí no hay nada que preservar, y un servidor huérfano sirviendo el
disco con un token que ya nadie recuerda es exactamente lo que no queremos.

### Capacidad `system.mcp`

Con la misma forma que `browser.mcp`: `arrancar`, `parar`, `estado`. Va en
`CAPABILITIES` y en `CAPACIDADES_ESCRITORIO` de `app/nodes.py`, porque el
servidor viejo descarta en silencio las capacidades que no conoce.

### Declaración en el servidor

`agy_mcp_config.py` gana `SERVIDOR_SISTEMA = "pc"` —nombre corto, porque prefija
las tools que ve el modelo: `pc_leer`, `pc_ejecutar`—, declarado con `serverUrl`
cuando hay un nodo que lo sirve y borrado cuando no, que es la regla que ya
tiene ese archivo para todos los demás.

`claude_chat.py` lo añade a sus `mcp_servers` como servidor HTTP externo, junto
al `create_sdk_mcp_server` que ya usa.

### Reglas del prompt

El bloque que decide si esto funciona en la práctica. Sin él el modelo seguirá
escribiendo en `/srv/vibi/workspace`, porque es lo que tiene más a mano y lo
que su system prompt le describe como suyo.

Tiene que decir tres cosas: que hay un ordenador de verdad detrás de `pc_*`, que
las rutas de ahí son las que el usuario escribe (`C:\Users\...`) y no las del
contenedor, y que un archivo del disco es contenido ajeno —un PDF descargado, el
README de un repo clonado— y no una instrucción.

Se añade solo cuando el servidor está de verdad en pie, igual que las del
navegador: prometer una capacidad que no está lleva a que asegure haberla usado.

## Contaminación

El servidor entra en `SERVIDORES_EXTERNOS` de `agy_mcp_config` y en las fuentes
de `app/taint.py`: lo que Vibi lea del disco no lo escribió necesariamente el
usuario. Eso anota el riesgo en Actividad, que es todo lo que `taint` hace desde
que las confirmaciones se retiraron el 5 de agosto.

## Pruebas

- `fs_scope`: exclusiones, rutas relativas, y que un enlace apuntando a un sitio
  excluido no lo esquiva.
- `system_fs`: las cinco operaciones contra un directorio temporal, incluido que
  `editar` se niegue cuando el fragmento aparece dos veces o ninguna.
- `system_shell`: un trabajo lanzado que termina, y su salida consultada después.
- La configuración MCP: que el servidor se declare cuando hay nodo y se borre
  cuando no.

El servidor vivo y el intérprete de comandos real no se prueban en CI.

## Lo que no entra

Ver la pantalla y controlar ventanas, ratón y teclado. Se descartó al acotar el
alcance: es otro proyecto, con otra forma.
