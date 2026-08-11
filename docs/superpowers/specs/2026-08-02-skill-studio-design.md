# Skill Studio de Vibi — diseño

**Fecha:** 2026-08-02

## Objetivo

Convertir el catálogo de herramientas de Vibi en una plataforma donde cada
usuario pueda crear comportamientos reutilizables, probarlos y activarlos sin
instalar código arbitrario. Una skill combinará instrucciones, ejemplos de uso
y un conjunto explícito de herramientas ya autorizadas por Vibi.

## Enfoques considerados

### 1. Añadir más presets a Herramientas

Extender el constructor actual con más argumentos preconfigurados es barato y
mantiene el modelo de seguridad, pero cada composición seguiría representando
una sola llamada a una primitiva. No permite expresar tono, procedimiento,
criterios de calidad ni combinar contexto de varias capacidades.

### 2. Biblioteca de manifiestos exportables

Guardar instrucciones y generar un `SKILL.md` crea un formato portable y útil
para compartir, pero deja los manifiestos inertes dentro de Vibi. El usuario
no puede comprobar si la skill funciona ni invocarla desde el chat.

### 3. Skill Studio con runner restringido — elegido

Crear una capa de skills versionadas sobre el catálogo existente. Cada skill
tiene instrucciones, ejemplos y hasta cuatro herramientas permitidas. Vibi
infiere argumentos estructurados, valida cada llamada con el esquema Pydantic
de la primitiva y usa los resultados como datos no confiables para elaborar la
respuesta. La skill puede probarse en el estudio, exportarse e invocarse de
forma explícita con `/skill <slug> <petición>`.

Este enfoque aporta comportamiento real y conserva la frontera de seguridad:
SQLite nunca puede introducir Python, shell, SQL, módulos ni herramientas que
no existan en `app/tools.py`.

## Modelo de producto

Una skill contiene:

- nombre y `slug` estable para invocación;
- descripción orientada a descubrimiento;
- instrucciones Markdown, tratadas como directrices del propietario;
- entre uno y cinco ejemplos de petición;
- cero a cuatro herramientas del catálogo visible para el usuario;
- alcance `personal` o `lab`;
- estado borrador o activo;
- número de versión y fechas de creación/edición.

Los borradores personales son privados. Las skills del laboratorio solo pueden
crearse o editarse por administradores y solo pueden depender de herramientas
de sistema o del laboratorio; nunca de una herramienta personal. Los usuarios
normales solo ven skills de laboratorio activas.

## Persistencia y revisiones

`skills` conserva el estado actual y `skill_versions` una instantánea JSON
inmutable de cada versión de contenido. Crear produce la versión uno; editar
nombre, descripción, instrucciones, ejemplos, herramientas o alcance incrementa
la versión y escribe otra instantánea. Activar o desactivar no modifica el
contenido ni crea una revisión.

Los índices parciales garantizan que el `slug` sea único dentro de las skills
personales de un usuario y dentro del laboratorio. Al duplicar se crea una skill
personal desactivada con un sufijo libre y una historia independiente.

## Validación de calidad

El servicio normaliza espacios, ejemplos y `slug`, elimina herramientas
duplicadas y devuelve un informe con puntuación, estado `ready` e incidencias
de severidad `error` o `warning`.

La activación exige:

- nombre, descripción e instrucciones suficientemente descriptivos;
- al menos un ejemplo de invocación;
- referencias a herramientas existentes, visibles y activas;
- un máximo de cuatro herramientas;
- compatibilidad entre alcance de la skill y alcance de sus herramientas.

Un borrador puede guardarse con avisos, pero no con referencias de herramienta
inválidas. Así el trabajo incompleto no se pierde y el runtime nunca recibe una
composición incoherente.

## Ejecución

El banco de pruebas permite ejecutar también un borrador propio; la invocación
por chat exige que la skill esté activa. El runner realiza estos pasos:

1. Resuelve la skill con aislamiento por usuario.
2. Para cada herramienta seleccionada, pide al modelo del carril `tools` un
   objeto JSON conforme a su esquema, excluyendo argumentos ya fijados.
3. Ejecuta la herramienta por `tools.execute`, que conserva validación,
   permisos y auditoría actuales.
4. Limita y serializa los resultados; los encierra como datos no confiables.
5. Pide al mismo carril una respuesta siguiendo las instrucciones de la skill.

Una skill sin herramientas funciona como una plantilla de razonamiento o
redacción. El runner no hace bucles abiertos: como máximo ejecuta una vez cada
herramienta declarada. Las ejecuciones se registran en el log append-only.

La sintaxis `/skill <slug> <petición>` es deliberadamente explícita. Evita que
un clasificador active por accidente una skill costosa o con efectos. El chat y
Telegram reutilizan el mismo caso de uso y persisten el turno como conversación.

## API

- `GET /api/skills`: skills visibles y resumen del estado del estudio.
- `POST /api/skills`: crea un borrador.
- `PUT /api/skills/{id}`: guarda una nueva versión.
- `POST /api/skills/{id}/estado`: activa o desactiva tras validar.
- `POST /api/skills/{id}/duplicar`: crea una copia personal desactivada.
- `GET /api/skills/{id}/versiones`: devuelve la historia inmutable.
- `GET /api/skills/{id}/exportar`: compila un `SKILL.md` portable.
- `POST /api/skills/{id}/probar`: ejecuta el banco de pruebas.

Los errores de propiedad devuelven 404 para no revelar ids ajenos; conflictos
de `slug`, estado o calidad usan 409; manifiestos mal formados usan 422.

## Experiencia de usuario

`/skills` tendrá una cabecera con contadores de activas y borradores, tarjetas
de catálogo y un constructor. El editor muestra instrucciones, ejemplos por
línea, alcance y selección de capacidades con permisos y efectos visibles.

Cada tarjeta permite editar, activar/desactivar, duplicar, exportar y abrir un
banco de pruebas. El resultado de prueba muestra respuesta, herramientas
ejecutadas y artefactos sin obligar al usuario a abandonar el estudio. La UI
explica la invocación `/skill` y distingue con claridad borrador, activa,
personal y laboratorio.

## Seguridad y límites

- No hay carga dinámica de código ni ejecución de comandos desde manifiestos.
- Toda herramienta se vuelve a resolver y validar en cada ejecución.
- Las tools desactivadas bloquean activación y ejecución.
- Los resultados se tratan como contenido no confiable frente a prompt
  injection y se recortan antes de enviarlos al modelo.
- Las skills personales y sus revisiones no cruzan usuarios.
- La publicación al laboratorio sigue exigiendo `is_admin`.
- La primera versión no activa skills por intención difusa ni permite bucles,
  condiciones o escritura arbitraria; esas extensiones requieren un diseño de
  permisos adicional.

## Pruebas y aceptación

La implementación se considera completa cuando pruebas de servicio y API
demuestran aislamiento, revisiones, validación de activación, restricciones de
alcance, exportación, duplicado y ejecución allowlisted; el core reconoce el
comando explícito; y pruebas de React cubren creación, activación, prueba y
exportación. También deben pasar pytest completo, Vitest, ESLint, ambos
proyectos TypeScript y el build de Vite.
