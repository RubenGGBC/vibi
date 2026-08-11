# Managed Uploads in Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guardar y migrar las subidas gestionadas dentro del workspace personal para que Vibi pueda enumerarlas y abrirlas por su nombre real.

**Architecture:** `app.files` será la única autoridad sobre rutas de subidas y usará `WORKSPACE_ROOT/<user_id>/Archivos subidos` como almacén canónico. Las filas `managed` conservarán cuota, propiedad y descargas; `FILE_STORAGE_ROOT` quedará como fallback histórico hasta que cada blob se copie, verifique y confirme en SQLite.

**Tech Stack:** Python 3.12, FastAPI `UploadFile`, `pathlib`, SQLite, SHA-256 y Docker Compose.

## Global Constraints

- La carpeta canónica se llama exactamente `Archivos subidos`.
- No crear enlaces simbólicos ni mantener dos copias permanentes.
- No borrar un blob histórico hasta verificar la copia y confirmar SQLite.
- No exponer rutas absolutas ni `storage_key` mediante la API.
- No indexar la carpeta canónica como workspace ni mostrarla como proyecto.
- Por petición expresa del usuario, no crear ni ejecutar pruebas automatizadas.
- Preservar todos los cambios locales no relacionados que ya existen en el repositorio.

## File Map

- `app/config.py`: nombre compartido de la carpeta canónica y semántica histórica de `file_storage_root`.
- `app/db.py`: listado completo de filas `managed` y confirmación transaccional de una ubicación migrada.
- `app/files.py`: construcción segura de rutas, nombres únicos, escritura canónica, migración, fallback, exclusión del índice y borrado.
- `app/tasks.py`: excluir `Archivos subidos` de la lista de proyectos.
- `app/executors/claude_chat.py`: preparar las subidas antes de crear una sesión Claude sobre el workspace.
- `app/executors/antigravity_chat.py`: preparar las subidas antes de crear o precalentar una sesión Antigravity.
- `.env.example`: explicar que `FILE_STORAGE_ROOT` es histórico.
- `README.md`: documentar la ubicación visible y la migración automática.

---

### Task 1: Persistencia canónica y compatibilidad histórica

**Files:**
- Modify: `app/config.py`
- Modify: `app/db.py`
- Modify: `app/files.py`

**Interfaces:**
- Produces: `MANAGED_UPLOADS_DIRECTORY: str = "Archivos subidos"`
- Produces: `db.list_managed_files(user_id: str) -> list[dict]`
- Produces: `db.update_managed_file_location(file_id: str, user_id: str, name: str, storage_key: str) -> dict | None`
- Produces: `files.ensure_managed_uploads_visible(user_id: str) -> int`
- Preserves: `files.path_for_file(file: dict, user_id: str) -> Path`

- [ ] **Step 1: Declarar la carpeta canónica y aclarar la configuración histórica**

Añadir junto a la configuración central:

```python
MANAGED_UPLOADS_DIRECTORY = "Archivos subidos"
```

Actualizar el comentario de `file_storage_root` para indicar que solo localiza blobs históricos pendientes de migrar.

- [ ] **Step 2: Añadir las operaciones SQLite acotadas**

Añadir a `app/db.py`:

```python
def list_managed_files(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM files
               WHERE user_id = ? AND source = 'managed' AND deleted_at IS NULL
               ORDER BY created_at, id""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_managed_file_location(
    file_id: str,
    user_id: str,
    name: str,
    storage_key: str,
) -> dict | None:
    with _conn() as c:
        cursor = c.execute(
            """UPDATE files SET name = ?, storage_key = ?, modified_at = ?
               WHERE id = ? AND user_id = ? AND source = 'managed'
                 AND deleted_at IS NULL""",
            (name, storage_key, time.time(), file_id, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row)
```

- [ ] **Step 3: Separar la raíz canónica de la raíz histórica**

En `app/files.py`, importar `shutil` y `MANAGED_UPLOADS_DIRECTORY`, y sustituir la raíz actual por dos helpers:

```python
def _managed_user_root(user_id: str) -> Path:
    workspace = tasks.directorio_usuario(user_id)
    candidate = workspace / MANAGED_UPLOADS_DIRECTORY
    if candidate.is_symlink():
        raise UnsafeFilePath("Directorio de archivos inválido")
    candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve()
    if resolved.parent != workspace:
        raise UnsafeFilePath("Directorio de archivos inválido")
    return resolved


def _legacy_managed_user_root(user_id: str) -> Path:
    root = Path(settings.file_storage_root).expanduser().resolve()
    user_root = (root / user_id).resolve()
    if user_root.parent != root:
        raise UnsafeFilePath("Directorio histórico inválido")
    return user_root
```

Crear un candado por usuario siguiendo el patrón ya usado por el índice de workspace. Crear también helpers que:

- validen un archivo regular situado directamente bajo una raíz;
- reserven `nombre.ext`, `nombre (2).ext`, etc.;
- consideren ocupados tanto los nombres físicos como todos los `storage_key` de filas `managed`;
- calculen SHA-256 por bloques para verificar migraciones.

- [ ] **Step 4: Escribir nuevas subidas y notas directamente en el workspace**

Mantener la lectura por bloques y los límites actuales. Tras completar el temporal, entrar en el candado del usuario, elegir el nombre final y usarlo a la vez como `name` y `storage_key`:

```python
reserved = {item["storage_key"] for item in db.list_managed_files(user_id)}
storage_key = _available_managed_name(root, name, reserved)
destination = root / storage_key
os.replace(temporary, destination)
stored = db.create_managed_file_within_quota(
    user_id,
    storage_key,
    storage_key,
    media_type,
    total,
    digest.hexdigest(),
    settings.file_user_quota_bytes,
)
```

Aplicar el mismo patrón a `create_text_file`. Si SQLite rechaza la reserva o lanza una excepción, eliminar únicamente el destino que acaba de publicar esta operación.

- [ ] **Step 5: Implementar migración verificada y reintentable**

Añadir `ensure_managed_uploads_visible(user_id) -> int`. Bajo el candado del usuario, recorrer `db.list_managed_files(user_id)` y:

1. Omitir filas cuyo `storage_key` ya resuelva a un archivo canónico válido.
2. Resolver sin enlaces `FILE_STORAGE_ROOT/<user_id>/<storage_key>`.
3. Reutilizar un destino huérfano con el nombre deseado solo si no pertenece a otra fila y coinciden tamaño y SHA-256.
4. En otro caso, copiar con `shutil.copyfile` a `.<file_id>.migrate`, verificar tamaño y hash y publicar con `os.replace`.
5. Llamar a `db.update_managed_file_location(...)`.
6. Borrar el blob histórico solo después de recibir la fila actualizada.
7. Ante cualquier `OSError` o discrepancia, retirar solo el temporal, conservar el original, registrar un warning y continuar con el siguiente archivo.

La función devuelve el número de filas migradas.

- [ ] **Step 6: Mantener el fallback de lectura y borrado**

Actualizar `path_for_file` para intentar primero el archivo canónico y después el blob histórico, aplicando la misma validación de propiedad, contención, archivo regular y ausencia de enlaces. `delete_managed_file` seguirá usando `path_for_file`, por lo que podrá retirar tanto una subida nueva como una fila aún no migrada.

- [ ] **Step 7: Revisar el diff de este bloque sin ejecutar pruebas**

Inspeccionar únicamente `app/config.py`, `app/db.py` y `app/files.py`; confirmar que no se hayan alterado límites, serializadores, rutas HTTP ni código ajeno al almacenamiento.

- [ ] **Step 8: Commit acotado**

```powershell
git add -- app/config.py app/db.py app/files.py
git commit -m "fix: expose managed uploads in user workspace"
```

---

### Task 2: Visibilidad para motores sin duplicados internos

**Files:**
- Modify: `app/tasks.py`
- Modify: `app/files.py`
- Modify: `app/executors/claude_chat.py`
- Modify: `app/executors/antigravity_chat.py`

**Interfaces:**
- Consumes: `MANAGED_UPLOADS_DIRECTORY`
- Consumes: `files.ensure_managed_uploads_visible(user_id: str) -> int`
- Preserves: `tasks.listar_proyectos(user_id: str) -> list[str]`

- [ ] **Step 1: Excluir la carpeta reservada de proyectos e índice**

En `tasks.listar_proyectos`, añadir:

```python
and entrada.name != MANAGED_UPLOADS_DIRECTORY
```

En el filtro de `dirs` de `files.index_workspace`, excluir el mismo nombre. En `list_directory`, omitir esa entrada antes de construir `folders`, de forma que la PWA siga mostrando las filas `managed` en la raíz sin ofrecer una segunda navegación que las indexe como `workspace`.

- [ ] **Step 2: Preparar archivos antes de crear una sesión Claude**

Importar `files` junto a los módulos internos y, al comienzo de `_create_live_session`, ejecutar:

```python
await asyncio.to_thread(files.ensure_managed_uploads_visible, user["id"])
```

La llamada debe ocurrir antes de construir las opciones con el `cwd` del usuario.

- [ ] **Step 3: Preparar archivos antes de crear o precalentar Antigravity**

Importar `files` y, al comienzo de `_start_session`, ejecutar la misma llamada mediante `asyncio.to_thread`. Como tanto el primer turno como `warm_up` terminan en `_start_session`, no duplicar la migración en otros métodos.

- [ ] **Step 4: Revisar el diff de integración sin ejecutar pruebas**

Confirmar por inspección que ambos motores conservan sus locks, sesión, historial, MCP y cwd actuales, y que el único comportamiento nuevo antes de crear la sesión es preparar las subidas.

- [ ] **Step 5: Commit acotado**

```powershell
git add -- app/tasks.py app/files.py app/executors/claude_chat.py app/executors/antigravity_chat.py
git commit -m "fix: prepare uploads before chat sessions"
```

---

### Task 3: Configuración, documentación y activación local

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Documents: `WORKSPACE_ROOT/<user_id>/Archivos subidos/<name>`
- Documents: `FILE_STORAGE_ROOT` como fallback histórico.

- [ ] **Step 1: Actualizar configuración de ejemplo**

Cambiar el comentario sobre `FILE_STORAGE_ROOT` para explicar que las nuevas subidas se guardan dentro del workspace y que esta variable solo señala blobs antiguos pendientes de migración. Mantener la variable y su valor para compatibilidad.

- [ ] **Step 2: Actualizar la sección de archivos multidispositivo**

Documentar la carpeta `Archivos subidos`, la conservación del nombre y extensión, la migración automática y que la PWA continúa usando descargas autenticadas sin exponer rutas absolutas.

- [ ] **Step 3: Revisar solo la documentación modificada**

Comprobar por lectura que README y `.env.example` coincidan con la especificación y no prometan análisis de formatos que el motor no soporte.

- [ ] **Step 4: Commit acotado**

```powershell
git add -- .env.example README.md
git commit -m "docs: explain visible managed uploads"
```

- [ ] **Step 5: Reconstruir el servicio local sin ejecutar pruebas**

```powershell
docker compose up -d --build vibi
```

No ejecutar suites, pruebas manuales ni comandos de validación funcional. Informar expresamente que el cambio fue desplegado sin pruebas por indicación del usuario.
