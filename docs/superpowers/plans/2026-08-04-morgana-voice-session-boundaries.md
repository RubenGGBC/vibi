# Morgana Voice Session Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que cada despertar de Morgana abra un hilo nuevo, conserve contexto solo durante esa invocación y archive el hilo al despedirse.

**Architecture:** FastAPI abrirá la conversación y devolverá su identificador; el cliente conservará ese identificador y lo enviará en todos los turnos y en el cierre. El procesamiento validará y fijará la conversación esperada para que una petición tardía no pueda saltar al hilo siguiente.

**Tech Stack:** Python 3, FastAPI, SQLite, React 19, TypeScript 6 y Tauri 2.

## Global Constraints

- No crear ni ejecutar tests automáticos, por instrucción expresa del usuario.
- Preservar los cambios locales preexistentes y no incluirlos en commits propios.
- Reutilizar `conversations.id`; no añadir tablas ni migraciones.
- Mantener compatibilidad con llamadas de voz que no usan `conversation_mode=true`.

---

### Task 1: Fijar la conversación esperada en el backend

**Files:**
- Modify: `app/db.py`
- Modify: `app/core/messages.py`
- Modify: `app/executors/claude_chat.py`
- Modify: `app/api.py`

**Interfaces:**
- Consumes: la conversación activa existente y el token de nodo.
- Produces: `POST /api/voz/abrir`, el formulario `conversation_id` de `POST /api/voz` y un cierre limitado a esa sesión.

- [ ] **Step 1: Hacer condicional el reinicio de base de datos**

Añadir `expected_conversation_id: str | None = None` a
`db.reset_active_conversation`. Dentro de la misma transacción, devolver `None`
si la conversación activa no coincide con el identificador esperado; en otro
caso archivar y crear la nueva conversación como hasta ahora.

- [ ] **Step 2: Impedir que Claude cambie de hilo silenciosamente**

Definir `ConversationChanged` en `claude_chat.py` y ampliar `respond`:

```python
async def respond(
    user: dict,
    text: str,
    origin: str,
    client_ref: str | None = None,
    attached_tool_ids: tuple[str, ...] = (),
    voz: bool = False,
    conversation_id: str | None = None,
) -> ChatResult:
```

Cuando exista `conversation_id`, comprobar antes y después de adquirir el lock
que sigue siendo la conversación activa; si no, lanzar `ConversationChanged`.

- [ ] **Step 3: Propagar el identificador por el núcleo de mensajes**

Añadir `conversation_id: str | None = None` a `procesar_mensaje`, validar ese
identificador también en la rama de skills y pasarlo a `claude_chat.respond`.
Las llamadas web y Telegram conservarán el valor predeterminado.

- [ ] **Step 4: Añadir apertura, validación y cierre de la sesión de voz**

Crear `POST /api/voz/abrir`. Ampliar `_reiniciar_conversacion` para aceptar un
identificador esperado y convertir una sustitución concurrente en HTTP 409.
En `POST /api/voz`, exigir `conversation_id` solo en modo conversación,
validarlo antes de transcribir, pasarlo al núcleo y usarlo al despedirse.
Ampliar `POST /api/voz/cerrar` con un cuerpo opcional:

```python
class CerrarConversacionVozBody(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)
```

Una sesión ya sustituida responderá sin modificar la sesión activa.

- [ ] **Step 5: Verificar sintaxis sin ejecutar tests**

Ejecutar el compilador de Python sobre los cuatro módulos modificados y revisar
el diff para confirmar que no se incluyeron cambios locales ajenos.

### Task 2: Vincular el cliente a la sesión abierta

**Files:**
- Modify: `frontend/src/lib/companionApi.ts`
- Modify: `frontend/src/components/CompanionApp.tsx`

**Interfaces:**
- Consumes: `POST /api/voz/abrir` y su `conversation_id`.
- Produces: `openCompanionConversation`, turnos etiquetados y cierres acotados.

- [ ] **Step 1: Ampliar el cliente HTTP**

Añadir:

```typescript
export async function openCompanionConversation(
  settings: CompanionSettings,
): Promise<string>;
```

Añadir `conversationId` a `sendCompanionVoice` y al `FormData`. Permitir que
`closeCompanionConversation` reciba el identificador y lo envíe como JSON,
manteniendo el argumento opcional para compatibilidad con consumidores
anteriores.

- [ ] **Step 2: Abrir antes de escuchar**

Guardar el identificador en `sessionIdRef`. Al despertar, marcar la sesión como
activa, esperar `openCompanionConversation` y solo entonces llamar a
`beginListeningRef.current()`. Si la UI se cerró mientras abría, cerrar el hilo
recién creado sin iniciar captura.

- [ ] **Step 3: Mantener y cerrar la sesión correcta**

Enviar `sessionIdRef.current` con cada clip. En despedida, limpiar el ref porque
el backend ya archivó. En cierre manual, esperar el cierre con ese identificador;
si falla, conservarlo y mostrar un error reintentable en vez de ignorarlo.

- [ ] **Step 4: Verificar tipos y compilación sin ejecutar tests**

Ejecutar `npm run build:companion`, revisar el diff y confirmar que las firmas
de TypeScript coinciden con el backend.

### Task 3: Desplegar el cambio local

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: backend y companion compilados.
- Produces: servicios locales actualizados.

- [ ] **Step 1: Reconstruir el contenedor de Morgana**

Ejecutar `docker compose up -d --build morgana` y comprobar con
`docker compose ps` que el servicio queda activo.

- [ ] **Step 2: Construir el instalador de escritorio**

Ejecutar `npm run desktop:build` desde `frontend` sin lanzar tests.

- [ ] **Step 3: Entregar artefactos y estado**

Informar de los archivos modificados, compilaciones realizadas y cualquier
paso de instalación que requiera confirmación del usuario.

