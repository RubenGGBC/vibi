# Servicio local de voz Codex para Vibi

**Goal:** Probar Juniper, Maple y Breeze en conversación real y conectar la voz con Vibi conservando Antigravity para programación.
**Architecture:** Servicio Python local independiente en `services/codex_voice`, con app-server de Codex por stdio y WebRTC en navegador. Una herramienta dinámica `vibi_request` llama a `/api/mensaje` autenticada con la cuenta de Vibi. No cambia proveedores, modelos ni la UI anterior. Selector de voces reversible; Maple elegida por el usuario.
**Stack:** Python estándar, HTML/CSS/JavaScript, Codex CLI instalado.
**Spec:** Petición del usuario y experimento documentado en `docs/investigacion-voz-codex-2026-10-26.md`.

## Restricciones
- Mantener sesión Codex en el host; no copiar OAuth ni montar credenciales en Docker.
- Inicio de micrófono explícito. Desconectar libera audio y proceso.
- Maple elegida por el usuario como predeterminada; selector de tres voces y reconexión explícita para cambiarla.
- Backend fijo configurable solo al arrancar; JWT de Vibi solo en memoria del servicio.
- No reemplazar Antigravity ni cambiar preferencias del usuario.
- Herramienta de Vibi usa sus permisos e historial actuales. Sin envío automático repetido tras timeout.

## Verificación
- [x] Pruebas de contratos: login, errores, delegación, permisos y validación de voz.
- [x] Pruebas RPC: respuesta dinámica, errores de backend y ausencia de credenciales en eventos.
- [x] Servicio y web con sesión por pestaña, CSRF, host/origen local, protección de sesiones ajenas.
- [x] Probar audio sintético con cada voz y verificar que no hay llamadas para cambiar el motor de Vibi.
- [x] Abrir selector para conversación humana. El usuario eligió Maple.

## Decisiones
Implementación directa autorizada. No se añade aún Codex como sustituto del agente programador: el servicio de voz lo usa como coordinador y delega en el motor actual de Vibi mediante API. La demostración debe distinguir voz disponible de integración autenticada, que requiere login de Vibi.

## Evidencia
21 pruebas Python del servicio, 3 pruebas de ensamblado de transcripciones y 40 pruebas de Frontend TFG correctas; compilación TypeScript/Vite correcta. Arranque documentado para macOS; prueba en Mac físico pendiente del usuario.

Las tres voces produjeron más de 2000 bytes de audio en navegador real con micrófono sintético. Se revisaron capturas de escritorio y móvil. Se corrigió el ensamblado de fragmentos de voz, que antes creaba una línea por palabra.

La primera prueba completa mostró que appendText solo añadía contexto silencioso. El campo de texto ahora inicia un turno normal de Codex. La segunda prueba recorrió página → turno Codex → herramienta dinámica → `/api/mensaje` simulado → resultado → audio remoto (4576 bytes). Hubo exactamente una llamada al backend simulado. No se usaron credenciales reales de Vibi ni se modificaron sus motores. La prueba humana autenticada sigue pendiente del login del usuario.
