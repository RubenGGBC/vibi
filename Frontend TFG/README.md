# Frontend TFG

Interfaz independiente de Vibi basada en el mock aprobado: Chat, Dispositivos y Skill Studio. No sustituye `../frontend` ni cambia el backend.

## Arranque

```powershell
cd 'Frontend TFG'
npm install
npm run dev
```

Abrir http://127.0.0.1:5174 e iniciar sesión con una cuenta existente de Vibi. El proxy HTTP y WebSocket apunta a http://127.0.0.1:8000. Para otro servidor, establecer `$env:VIBI_BACKEND_URL='http://servidor:8000'` antes del arranque. No se necesitan cambios de CORS.

Los componentes existentes se han copiado para mantener independencia: autenticación JWT, chat con historial, adjuntos y eventos, equipos y sus órdenes, y creación, edición, activación, exportación y prueba de skills. Las operaciones afectan al sistema real y usan sus permisos actuales. La vinculación de agentes sigue usando el procedimiento existente; no se simula un código de vinculación.

El tema se guarda en `vibi.tfg.theme`. La sesión se guarda por origen en `vibi.jwt`; el puerto separado exige iniciar sesión de nuevo. Una sesión caducada o cerrada vacía la caché privada.

`npm run build` compila a `dist`; `npm test -- --run` ejecuta las pruebas. El despliegue de producción necesita un proxy `/api` con WebSocket y fallback a `index.html`. No copiar este `dist` sobre el frontend actual.

Logo recuperado del commit `367ac4e`: `Pixel Fox Wizard on Dark Background.png`, copiado sin modificar a `public/fox-wizard.png` y usado también en el mock.
