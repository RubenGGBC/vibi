# Especialización por usuario — Diseño

Fecha: 26 de agosto de 2026.

## El problema

Vibi es hoy igual para todo el mundo. El mismo catálogo de herramientas, los
mismos MCP, la misma personalidad y las mismas skills, tenga delante a un
estudiante de medicina o a un programador. Eso tiene dos costes que se pagan
todos los turnos.

**El primero es de contexto.** Cada servidor MCP declarado añade esquemas de
herramientas que entran en cada turno, se usen o no. Ya se midió: el catálogo
de `agy` pasó de 97 a 65 esquemas al retirar las que no hacían falta, y el
recorte se notó. Un usuario que nunca va a leer un PDF científico paga el
esquema de esa herramienta en cada pregunta que hace.

**El segundo es de acierto.** Sin saber a qué se dedica quien pregunta, el
modelo elige peor. «Búscame los apuntes de farmaco» no significa lo mismo para
alguien que tiene una carpeta `Farmacología II` con cuarenta PDF que para
alguien que no.

Lo que se quiere: que cada instancia de Vibi acabe siendo distinta porque el
usuario es distinto, empezando por una entrevista corta el primer día y
corrigiéndose sola con el uso.

## Estado del arte y qué falta

Revisado el 26 de agosto de 2026.

| Sistema | Perfil de usuario | Arranque en frío | Evidencia del entorno | Corrección por uso | Evaluación |
|---|---|---|---|---|---|
| PersonaAgent (2506.06254) | Sí (persona) | No | No | No (simula el pasado) | Funcional, benchmark LaMP |
| PRTA (2607.19739) | Pesos por usuario | No | No | Sí, por reflexión | Funcional, catálogo de 3 |
| ETAPP (2503.00771) | Perfiles fijos | No | No | No | Funcional, 33 APIs |
| MCPfinder | **No** | **No** | No | No | — |
| Skilldex (2604.16911) | **No** | No | `package.json` | No | **Solo formato** |
| Este diseño | Sí, persistente | Sí | Disco y apps | Sí | Funcional |

Las tres cosas que nadie hace y que este diseño aborda:

1. **Un perfil persistente del usuario que decida qué capacidades tiene el
   agente.** MCPfinder y Skilldex declaran por escrito que su selección depende
   de la tarea o del proyecto, no de la persona.
2. **El arranque en frío informado por la máquina.** Skilldex lee un
   `package.json`; nadie mira qué hay instalado ni qué usa el usuario de verdad.
3. **La evaluación funcional de la especialización.** Skilldex puntúa
   conformidad de formato y sus autores aclaran que no es una medida de calidad
   funcional. Nadie mide si especializar al agente lo hace mejor.

## Decisiones tomadas

**La entrevista no pregunta lo que puede mirar.** El catálogo de aplicaciones y
el índice de Windows dan una hipótesis fuerte antes de la primera pregunta. La
entrevista pasa de cuestionario a confirmación, y baja de veinte preguntas a
tres o cuatro. Es también lo que separa este trabajo del estado del arte: nadie
más tiene acceso al escritorio.

**El perfil es una hipótesis, no un formulario.** Cada afirmación lleva de dónde
salió y cuánta confianza tiene. La entrevista la crea con confianza media; el
uso la sube o la tumba. Es la disciplina de `recetas.py` —solo lo verificado
vale— aplicada al perfil.

**La confianza no enciende ni apaga: decide cuánto contexto ocupa.** Aquí se
diverge de `recetas.py` a propósito. Una receta mala hace fallar la tarea, así
que retirarla a los tres fallos es correcto. Una capacidad poco usada no hace
fallar nada: solo ocupa esquema. Por eso baja de nivel en vez de morir, y la
retirada se propone al usuario en vez de ejecutarse.

**El descubrimiento se consume, no se reimplementa.** El registro oficial de MCP
expone una API REST pública (`registry.modelcontextprotocol.io/v0/servers?search=`),
verificada el 26 de agosto de 2026: devuelve nombre, descripción, versión, web,
estado y transporte. MCPfinder agrega además Glama y Smithery. Reescribir eso no
aporta nada al trabajo.

**El observador no piensa, cuenta.** Es el reparto de `avisos.py` y
`vigilancias.py`: la parte tonta sale gratis y el modelo entra una vez por
revisión, no una vez por evento. Cuatro llamadas al mes frente a las 288 diarias
que cuesta un heartbeat de cinco minutos.

**Nada se instala sin aprobación.** Instalar un MCP local es ejecutar código de
un tercero en la máquina del usuario. La propuesta es del sistema; la decisión
es siempre suya.

## Arquitectura

```
                    ┌──────────────────────────────┐
   Entrevista ─────▶│           perfil             │◀──── observador
   (una vez)        │  afirmaciones + confianza    │      (revisión)
                    └──────────────┬───────────────┘
                                   │
                             activador (puro)
                                   │
          ┌────────────┬───────────┴───────┬──────────────┐
          ▼            ▼                   ▼              ▼
   construir_       skills.            vigilancias    GEMINI.md
   servidores()     set_enabled()      (aficiones)    (resumen)
```

### Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `app/perfil.py` | Modelo de datos del perfil: afirmaciones, confianza, capacidades. |
| `app/perfil_entrevista.py` | Recoge evidencia, genera hipótesis, busca en el registro, arma la propuesta. |
| `app/perfil_activador.py` | Función pura: perfil → configuración. Sin efectos ni red. |
| `app/perfil_observador.py` | Lee contadores, mueve confianzas, propone cambios. |
| `app/registro_mcp.py` | Cliente del registro oficial de MCP. |

### Archivos que se tocan

| Archivo | Cambio |
|---|---|
| `app/db.py` | Tres tablas nuevas. |
| `app/executors/agy_mcp_config.py` | `construir_servidores()` consulta el perfil. |
| `app/executors/antigravity_chat.py` | El resumen del perfil entra en `GEMINI.md`. |
| `app/skills.py` | Nueva función para que el modelo vea el catálogo de skills. |
| `app/api.py` | Endpoints de entrevista, propuesta y aprobación. |

## Modelo de datos

```sql
CREATE TABLE IF NOT EXISTS perfil (
    user_id      TEXT PRIMARY KEY REFERENCES users(id),
    resumen      TEXT NOT NULL DEFAULT '',
    creado_en    REAL NOT NULL,
    revisado_en  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS perfil_afirmaciones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL REFERENCES users(id),
    clase        TEXT NOT NULL CHECK (clase IN
                     ('dominio', 'herramienta', 'preferencia', 'aficion')),
    valor        TEXT NOT NULL,
    procedencia  TEXT NOT NULL CHECK (procedencia IN
                     ('entrevista', 'inventario', 'uso')),
    confianza    REAL NOT NULL CHECK (confianza >= 0 AND confianza <= 1),
    apoyos       INTEGER NOT NULL DEFAULT 0,
    contras      INTEGER NOT NULL DEFAULT 0,
    creada_en    REAL NOT NULL,
    movida_en    REAL NOT NULL,
    UNIQUE(user_id, clase, valor)
);

CREATE TABLE IF NOT EXISTS perfil_capacidades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL REFERENCES users(id),
    tipo          TEXT NOT NULL CHECK (tipo IN ('mcp', 'skill', 'vigilancia')),
    referencia    TEXT NOT NULL,
    justificacion TEXT NOT NULL,
    transporte    TEXT NOT NULL DEFAULT '' CHECK (transporte IN
                      ('', 'remoto', 'local')),
    nivel         TEXT NOT NULL DEFAULT 'completo' CHECK (nivel IN
                      ('completo', 'catalogo', 'propuesta_retirada')),
    aprobada_en   REAL,
    usos          INTEGER NOT NULL DEFAULT 0,
    ultimo_uso    REAL,
    UNIQUE(user_id, tipo, referencia)
);
```

`referencia` guarda el nombre del servidor en el registro, el slug de la skill o
el identificador de la vigilancia, según el tipo.

### Umbrales

Números de partida, pensados para ser ajustados con la primera semana de uso
real y no para ser definitivos:

| Concepto | Valor |
|---|---|
| Confianza inicial desde la entrevista | 0,6 |
| Confianza inicial desde el inventario | 0,4 |
| Confianza inicial desde el uso | 0,8 |
| Apoyo por uso confirmado | +0,10 (tope 1,0) |
| Contradicción | −0,30 |
| Decaimiento por revisión sin uso | −0,05 |
| Nivel `completo` | confianza ≥ 0,6 |
| Nivel `catalogo` | 0,3 ≤ confianza < 0,6 |
| Nivel `propuesta_retirada` | confianza < 0,3 |
| Cadencia de revisión | semanal, o cada 50 invocaciones de herramienta |

### El nivel intermedio significa cosas distintas según el tipo

Los tres niveles no se aplican igual a todo, y conviene dejarlo escrito porque
es una limitación del transporte y no una decisión:

- **Skills**: admiten el término medio de verdad. En `catalogo` solo entran
  nombre y descripción, y el cuerpo se carga si el modelo decide que aplica. Es
  el reparto de dos niveles que hace que treinta skills cuesten treinta líneas.
- **MCP**: **no admiten término medio.** Un servidor declarado en
  `mcp_config.json` expone todas sus herramientas o no está. Para ellos,
  `catalogo` significa *aprobado pero no declarado*: se conserva la aprobación y
  la justificación, se retira del motor, y si la evidencia vuelve a subir se
  propone reactivarlo sin repetir la entrevista.
- **Vigilancias**: tampoco. Una vigilancia corre o no corre. `catalogo` la deja
  pausada, conservando su frase original.

## La entrevista

### Escalada de evidencia

Tres niveles. Solo se sube si el de abajo no basta.

**Nivel 1 — estructura.** `app_catalog.discover_windows_apps()` para las
aplicaciones, y `buscador.py` sobre el índice de Windows para el mapa del disco.
El nodo construye **en local** un resumen agregado y manda solo eso:

```
Documentos/Farmacología II   41 pdf, 3 docx   tocada hace 2 días
Documentos/Bioquímica        28 pdf, 12 png   tocada hace 3 semanas
Descargas                    17 pdf, 4 zip    tocada hoy
```

Unos cientos de tokens, y ni un solo archivo sale del equipo. El índice hace
esto en medio segundo; recorrer el disco costaba 300.

**Nivel 2 — nombres.** Si el nivel 1 es ambiguo, los nombres de archivo. Siguen
siendo metadatos, no contenido.

**Nivel 3 — contenido.** Solo para desambiguar, solo unos pocos archivos, y con
permiso explícito pedido en el momento: «para afinar esto necesito abrir dos PDF
de Farmacología, ¿puedo?». Requiere el spike de multimodalidad descrito en
riesgos.

### Las preguntas

Tres fijas más una libre:

1. ¿Para qué vas a usar Vibi?
2. ¿Qué esperas de ella?
3. ¿En qué te gustaría que te ayudara y hoy haces a mano?
4. Campo libre: lo que quieras contarle, aficiones incluidas.

Las hipótesis del inventario se presentan como confirmación, no como pregunta
abierta: «veo carpetas de Farmacología y Bioquímica con muchos PDF recientes,
¿estudias medicina?».

### La búsqueda, en dos niveles

**Literal.** Lo declarado se traduce a consultas contra el registro. «Medicina y
apuntes en PDF» → `search=pdf`, `search=drive`, `search=notes`.

**Adyacencia.** De lo encontrado se deduce lo que no se pidió: si hay lectura de
papers y toma de apuntes, un MCP de gestión bibliográfica encaja aunque nadie lo
mencionara. Este segundo nivel es donde entra el modelo y es lo que separa esto
de una tabla de correspondencias.

La profundidad de expansión es un parámetro configurable, porque es una de las
variables del experimento: a más expansión, más cobertura y más ruido.

### Verificación antes de proponer

Nada se propone sin comprobar. Un servidor entra en la propuesta solo si:

- aparece en el registro oficial con estado `active`;
- tiene transporte declarado (`remotes` o `packages`);
- y responde: los remotos, a una petición de handshake; los locales, a un
  arranque en seco que liste sus herramientas.

Es la regla de `RecetaNoVerificada` aplicada aquí: proponer lo no comprobado
empeora el sistema en vez de mejorarlo, porque el usuario aprueba confiando.

### La propuesta

Dos bloques separados, cada elemento con su justificación en una línea y su
riesgo declarado:

- **Lo que has pedido** — deriva de algo que el usuario dijo.
- **Lo que además encaja** — deriva de la expansión por adyacencia.

Y un campo para añadir lo que quiera a mano.

## La activación

`perfil_activador.aplicar(perfil) -> Configuracion` es una función pura: entra
un perfil, sale una configuración. Sin base de datos, sin red, sin efectos. Por
eso se testea con tablas de casos y por eso la ablación del experimento sale
gratis: se le pasa un perfil vacío y se compara.

Cuatro destinos:

| Destino | Qué recibe |
|---|---|
| `agy_mcp_config.construir_servidores()` | Solo los MCP en nivel `completo`. Los de `catalogo` quedan aprobados pero fuera del motor. |
| `skills.set_enabled()` | Las skills en `completo` y `catalogo`; el nivel decide si va el cuerpo o solo la descripción. |
| `vigilancias` | Una vigilancia activa por afición en `completo`; las de `catalogo` quedan pausadas. |
| `GEMINI.md` | El campo `resumen`, en un bloque delimitado. |

El bloque de `GEMINI.md` se reemplaza entre marcas y **no toca el resto del
archivo**, que es donde vive la personalidad y las reglas de locución. Escribir
ahí en vez de teclear el texto en el turno es lo que bajó la primera respuesta
de voz de 32-56 s a 1,3-2,1 s, y ese reparto no se rompe.

## El observador

### Señales

Todas existen ya en la base de datos. El observador es una consulta, no un
proceso:

| Señal | Origen | Qué aporta |
|---|---|---|
| Herramientas invocadas | `tool_invocations` | Qué se usa y, sobre todo, qué nunca. |
| Recetas creadas | `recetas` | Evidencia fuerte: una receta de una app significa que esa app se usa. |
| Skills invocadas | `skills` | Cuáles están activas y muertas. |
| Temas | `messages` | De qué se habla de verdad. |
| Avisos ignorados | `avisos_silenciados` | Qué no importa. |

### Movimiento

- Uso que confirma una afirmación → `apoyos + 1`, confianza `+0,10`.
- Revisión sin uso → confianza `−0,05`.
- Contradicción explícita → `contras + 1`, confianza `−0,30`.
- Un MCP que deja de responder → baja la confianza de las afirmaciones que lo
  justificaban.

Cuando la evidencia de uso contradice lo declarado en la entrevista, **gana el
uso**: lo que se hace pesa más que lo que se dijo.

### Cadencia

Una revisión semanal, o antes si se acumulan 50 invocaciones. Una sola llamada
al modelo por revisión, y solo para redactar la propuesta de cambios: mover
confianzas es aritmética y no necesita modelo.

### Lo que el observador no hace

No vuelve a leer el disco. La lectura de archivos pertenece a la entrevista, con
su escalada y su permiso. El observador trabaja sobre contadores locales y
agregados: **ningún dato nuevo del usuario sale hacia el modelo**.

## Seguridad y privacidad

**Dos riesgos distintos, dos tratos distintos.** El registro los separa y el
diseño lo aprovecha:

- **Remoto** (`remotes`, `streamable-http`): no ejecuta código en el equipo,
  pero los datos salen hacia ese servidor. Se propone diciendo qué datos van a
  salir.
- **Local** (`packages`: npm, pypi, oci): el dato no sale, pero corre código de
  un tercero. Se propone solo si está `active` en el registro oficial, y con
  aprobación explícita.
- **Fuera del registro**: no se instala. Se enseña con enlace para que lo
  instale el usuario si quiere.

**Lo que nunca sale del equipo sin permiso:** el contenido de los archivos. El
nivel 1 manda un agregado construido en local; el nivel 3 pide permiso en el
momento y nombra los archivos concretos.

**El perfil es del usuario y es legible.** Se puede consultar, editar y borrar
entero desde la interfaz. Un perfil que el usuario no puede ver es un perfil que
no puede corregir.

## Errores

| Situación | Comportamiento |
|---|---|
| Sin nodo conectado durante la entrevista | Se salta el inventario y se pregunta. No se inventa evidencia. |
| El registro no responde | La entrevista termina sin propuesta de MCP. El perfil se guarda igual. |
| Un servidor no supera la verificación | No entra en la propuesta. Se registra por qué. |
| La revisión del observador falla | El perfil se queda como estaba. Un perfil viejo es peor que uno actualizado y mucho mejor que uno a medias. |
| Perfil vacío o entrevista sin terminar | Vibi funciona como hoy: catálogo completo, sin especialización. Es el baseline. |
| Un MCP aprobado deja de arrancar | Baja a `propuesta_retirada` y se avisa. No se desactiva solo. |

## Pruebas

- **`perfil_activador`**: función pura, tabla de casos. Perfil de medicina,
  perfil de programación, perfil vacío, perfil contradictorio. Sin base de datos
  ni red.
- **`perfil_observador`**: base de datos sembrada con invocaciones y recetas
  sintéticas; se comprueba que las confianzas se mueven como marcan los
  umbrales. **Contra una base de pruebas, nunca contra la real** — ya ocurrió
  que 600 de 683 filas del histórico las escribió pytest.
- **`perfil_entrevista`**: inventarios sintéticos (medicina, programación,
  audiovisual) y comprobación de qué hipótesis salen. Estos mismos inventarios
  son los casos del experimento.
- **`registro_mcp`**: contra respuestas grabadas del registro, no contra la red.
  Un test que depende de internet falla el día de la defensa.

## Evaluación

Esta sección existe porque el trabajo es también un TFG y la evaluación es la
contribución, no un añadido.

**Hipótesis:**

- **H1** — Una propuesta informada por el perfil obtiene mayor tasa de
  aceptación que una propuesta basada solo en la tarea.
- **H2** — Las capacidades instaladas con perfil siguen usándose más a las dos
  semanas que las instaladas sin él.
- **H3** — Una instancia especializada resuelve las tareas del dominio del
  usuario con menos llamadas al modelo y mayor tasa de acierto.

**Métricas.** Se adoptan las tres de ETAPP (0-5, con puntos clave anotados a
mano, que es más consistente que un juez LLM suelto): procedimiento, personali-
zación y proactividad. Se añaden dos que ningún trabajo del área reporta y que
aquí se pueden medir: **llamadas al modelo por tarea** y **supervivencia de la
capacidad a las dos semanas**.

**Ablación**, con la estructura de PersonaAgent: sistema completo / sin
observador / sin perfil / sin inventario. El activador puro hace que cada
configuración sea un parámetro, no una rama de código.

## Fuera de alcance

- **Que Vibi escriba skills nuevas.** El almacén (`skills`, `skill_versions`) ya
  soporta versionado, así que queda preparado. Implementarlo a medias resta más
  de lo que suma.
- **Federación entre instancias.** Que una Vibi especializada le pida algo a
  otra. La arquitectura de nodos ya lo soportaría; es la línea futura natural.
- **Perfiles multiusuario en el mismo equipo.** Un perfil por `user_id`, y la
  máquina se asume de una persona.
- **Especialización del modelo.** No se entrena ni se afina nada: la
  especialización es de capacidades y de contexto.

## Riesgos conocidos

**El nivel 3 depende de un spike sin hacer.** Está verificado que `agy` reenvía
al modelo el `ImageContent` de una tool MCP (10 de agosto de 2026,
`devices.screenshot`). **No está verificado que lea un PDF**: un PDF no es
`ImageContent` y habría que convertirlo a imagen o extraer el texto. Es una hora
de trabajo y condiciona el diseño del nivel 3, así que se hace antes de
implementarlo.

**Depender de un registro externo.** Si el registro oficial cambia su API o cae,
la entrevista se queda sin propuesta de MCP. Por eso el fallo está contemplado
en la tabla de errores y por eso el cliente vive aislado en `registro_mcp.py`.

**Sobre-inferencia del inventario.** De una carpeta llamada `Bioquímica` a
«estudia medicina» hay un salto: podría ser docente, o de otra persona. Lo cubre
que la entrevista confirme en vez de asumir, y que el inventario entre con
confianza 0,4 y no con 1,0.

**El campo se mueve rápido.** Skilldex es de abril de 2026 y MCPfinder es un
producto vivo. La contribución se ancla en la evaluación y no en la novedad,
precisamente porque la novedad puede caerse en cualquier momento y un
experimento medido no.
