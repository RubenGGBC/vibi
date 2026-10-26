# Frontend TFG Implementation Plan

**Goal:** Conectar el mock aprobado a Vibi sin sustituir la interfaz existente.
**Architecture:** Aplicación React y Vite separada en `Frontend TFG`, con copia independiente de los componentes de conexión existentes. Proxy HTTP/WebSocket al mismo backend; sin cambios de contratos ni del despliegue actual.
**Tech Stack:** React, TypeScript, TanStack Query, Vite, Vitest.
**Spec:** Mock aprobado `docs/mockups/vibi-interface.html` y petición de ejecución del usuario.

## Constraints
- Conservar `frontend` y el backend intactos.
- Chat, Dispositivos y Skill Studio; móvil y escritorio, blanco/negro/rojo.
- Usar autenticación real; sin datos ficticios ni tokens incorporados.

## Review Focus
- Sesión caducada: cerrar sesión y vaciar caché privada.
- Backend inaccesible: mostrar error, nunca equipos inventados.
- Reconexión: reutilizar recuperación del historial y eventos existente.
- Pantallas pequeñas: navegación inferior y formularios utilizables.
- Mutaciones de skills y chat: reutilizar contratos ya probados.

## Tasks
- [x] Crear aplicación independiente y copiar componentes y dependencias locales necesarios.
- [x] Verificar primero autenticación obligatoria, navegación y cambio de tema con pruebas de integración.
- [x] Implementar shell nuevo y login; integrar ChatPanel, EquiposPage, SkillsPage y useEvents.
- [x] Aplicar estética aprobada y responsive; documentar arranque y proxy configurable.
- [x] Ejecutar tests de componentes reutilizados, tests nuevos y compilación de producción.

## Execution notes
Ejecución directa autorizada por el usuario. No se sustituye la UI existente ni se publica. Copias locales para mantener ambos proyectos independientes; deberán sincronizarse deliberadamente en futuras correcciones de contratos.

Se eliminó del snapshot nuevo el código de páginas no utilizadas: se conservan los componentes y módulos realmente importados y sus pruebas. La primera suite sobre el snapshot completo mostró un fallo de selector duplicado en SettingsPage (pantalla no usada) y un timeout de SkillsPage; Skill Studio pasa al ejecutarse por separado. Suite final de componentes utilizados: 9 archivos, 40 pruebas correctas.

Logo recuperado del commit 367ac4e: Pixel Fox Wizard on Dark Background.png. Vite activo en 127.0.0.1:5174, página y logo devuelven HTTP 200 y /api/nodos devuelve 401 sin credenciales, como corresponde. Pendiente validación manual autenticada y entre dos máquinas físicas; no se ejecutaron operaciones reales de chat ni skills con credenciales de usuario.

Compilación final verificada: TypeScript y Vite correctos. Se restauró vite/client para tipos CSS y se hizo explícita la importación de manrope/index.css después de retirar el snapshot sobrante. Navegador abierto en la aplicación nueva.
