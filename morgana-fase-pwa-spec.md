# Morgana — Fase PWA (especificación v1)

Objetivo de la fase: una única PWA que sirve los tres entry points
(móvil, PC, tablet/Pi del lab), servida por el propio backend.
Telegram queda como canal de notificación con deep-links a la PWA.

Principio invariable: la PWA es un cliente más. Toda la lógica vive
en el core. Nada de negocio en el frontend.

---

## 1. Backend

### 1.1 Auth (requisito previo a todo lo demás)

- Login con `nombre` + `contraseña` contra la tabla `users`.
  - Añadir columna `password_hash` (bcrypt) a `users`.
  - Script/comando CLI para fijar la contraseña del usuario existente
    (`python -m scripts.set_password ruben`).
- `POST /api/auth/login` → `{token}` (JWT, expiración larga tipo 30 días;
  secret en `.env` como `JWT_SECRET`).
- Todos los endpoints `/api/*` (salvo login) exigen `Authorization: Bearer`.
- El WebSocket autentica con el token como query param o primer mensaje.
- Los endpoints existentes (`/salud`, `/tareas/{id}`) se migran bajo
  `/api/` y quedan protegidos; `/salud` puede quedar público.

### 1.2 Endpoints REST

Convención: JSON, errores como `{"error": "mensaje"}` con status apropiado.

- `GET  /api/tareas?estado=&proyecto=&limite=` — lista de tareas del
  usuario autenticado, más reciente primero.
- `GET  /api/tareas/{id}` — detalle completo (prompt, estado, plan,
  resultado, workspace, timestamps).
- `POST /api/tareas/{id}/aprobar` — misma lógica que el botón de Telegram
  (reutilizar `tasks.aprobar_tarea`; validar que la tarea es del usuario).
- `POST /api/tareas/{id}/rechazar` — ídem.
- `POST /api/mensaje` — `{texto}` → pasa por el router igual que Telegram:
  - vía rápida → `{via: "rapida", respuesta}`
  - vía agéntica → `{via: "agentica", task_id}` (encolada)
- `GET  /api/proyectos` — subdirectorios del workspace del usuario.
- `POST /api/proyectos/clonar` — `{url}` → git clone dentro del workspace
  del usuario. Validar URL (solo https://github.com/... o git@ conocidos),
  sanear nombre destino, realpath dentro del workspace. Responde con el
  nombre del proyecto creado.
- `GET  /api/yo` — datos del usuario autenticado (nombre, id).

Refactor implícito: la lógica compartida entre Telegram y la API
(procesar mensaje, resolver proyecto) se extrae a funciones del core
si aún vive en el handler de Telegram. Telegram y la API deben llamar
exactamente al mismo código.

### 1.3 WebSocket de eventos

- `WS /api/eventos` (autenticado).
- El servidor emite JSON por cada cambio relevante del usuario:
  `{"tipo": "tarea_actualizada", "task": {...}}` — con la tarea completa,
  para que el frontend no tenga que re-fetch.
  `{"tipo": "notificacion", "texto": "..."}` — mensajes sueltos.
- Implementación: gestor de conexiones por user_id; el orquestador
  (`tasks.py`) emite al gestor además de al notificador de Telegram.
  (Mismo patrón callback que ya existe: registrar un segundo notificador.)
- La ruta `/cara` usará este mismo WS en la fase tablet (estados de la
  cara = eventos); no implementar nada específico de cara todavía.

### 1.4 Telegram como notificador con deep-links

- Las notificaciones de Telegram añaden al final la URL de la PWA:
  `🔗 {PWA_BASE_URL}/tareas/{id}` (nueva var de entorno `PWA_BASE_URL`).
- Los botones Aprobar/Rechazar de Telegram SE MANTIENEN (aprobar rápido
  sin abrir la app sigue siendo oro).

### 1.5 Servir la PWA

- FastAPI sirve el build estático del frontend en `/` (StaticFiles),
  con fallback a `index.html` para rutas del router del frontend.
- Un solo contenedor, un solo origen → sin CORS.
- El Dockerfile pasa a multi-stage: stage node para `npm run build`
  del frontend, stage python copia `dist/` y sirve.

---

## 2. Frontend

### 2.1 Stack

- React + Vite + TypeScript. Tailwind para estilos.
- `vite-plugin-pwa` para manifest + service worker (instalable,
  icono, standalone). Nombre: Morgana. Tema oscuro por defecto.
- Estado: React Query (fetch + caché) + el WS actualizando la caché.
  Nada de Redux; no hace falta.
- Rutas (react-router):
  - `/login`
  - `/` → Bandeja
  - `/tareas/:id` → Detalle
  - `/chat`
  - `/proyectos`
  - `/cara` → placeholder vacío ("próximamente") para la fase tablet

### 2.2 Pantallas v1

**Bandeja (`/`)**
- Lista de tareas: prompt truncado, proyecto, estado con color,
  tiempo relativo. Orden: esperando_aprobacion primero, luego activas,
  luego el resto por fecha.
- Se actualiza en vivo por WS. Filtros: estado, proyecto.
- FAB / input "nueva tarea" → misma caja que el chat pero pre-enfocada
  a encargo (usa POST /api/mensaje).

**Detalle (`/tareas/:id`)**
- Prompt completo, estado, proyecto, timestamps.
- Plan renderizado como markdown (react-markdown) — legible, con
  bloques de código bien formateados.
- Si `esperando_aprobacion`: botones grandes Aprobar / Rechazar.
- Resultado (markdown) cuando exista.
- Actualización en vivo por WS (ver el paso de planificando →
  esperando_aprobacion sin refrescar).

**Chat (`/chat`)**
- Conversación con la vía rápida. Burbujas, input abajo, enter envía.
- Si el router deriva a agéntica, mostrar tarjeta "tarea encolada"
  con link al detalle.
- Historial: el que devuelva el backend (si aún es en memoria, mostrar
  solo la sesión actual; la persistencia del historial rápido es una
  tarea aparte ya conocida).

**Proyectos (`/proyectos`)**
- Lista de carpetas del workspace.
- Botón "Clonar repo" → modal con input de URL → POST clonar →
  feedback de éxito/error.

**Login (`/login`)**
- Nombre + contraseña → guarda token en localStorage → redirige a `/`.
- Interceptor: 401 en cualquier llamada → volver a /login.

### 2.3 Estética

- Oscuro, limpio, un acento morado (es Morgana 🔮). Sin frameworks de
  componentes pesados; Tailwind y ya. Mobile-first: la bandeja y el
  detalle tienen que ser cómodos en el móvil, que es donde se aprueban
  los planes.

---

## 3. Orden de tareas sugerido (para el diario)

1. Auth: columna password_hash, script de contraseña, login JWT,
   middleware de protección. Tests manuales con curl.
2. Endpoints REST (tareas, mensaje, proyectos, clonar) reutilizando
   el core; refactor de lo que viva en Telegram.
3. WebSocket de eventos + emisión desde el orquestador.
4. Deep-links en las notificaciones de Telegram.
5. Esqueleto frontend: Vite + rutas + login + layout.
6. Bandeja + Detalle (con aprobar/rechazar) — el corazón.
7. Chat y Proyectos.
8. PWA: manifest, icono, service worker. Multi-stage Dockerfile.
9. Prueba de fuego: ciclo completo desde el móvil.

Cada tarea termina con su entrada en docs/diario.md.

---

## 4. Fuera de alcance en esta fase (no implementar)

- La cara animada y todo lo de voz/STT/TTS (fase tablet/Pi).
- Multi-usuario real (registro, users de Linux, secretos por usuario).
- Notificaciones push web. Telegram cubre las notificaciones.
- Diffs de git renderizados en el detalle (nice-to-have; anotar para v1.1).
- Selección de modelo/executor por tarea.
