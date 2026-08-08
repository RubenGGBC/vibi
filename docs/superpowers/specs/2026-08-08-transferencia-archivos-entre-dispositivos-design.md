# Transferencia de archivos entre dispositivos

**Fecha:** 2026-08-08
**Estado:** aprobado para planificación
**Alcance:** mover archivos entre las máquinas del usuario y su móvil, usando
Telegram como cliente móvil

## Problema

La malla de nodos ya permite ejecutar trabajo a distancia: `shell.run`,
`files.search`, `open.path` y compañía viajan por el WebSocket de
`/api/nodos/ws` hasta el agente de cada máquina. Desde Telegram también se puede
pedir esa ejecución, porque el canal pasa por `message_core` como cualquier otro.

Lo que no existe es el transporte de contenido. Hoy Morgana encuentra un archivo
en el MacBook y no puede traerlo; genera un informe y no puede dejarlo en el PC;
recibe un PDF por Telegram y lo ignora, porque el bot solo escucha
`filters.TEXT`. El resultado es que la malla sabe actuar sobre las máquinas pero
no sabe mover nada entre ellas.

## Resultado esperado

Tres trayectos funcionando de punta a punta:

- **PC → MacBook.** «Coge el informe del PC y déjalo en el MacBook.»
- **PC → móvil.** «Sácame las reviews en un .md y mándamelo al móvil.»
- **Móvil → PC.** Mandas un PDF al bot y luego dices dónde lo quieres.

Todo lo que viaja queda registrado como archivo tuyo en Morgana Files, visible y
buscable con las herramientas de siempre.

## Decisiones tomadas

**El servidor es siempre el intermediario.** El agente solo abre conexiones
salientes —es lo que evita abrir puertos y pelear con el NAT—, así que no hay
transferencia directa entre máquinas. Origen sube, servidor guarda, destino baja.

**El contenido viaja por HTTP en streaming, no por el WebSocket.** La orden por
WebSocket lleva únicamente metadatos. El cuerpo va por `POST`/`GET` normales
contra el servidor, autenticados con el token de nodo que el agente ya guarda en
`~/.morgana/node.json`. Así hay streaming nativo en los dos extremos, memoria
constante, `Range` para reanudar descargas, y el canal de órdenes queda libre.
Trocear en base64 por el WebSocket costaría un 33 % de sobrecarga, bloquearía el
canal y obligaría a reimplementar a mano el control de flujo que HTTP ya da.

**Buzón persistente, no tubería en vivo.** Si el destino está apagado, el archivo
espera en el servidor y se entrega al encender, con el mecanismo de órdenes
pendientes que ya existe.

**Sin tope duro de tamaño, pero con aviso.** `file_max_bytes` (100 MB) y
`file_user_quota_bytes` (2 GB) dejan de rechazar transferencias y pasan a ser
umbrales de aviso: por debajo va directo; por encima Morgana dice cuánto pesa y
espera confirmación explícita. Esta confirmación no contradice la retirada de las
confirmaciones de ejecución remota del 2026-08-05: aquella era de seguridad, esta
es sobre consumo de disco.

**Lo entrante cae siempre en una carpeta fija.** Nada de adivinar destinos dentro
de la máquina.

## Modelo de datos

**`transfers`** (tabla nueva)

- `id` TEXT (pk) — UUID.
- `user_id` (fk → users).
- `origen_node_id` (fk → nodes, NULL si el origen es Telegram o el servidor).
- `destino_node_id` (fk → nodes, NULL si el destino es Telegram o solo Files).
- `destino_canal` TEXT NULL — `telegram` cuando el destino es el móvil.
- `file_id` (fk → files, NULL hasta que el contenido se materializa).
- `nombre` TEXT — nombre legible con el que se registrará el archivo.
- `ruta_origen` TEXT NULL — ruta en la máquina de origen, solo para diagnóstico.
- `bytes_esperados` INTEGER NULL — lo que declaró `files.stat`.
- `bytes_recibidos` INTEGER — se actualiza al cerrar la subida.
- `estado` TEXT — ver máquina de estados.
- `error` TEXT NULL.
- `created_at`, `expires_at`.

`expires_at` usa el mismo TTL que las órdenes de nodo. Al caducar, la
transferencia se marca `caducada`; **el archivo ya materializado en Files no se
borra**, porque es un archivo tuyo como cualquier otro.

### Máquina de estados

```
esperando_origen ──(POST completo)──> en_servidor ──(files.pull emitido)──> entregando
       │                                    │                                   │
       │                                    └──(destino = Files o Telegram)──> entregado
       │                                                                        │
       └──(caducidad / error)──> caducada | error <───────────────────────────┘
```

Una transferencia nace en `en_servidor` cuando el origen no es un nodo (subida
por Telegram o archivo que Morgana ya tiene).

## Componentes

### `app/transfers.py` (nuevo)

Orquesta el ciclo completo: crea la fila, emite las órdenes a los nodos, recibe
el contenido, materializa el archivo y entrega al destino. Vive aparte de
`app/nodes.py` porque es otra responsabilidad —correlacionar dos extremos y un
blob— y porque `nodes.py` ya ronda las 730 líneas. `nodes.py` sigue siendo quien
despacha órdenes; `transfers.py` es cliente suyo.

Interfaz pública:

- `iniciar(user, origen, destino, ruta, confirmado_grande=False) -> dict`
- `recibir_contenido(node, transfer_id, stream) -> dict`
- `entregar(user, transfer) -> dict`
- `serialize(transfer) -> dict`

### Endpoints nuevos

- `POST /api/nodos/transferencias/{id}/contenido` — el origen sube el cuerpo en
  streaming.
- `GET /api/nodos/transferencias/{id}/contenido` — el destino descarga; acepta
  `Range`.

Ambos se autentican con el token de nodo en `Authorization: Bearer <token>`,
validado con `nodes.node_from_token`. Nunca con el JWT de usuario. Cada petición
comprueba que la transferencia pertenece al `user_id` del nodo y que el nodo es
el extremo que le corresponde: solo el origen puede subir y solo el destino
puede bajar.

### Capacidades nuevas del agente

- **`files.stat`** — `{ruta}` → `{existe, bytes, modificado_en, nombre}`. Lectura
  pura; existe para poder avisar del tamaño antes de mover un solo byte.
- **`files.push`** — `{ruta, transfer_id}`. Lee el archivo local y lo sube por
  HTTP en trozos de 1 MB. Devuelve `{bytes_enviados, sha256}`.
- **`files.pull`** — `{transfer_id, nombre}`. Descarga por HTTP y escribe en la
  carpeta de entrada. Devuelve `{ruta}` con la ruta final.

Clasificación en `app/nodes.py`:

- `files.stat` → `CAPACIDADES_LECTURA`.
- `files.push` → `CAPACIDADES_CON_CONTENIDO_AJENO`, y `devices.files_push` se
  añade a `taint.FUENTES_EXTERNAS`: trae bytes que el usuario no escribió.
- `files.pull` → riesgo alto por defecto (escribe en disco ajeno), sin
  aprobación, como todo lo demás desde el 2026-08-05.

Las tres se añaden a `CAPABILITIES` y a `HANDLERS`. Como el servidor rechaza
capacidades que el agente no declara, un agente sin actualizar dará un error
claro pidiendo que se actualice, en lugar de encolar una orden que rebotará.

### Carpeta de entrada del nodo

Campo nuevo en `NodeConfig`: `inbox_root`, por defecto `~/Morgana/Entrante`. Se
crea al vuelo si no existe. Las colisiones se resuelven con el mismo criterio que
`app/files.py`: `informe.pdf`, `informe (2).pdf`, `informe (3).pdf`.

`files.pull` reduce el nombre recibido a un único componente: sin separadores,
sin `..`, sin rutas absolutas, sin caracteres de control. Después de resolver,
comprueba que el resultado sigue dentro de `inbox_root`. No se siguen enlaces
simbólicos.

Los nodos ya registrados no tienen el campo en su `node.json`; al faltar, se usa
el valor por defecto sin obligar a volver a registrarse.

### Materialización en `app/files.py`

El contenido recibido se guarda como archivo gestionado del usuario en
`WORKSPACE_ROOT/<user_id>/Archivos subidos/`, la ubicación canónica que fijó el
spec de subidas gestionadas del 2026-08-08.

Hace falta una función nueva porque `store_upload` está atada a `UploadFile` de
FastAPI y a los límites como muro:

`store_stream(user_id, name, stream, *, content_type=None, ignorar_limites=False) -> dict`

Repite el patrón probado de `store_upload`: temporal dentro de la carpeta de
destino → SHA-256 y tamaño mientras se escribe → elección del nombre libre bajo
`_managed_file_lock` → `os.replace` atómico → fila en `files` → indexado del
contenido. Si el registro falla, se borra el archivo publicado.

Con `ignorar_limites=True` no se aplican `file_max_bytes` ni la cuota; ese flag
solo lo activa una transferencia que el usuario ya confirmó. `store_upload` se
refactoriza para delegar en `store_stream`, de forma que exista un único camino
de escritura de archivos gestionados.

### Herramienta para el modelo

`devices.send_file` en `app/tools.py`:

- `origen` — nombre del dispositivo, o vacío si el archivo ya está en Morgana.
- `destino` — nombre del dispositivo, `movil`/`telegram`, o vacío para que se
  quede solo en tus archivos.
- `ruta` — ruta en el origen, o nombre del archivo si ya está en Morgana.
- `confirmar_tamano` — booleano; el modelo lo pone a `true` solo después de que
  el usuario haya dicho que sí a un archivo grande.

Los dispositivos se resuelven con `nodes.resolve`, que ya entiende nombres
parciales y avisa cuando son ambiguos.

## Flujos

### PC → MacBook

1. `files.stat` al PC. Si no existe, se responde con el error y se acaba.
2. Si `bytes` supera `file_max_bytes` o la cuota restante, Morgana responde con
   el tamaño y pregunta si tirar adelante. **No se crea la transferencia.** El
   usuario confirma y el modelo repite la llamada con `confirmar_tamano=true`.
3. Se crea la fila `transfers` en `esperando_origen` y se despacha `files.push`
   al PC con el `transfer_id`.
4. El PC sube por HTTP. El servidor materializa el archivo, guarda `file_id` y
   pasa a `en_servidor`.
5. Se despacha `files.pull` al MacBook. Si está apagado, la orden queda pendiente
   y se entregará al encender, sin que nadie tenga que repetir nada.
6. El MacBook descarga, escribe en `~/Morgana/Entrante` y devuelve la ruta. La
   transferencia pasa a `entregado`.

### PC → móvil (Telegram)

Pasos 1 a 4 idénticos. Después, en lugar de `files.pull`, el canal Telegram
entrega el archivo con `send_document`.

El bot de Telegram no puede enviar más de 50 MB. Por encima de ese tamaño, en
lugar del documento se manda el enlace de descarga autenticado de la PWA, con una
línea que explica por qué. Es un límite de la API de Telegram, no nuestro, y el
mensaje debe decirlo para que no parezca un fallo.

### Móvil → PC

1. El bot gana un `MessageHandler` para `filters.Document | filters.PHOTO`.
2. Descarga el archivo de Telegram y lo pasa a `files.store_stream`. Nace una
   fila `transfers` ya en `en_servidor`, con `origen_node_id` nulo.
3. El bot confirma con el nombre registrado: «Guardado como informe.pdf».
4. Cuando el usuario diga «mándalo al PC», es `devices.send_file` con origen
   vacío: el archivo ya está en el servidor y solo falta el `files.pull`.

La API de Telegram no deja al bot descargar archivos de más de 20 MB. Ese es el
techo real de este trayecto; el bot lo explica cuando se alcanza.

## Notificación

Al cambiar de estado, `transfers` emite por `events.manager` un evento
`{"tipo": "transferencia", "transferencia": {...}}` a todas las ventanas del
usuario, con el mismo patrón que `nodo_presencia`. Cada cambio relevante queda
además en Actividad vía `db.log_event`: `transferencia_iniciada`,
`transferencia_recibida`, `transferencia_entregada`, `transferencia_fallida`.

## Seguridad

- El token de nodo solo da acceso a transferencias de su propio `user_id`, y solo
  al extremo que le toca.
- `files.pull` escribe únicamente dentro de `inbox_root`, con el nombre reducido
  a un componente y verificación posterior de que la ruta resuelta sigue dentro.
- `files.push` puede leer cualquier ruta de la máquina de origen. Es coherente
  con el `shell.run` libre: quien controla Morgana ya puede leer esos archivos.
- El servidor corta la subida si el cuerpo excede `bytes_esperados` con margen.
  Cuando `bytes_esperados` es nulo se aplica un techo de seguridad configurable;
  no es un límite para el usuario —el tamaño lo decide él con la confirmación—
  sino la defensa contra un nodo comprometido que intente llenar el disco.
- Una transferencia en `esperando_origen` solo acepta una subida; la segunda se
  rechaza.
- Las respuestas HTTP siguen sin exponer rutas absolutas del servidor ni
  `storage_key`.
- Los resultados de `files.push` contaminan el contexto (`taint`), como cualquier
  capacidad que devuelva contenido ajeno.

## Verificación

Por decisión expresa del usuario, este cambio no lleva pruebas automatizadas. La
verificación es manual sobre los tres trayectos:

1. PC → MacBook con el MacBook encendido: el archivo aparece en
   `~/Morgana/Entrante` y Morgana responde con la ruta final.
2. PC → MacBook con el MacBook apagado: al encenderlo, el archivo llega solo.
3. Archivo de más de 100 MB: Morgana avisa del tamaño y no mueve nada hasta que
   se confirma.
4. PC → móvil con un .md: llega como documento a Telegram.
5. Móvil → PC: se manda un PDF al bot, se confirma el nombre, y «mándalo al PC»
   lo deposita en la carpeta de entrada.
6. Colisión de nombres: el segundo envío del mismo archivo aterriza como
   `informe (2).pdf` en las dos puntas.
7. Un nodo con el agente sin actualizar recibe un error que le dice que
   actualice, en vez de quedarse con una orden encolada.

Recordatorio operativo: las capacidades nuevas exigen reconstruir el Docker y
reiniciar el agente; si no, el servidor las descarta sin avisar.

## Fuera de alcance

- Pantalla de transferencias en la PWA. Solo hay evento por WebSocket y entradas
  en Actividad.
- Sincronización continua de carpetas entre máquinas.
- Transferencia directa entre nodos sin pasar por el servidor.
- El aviso proactivo genérico de tareas largas, que es un problema distinto.
- Vista previa, conversión o transcodificación de lo transferido.
- Reanudación de subidas interrumpidas. Las descargas sí soportan `Range`; una
  subida cortada se reintenta entera.
- Cambiar la cuota o los límites para las subidas normales de la PWA, que siguen
  exactamente igual.
