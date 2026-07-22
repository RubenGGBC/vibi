# Diario de implementación

## 2026-07-18 — Fase B: sincronización multidispositivo

- **Dispositivos:** cada PWA conserva un UUID, la Cara usa identidad de kiosco
  y Telegram un id lógico; SQLite registra tipo, nombre, creación y actividad.
- **WebSocket:** las conexiones se agrupan por usuario y dispositivo, admiten
  pestañas duplicadas, autentican el handshake y refrescan actividad por heartbeat.
- **Chat en vivo:** los mensajes persistidos de usuario y Morgana se serializan
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
- **Frontend base:** Vite, React, TypeScript, Tailwind, tema Morgana,
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
