# Vibi — Requisitos funcionales

2 de octubre de 2026

## Introducción

Vibi es un asistente personal multiusuario y autoalojado que usa el ordenador del usuario: disco, terminal, pantalla, ratón, teclado, ventanas, navegador y notificaciones. Se le habla desde la PWA, Telegram, la app de escritorio o por voz, y la conversación es siempre la misma.

Este documento recoge los requisitos funcionales del sistema tal como está implementado hoy en el repositorio (core FastAPI en `app/`, agente de nodo en `agent/`, PWA y companion en `frontend/`). Cada requisito lleva un identificador `RF-<módulo>-<n>` y una prioridad MoSCoW (Must, Should, Could).

**Glosario**

| Término | Significado |
| --- | --- |
| Core | Proceso FastAPI que sirve API, PWA, worker de encargos, caducadores y bot de Telegram; persiste en SQLite |
| Agente de nodo | Proceso que corre fuera de Docker en cada máquina del usuario y conecta al core por WebSocket saliente |
| Motor | Modelo que contesta la conversación: Claude Code (Agent SDK) o Antigravity (CLI `agy` de Gemini) |
| Carril | Uso independiente de IA configurable por usuario: chat, tools, speech, agent |
| Encargo | Tarea agéntica de larga duración gestionada en la cola del workspace |
| Primitiva | Herramienta de Vibi publicada al motor por MCP (48 en total) |
| Receta | Instrucción verificada de cómo manejar una aplicación concreta |
| Trastienda | Escritorio Windows aparte, invisible para el usuario, donde Vibi trabaja |
| Relevo | Retomar una tarea que el usuario ya tenía a medias en pantalla |

## Actores y contexto de uso

Hay cinco actores: tres humanos y dos procesos que actúan en su nombre. Todos los canales entran por el mismo caso de uso del core (`core/messages.py`), así que un requisito de conversación aplica igual a PWA, Telegram, voz y companion.

| Actor | Quién es | Canales |
| --- | --- | --- |
| Usuario | Persona con cuenta Vibi; conversa, sube archivos, gestiona proyectos y máquinas | PWA, companion de escritorio, voz, Telegram |
| Administrador | Usuario con rol admin; crea cuentas y publica herramientas y skills para todo el lab | PWA, scripts `create_user` / `set_password` |
| Miembro de equipo | Usuario cuyo nodo aporta señales al coordinador de equipo, con su consentimiento | PWA (seguimientos) |
| Motor de chat | Claude Code, Antigravity o Mercury; decide y llama a las primitivas | MCP interno de Vibi, MCP `pc`, Playwright |
| Agente de nodo | Proceso en cada máquina del usuario; ejecuta órdenes y sondas | WebSocket saliente al core |

Sistemas externos: Groq (transcripción y modelo rápido), Anthropic, Gemini vía `agy`, Inception Mercury, Telegram Bot API, MCP oficiales de Google (Gmail, Drive, Calendar), registro oficial de MCP, npm y PyPI.

## Requisitos funcionales

Son 17 módulos. Prioridad: **Must** = sin esto Vibi no cumple su propósito; **Should** = importante pero hay alternativa; **Could** = mejora.

### 1. Cuentas y autenticación (AUT)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-AUT-01 | El sistema debe permitir crear cuentas de usuario y de administrador, y cambiar su contraseña | Must |
| RF-AUT-02 | El usuario debe iniciar sesión con usuario y contraseña y recibir un JWT que caduca a los 30 días | Must |
| RF-AUT-03 | El servidor no debe arrancar sin un `JWT_SECRET` de al menos 32 caracteres | Must |
| RF-AUT-04 | Cada usuario debe poder guardar sus propias claves de API, cifradas en la base de datos | Should |
| RF-AUT-05 | Si el usuario no tiene clave propia, el sistema debe usar la del sistema y marcar en la interfaz cuando cae a un proveedor de respaldo | Should |
| RF-AUT-06 | Toda consulta de datos debe quedar confinada al usuario autenticado | Must |

### 2. Conversación y motores de chat (CONV)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-CONV-01 | Cada usuario debe tener una única conversación activa compartida entre PWA, voz, companion y Telegram | Must |
| RF-CONV-02 | El usuario debe poder elegir el motor de chat (Claude Code o Antigravity) y el proveedor de cada carril: chat, tools, speech y agent | Must |
| RF-CONV-03 | Con Mercury activado por configuración, Mercury debe contestar el chat y las tareas cortas (router, avisos, vigilancias, entrevista) sin pisar lo elegido por cada usuario | Could |
| RF-CONV-04 | El motor debe reanudar la misma sesión desde cualquier canal | Must |
| RF-CONV-05 | Si Antigravity no está instalado, sin sesión o se cae, debe responder Claude; por escrito se indica, por voz no, y queda en Actividad como `motor_caido` | Must |
| RF-CONV-06 | Un trabajo externo en marcha no debe pasarse al motor de respaldo; Vibi debe decir que lo dejó lanzado | Should |
| RF-CONV-07 | El turno debe cortarse por silencio (25 s charla, 60 s herramienta, 300 s comando externo) y por tope absoluto (180 s, 600 s con comando) | Should |
| RF-CONV-08 | El usuario debe poder activar o desactivar Thinking por conversación, y el valor se comparte entre dispositivos | Could |
| RF-CONV-09 | «Empezar de cero» debe abrir una sesión nueva y borrar la marca de procedencia | Must |
| RF-CONV-10 | El prompt solo debe describir capacidades que estén disponibles en ese momento (navegador, nodos, MCP declarados) | Must |
| RF-CONV-11 | Cada turno debe registrar sus tiempos sin contenido y marcar como `turno_lento` los que pasen de 8 s | Should |
| RF-CONV-12 | El usuario debe poder adjuntar archivos a un mensaje; el motor recibe nombre, tipo y hasta 6.000 caracteres extraídos de cada uno | Should |

### 3. Interfaz PWA (UI)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-UI-01 | La PWA debe ofrecer los destinos Ahora, Hilo, Encargos, Equipos, Taller y Configuración | Must |
| RF-UI-02 | «Ahora» debe mostrar el turno en curso paso a paso, los equipos vivos y lo pendiente de decisión, sin acciones que cambien nada | Should |
| RF-UI-03 | «Hilo» debe ofrecer modo Chat escrito y modo Cara con pulsar para hablar | Must |
| RF-UI-04 | «Encargos» debe listar las tareas agénticas filtrables por estado y proyecto | Must |
| RF-UI-05 | «Equipos» debe mostrar las máquinas, si están vivas, sus capacidades y lo que han ejecutado | Must |
| RF-UI-06 | Las rutas antiguas (`/perfil`, `/actividad`, etc.) deben redirigir a su nueva ubicación | Could |
| RF-UI-07 | La PWA debe ser instalable en el móvil y servirse por HTTPS para poder usar el micrófono | Must |

### 4. Disco y terminal (PC)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-PC-01 | El agente de nodo debe servir por MCP el disco y el intérprete de la máquina con las rutas reales del usuario (`pc_info`, `pc_listar`, `pc_leer`, `pc_escribir`, `pc_editar`, `pc_buscar`, `pc_ejecutar`, `pc_lanzar`, `pc_progreso`, `pc_parar_trabajo`, `pc_trabajos`) | Must |
| RF-PC-02 | Un comando que no termine en 45 s debe devolver un identificador y seguir en segundo plano; el nodo avisa al terminar, incluso tras reconectar | Must |
| RF-PC-03 | El usuario debe poder consultar el progreso y detener un trabajo en curso | Must |
| RF-PC-04 | En Windows los comandos deben ejecutarse con PowerShell (`pwsh` si existe) | Should |
| RF-PC-05 | Las herramientas de archivos no deben abrir rutas sensibles (`~/.ssh`, `~/.aws`, `.env`, `*.pem`…), ampliables con `VIBI_FS_EXCLUIR` | Should |
| RF-PC-06 | El servidor MCP del disco debe exigir un secreto por arranque en la ruta y escuchar solo en localhost salvo configuración explícita | Must |
| RF-PC-07 | El usuario debe poder buscar archivos por patrón en todo el disco; en Windows usando el índice del sistema | Should |
| RF-PC-08 | La salida de un comando debe truncarse (60.000 caracteres en el nodo, 200 KB en el servidor) | Should |

### 5. Escritorio: pantalla, ventanas y entrada (ESC)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-ESC-01 | El sistema debe capturar la pantalla de una máquina y devolver el mapa de coordenadas de la captura | Must |
| RF-ESC-02 | El sistema debe mover el ratón, hacer clic, arrastrar, desplazar, escribir texto Unicode y pulsar teclas | Must |
| RF-ESC-03 | Las acciones de ratón deben usar coordenadas de la última captura y rechazarse si no hay captura previa | Must |
| RF-ESC-04 | El sistema debe leer una ventana como texto desde el árbol de accesibilidad, podado y con etiquetas cortas (`e12`) | Must |
| RF-ESC-05 | El sistema debe ejecutar un lote de acciones (`clic`, `escribir`, `tecla`, `seleccionar`, `expandir`, `contraer`, `enfocar`, `esperar`, `snapshot`, `activar`, `desplazar`) en una llamada, resolviendo cada paso justo antes | Must |
| RF-ESC-06 | Un lote debe parar ante candidatos ambiguos o el primer fallo, y devolver siempre el árbol final | Must |
| RF-ESC-07 | `tecla` y `escribir` sin referencia deben rechazarse con `ventana_de_fondo` si la ventana no está delante | Should |
| RF-ESC-08 | El sistema debe ejecutar JavaScript dentro de aplicaciones Chromium/Electron/WebView2 por CDP y enumerar con cuáles puede | Should |
| RF-ESC-09 | En Windows, el sistema debe abrir aplicaciones en un escritorio aparte (trastienda) y trabajar en él sin que el usuario lo vea | Could |
| RF-ESC-10 | Relevo: el sistema debe reconstruir objetivo, progreso y pendientes de la tarea en pantalla, esperar confirmación y no ejecutar acciones finales irreversibles sin límite explícito | Should |
| RF-ESC-11 | Relevo no debe guardar vídeo, capturas, pulsaciones ni valores de campos de contraseña | Must |
| RF-ESC-12 | Enseñar: el sistema debe enviar al usuario una captura con hasta 6 recuadros numerados sobre los elementos explicados, sin mover el ratón | Should |
| RF-ESC-13 | Una guía debe caducar a los 10 minutos, servirse solo a su dueño y no guardarse en el historial | Must |

### 6. Navegador (NAV)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-NAV-01 | El agente debe abrir en el escritorio del usuario un navegador propio de Vibi con perfil persistente y pilotarlo con Playwright | Must |
| RF-NAV-02 | Debe existir un modo de repliegue con perfil temporal | Could |
| RF-NAV-03 | Antes de conectar, el sistema debe despertar las pestañas restauradas sin cargar | Should |
| RF-NAV-04 | El servidor de Playwright debe escuchar solo en localhost salvo configuración explícita | Must |

### 7. Aplicaciones y multimedia (APP)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-APP-01 | Las órdenes completas «abre / inicia / lanza / ejecuta X» deben resolverse sin llamar a ningún modelo | Should |
| RF-APP-02 | El agente debe construir un catálogo de aplicaciones y abrir solo por alias exacto o id; si hay ambigüedad devuelve hasta 5 candidatas sin abrir ninguna | Must |
| RF-APP-03 | El texto del usuario nunca debe convertirse en un comando de shell al abrir una aplicación | Must |
| RF-APP-04 | Una apertura no debe encolarse con el equipo apagado ni repetirse si el resultado llega tarde | Should |
| RF-APP-05 | El sistema debe controlar la reproducción y leer lo que suena (solo Windows) | Could |
| RF-APP-06 | El sistema debe reproducir directamente el primer resultado de YouTube o el último vídeo de un canal, sin API key | Could |

### 8. Recetas (REC)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-REC-01 | El sistema debe guardar recetas de cómo manejar una aplicación, con la vía (`cdp` o `arbol`) y el resultado esperado de cada paso | Should |
| RF-REC-02 | Una receta solo debe guardarse con un campo `comprobacion` que diga qué se verificó | Must |
| RF-REC-03 | La receta debe adjuntarse sola a la respuesta de abrir, leer o hablar con esa aplicación | Should |
| RF-REC-04 | Una receta debe retirarse sola tras 3 fallos seguidos, y el usuario debe poder olvidarla a mano | Should |

### 9. Notificaciones y vigilancias (AVI)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-AVI-01 | El nodo debe leer las notificaciones nuevas del sistema (Windows y macOS) cada 1,5 s y enviarlas al servidor | Should |
| RF-AVI-02 | El servidor debe filtrar con lista negra y enunciar el aviso en voz alta en lenguaje natural | Should |
| RF-AVI-03 | El aviso debe llegar aunque el modelo no esté disponible, con una frase genérica | Must |
| RF-AVI-04 | El usuario debe poder silenciar por voz o texto (aplicación, tema o contenido), y Vibi debe decir qué ha silenciado | Should |
| RF-AVI-05 | Los silencios deben ser del usuario y aplicarse en todas sus máquinas | Should |
| RF-AVI-06 | Sin permiso de lectura, el nodo debe indicar qué permiso falta y dónde se concede | Should |
| RF-AVI-07 | El usuario debe poder crear, ver y soltar vigilancias con 5 sondas: `proceso`, `archivo`, `web`, `ventana`, `actividad` | Should |
| RF-AVI-08 | La vigilancia debe guardar lo que espera el usuario con sus palabras y llamar al modelo solo cuando la sonda detecta un cambio estable (2 vueltas) | Must |
| RF-AVI-09 | El juicio debe tener tres salidas: contar, callar o cumplido (cierra la vigilancia) | Must |
| RF-AVI-10 | Una vigilancia debe poder llevar una continuación que sobrevive a reinicios y se ejecuta al cumplirse | Could |
| RF-AVI-11 | En stand-by deben retenerse hasta 20 avisos normales y contarse resumidos al terminar; solo lo urgente interrumpe | Could |
| RF-AVI-12 | Las vigilancias deben caducar a las 2 h (techo 24 h) avisando, con un máximo de 3 vivas por usuario, y retirarse solas tras 8 novedades | Must |
| RF-AVI-13 | Servidor y nodo deben validar por separado la lista de sondas permitidas | Must |

### 10. Archivos, proyectos y conversaciones guardadas (ARC)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-ARC-01 | El usuario debe poder subir, navegar, buscar (nombre, ruta y contenido de PDF, DOCX y texto), descargar y borrar sus archivos | Must |
| RF-ARC-02 | El sistema debe aplicar límites de tamaño y cuota por usuario | Must |
| RF-ARC-03 | El usuario debe poder pedir un archivo en el chat y recibirlo como resultado descargable | Should |
| RF-ARC-04 | El sistema debe enviar un archivo de una máquina a otra, a los archivos de Vibi o al móvil por Telegram, sin conexión directa entre máquinas | Should |
| RF-ARC-05 | Un envío grande debe pedir confirmación antes de continuar | Should |
| RF-ARC-06 | Vibi nunca debe responder con un `file://` o una ruta absoluta como forma de entrega | Must |
| RF-ARC-07 | El usuario debe poder crear un proyecto vacío o clonar un repositorio; una carpeta existente en el workspace aparece como proyecto | Must |
| RF-ARC-08 | El usuario debe poder renombrar y borrar un proyecto; al borrar, sus archivos y conversaciones siguen siendo del usuario | Must |
| RF-ARC-09 | El usuario debe poder meter y sacar archivos de un proyecto sin borrarlos | Should |
| RF-ARC-10 | El usuario debe poder guardar la conversación activa con título (automático si no lo da) dentro de un proyecto, sin cerrarla | Should |
| RF-ARC-11 | El usuario debe poder reanudar una conversación guardada; la activa se archiva en la misma operación | Should |
| RF-ARC-12 | Los archivos de versiones anteriores deben migrarse verificando tamaño y SHA-256 antes de borrar el original | Should |

### 11. Malla de dispositivos y ejecución remota (MAL)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-MAL-01 | El usuario debe registrar un nodo con usuario y contraseña una sola vez; se guarda un token propio del nodo, no la contraseña | Must |
| RF-MAL-02 | El nodo debe conectar por WebSocket saliente, sin abrir puertos de entrada | Must |
| RF-MAL-03 | El usuario debe poder listar y revocar nodos; revocar caduca sus órdenes pendientes | Must |
| RF-MAL-04 | Las órdenes deben persistir si el equipo está apagado, entregarse al reconectar y caducar a las 6 h, sin reintentos automáticos | Must |
| RF-MAL-05 | El nodo debe declarar sus capacidades al conectar, y el servidor debe rechazar órdenes no declaradas; ambos lados validan | Must |
| RF-MAL-06 | El sistema debe resolver la máquina por nombre natural y preguntar si es ambiguo | Should |
| RF-MAL-07 | El usuario debe poder apagar la ejecución por máquina y en todas a la vez (kill switch) | Must |
| RF-MAL-08 | Cada orden debe registrarse con su riesgo (`bajo`, `medio`, `alto`) y su resultado | Must |
| RF-MAL-09 | El sistema debe marcar durante 10 minutos la procedencia cuando entra texto ajeno al contexto y anotarla en el riesgo | Should |
| RF-MAL-10 | La maquinaria de aprobación de órdenes debe seguir disponible aunque hoy no se active | Should |

### 12. Herramientas, forja y skills (HER)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-HER-01 | El sistema debe publicar 48 primitivas al motor por MCP, cada una con cuándo usarla y cuándo no | Must |
| RF-HER-02 | Si el MCP `pc` está activo, deben ocultarse las primitivas duplicadas; si no, publicarse todas | Should |
| RF-HER-03 | El usuario debe poder probar primitivas desde formularios generados por esquema y componer herramientas personales con argumentos prefijados | Should |
| RF-HER-04 | Un administrador debe poder publicar una herramienta o skill para todo el lab | Could |
| RF-HER-05 | La forja debe generar una herramienta a partir de una petición en lenguaje natural, probarla hasta 3 veces y guardarla desactivada si falla | Should |
| RF-HER-06 | Los guiones forjados deben ejecutarse aislados, sin secretos en el entorno y con topes de tiempo, memoria y salida | Must |
| RF-HER-07 | El usuario debe poder leer el código de una herramienta forjada y desactivarla | Must |
| RF-HER-08 | El usuario debe poder crear skills con instrucciones, ejemplos y hasta 4 herramientas, probarlas y activarlas solo si están completas | Should |
| RF-HER-09 | Cada edición de una skill debe crear una versión inmutable; debe poder duplicarse y exportarse como `SKILL.md` | Could |
| RF-HER-10 | El usuario debe poder invocar una skill con `/skill <slug> <petición>` desde cualquier canal | Should |

### 13. Perfil y especialización por usuario (PER)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-PER-01 | El sistema debe guardar afirmaciones sobre el usuario (dominio, rasgo, herramienta, preferencia, afición) con procedencia y confianza (uso 0,8; entrevista 0,6; inventario 0,4) | Should |
| RF-PER-02 | Con un nodo conectado, el sistema debe obtener un mapa agregado del equipo (carpetas y extensiones, sin nombres de archivo ni contenido) y proponer hipótesis | Should |
| RF-PER-03 | El usuario debe poder hacer la entrevista por texto o voz; la conversación no se guarda, solo lo aprobado | Should |
| RF-PER-04 | El sistema debe proponer capacidades del registro oficial de MCP, mostrando si son locales o remotas, y solo paquetes verificados en npm o PyPI | Could |
| RF-PER-05 | Cada capacidad aprobada debe asignarse a un nivel: completo (≥ 0,6), catálogo (≥ 0,3) o propuesta de retirada | Should |
| RF-PER-06 | Un observador debe ajustar la confianza con contadores de uso ya existentes; lo observado prevalece sobre lo declarado | Should |
| RF-PER-07 | Una retirada debe proponerse al usuario, nunca aplicarse sola | Must |
| RF-PER-08 | El usuario debe poder añadir y borrar afirmaciones, cambiar el nivel de una capacidad y borrar su perfil entero | Must |
| RF-PER-09 | El sistema debe medir tasa de aceptación y supervivencia a 14 días | Could |

### 14. Voz y companion de escritorio (VOZ)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-VOZ-01 | La cara debe grabar al tocarla, cortar tras un silencio breve, transcribir en español y entregar el texto a la misma conversación | Must |
| RF-VOZ-02 | La respuesta debe locutarse con voz local (Kokoro), con respaldo en edge-tts y después en la síntesis del navegador; Vibi nunca queda muda | Must |
| RF-VOZ-03 | Las respuestas para voz deben ir sin markdown, con cifras en palabras, sin URLs y con una muletilla antes de usar una herramienta | Should |
| RF-VOZ-04 | Una invocación de voz debe tener apertura y cierre («adiós Vibi», «gracias Vibi»); un turno de una invocación cerrada se rechaza con 409 | Should |
| RF-VOZ-05 | El audio no debe guardarse en disco ni en base de datos | Must |
| RF-VOZ-06 | El companion debe despertar con la palabra «Vibi» detectada en local sin red, o manteniendo Alt (Windows) o Fn (macOS) 400 ms | Should |
| RF-VOZ-07 | La cara debe cambiar de forma según la herramienta en uso | Could |
| RF-VOZ-08 | El companion debe vincularse una vez con URL, cuenta y nombre del equipo; la contraseña no se guarda | Must |
| RF-VOZ-09 | El menú de bandeja debe permitir despertar, pausar la escucha, ver el registro, abrir la PWA y ver qué está haciendo | Should |
| RF-VOZ-10 | La consola del companion debe mostrar permisos pendientes, tareas y archivos (con subida por arrastre) | Should |

### 15. Telegram (TEL)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-TEL-01 | El bot debe arrancar si hay token; sin él, Vibi arranca solo con la API | Should |
| RF-TEL-02 | `/start` debe vincular el chat con un usuario y `/proyectos` listar sus proyectos | Should |
| RF-TEL-03 | El usuario debe poder enviar documentos y fotos (hasta 20 MB) y recibir archivos (hasta 50 MB) | Should |
| RF-TEL-04 | Las respuestas por Telegram deben ser más cortas y sin rutas ni enlaces `file://` | Should |
| RF-TEL-05 | Los planes de encargos deben llegar con botones Aprobar y Rechazar | Should |

### 16. Encargos agénticos, actividad y conectores (ENC)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-ENC-01 | Un encargo debe seguir el ciclo `pendiente → planificando → esperando_aprobacion → ejecutando → completada`, con salidas `rechazada` y `error` | Must |
| RF-ENC-02 | El usuario debe aprobar el plan de un encargo antes de ejecutarlo | Must |
| RF-ENC-03 | Un encargo en error debe poder reintentarse como tarea nueva con el mismo prompt, proyecto y modelo, que vuelve a pedir aprobación | Should |
| RF-ENC-04 | Actividad debe mostrar trabajo activo, aprobaciones pendientes, cuota, dispositivos e historial filtrable con cursor estable | Should |
| RF-ENC-05 | La API de Actividad solo debe exponer una proyección permitida de cada evento, sin rutas absolutas, prompts, tokens ni ids de Telegram | Must |
| RF-ENC-06 | El sistema debe declarar Gmail, Drive y Calendar (MCP oficiales de Google) solo si hay credenciales, seleccionables uno a uno | Could |
| RF-ENC-07 | Lo que entra por esos conectores debe marcar procedencia | Must |

### 17. Coordinador de equipo (EQU)

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-EQU-01 | El sistema debe derivar el estado del trabajo de un equipo a partir de señales observadas en los nodos de sus miembros, con un vocabulario cerrado (avance, entregado, revisión pendiente, sin avance, fallo repetido, tarea larga, integración rota) | Could |
| RF-EQU-02 | Cada seguimiento debe requerir aprobación del miembro, y éste debe poder rechazarlo o revocarlo | Must |
| RF-EQU-03 | El coordinador debe proponer intervenciones priorizadas con un presupuesto de 4 al día | Could |
| RF-EQU-04 | Las señales deben caducar a las 24 h | Should |

## Plataforma e integraciones

Vibi debe funcionar nativo en Windows y macOS; Docker es opcional. Varias capacidades del agente de nodo solo existen en Windows.

| Capacidad | Windows | macOS |
| --- | --- | --- |
| Disco y terminal por MCP | Sí (PowerShell) | Sí |
| Árbol de accesibilidad, captura, ratón y teclado | Sí (UI Automation, SendInput) | Sí (API de accesibilidad, Quartz / `usecomputer`) |
| Navegador de Vibi | Sí | Sí |
| CDP con apps abiertas por el usuario | Sí (política WebView2) | Solo el navegador de Vibi |
| Trastienda | Sí | No |
| Índice de búsqueda del disco | Sí | No (recorrido podado) |
| Catálogo de aplicaciones y apertura rápida | Sí | No |
| Control multimedia | Sí | No |
| Lectura de notificaciones | Sí | Sí (requiere Acceso a disco completo) |
| Palabra de activación y tecla | Sí (Alt) | Sí (Fn) |
| Voz local Kokoro | No | Sí (Apple Silicon) |

Requisitos de instalación y operación:

| ID | Requisito | Prioridad |
| --- | --- | --- |
| RF-PLT-01 | Un instalador guiado (`install.py`, solo biblioteca estándar) debe comprobar dependencias, crear el entorno, escribir el `.env` conservando valores, crear la cuenta y arrancar Vibi | Should |
| RF-PLT-02 | El instalador debe detectar y aplicar actualizaciones, y negarse si hay cambios sin guardar | Should |
| RF-PLT-03 | El servidor debe escuchar solo en loopback por defecto | Must |
| RF-PLT-04 | Claude debe poder autenticarse por API key o por suscripción Pro/Max (`CLAUDE_AUTH_MODE`) | Must |
| RF-PLT-05 | Antigravity debe mantenerse caliente hasta 1 h sin uso y precalentarse al arrancar | Should |
| RF-PLT-06 | Un MCP de terceros sin credencial no debe declararse, y su entrada debe borrarse de la configuración | Should |

Integraciones externas: Anthropic (Agent SDK), Gemini vía `agy`, Inception Mercury, Groq (Whisper y modelo rápido), edge-tts, Vosk, Playwright, Telegram Bot API, MCP de Google y registro oficial de MCP.

## Fuera de alcance y preguntas abiertas

Fuera de alcance en la versión actual (según el roadmap del README):

- Memoria persistente que sobreviva a la conversación donde se pidió un encargo
- Sandbox real por usuario (contenedor o UID) y secretos por usuario
- Telegram multiusuario con vinculación por código
- Diffs ricos e importación de skills
- Fase 3: cara física (Pi Zero 2 W + HyperPixel Round), login por voz y NFC, memoria de usuario y grupo

Preguntas abiertas:

- [ ] ¿Se devuelven las confirmaciones de órdenes a dispositivos usando la procedencia como criterio? Hoy `requiere_aprobacion` es siempre falso (decisión del 2026-08-05)
- [ ] ¿Mercury pasa de motor de prueba a opción elegible por usuario en Configuración?
- [ ] ¿Se cierran las brechas de macOS (catálogo de apps, multimedia, índice de búsqueda) o se aceptan como limitación?
- [ ] ¿El coordinador de equipo entra en el alcance del producto o sigue como línea de investigación?
