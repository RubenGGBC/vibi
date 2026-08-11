# Spec — Fase A: Persistencia de la conversación y construcción de contexto por capas

> Para el agente de codificación de Vibi. Leer `CLAUDE.md` antes de empezar.
> Al terminar, entrada en `docs/diario.md` como siempre.

## Contexto

Hoy el historial de la vía rápida (Groq) vive en memoria del proceso: se pierde
al reiniciar y no puede compartirse entre dispositivos. Esta fase lo mueve a
SQLite y cambia cómo se construye el contexto que se envía a Groq en cada turno.
Es el prerequisito de la fase multi-dispositivo (Fase B, spec aparte, no incluida aquí).

## Objetivo

1. La conversación de la vía rápida persiste en SQLite y sobrevive reinicios.
2. El contexto de cada turno se construye por capas con presupuesto de tokens
   acotado, en vez de volcar el historial entero.
3. El usuario puede "empezar de cero" archivando la conversación actual.

## Modelo de datos (nuevas tablas)

**`conversations`**
- `id` (pk)
- `user_id` (fk → users)
- `titulo` TEXT NULL (generado después, puede quedar NULL de momento)
- `estado` TEXT: `activa` | `archivada`
- `resumen_acumulativo` TEXT NULL — reservado para Fase A2, esta fase NO lo rellena
- `created_at`, `updated_at`

Invariante: **como máximo una conversación `activa` por usuario**. Si no existe,
se crea al primer mensaje.

**`messages`**
- `id` (pk)
- `conversation_id` (fk → conversations)
- `role` TEXT: `user` | `assistant`
- `content` TEXT
- `origen` TEXT: `pwa` | `telegram` | `cara` (según canal de entrada; las
  respuestas del asistente heredan el origen del mensaje al que responden)
- `tokens_aprox` INTEGER NULL (estimación al insertar; vale `len(content) // 4`)
- `created_at`

Índices: `messages(conversation_id, created_at)`, `conversations(user_id, estado)`.

Migración con el mecanismo que ya use el proyecto. No hay datos que migrar
(el historial actual en memoria se descarta, es aceptable).

## Comportamiento

### Escritura
Cada mensaje del usuario y cada respuesta de la vía rápida se insertan en
`messages` dentro de la conversación activa del usuario. La vía agéntica NO
cambia en esta fase (las tareas siguen en `tasks` como hasta ahora).

### Construcción del contexto por turno (vía rápida)

Orden de ensamblado del prompt que recibe Groq:

1. **System prompt** de Vibi (el actual; su rediseño es otra tarea, fuera de alcance).
2. **Bloque de estado del sistema**: lista compacta de las tareas del usuario
   en estados no terminales (`pendiente`, `planificando`, `esperando_aprobacion`,
   `ejecutando`), con formato una línea por tarea: id corto, proyecto, estado,
   descripción truncada. Máximo ~200 tokens; si hay más tareas, priorizar
   `esperando_aprobacion` y truncar el resto con "y N más".
   Si no hay tareas vivas, omitir el bloque entero.
3. **Ventana reciente**: últimos mensajes de la conversación activa, del más
   antiguo al más nuevo, hasta un presupuesto de **4000 tokens aprox**
   (usar `tokens_aprox`; cortar por mensajes completos, nunca partir uno).
4. El mensaje nuevo del usuario.

Los presupuestos (200 / 4000) van en configuración, no hardcodeados.

### Comando "empezar de cero"
- Endpoint REST (p. ej. `POST /conversations/reset`) que marca la activa como
  `archivada` y crea una nueva `activa` vacía.
- Botón discreto en la pantalla de Chat de la PWA que lo llama, con confirmación.
- No hace falta detectarlo por lenguaje natural en esta fase.

### Carga de historial en la PWA
Al abrir Chat, la PWA pide los últimos N mensajes de la conversación activa
por REST (endpoint nuevo, p. ej. `GET /conversations/active/messages?limit=50`)
y los pinta. Paginación hacia atrás no es necesaria en esta fase (dejar el
endpoint preparado con `before_id` opcional si sale barato, sin UI).

## Fuera de alcance (explícito)

- **Fase A2 — resumen acumulativo / compactación**: la columna existe pero
  nadie la escribe ni se inyecta en el prompt. Spec aparte.
- **Fase B — sincronización multi-dispositivo por WebSocket**: los mensajes
  no se difunden a otros sockets del usuario todavía. Spec aparte.
- Rediseño del system prompt / personalidad de Vibi.
- Múltiples conversaciones visibles con selector en la UI (solo hay una activa;
  las archivadas no se muestran).
- Generación automática de `titulo`.
- Cualquier cambio en la vía agéntica, el router o Telegram más allá de que
  sus mensajes de chat entren en `messages` con su `origen`.
- Búsqueda en el historial.

## Criterios de aceptación (review por resultados)

1. Arranca en Docker sin errores y la migración crea las tablas.
2. Conversación normal por la PWA → los mensajes aparecen en SQLite con
   `origen=pwa` y roles correctos.
3. **Reinicio del contenedor a mitad de conversación** → al volver, el chat
   de la PWA muestra el historial y Groq responde con memoria de lo anterior
   ("¿de qué estábamos hablando?" funciona).
4. Con una tarea en `esperando_aprobacion`, preguntar por chat "¿tengo algo
   pendiente?" → la respuesta la menciona (prueba del bloque de estado).
5. Conversación larga artificial (rellenar >4000 tokens) → el prompt enviado
   a Groq queda dentro del presupuesto y corta por mensajes completos
   (verificable por log del tamaño del contexto en cada turno — añadir ese log).
6. "Empezar de cero" desde la PWA → conversación nueva vacía, la anterior
   queda `archivada` en DB, y Groq ya no recuerda lo anterior.
7. Sin token JWT, los endpoints nuevos devuelven 401.

## Notas de implementación

- Estimación de tokens: `len(texto) // 4` es suficiente; no añadir dependencia
  de tokenizador.
- El ensamblado del contexto debe quedar en una función/módulo propio
  (p. ej. `context_builder`) con test unitario del recorte por presupuesto:
  la Fase A2 lo va a extender y conviene que esté aislado.
- Log por turno: tokens del bloque de estado, de la ventana y total (nivel debug).
