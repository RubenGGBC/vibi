# Archivos subidos visibles en el workspace

**Fecha:** 2026-08-08  
**Estado:** aprobado para planificación  
**Alcance:** almacenamiento y resolución de archivos gestionados por Vibi

## Problema

Vibi usa dos árboles de directorios distintos para una misma cuenta:

- El motor conversacional trabaja en `WORKSPACE_ROOT/<user_id>`.
- Las subidas de la PWA se guardan en
  `FILE_STORAGE_ROOT/<user_id>/<storage_key>`.

El catálogo y la base de datos conocen las subidas, pero las herramientas
normales del motor —terminal, listado y lectura directa— solo ven el workspace.
Además, el nombre físico actual es un UUID sin extensión. Por eso Vibi puede
encontrar los metadatos de un archivo y, aun así, no conseguir abrirlo o no
incluirlo cuando enumera el directorio del usuario.

## Resultado esperado

Cada archivo que suba el usuario será un archivo normal dentro de:

`WORKSPACE_ROOT/<user_id>/Archivos subidos/<nombre legible>`

El archivo conservará un nombre legible y su extensión. Claude y Antigravity
podrán enumerarlo y abrirlo con sus capacidades ordinarias, además de seguir
accediendo a él mediante Vibi Files y la descarga autenticada de la PWA.

## Decisión arquitectónica

La carpeta `Archivos subidos` será la ubicación canónica y la única copia
permanente de cada nueva subida. No se crearán enlaces simbólicos ni un espejo
sincronizado en `data/files`.

La fila de la tabla `files` seguirá siendo la fuente de verdad para propiedad,
cuota, tipo MIME, hash, descarga y borrado. `storage_key` identificará el nombre
físico asignado dentro de `Archivos subidos`; no se expondrá en la API.

`FILE_STORAGE_ROOT` se conservará como ubicación histórica para encontrar y
migrar los blobs creados por versiones anteriores. No recibirá nuevas subidas.

## Responsabilidades y activación

- `app.files` será el único componente que construya rutas de subidas, elija
  nombres libres, migre blobs y mantenga el fallback histórico.
- `app.db` ofrecerá una actualización acotada de `name` y `storage_key` para
  confirmar una migración de una fila `managed` perteneciente al usuario.
- La creación de una sesión viva de Claude o Antigravity llamará a
  `files.ensure_managed_uploads_visible(user_id)` antes de entregar el workspace
  al motor. Esto cubre tanto el primer turno como el precalentado de Antigravity.
- Una subida nueva aparecerá inmediatamente en una sesión que ya esté viva,
  porque el motor conserva el mismo directorio de trabajo y el archivo nace
  directamente dentro de él.

La preparación y la migración de las subidas de una cuenta se serializarán con
un candado por usuario. Ese mismo candado protegerá la elección y publicación
del nombre final, evitando que dos subidas concurrentes se sobrescriban.

## Flujo de una nueva subida

1. Se limpia el nombre recibido con las reglas actuales de nombres seguros.
2. Se crea, si hace falta, el directorio personal y su carpeta
   `Archivos subidos`.
3. Bajo el candado del usuario se elige un nombre libre. Si ya existe
   `informe.pdf`, se intenta
   `informe (2).pdf`, después `informe (3).pdf`, y así sucesivamente.
4. El cuerpo se escribe en un temporal dentro de la carpeta de destino mientras
   se calculan tamaño y SHA-256 y se aplican los límites actuales.
5. El temporal se publica de forma atómica con `os.replace`.
6. La base de datos reserva la cuota y registra el nombre físico definitivo.
7. Si el registro falla, se elimina el archivo recién publicado. El mecanismo
   actual de limpieza de temporales se mantiene.

El nombre registrado y el nombre físico serán el mismo, para que los resultados
de Vibi Files coincidan con lo que el motor encuentra en el directorio.

## Migración de subidas existentes

Antes de que un motor use el workspace de un usuario, Vibi comprobará sus
filas `managed` que todavía apunten al almacenamiento histórico.

Para cada una:

1. Se valida que el blob histórico sea un archivo regular perteneciente al
   usuario y no un enlace simbólico.
2. Se reserva un nombre legible y libre a partir del campo `name`.
3. Se copia a un temporal situado dentro de `Archivos subidos`. La copia permite
   migrar entre los dos volúmenes de Docker, aunque pertenezcan a sistemas de
   archivos distintos.
4. Se comparan tamaño y SHA-256 con la fila de la base de datos.
5. Se publica la copia de forma atómica.
6. Se actualizan `name` y `storage_key` dentro de una transacción.
7. Solo después de confirmar la actualización se elimina el blob histórico.

Si la copia, la verificación o la actualización de SQLite falla, el blob
histórico no se elimina. `path_for_file` mantendrá un fallback de lectura a la
ubicación histórica para que la descarga y Vibi Files continúen funcionando.
Una ejecución posterior podrá reintentar la migración.

Si una interrupción deja una copia ya publicada antes de actualizar SQLite, el
reintento reutilizará esa copia cuando tamaño y hash coincidan; si no coinciden,
escogerá otro nombre sin sobrescribirla.

## Visibilidad y ausencia de duplicados

La carpeta será visible para el sistema de archivos del motor, pero tendrá un
tratamiento reservado dentro de Vibi:

- `tasks.listar_proyectos` no la ofrecerá como proyecto.
- El indexador de workspace no recorrerá su contenido.
- El navegador de carpetas de la PWA no la mostrará como carpeta independiente,
  porque las filas gestionadas ya aparecen en la vista raíz.
- `files.search` y `files.read` continuarán usando la fila `managed`; no se
  creará una segunda fila `workspace` para el mismo archivo.

## Seguridad

- La carpeta de subidas debe ser hija directa del workspace resuelto del usuario.
- Los nombres se reducen a un único componente; no se admiten rutas absolutas,
  `..`, caracteres de control ni separadores introducidos por el cliente.
- Toda resolución comprueba que el resultado permanece dentro de
  `Archivos subidos`.
- No se siguen enlaces simbólicos ni durante la lectura ni durante la migración.
- Una fila de otro usuario nunca puede resolverse en el workspace actual.
- Las respuestas HTTP continúan ocultando rutas absolutas y `storage_key`.

## Borrado y cuota

El cálculo de cuota seguirá basado en las filas `managed`, por lo que el cambio
de ubicación no altera sus límites. Al borrar una subida, Vibi elimina el
archivo canónico y marca la fila como borrada igual que ahora. Durante el periodo
de compatibilidad también podrá retirar un blob histórico si la fila todavía no
se había migrado.

## Compatibilidad operativa

El volumen de workspace ya está persistido por Docker Compose, así que no hace
falta añadir otro montaje. Los despliegues con `WORKSPACE_HOST_PATH` personalizado
recibirán la carpeta dentro de ese mismo volumen. La ubicación histórica
`FILE_STORAGE_ROOT` permanece montada durante la migración de los archivos
existentes.

La documentación de configuración indicará que las nuevas subidas viven en el
workspace personal y que `FILE_STORAGE_ROOT` solo conserva blobs anteriores
pendientes de migrar.

## Verificación acordada

Por petición expresa del usuario, esta modificación no añadirá ni ejecutará
pruebas automatizadas. La implementación se limitará al cambio de almacenamiento,
la migración segura, la compatibilidad de lectura y las validaciones de rutas.

## Fuera de alcance

- Analizar semánticamente formatos que el motor no soporte.
- Convertir o transcodificar imágenes, audio o vídeo.
- Mostrar rutas absolutas internas en la API o en las respuestas de Vibi.
- Rediseñar la pantalla de archivos.
- Cambiar las cuotas o los límites de tamaño actuales.
