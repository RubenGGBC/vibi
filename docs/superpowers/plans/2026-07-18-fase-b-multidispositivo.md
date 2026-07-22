# Fase B multidispositivo — Plan de implementación

> Ejecución inline en esta sesión. Por petición expresa, este plan no crea ni ejecuta tests.

**Objetivo:** Convertir cada PWA abierta en una ventana en vivo de la conversación persistida, con recuperación tras desconexión y reset sincronizado.

**Arquitectura:** SQLite mantiene la identidad y última actividad de cada dispositivo. El WebSocket autenticado conserva conexiones agrupadas por usuario y dispositivo; los mensajes se serializan en un único sitio y se emiten solamente después de persistirse. React Query mantiene el historial canónico y reconcilia los mensajes optimistas mediante `client_ref`.

**Tecnologías:** FastAPI, WebSocket, SQLite, React, TypeScript y TanStack Query.

## Restricciones globales

- Mantener sin cambios la autenticación JWT y los eventos de tareas existentes.
- No añadir presencia, gestión de dispositivos, push, indicadores de escritura ni cifrado adicional.
- Permitir varias pestañas con el mismo `device_id` sin perder conexiones vivas.
- Emitir mensajes únicamente después del commit de SQLite.
- No crear ni ejecutar tests.

### Tarea 1: Persistencia e identidad de dispositivos

**Archivos:** `app/db.py`, `app/serializers.py`

- [ ] Crear la tabla `devices`, sus índices y la migración idempotente de `messages.client_ref`.
- [ ] Añadir upsert/touch de dispositivos sin permitir que un usuario reclame el identificador de otro.
- [ ] Extender la lectura del historial con `after_id`, detección de conversación cambiada y orden cronológico.
- [ ] Definir `serializar_mensaje()` como formato único para REST y WebSocket.

### Tarea 2: WebSocket multidispositivo y difusión del core

**Archivos:** `app/events.py`, `app/executors/groq_chat.py`, `app/core/messages.py`, `app/api.py`

- [ ] Agrupar conexiones por `user_id` y `device_id`, con varias conexiones por dispositivo.
- [ ] Validar y registrar el handshake, enviar `conexion_lista` y refrescar `last_seen` mediante heartbeat.
- [ ] Emitir `chat_message` tras guardar cada turno rápido y `conversation_reset` tras el reset.
- [ ] Aceptar `client_ref` desde PWA y registrar Telegram como dispositivo lógico.
- [ ] Exponer `after_id` mutuamente excluyente con `before_id` y señalar resets desconectados.

### Tarea 3: Cliente PWA, reconciliación y puesta al día

**Archivos:** `frontend/src/types.ts`, `frontend/src/lib/device.ts`, `frontend/src/lib/conversation.ts`, `frontend/src/lib/useEvents.ts`, `frontend/src/pages/ChatPage.tsx`

- [ ] Crear una identidad persistente e inferir `movil`, `pc` o `kiosko`.
- [ ] Enviar la identidad en el handshake y mantener heartbeat/reconexión.
- [ ] Fusionar eventos por id, reemplazar optimistas por `client_ref` y vaciar al recibir reset.
- [ ] Al recibir `conexion_lista`, pedir `after_id`; si cambió la conversación, reemplazar el historial.
- [ ] Hacer que Chat use la caché compartida como fuente canónica y conserve solo elementos transitorios locales.

### Tarea 4: Documentación y revisión estática

**Archivo:** `docs/diario.md`

- [ ] Documentar la Fase B.
- [ ] Revisar imports, tipos, sintaxis y diff sin ejecutar suites de tests.
