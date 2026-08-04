# Tool Workbench 2.0 — diseño

## Problema

El catálogo de tools ya permite ejecutar cuatro primitivas seguras y crear aliases con argumentos preconfigurados, pero la experiencia sigue siendo rígida: la UI solo conoce dos primitivas, los argumentos de ejecución están cableados a `{}`, los presets tienen que formar una petición completa y no existe una vista de uso o historial. Esto limita tanto el uso directo como las posibilidades reales de las skills que enlazan estas tools.

## Enfoques considerados

1. **Pulido únicamente visual.** Mejoraría la legibilidad, pero no añadiría capacidades ni resolvería el constructor cableado. Se descarta porque el usuario pidió enriquecer el sistema, no solo su presentación.
2. **Añadir muchas primitivas ad hoc.** Daría más acciones rápidamente, pero cada nueva primitiva exigiría cambios manuales en la pantalla y multiplicaría una deuda ya visible. Se descarta como solución aislada.
3. **Workbench guiado por esquemas + primitivas fundamentales + observabilidad.** El backend publica contratos JSON Schema, la UI genera formularios desde esos contratos y el mismo flujo sirve para cualquier primitiva futura. A la vez se añaden capacidades seguras de tareas, proyectos, actividad y creación de notas. Es el enfoque elegido porque aumenta capacidad y extensibilidad sin ejecutar código arbitrario.

## Objetivos

- Añadir cuatro primitivas explícitas y aisladas por usuario: listar tareas, listar proyectos, consultar actividad reciente y crear una nota de texto gestionada.
- Permitir presets parciales: una tool personalizada puede fijar solo algunos campos y pedir el resto al ejecutarla.
- Ofrecer creación, edición, duplicado, activación y prueba desde un workbench guiado por el esquema publicado por el backend.
- Mostrar métricas e historial personal de invocaciones sin almacenar argumentos ni resultados sensibles.
- Mantener los IDs y contratos existentes para no romper el router, las skills ni clientes actuales.

## No objetivos

- No se permitirá cargar Python, comandos de shell, URLs arbitrarias ni plugins desde la pantalla.
- No se eliminarán tools: desactivarlas mantiene resolubles las dependencias históricas de skills.
- No se almacenarán argumentos, contenido de archivos ni resultados en el historial de invocaciones.
- No se convertirá el editor en un motor de workflows; cada tool personalizada seguirá envolviendo una única primitiva revisada.

## Backend

### Primitivas

El registro `PRIMITIVES` incorpora:

- `tasks.list`: filtros opcionales `state`, `project` y `limit`; devuelve solo metadatos seguros de tareas propias (sin prompt, plan, resultado ni ruta absoluta).
- `projects.list`: devuelve nombres de subdirectorios válidos del workspace propio.
- `activity.recent`: filtro opcional de categoría y límite; usa la proyección pública existente, nunca el payload interno del evento.
- `files.create_note`: recibe nombre y contenido UTF-8, aplica los límites de archivo y cuota existentes, usa escritura temporal + reemplazo atómico y registra el archivo como gestionado.

Cada definición seguirá publicando permisos, efectos e `input_schema`. La escritura de notas declara `files:write:self` y `filesystem:write`; las otras capacidades son de lectura.

### Presets parciales

La creación y actualización validarán únicamente los campos presentes contra tipos y restricciones Pydantic, rechazando propiedades desconocidas. La validación completa se conserva al ejecutar después de mezclar `bound_arguments` y argumentos runtime; los argumentos runtime tienen precedencia.

### Ciclo de vida y autorización

- Una tool personal solo puede editarse o activarse por su dueño.
- Una tool de laboratorio solo puede editarse o activarse por un administrador.
- Cualquier usuario que pueda ver una tool habilitada puede duplicarla como tool personal.
- Las primitivas de sistema no son editables ni desactivables, pero sí duplicables.
- Cambiar nombre, descripción, primitiva, alcance o presets usa `PUT /api/herramientas/{id}`.
- Duplicar usa `POST /api/herramientas/{id}/duplicar`.

### Observabilidad

El catálogo añade a cada tool un resumen de invocaciones del usuario autenticado: total, éxitos, fallos, última ejecución y duración media. `GET /api/herramientas/{id}/invocaciones` devuelve como máximo 100 registros propios con estado, código de error seguro y tiempos. Las ejecuciones inválidas, fallidas y exitosas generan eventos de actividad con códigos no sensibles.

## Frontend

La página pasa de un grid estático a un banco de trabajo con:

- cabecera con contadores de tools activas, ejecuciones y tasa de éxito;
- filtros por texto, alcance y capacidad;
- tarjetas con estado, efectos, uso y acciones de probar, editar/duplicar y activar;
- editor lateral reutilizado para crear o editar;
- campos generados desde `input_schema` para strings, números, booleanos y enums;
- selector por campo para decidir si queda preconfigurado;
- panel de ejecución que pide solo los campos no fijados y muestra el resultado estructurado;
- historial de invocaciones personales de la tool seleccionada.

Los campos desconocidos se degradan a una entrada JSON, de modo que una evolución compatible del esquema no deja la página inutilizable.

## Manejo de errores

- Los errores Pydantic se presentan como `422` con mensajes estables, sin volcar detalles internos.
- Los problemas de archivo (límite, cuota, nombre o contenido vacío) se traducen a errores de cliente.
- Una primitiva retirada deja la tool personalizada desactivada y visible, como ya ocurre.
- La UI conserva el formulario y muestra el error inline si una mutación falla.

## Pruebas

- Backend: aislamiento por usuario de las cuatro primitivas, cuota/escritura de notas, presets parciales, override runtime, edición/autorización, duplicado e historial/estadísticas.
- Frontend: constructor generado desde esquema, ejecución con argumentos runtime y representación de métricas/historial.
- Regresión: suite Python completa, Vitest completa, ESLint, TypeScript y build de producción.

