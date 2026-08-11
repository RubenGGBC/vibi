# Rebranding integral de Morgana a Vibi

## Objetivo

El producto conserva exactamente sus capacidades y comportamiento, pero adopta
`Vibi` como única identidad activa. El cambio incluye la interfaz, la palabra de
activación, las personalidades de los motores, los canales, los artefactos de
escritorio y los identificadores técnicos propios del proyecto.

## Alcance

- Sustituir `Morgana` por `Vibi` en textos, prompts, documentación y pruebas.
- Usar `vibi` como wake word y en las órdenes de cierre de la sesión de voz.
- Renombrar componentes, paquetes, eventos, servicios, ejecutables, archivos y
  servidores MCP propios del producto cuando el nombre forme parte de su
  identidad.
- Hacer que las variables nuevas usen el prefijo `VIBI_`.
- Mantener el aspecto visual y toda la funcionalidad existente.

El historial de Git y el nombre de la carpeta externa del checkout no se
reescriben.

## Compatibilidad y migración

Los nombres nuevos son canónicos. Una instalación actual debe conservar sus
datos y ajustes:

- La configuración acepta las variables antiguas `MORGANA_*` como fallback
  cuando no exista su equivalente `VIBI_*`.
- El almacenamiento del companion migra los ajustes desde la clave antigua a la
  nueva sin borrar el original si la escritura nueva falla.
- La base de datos canónica pasa a ser `vibi.db`; si solo existe la base anterior,
  el arranque la adopta de forma segura sin crear una instalación vacía.
- Las rutas persistentes de aplicaciones auxiliares se migran o se reutilizan
  cuando hacerlo sea necesario para no perder sesiones.

Las referencias a `Morgana` que sobrevivan en el código activo estarán limitadas
a estos fallbacks explícitos de compatibilidad.

## Componentes afectados

1. Backend FastAPI, configuración, canales y motores conversacionales.
2. Agente de nodo y sus scripts de instalación o arranque.
3. PWA React y companion Tauri, incluidos eventos, almacenamiento y binarios.
4. Detector Vosk y cierre de sesiones de voz.
5. Docker, paquetes, iconos, ejemplos de entorno y documentación.
6. Pruebas backend, frontend, wake listener y escritorio.

## Tratamiento de errores

Una migración de datos nunca debe sustituir una base existente ni dejar al
producto apuntando a una ruta vacía. Si un ajuste antiguo no se puede copiar, se
seguirá leyendo durante ese arranque y se registrará el problema. Las variables
nuevas siempre prevalecen sobre sus alias antiguos.

## Verificación

- Pruebas específicas que demuestren el wake word `vibi`, las frases de cierre y
  los fallbacks de configuración/datos.
- Suites completas de Python y frontend.
- Comprobaciones de tipos, lint y compilaciones web/companion.
- Búsqueda final de referencias y nombres `morgana`, clasificando cualquier
  resto como compatibilidad deliberada.
