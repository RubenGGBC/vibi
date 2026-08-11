# Centro de actividad y recuperación — diseño

## Contexto

Vibi ya conserva un log append-only de acciones y el ciclo completo de las
tareas, pero esa información solo está disponible en SQLite. Cuando una tarea
falla, la PWA muestra el error, aunque obliga a volver a redactar el encargo.
La mejora convierte esos datos en una superficie operativa personal y añade
una acción de recuperación deliberadamente acotada.

## Alternativas consideradas

1. **Centro de actividad y recuperación (elegida).** Expone una proyección
   segura del log, un resumen operativo y permite reintentar tareas con error.
   Aporta diagnóstico y una acción útil manteniendo el modelo actual.
2. **Panel calculado solo en el cliente.** Reutilizaría los endpoints de tareas,
   proyectos y archivos, pero no podría mostrar el historial real ni paginarlo
   de forma eficiente.
3. **Búsqueda global.** Sería vistosa, aunque exigiría indexar entidades con
   contratos y permisos distintos. Tiene más superficie y menos utilidad
   inmediata para el estado actual del producto.

## Alcance

### Resumen operativo

`GET /api/actividad` devuelve, siempre para el usuario autenticado:

- tareas activas y tareas que esperan aprobación;
- tareas completadas históricas;
- almacenamiento gestionado usado y cuota configurada;
- dispositivos conocidos y dispositivos vistos en los últimos dos minutos.

El resumen se incluye en cada respuesta para que cualquier página paginada sea
autosuficiente. No se añaden tablas ni dependencias.

### Historial personal

El mismo endpoint devuelve eventos en orden descendente y acepta:

- `limite`, entre 1 y 100;
- `antes_de`, cursor entero exclusivo;
- `categoria`, una de `tareas`, `conversacion`, `archivos`, `proyectos`,
  `herramientas` o `cuenta`.

Se consulta una fila adicional para determinar `siguiente_cursor`. El índice
`events(user_id, id DESC)` mantiene la consulta eficiente.

La API no expone el JSON interno. Un serializador con allowlist transforma cada
tipo conocido en `{id, tipo, categoria, titulo, detalle, creado_en, enlace}`.
Los eventos desconocidos reciben una descripción genérica. Nunca se devuelven
rutas absolutas, prompts completos, tokens, claves ni identificadores de chat.
Los eventos de tareas enlazan al detalle de la tarea solo si todavía pertenece
al usuario.

### Reintento seguro

`POST /api/tareas/{task_id}/reintentar` crea una tarea nueva a partir de una
tarea propia en estado `error`. Conserva prompt, modelo y workspace, vuelve a
pasar por la validación de confinamiento y entra en la cola normal de
planificación. No modifica el registro original.

- Otra cuenta recibe `404`, igual que en el resto de endpoints de tareas.
- Un estado distinto de `error` recibe `409`.
- Un proyecto eliminado o movido recibe `409` con un mensaje estable.
- La respuesta contiene la tarea nueva serializada y su id queda registrado en
  un evento `tarea_reintentada` junto al id de origen.

Esta semántica evita reanudar ejecuciones parciales: cada intento obtiene un
plan nuevo y vuelve a requerir aprobación humana.

## Interfaz PWA

Se añade **Actividad** al rail y una página central con:

- cuatro tarjetas compactas para trabajo activo, aprobaciones, almacenamiento y
  dispositivos;
- filtros de categoría accesibles mediante botones con `aria-pressed`;
- una cronología con icono, título, detalle, fecha y enlaces internos;
- estados explícitos de carga, vacío y error;
- botón «Cargar anteriores» cuando existe cursor.

En el detalle de una tarea con error aparece «Reintentar tarea». Al completarse,
la navegación cambia al nuevo detalle y las cachés de tareas y actividad se
invalidan. Los eventos WebSocket que ya indican cambios de tareas o archivos
también invalidan la actividad para mantenerla razonablemente fresca.

La estética conserva la paleta violeta, tipografía editorial y densidad de la
consola existente. No se crea un dashboard genérico ni se cambia la estructura
de tres columnas.

## Componentes y límites

- `app/activity.py`: clasificación y serialización segura; no accede a HTTP.
- `app/db.py`: consultas SQL de eventos y resumen; no decide copy ni enlaces.
- `app/api.py`: validación HTTP, ownership y orquestación del reintento.
- `frontend/src/pages/ActivityPage.tsx`: consulta, filtros, paginación y vista.
- `TaskDetailPage.tsx`: única acción de recuperación visible.

## Errores y privacidad

Las consultas filtran por `user_id` en SQL, no después de serializar. Los
payloads se parsean defensivamente y un JSON histórico corrupto no rompe la
página. El resumen no revela nombres de otros usuarios ni datos del sistema.
Los errores de red mantienen visibles los datos ya cargados cuando sea posible.

## Pruebas y criterios de aceptación

1. La paginación no repite eventos y respeta categoría y usuario.
2. Ninguna respuesta contiene `workspace`, prompt completo ni payload crudo.
3. Los contadores representan exclusivamente al usuario autenticado.
4. Solo una tarea propia con `estado=error` se puede reintentar.
5. El reintento conserva prompt/modelo, crea otro id y usa la cola normal.
6. La página filtra, carga páginas anteriores y enlaza tareas.
7. El botón de reintento navega al nuevo intento y desaparece en otros estados.
8. Pytest, Vitest, ESLint, TypeScript y el build de Vite terminan sin errores.

## Fuera de alcance

- Borrar o editar el log de auditoría.
- Cancelar una ejecución en curso.
- Reintentar automáticamente o saltarse la aprobación.
- Mostrar presencia exacta; «reciente» solo usa `last_seen`.
- Exponer un panel global de administración o actividad de otras cuentas.
