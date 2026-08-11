# Ejecución interactiva rápida con AGY

Fecha: 2026-08-09

Estado: diseño aprobado

## Objetivo

Reducir al mínimo el tiempo entre una orden como «abre Spotify» y la entrega de
esa orden al sistema operativo, sin convertir texto libre en comandos de shell
ni quitarle a AGY las peticiones ambiguas o compuestas.

El diseño es híbrido:

- las aperturas inequívocas de aplicaciones conocidas toman un carril local y
  determinista;
- AGY conserva toda petición que requiera interpretar, encadenar pasos, pasar
  argumentos, manipular contenido o decidir entre varias acciones;
- ambos caminos usan la misma capacidad tipada, la misma auditoría y el mismo
  agente de nodo.

La referencia arquitectónica es OpenClaw: proceso de control persistente, nodo
conectado por WebSocket, ejecución tipada en el nodo y superficie de tools
reducida antes de la inferencia. El carril determinista es una optimización
adicional de Vibi; OpenClaw mantiene el modelo dentro de su agent loop para
las órdenes naturales.

## Lo medido hoy

La base de datos y los logs actuales separan con suficiente claridad el coste
del modelo del coste de la ejecución:

| Tramo | Mediana observada |
|---|---:|
| AGY decide llamar `browser.open` | 5,445 s |
| Vibi entrega la orden al nodo | 0,039 s |
| El nodo ejecuta la apertura | 0,066 s |
| Tool completa `devices.open_url` | 0,151 s |
| Mensaje parecido a una apertura, extremo a extremo | 5,339 s |

Los once `turno_lento` registrados tampoco señalan al montaje: su mediana fue
5 ms montando y 21,276 s respondiendo. El proceso y la sesión calientes ya no
son el problema habitual. El coste dominante es pedirle al modelo que elija
una acción obvia y volver a invocarlo después de la tool para redactar la
confirmación.

El sistema tiene además seis servidores MCP potenciales —Vibi, Playwright,
PC, Gmail, Drive y Calendar—. OpenClaw evita que catálogos así lleguen enteros
al modelo mediante perfiles, políticas y Tool Search. AGY no ofrece hoy esa
misma primitiva, por lo que la compactación del catálogo se separa como segundo
proyecto y no bloqueará la mejora inmediata.

## Alcance y descomposición

### Proyecto 1: este diseño

1. Instrumentación por etapas.
2. Inventario local y capacidad segura para aplicaciones.
3. Carril rápido delante del motor conversacional.
4. Menos trabajo de control en el camino caliente de AGY.

### Proyecto 2: especificación posterior

Compactar o diferir las tools que AGY recibe de los MCP. Las alternativas a
medir serán un broker con búsqueda de tools, cuatro tools por dominio o varios
perfiles de proceso persistente. No se elegirá una sin medir el coste de las
inferencias adicionales: copiar Tool Search sin el Code Mode anidado de
OpenClaw podría añadir viajes al modelo y hacer más lento el caso que pretende
arreglar.

## Presupuesto de latencia

Para un nodo conectado, catálogo caliente y una orden inequívoca recibida como
texto:

- reconocimiento local: p95 menor de 2 ms;
- API, auditoría, WebSocket y aceptación del lanzamiento por el nodo: p50 menor
  de 300 ms y p95 menor de 750 ms;
- cero invocaciones al modelo;
- la aparición de la ventana queda fuera del SLA, porque depende del programa,
  del disco y del propio sistema operativo.

En voz se mide desde que existe la transcripción final. Reconocimiento de voz y
tiempo de carga visual de la aplicación se registran aparte para no atribuirlos
a AGY.

## Arquitectura

```text
texto final
    |
    v
reconocedor estricto de acciones
    |                         \
    | coincidencia             \ sin coincidencia
    v                           v
tools.execute(devices.launch_app) motor elegido (AGY o Claude)
    |                           |
    v                           v
nodes.dispatch             tool apps.launch cuando proceda
    |                           |
    +-------------+-------------+
                  v
       agente del PC / catálogo local
                  |
                  v
          sistema operativo
```

La capacidad de lanzamiento no pertenece al carril rápido. Es una primitiva
normal del sistema y el carril rápido es solo otro consumidor. Así AGY puede
usar exactamente la misma operación dentro de una tarea compleja, sin una
segunda implementación con reglas de seguridad distintas.

## Reconocedor determinista

Un módulo puro reconoce solamente el enunciado completo. En la primera versión
acepta imperativos directos equivalentes a:

- `abre <aplicación>`;
- `inicia <aplicación>`;
- `lanza <aplicación>`;
- `ejecuta <aplicación>`.

Se normalizan mayúsculas, acentos, espacios, artículos y un «por favor» final.
No hay fuzzy matching en el servidor ni clasificación con otro LLM.

El carril se rechaza y deja la petición a AGY cuando aparece cualquiera de
estas condiciones:

- texto antes o después que añada otra acción;
- conjunciones como «y», «después» o «cuando»;
- argumentos, archivos, URLs o instrucciones sobre qué hacer dentro de la app;
- herramientas adjuntas al turno;
- más de un dispositivo posible;
- ninguna coincidencia exacta y única en el catálogo del nodo.

Ejemplos:

| Petición | Ruta |
|---|---|
| «Abre Spotify» | rápida |
| «Inicia Visual Studio Code, por favor» | rápida |
| «Abre Spotify y pon mi lista de trabajo» | AGY |
| «Abre el PDF que descargué» | AGY |
| «Abre el editor que usamos ayer» | AGY |

Un falso negativo solo cuesta el camino actual. Un falso positivo puede abrir
algo que el usuario no pidió, por eso la frontera favorece deliberadamente el
falso negativo.

## Catálogo de aplicaciones del nodo

El agente crea en segundo plano una instantánea inmutable del catálogo y la
reemplaza de forma atómica cuando termina de refrescarla. Construirla no debe
retrasar la conexión WebSocket del nodo.

La primera plataforma es Windows. Las fuentes son:

- aplicaciones del menú Inicio;
- accesos directos del usuario y del sistema;
- `App Paths` registrados;
- aplicaciones empaquetadas que Windows publica como iniciables.

Cada entrada tiene un identificador opaco, etiqueta, alias normalizados, tipo
de lanzamiento y objetivo resuelto por el propio nodo. El servidor nunca recibe
una ruta ejecutable para reenviarla después ni puede inventar un objetivo.

La resolución solo lanza una coincidencia exacta y única. Una coincidencia
parcial devuelve como máximo cinco candidatos, pero no ejecuta ninguno. El
inventario completo no se manda al servidor: la consulta viaja al nodo y solo
vuelven el resultado o esos candidatos acotados.

El refresco ocurre al arrancar el agente y con una cadencia larga. También se
podrá forzar cuando una búsqueda falle, con límite de frecuencia para que dos
órdenes seguidas no vuelvan a explorar el sistema.

## Capacidad `apps.launch`

La capacidad del nodo recibe un nombre o identificador de catálogo, nunca una
línea de comandos. Sus resultados distinguen:

- `launched`: el sistema operativo aceptó el objetivo;
- `not_found`: no existe una coincidencia;
- `ambiguous`: hay varias candidatas y no se lanzó nada;
- `launch_failed`: se resolvió una entrada, pero el sistema no pudo abrirla;
- `catalog_starting`: el primer inventario aún no está listo.

En Windows se usan APIs o procesos con `argv` construido a partir del catálogo.
No se interpola la petición en PowerShell, `cmd.exe` ni otra shell. No se
admiten argumentos, elevación ni rutas arbitrarias en esta primera versión.

La capacidad del nodo se llama `apps.launch`; la primitiva pública de Vibi,
`devices.launch_app`. Esta pasa por `tools.execute` y por `nodes.dispatch`, por
lo que conserva validación, `tool_invocations`, cálculo de riesgo, taint,
política de consentimiento, interruptor de ejecución remota y auditoría. La
política actual no solicita confirmaciones —decisión explícita del dueño del 5
de agosto—, pero el carril rápido no crea un atajo alrededor de esa autoridad.
Una apertura interactiva nunca se encola para cuando el equipo vuelva a
conectarse: horas después ya no representa la intención del usuario.

AGY recibe también esta primitiva por su MCP de Vibi. Sus reglas indicarán
que abra aplicaciones con `devices_launch_app` y no generando comandos
mediante `pc_ejecutar`.

## Integración con la conversación

El reconocimiento ocurre dentro de `chat.respond`, después de validar la
conversación y adquirir su candado, pero antes de construir historial o
consultar la salud del motor. El mensaje del usuario, el inicio y fin del turno
y la respuesta del asistente siguen el mismo camino de persistencia y eventos
que cualquier respuesta del modelo.

Resultados terminales se redactan sin modelo:

- éxito: «Abriendo Spotify.»;
- ambiguo: «He encontrado Spotify y Spotify Music. ¿Cuál quieres?»;
- fallo: «Encontré Spotify, pero Windows no pudo abrirlo.»;
- timeout después de entregar: «He enviado la orden, pero no he podido
  confirmar si se abrió.»

`not_found` y `catalog_starting` no afirman nada y ceden el turno a AGY. Un
timeout o `launch_failed` no se reintenta con el modelo, porque la aplicación
podría haberse abierto y una segunda ejecución produciría duplicados.

### Coherencia del historial

El turno rápido se guarda en SQLite, pero no entra en la conversación interna
del motor. Después de un resultado manejado se invalida la sesión
conversacional del motor actual, sin matar su proceso. El siguiente turno que
necesite modelo abre una conversación limpia e inyecta el historial persistido,
incluida la apertura. Esto permite entender continuaciones como «ahora
ciérrala» y evita mantener dos historias divergentes.

El coste queda desplazado al siguiente turno complejo: abrir una conversación
nueva en un proceso AGY caliente cuesta mucho menos que invocar el modelo en
cada apertura simple.

## Optimizaciones del camino caliente de AGY

Estas mejoras acompañan al carril rápido porque son independientes del modelo y
no cambian sus decisiones:

1. **Arranque único por usuario.** Un candado o single-flight protege la
   creación del proceso. Dos conversaciones simultáneas del mismo usuario no
   pueden levantar dos `agy` ni reescribir su configuración a la vez.
2. **MCP locales en paralelo.** Playwright y el servidor del PC se aseguran con
   `asyncio.gather`, pues ninguno depende del otro. La configuración se escribe
   cuando ambos terminan.
3. **Salud con vigencia corta.** Una comprobación sana se reutiliza durante un
   intervalo pequeño. Un fallo al abrir stream o enviar el turno sigue
   invalidando inmediatamente el proceso; el cache no oculta errores reales.
4. **Acuse por el stream, sujeto a prueba real.** El stream de trayectoria ya
   trae los pasos `USER_INPUT`. Se estudiará guardar el contador en la sesión y
   confirmar ahí el nuevo turno, eliminando `GetCascadeTrajectorySteps` y su
   sondeo de una trayectoria que crece. Solo se sustituye el método actual si
   una traza real demuestra que cada entrada aceptada aparece de forma fiable.
5. **Clientes persistentes donde aporten.** El puente MCP no debe construir un
   cliente HTTP nuevo por tool si puede reutilizar uno de vida larga. La mejora
   se acepta solo tras benchmark, pues localhost ya representa una fracción
   pequeña del coste total.

No se baja globalmente `ANTIGRAVITY_EFFORT`: el usuario tiene `medium` y una
apertura rápida ya no pasa por AGY. Reducirlo afectaría las tareas complejas para
resolver un problema que este diseño elimina por otra vía.

## Telemetría

Cada turno tendrá marcas monotónicas sin guardar el texto del usuario:

- `route_decision_ms`;
- `session_health_ms`;
- `stream_open_ms`;
- `input_ack_ms`;
- `time_to_first_text_ms`;
- `tool_running_ms`;
- `node_dispatch_ms`;
- `node_execution_ms`;
- `post_tool_ms`;
- `total_ms`;
- ruta elegida: `fast_action`, `agy` o `fallback`.

Los logs reciben el resumen de todos los turnos. SQLite conserva las acciones
rápidas y solo los turnos AGY que superen el umbral, para no convertir
Actividad en un volcado de telemetría. Las métricas nunca incluyen la URL
secreta del MCP del PC, argumentos sensibles ni contenido de herramientas.

## Fallos y recuperación

- **Nodo desconectado:** no se encola la apertura; AGY recibe el turno si puede
  aportar una alternativa, o se informa de que el equipo no está conectado.
- **Catálogo frío o aplicación desconocida:** AGY decide cómo continuar.
- **Ambigüedad:** no se lanza nada y se pregunta con una lista acotada.
- **Entrega confirmada pero resultado tardío:** no se duplica la acción.
- **Proceso AGY enfermo:** se conserva el fallback actual a Claude y el
  precalentado posterior.
- **Servidor MCP opcional caído:** la capacidad `apps.launch` sigue disponible
  por el WebSocket normal del nodo; no depende del nuevo MCP de disco completo.
- **Construcción de catálogo fallida:** el agente sigue conectado con las demás
  capacidades y registra el motivo sin bloquear su bucle.

## Seguridad

- Solo mensajes autenticados que llegan como entrada directa del usuario pueden
  activar el reconocedor.
- El texto decide un alias, nunca un comando.
- El objetivo ejecutable procede de un catálogo local y acotado.
- No hay argumentos, elevación, instalación ni búsqueda arbitraria de binarios.
- `tools.execute` y `nodes.dispatch` siguen siendo las autoridades de política
  y auditoría.
- El interruptor de ejecución remota del nodo desactiva también aplicaciones.
- Tras contenido contaminado se conserva el marcado de riesgo existente. La
  política vigente lo registra, pero no pide aprobación automática.
- La respuesta dice «Abriendo» porque se confirma la aceptación por el sistema,
  no que una ventana ya esté visible y lista.

## Pruebas

### Unitarias

- corpus en español de frases aceptadas y rechazadas, incluidas negaciones,
  conjunciones, nombres con artículos y puntuación;
- normalización, alias, coincidencia única, ambigüedad y catálogo frío;
- garantía de que una consulta nunca se convierte en shell ni ruta;
- resultados tipados de `apps.launch` en Windows con el sistema sustituido;
- single-flight por usuario y arranque paralelo de los MCP;
- cálculo de cada marca de telemetría sin depender del reloj de pared.

### Integración

- una apertura rápida persiste ambos mensajes y emite los eventos normales;
- el motor no recibe ninguna llamada en el camino rápido;
- `not_found` cae a AGY una sola vez;
- timeout o fallo posterior a la entrega no provoca segundo lanzamiento;
- el motor se invalida tras una acción manejada y el siguiente turno recibe el
  historial completo;
- `tools.execute` registra la invocación y respeta el cálculo de riesgo, la
  política vigente y la ejecución remota desactivada;
- dos conversaciones simultáneas de un usuario arrancan un solo proceso AGY.

### Verificación real

En Windows se harán al menos treinta aperturas calientes de aplicaciones
ligeras y pesadas. Se informarán p50, p95 y máximo por etapa. También se probará
una apertura con catálogo recién construido, una ambigua, una aplicación
inexistente y un nodo desconectado.

El acuse de entrada por stream tendrá una prueba separada contra el AGY real con
turnos cortos, largos y herramientas. Si aparece una entrada aceptada que no se
refleje de manera inequívoca en el stream, se conserva el sondeo actual.

## Criterios de aceptación

1. Una orden inequívoca abre una aplicación sin invocar ningún modelo.
2. Con nodo y catálogo calientes, la aceptación del lanzamiento cumple p50
   menor de 300 ms y p95 menor de 750 ms en treinta muestras.
3. El corpus de regresión no contiene aperturas falsas.
4. Las órdenes compuestas siguen pasando completas a AGY.
5. La conversación siguiente conoce la acción rápida realizada.
6. No se puede introducir una ruta, argumento o comando a través del nombre de
   aplicación.
7. Cada ejecución conserva validación, cálculo de riesgo, política vigente y
   auditoría.
8. El arranque concurrente crea un solo AGY por usuario y asegura los MCP
   independientes en paralelo.
9. La suite existente de chat, AGY, tools, nodos y agente continúa pasando.

## Fuera de alcance

- controlar menús, ventanas, teclado o ratón dentro de una aplicación;
- cerrar, enfocar o pasar argumentos a aplicaciones;
- instalar programas;
- descubrir aplicaciones en macOS y Linux en esta primera entrega;
- garantizar cuándo una ventana termina de cargar;
- implementar todavía el catálogo diferido completo inspirado en Tool Search;
- cambiar de modelo o bajar globalmente el esfuerzo de AGY.
