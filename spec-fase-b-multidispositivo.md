# Spec — Fase B: Los dispositivos son ventanas (sincronización multi-dispositivo)

> Para el agente de codificación de Morgana. Leer `CLAUDE.md` antes de empezar.
> Requiere Fase A completada (persistencia + context_builder).
> Al terminar, entrada en `docs/diario.md`.

## Contexto

Con la Fase A, la conversación vive en SQLite en el servidor. Pero cada
dispositivo sigue siendo una isla: si escribes desde el PC, el móvil no se
entera hasta recargar. Esta fase convierte los dispositivos en ventanas de
la misma sesión: todo mensaje de chat se difunde en vivo por el WebSocket
existente a todas las conexiones del usuario, y al reconectar un dispositivo
se pone al día solo. Es el diferencial "la sesión sigue a la persona".

## Objetivo

1. Cada conexión WebSocket queda identificada por usuario y dispositivo.
2. Los mensajes de chat (del usuario y de Morgana) se difunden en vivo a
   todas las conexiones del usuario, vengan del canal que vengan (PWA,
   Telegram, cara).
3. Un dispositivo que se reconecta recupera lo que se perdió sin recargar
   la página.
4. El reset de conversación ("empezar de cero") también se difunde: todas
   las ventanas se vacían a la vez.

## Modelo de datos

**`devices`** (tabla nueva)
- `id` TEXT (pk) — UUID generado por el cliente la primera vez y guardado
  en localStorage de la PWA; Telegram y cara usan ids fijos por canal
  (p. ej. `telegram:<chat_id>`, `cara:<device>`).
- `user_id` (fk → users)
- `tipo` TEXT: `movil` | `pc` | `kiosko` | `telegram` (mejor esfuerzo:
  la PWA lo infiere de user agent / modo instalado; no es crítico que acierte)
- `nombre` TEXT NULL (legible, p. ej. "Chrome en PC"; opcional)
- `last_seen` DATETIME (se actualiza al conectar el WS y a intervalos)
- `created_at`

No hay gestión de dispositivos en UI (listar/revocar) — fuera de alcance.
La tabla existe para identidad, diagnóstico y para la futura fase de presencia.

## Comportamiento

### Identificación de la conexión
- La PWA genera un `device_id` (UUID v4) si no existe en localStorage y lo
  manda al conectar el WebSocket (query param o primer mensaje de handshake,
  lo que encaje mejor con el WS actual).
- El servidor hace upsert en `devices` y asocia la conexión a
  `(user_id, device_id)`. El registro de conexiones vivas pasa de
  "lista por usuario" a "mapa usuario → {device_id → conexión}"
  (o equivalente según lo que exista hoy).
- `last_seen` se refresca al conectar y con el ping/keepalive que ya haya.

### Difusión de mensajes de chat
- Tras persistir cada mensaje en `messages` (lo hace ya la Fase A), el
  servidor emite por el WS un evento nuevo, p. ej.:
  `{ "type": "chat_message", "message": { id, role, content, origen, created_at } }`
  a **todas** las conexiones del usuario, incluida la del dispositivo emisor.
- La PWA deja de fiarse solo del eco optimista: pinta el mensaje optimista
  al enviar (como ahora) y lo **reconcilia** cuando llega el evento con el
  `id` real (evitar duplicados: si el evento corresponde al optimista
  pendiente, se sustituye; si es de otro dispositivo, se añade).
- Aplica a los cuatro flujos: mensaje de usuario desde PWA, respuesta de
  Morgana, mensajes que entren por Telegram y por la cara. Todos acaban
  como eventos `chat_message` en todas las ventanas.

### Puesta al día al (re)conectar
- Nuevo comportamiento en la PWA: al establecerse el WS (primera vez o
  reconexión), pedir por REST los mensajes con `after_id = <último id local>`
  y fusionarlos. Requiere extender el endpoint de la Fase A:
  `GET /api/conversations/active/messages` acepta `after_id` además de
  `before_id` (mutuamente excluyentes; con `after_id` devuelve en orden
  cronológico ascendente desde ese id, límite igual).
- Si el `after_id` local pertenece a una conversación ya archivada (hubo
  reset mientras estaba desconectado), el endpoint lo señala (p. ej.
  respuesta con `conversation_changed: true` y los últimos N de la nueva)
  y la PWA repinta desde cero.

### Difusión del reset
- `POST /api/conversations/reset` emite a todas las conexiones del usuario
  un evento `{ "type": "conversation_reset", "conversation_id": <nueva> }`.
- Las ventanas que lo reciben vacían el chat y quedan sobre la conversación
  nueva sin recargar.

### Telegram y cara
- Telegram: al recibirse un mensaje de chat por Telegram, además de lo que
  ya hace, se difunde como `chat_message` (origen `telegram`). No hace falta
  que Telegram "reciba" difusiones (es un canal de notificaciones, no una
  ventana completa) — su conexión no es WS y queda fuera.
- Cara (`/cara`): usa el mismo mecanismo que la PWA (es la misma app);
  basta con que su `device_id` fijo la identifique como `kiosko`.

## Fuera de alcance (explícito)

- Presencia ("¿quién está en el lab?"), mensajes diferidos, saludos al llegar.
- UI de gestión de dispositivos (listar, renombrar, revocar sesiones).
- Indicador de "escribiendo..." o de qué dispositivo está activo.
- Multi-usuario: todo esto es dentro de un mismo usuario.
- Push nativo / notificaciones nuevas (Telegram sigue siendo el canal push).
- Cambios en la vía agéntica y en los eventos de tareas ya existentes del WS
  (siguen funcionando igual; solo se añaden tipos de evento nuevos).
- Cifrado o auth adicional del WS más allá del JWT actual.

## Criterios de aceptación (review por resultados)

1. Dos ventanas abiertas (PC + móvil): escribir en una → el mensaje y la
   respuesta de Morgana aparecen en la otra en vivo, sin recargar, sin
   duplicados en la emisora.
2. Mandar un mensaje por Telegram → aparece en las ventanas abiertas de la
   PWA con `origen=telegram`, y la respuesta también.
3. Móvil en avión durante unos mensajes desde el PC → al volver la conexión,
   el móvil se pone al día solo (sin recargar la página) y en orden correcto.
4. "Empezar de cero" desde una ventana → todas las ventanas se vacían a la
   vez; un dispositivo que estaba desconectado durante el reset, al volver,
   detecta el cambio de conversación y repinta desde cero.
5. En la tabla `devices` hay una fila por dispositivo real usado, con
   `last_seen` reciente y tipo razonable.
6. WS sin JWT válido → rechazado (comportamiento actual intacto).
7. Los eventos de tareas de siempre (aprobaciones, estados) siguen llegando
   igual que antes.

## Notas de implementación

- El evento `chat_message` lleva el mensaje completo ya serializado igual
  que lo devuelve el endpoint REST — un solo formato de mensaje en todo el
  sistema, definido en un solo sitio.
- La reconciliación optimista en la PWA: el mensaje optimista guarda un
  `client_ref` (uuid local); si se puede, el servidor lo acepta en el POST
  de envío y lo devuelve dentro del evento, y la reconciliación es exacta.
  Si complica, heurística role+content+ventana temporal es aceptable en v1.
- Emitir la difusión **después** del commit en SQLite, nunca antes.
- El mapa de conexiones debe tolerar el mismo `device_id` conectando dos
  veces (pestañas duplicadas): última conexión gana o lista por device,
  a criterio, pero sin crashear ni filtrar mensajes a conexiones muertas.
