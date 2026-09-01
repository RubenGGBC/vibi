# Diario de implementación

## 2026-09-01 — Enseñar en vez de hacer: la guía

- **La tercera cosa que se puede hacer con una ventana.** Se podía mirarla
  (`devices_ui_snapshot`) y tocarla (`devices_ui_batch`); faltaba señalarla.
  `devices_ui_guide` manda a la pantalla del usuario una foto de lo que tiene
  delante con un recuadro numerado sobre cada elemento del que se habla, y el
  texto de Vibi va numerado igual. Quien pulsa es la persona.
- **Por qué, más allá de la comodidad:** un asistente que solo sabe hacer las
  cosas por ti te deja sabiendo cada vez menos de tu propio ordenador. Ante la
  duda, la herramienta pide preguntar: «¿te lo hago o te lo enseño?».
- **Las marcas salen del árbol de accesibilidad, no de mirar la foto.** El
  sistema publica el rectángulo exacto de cada elemento y la captura ya traía
  el mapa de escritorio a imagen (`origen_x`, `ancho_real`, `ancho`), así que
  señalar es una multiplicación. La caja cae donde cae el botón, con la
  precisión del sistema operativo y no la del ojo del modelo sobre un JPEG
  reducido a 1568 px.
- **Y por eso una guía cuesta cero tokens de imagen.** El modelo no la mira:
  ya sabe lo que hay en la ventana porque leyó el árbol, y de vuelta solo
  recibe qué número quedó puesto sobre qué. La foto viaja hacia la persona y
  nunca hacia el contexto.
- **Geometría por el cable, dibujo en la PWA.** El nodo manda el JPEG limpio y
  los rectángulos en píxeles de esa imagen; el recuadro es un SVG por encima.
  No añade dependencias al agente —Pillow solo está declarada en Windows—, se
  ve nítido en un móvil que amplía, y cambiar cómo se señala no obliga a
  actualizar el agente de cada máquina.
- **La guía caduca a los diez minutos y no se guarda.** Hereda la regla de
  `screenshots.py` —una captura no es un archivo tuyo— y le cambia el número:
  dos minutos es lo que dura un relevo hacia el modelo, diez es lo que tarda
  una persona en seguir los pasos con las manos. Vive en memoria, se sirve por
  una URL autenticada con comprobación de dueño y `no-store`, y no entra en el
  transcript: recargar la conversación de ayer no reenseña la pantalla de ayer.
- **Llega por el canal de eventos y no colgada de la respuesta del turno.** Con
  Antigravity las herramientas se ejecutan fuera de proceso y el turno nunca ve
  su resultado, así que por ahí la guía solo existiría con Claude. Y quien
  pregunta puede estar preguntando desde el móvil sobre lo que tiene en la
  pantalla del ordenador: tiene que aparecer en las dos.
- **Señalar es leer:** `ui.guide` entra en `CAPACIDADES_LECTURA` con permisos
  `devices:read:self`. No mueve el ratón, no escribe y no roba el foco. En la
  trastienda no existe a propósito: enseñarle a alguien dónde pulsar en un
  escritorio que nadie está viendo no significa nada.
- **Ambiguo sigue siendo una pregunta.** Si una descripción casa con tres
  elementos, se enumeran los tres en vez de señalar el primero. Importa más
  aquí que en un lote: la persona va a pulsar donde se le diga y va a creer que
  el error lo cometió ella.
- **Seis marcas como tope**, y solo de lo que se ve ahora. Un camino de doce
  pasos se cuenta en varias guías con la persona avanzando entre medias, que es
  como se enseña algo de verdad.
- **Lo que costó meterlo en el prompt de Antigravity.** Está topado en 13.000
  caracteres con un test que lo vigila, y la regla es que antes de subirlo hay
  que buscar qué se está diciendo dos veces. Lo había: el mecanismo de las
  coordenadas de `devices_click` estaba escrito en las reglas y, palabra por
  palabra, en la descripción de la propia herramienta, que `agy` ya recibe.
- **Una rama muerta menos.** La primera versión comprobaba que el elemento
  tuviera sitio en pantalla; el test enseñó que no puede pasar, porque
  `ui_tree.podar` descarta los rectángulos vacíos antes de que nadie pregunte.

## 2026-08-31 — La forja: herramientas que Vibi se escribe a sí misma

- **Claude deja de ser solo el respaldo.** Entraba en dos sitios: como motor
  elegido y como red bajo `agy` cuando se cae. Ahora tiene un encargo propio
  que no depende de qué motor esté conversando: escribir el guion de una
  herramienta nueva. Lo pida quien lo pida —Gemini desde Antigravity, Claude
  desde su propio motor o la persona desde la PWA—, ese guion lo escribe
  Claude, con Haiku 4.5.
- **Por qué no lo escribe el motor que atiende.** Una herramienta se redacta
  una vez y se ejecuta muchas, sin nadie mirando. Lo que en una conversación es
  un tropiezo que se corrige al turno siguiente —una firma que no encaja con
  sus parámetros, un `print` en vez de un `return`, una biblioteca que no está
  instalada— aquí se queda guardado y falla cada vez.
- **Haiku 4.5 y no el modelo grande:** es un archivo de cien líneas con un
  contrato fijo. Con Sonnet, crear la herramienta costaba más que la tarea que
  la herramienta venía a ahorrar.
- **Se prueba antes de guardarse.** El modelo devuelve también unos argumentos
  de ejemplo, y Vibi ejecuta el guion con ellos ahí mismo. Si revienta, el
  error vuelve al modelo y hay un intento más (tres en total). Si a la tercera
  sigue sin arrancar, la herramienta se guarda **desactivada** y se dice por
  qué, en vez de anunciar una capacidad que no existe.
- **La contención es de proceso, no de sintaxis.** El guion corre en un
  intérprete aparte y aislado (`-I`), en un directorio temporal vacío, con el
  entorno construido por lista blanca —sin `ANTHROPIC_API_KEY`, sin
  `JWT_SECRET`, sin la ruta de la base— y con topes de tiempo, memoria y
  salida. No hay lista negra de `import`: da una sensación de seguridad que no
  se sostiene, y la frontera de verdad es que ese proceso no tenga delante nada
  que valga la pena robar.
- **Tabla aparte, y a propósito.** Una fila de `tools` es una composición sobre
  una primitiva revisada y no puede ejecutar código; eso sigue igual. Las
  forjadas viven en `tool_scripts`. Mezclarlas habría convertido ese límite en
  una columna opcional que es fácil olvidar mirar.
- **Un solo punto de entrada.** `tools.execute` sigue siendo el único camino:
  la contabilidad de la invocación —fila abierta antes, cerrada con estado y
  duración, nunca con argumentos ni resultados— se sacó a `_auditar` y la
  comparten primitivas y guiones.
- **Aparecen solas en los dos motores.** El catálogo del motor de Claude se
  reconstruye cuando cambia su firma, así que la herramienta recién forjada
  está disponible en el mensaje siguiente; a `agy` se le publican por el puente
  MCP, que ahora pregunta por HTTP qué tiene forjado ese usuario.

## 2026-08-29 — Vibi local: silueta SVG fiel y ocho familias

- **Un rig, no ocho dibujos:** el companion local monta una sola figura SVG y
  cambia ojos, boca y complementos para reposo, recelo, contenta, trabajando,
  duda, hablando, ejecutando y buscando. Los 32 estados existentes se reparten
  entre esas ocho familias sin modificar la cara de la PWA.
- **La lámina es la geometría:** copa, pliegue, ala, mandíbula y llama se
  reconstruyeron como curvas SVG editables a partir de los contornos de la
  referencia. La aplicación no incrusta el PNG. En la comparación alineada, la
  máscara roja solapa un 98,2 % y la blanca un 96,5 % con el original.
- **Movimiento por piezas:** cuerpo, sombrero, mirada, parpadeo, lenguas de
  fuego y accesorios conservan transforms independientes; hay cadencia de
  reposo, respuesta a voz/puntero/señales y una ruta sin movimiento para
  `prefers-reduced-motion`.
- **Solo companion:** `VibiFace` selecciona esta escena únicamente en el
  proceso local. Los tokens de color y sombra también están limitados a
  `.face-canvas-companion`.
- **Revisión reproducible:** una superficie local congela las ocho familias en
  la misma cuadrícula para compararlas sin que la animación altere cada captura.
- **Verificación:** 50 pruebas focalizadas en verde, ESLint limpio en los
  archivos tocados y build de producción del companion completado.

## 2026-08-24 — Stand-by: quedarse pendiente de algo

- **El encargo vive en el servidor y la sonda en el nodo.** Es el reparto de
  `avisos.py` repetido: la sonda es tonta y gratis —saca un sello y lo compara
  con el anterior— y el modelo entra una vez por **cambio**, no una por vuelta.
  Vigilar una web quieta dos horas cuesta cero llamadas; con el modelo en el
  bucle habrían sido 1.440.
- **Tres sondas, medidas:** `proceso` 2,5 ms (ctypes sobre `OpenProcess` y
  `GetExitCodeProcess`, sin dependencias nuevas), `web` 31 ms por CDP y
  `ventana` 251 ms por el árbol de accesibilidad.
- **La sonda de ventana no puede usar `ui.capturar`.** Numera sobre el registro
  compartido de `ref`, así que sondear cada cinco segundos le habría caducado al
  modelo sus `e12` en mitad de un turno. Se añadió `ui.sello_de`, que numera
  sobre un `Registro()` de usar y tirar y tampoco toca `_ultimo`. El patrón ya
  estaba en el propio archivo, en la rama de `expandir`.
- **El antirrebote:** un sello nuevo no cuenta hasta repetirse dos vueltas
  seguidas. Sin él, cualquier página con un contador dispara para siempre. Y
  con `MAX_NOVEDADES` la vigilancia se retira sola diciendo que no para de
  cambiar, en vez de avisar cien veces.
- **El juicio tiene tres salidas:** contar, callar y **cumplido**, que cierra el
  encargo. Sin la tercera, «avísame cuando acabe» no tiene final.
- **Un fallo de sonda es un sello más.** La ventana que se cierra o el puerto
  que deja de contestar pasan por el mismo antirrebote: un tropiezo suelto no
  dispara nada, una aplicación que se fue de verdad sí acaba contándose.
- **La suscripción viaja entera, no como incremento.** Un delta perdido en una
  reconexión dejaría al nodo sondeando algo ya soltado o ciego ante algo nuevo;
  con la lista completa el mensaje es idempotente y reconciliar es trivial.
- **El stand-by es un modificador del reposo, no un estado de la voz.** Vive en
  `useFaceMood` como `pendienteDe`, por debajo de la cola de permisos y por
  encima de `idle`. Así hablarle no lo cancela, y la cara de la PWA se entera
  gratis. Cara nueva `vigilando`: quieta, atenta y mirando a un punto.
- **En stand-by las notificaciones se retienen y se cuentan resumidas al
  salir.** Juzgar si algo es urgente no cuesta ninguna llamada extra: va en la
  que ya se hacía para redactar el aviso, cambiando solo las instrucciones.
- **Caducan a las dos horas y lo dicen.** «No ha pasado nada» y «he dejado de
  mirar» no son lo mismo.
- **Verificación:** prueba de humo del ciclo completo contra una base temporal
  (alta, tope de tres, rechazo sin `que_espero`, suscripción, caducidad, cierre,
  retención y resumen), TypeScript sin errores y las 151 pruebas de la cara en
  verde. Sin pruebas nuevas, a petición expresa.

## 2026-08-04 — Malla de nodos ejecutores (fase A)

- **La PWA no ejecuta nada:** quien ejecuta es un daemon nativo (`agent/`) que
  se instala en cada máquina, corre fuera de Docker con el usuario del sistema
  y por eso ve el disco real y no solo el volumen del contenedor.
- **Conexión saliente:** el agente abre un WebSocket hacia
  `/api/nodos/ws` y lo mantiene con reconexión y espera creciente. No escucha
  en ningún puerto: nada que abrir en el router ni que exponer a la red.
- **Credencial:** el alta pide usuario y contraseña una vez y devuelve un token
  propio del nodo, guardado hasheado (SHA-256) en el servidor y con permisos
  `0600` en la máquina. La contraseña no se escribe en disco y revocar un nodo
  no afecta a los demás.
- **Órdenes con caducidad:** una orden a un equipo apagado espera en SQLite y se
  entrega al reconectar; si nadie la recoge en `NODE_ORDER_TTL_SECONDS`, caduca.
  Nunca se reintenta sola. `devices.ping` es la excepción deliberada: no encola,
  porque la respuesta útil es "está apagado".
- **Doble validación:** servidor y agente comprueban por separado que la
  capacidad pedida existe. El agente solo ejecuta funciones escritas a mano en
  `capabilities.py`; no hay camino a shell y esta fase no lo abre.
- **Tabla propia:** `nodes` y `node_orders` conviven con `devices` sin mezclarse:
  una ventana de navegador y una máquina ejecutora tienen ciclos de vida
  distintos. El nombre del nodo es único entre los activos del usuario, que es
  lo que permite resolver "en el MacBook" sin adivinar.
- **En la conversación:** `devices.list`, `devices.ping` y `devices.projects`
  entran en el catálogo de tools, así que funcionan desde chat, voz y Telegram
  sin código por canal. Un nombre ambiguo pregunta en vez de elegir.
- **Auditoría:** altas, conexiones, órdenes, resultados y caducidades quedan en
  el log append-only bajo la categoría nueva Dispositivos de Actividad.
- **Verificación:** 47 pruebas Python nuevas (34 de servidor, 13 de agente, 1
  omitida por permisos POSIX en Windows) en verde; suite backend completa con
  159 pasando y los 8 fallos preexistentes de `router.clasificar` intactos;
  TypeScript sin errores y `ActivityPage` en verde.

## 2026-08-02 — Tool Workbench 2.0

- **Capacidades reales nuevas:** tareas, proyectos, actividad reciente y creación
  atómica de notas se incorporan al registro permitido, siempre aisladas por usuario.
- **Constructor por contrato:** React genera controles a partir del JSON Schema
  Pydantic; una primitiva futura ya no necesita un formulario cableado a mano.
- **Presets parciales:** una composición puede fijar parte de los argumentos y
  dejar los obligatorios restantes para la ejecución; propiedades desconocidas y
  valores fuera de rango se rechazan antes de persistir.
- **Ciclo de vida:** edición con propiedad/admin, duplicado personal, activación y
  banco de prueba conservan compatibilidad con tools ya enlazadas por skills.
- **Observabilidad privada:** métricas agregadas e historial por tool incluyen
  estado, error seguro y duración, nunca argumentos ni resultados.
- **Artefactos:** las notas creadas por tools también se devuelven en `files`, por
  lo que Skill Studio puede mostrarlas como archivos descargables.
- **Interfaz:** el catálogo adopta un patchbay de módulos con filtros, railes de
  efectos lectura/escritura, editor schema-driven, runner y línea temporal.
- **Errores:** la PWA presenta el campo `detail` estándar de FastAPI y distingue
  límites/cuota de archivos con HTTP 413.
- **Verificación:** 109 pruebas Python y 4 subtests, 31 pruebas Vitest en 14
  archivos, ESLint, TypeScript (app y configuración) y build PWA de Vite con
  salida correcta; permanece el aviso informativo del chunk principal de 522 kB.

## 2026-08-02 — Skill Studio versionado y ejecutable

- **Manifiestos ricos:** cada skill combina identidad, instrucciones Markdown,
  ejemplos y hasta cuatro tools permitidas; no admite código dinámico.
- **Ciclo editorial:** borrador, informe de preparación, activación, edición que
  crea snapshots inmutables, desactivación automática si una revisión deja de
  ser válida y duplicado con historia independiente.
- **Runner restringido:** el carril `tools` infiere argumentos JSON según el
  schema, `tools.execute` conserva validación y auditoría, y una llamada acotada
  compone la respuesta tratando los resultados como datos no confiables.
- **Invocación multicanal:** `/skill <slug> <petición>` funciona desde PWA, Cara
  y Telegram sin clasificación implícita; el turno se conserva en la conversación.
- **Portabilidad:** el exportador compila un `SKILL.md` con frontmatter,
  instrucciones, capacidades y ejemplos, sin exponer datos de ejecución.
- **Aislamiento:** personales privadas por usuario; publicación `lab` solo para
  administradores y sin dependencias de tools personales.
- **Workbench:** catálogo compacto, editor con costura de preparación, selector
  de permisos, playground y previsualización del manifiesto exportado.
- **Observabilidad:** creación, versiones, estado, duplicado y ejecuciones se
  proyectan en Actividad mediante una allowlist que omite prompts y resultados.

## 2026-08-02 — Centro de actividad y recuperación

- **Bitácora personal:** `GET /api/actividad` pagina el log por cursor y filtra
  por categorías sin cruzar usuarios.
- **Proyección segura:** el cliente recibe títulos, detalles y enlaces derivados
  mediante allowlist; payloads, rutas, prompts completos e ids de chat permanecen
  internos.
- **Pulso operativo:** la PWA resume tareas vivas, aprobaciones, completadas, uso
  de la cuota y dispositivos conocidos/recientes.
- **Recuperación inmutable:** solo una tarea con error puede reintentarse; se
  conserva el original y se encola otro id que vuelve a plan y aprobación.
- **Tiempo real:** cambios de tareas y archivos invalidan la bitácora en React
  Query para refrescarla sin acoplar SQLite al WebSocket.
- **Pruebas frontend:** Vitest usa una configuración separada del build para no
  cargar Tailwind ni el plugin PWA durante las pruebas unitarias.

## 2026-07-18 — Fase B: sincronización multidispositivo

- **Dispositivos:** cada PWA conserva un UUID, la Cara usa identidad de kiosco
  y Telegram un id lógico; SQLite registra tipo, nombre, creación y actividad.
- **WebSocket:** las conexiones se agrupan por usuario y dispositivo, admiten
  pestañas duplicadas, autentican el handshake y refrescan actividad por heartbeat.
- **Chat en vivo:** los mensajes persistidos de usuario y Vibi se serializan
  una sola vez y se difunden a todas las ventanas después del commit.
- **Reconciliación:** la PWA conserva el envío optimista con client_ref y lo
  sustituye por el mensaje canónico sin duplicarlo cuando llega el evento.
- **Recuperación:** al conectar o reconectar, la PWA pide todos los mensajes
  posteriores a su último id y los fusiona en orden.
- **Reset global:** todas las ventanas vacían el chat al cambiar la conversación;
  un dispositivo desconectado detecta que su cursor quedó archivado y repinta.

## 2026-07-18 — Fase A: contexto persistente

- **Persistencia:** conversaciones y mensajes de la vía rápida viven en SQLite,
  con una única conversación activa por usuario y origen por canal.
- **Contexto:** cada turno combina personalidad, tareas no terminales y una
  ventana reciente acotada por presupuestos configurables de tokens aproximados.
- **Canales:** PWA, Telegram y Cara comparten la conversación persistida; las
  respuestas heredan el origen del mensaje al que contestan.
- **REST:** historial reciente y reinicio de conversación bajo autenticación JWT,
  con cursor `before_id` opcional para una futura paginación hacia atrás.
- **Chat:** restaura los últimos cincuenta mensajes y permite archivar la
  conversación actual mediante un control discreto con confirmación.
- **Observabilidad:** log debug por turno con tokens de tareas, ventana y total.

## 2026-07-14 — Fase PWA

- **Auth:** migración idempotente de `users.password_hash`, hashes bcrypt,
  JWT HS256 de 30 días y comando `python -m scripts.set_password <nombre>`.
- **Core y proyectos:** procesamiento de mensajes independiente del canal y
  clonado seguro sin shell, con allowlist de URLs y destino confinado.
- **REST:** login y endpoints `/api/yo`, tareas, mensajes y proyectos,
  protegidos por Bearer y con errores JSON uniformes.
- **Tiempo real:** WebSocket autenticado por usuario y emisión de tareas
  completas en cada transición del orquestador.
- **Telegram:** deep-links a cada tarea sin retirar los botones de aprobación,
  con comprobación de propiedad en los callbacks.
- **Frontend base:** Vite, React, TypeScript, Tailwind, tema Vibi,
  autenticación persistida y navegación responsive protegida.
- **Bandeja y detalle:** prioridad visual de aprobación, filtros, Markdown,
  acciones grandes y caché de React Query sincronizada por WebSocket.
- **Chat y proyectos:** conversación de sesión con tarjetas agénticas, listado
  de workspaces y modal accesible de clonado con feedback.
- **PWA y despliegue:** manifest oscuro instalable, service worker, icono
  maskable, fallback de rutas React y Docker multi-stage de un solo origen.
- **Cierre de revisión:** fallback `/api` reservado, JWT del WebSocket enviado
  en el primer mensaje, cachés filtradas coherentes y cabeceras defensivas.
- **Recuperación:** ejecuciones aprobadas registradas y canceladas al apagar;
  cualquier ejecución cortada por un reinicio queda marcada como error.
- **Operación:** el primer `/start` reclama Telegram de forma persistente,
  clonados con timeout y workspace Docker configurable desde `.env`.
