# Coordinador de equipo — Diseño

Fecha: 16 de septiembre de 2026.

## El problema

Todos los coordinadores de IA que existen hoy —académicos y comerciales—
coordinan a partir de **lo que la gente escribe**, no de lo que la gente hace.

Asana y Rovo leen el tablero y el ticket. El Manager Agent, que es la agenda de
investigación de referencia del área, lo dice de sí mismo con todas las letras:
accede solo a metadatos de tarea, registros de comunicación y registros de
artefactos, y *«los trabajadores envían informes de estado, pero el agente no
puede verificar el trabajo real de forma independiente. Esto crea potencial de
incentivos desalineados.»*

De ahí sale el problema de siempre: **el tablero está desactualizado porque
actualizarlo es trabajo.** Ana movió su tarea a «en progreso» el lunes; es
jueves y sigue ahí. Dani lleva tres días atascado y se sabrá el viernes en la
reunión, porque decir que estás atascado da vergüenza y siempre parece que lo
vas a resolver en la próxima hora. Bruno pregunta en el canal general e
interrumpe a seis personas para que le contesten dos.

Vibi tiene una cosa que ninguno de ellos tiene: **un agente de nodo corriendo en
la máquina de cada miembro**. Puede saber cosas sin que nadie las escriba.

Lo que se quiere: un coordinador que sostenga el estado del trabajo del equipo a
partir de evidencia observada en las máquinas, en vez de declarada por las
personas, y que lo haga a un coste viable y sin convertirse en vigilancia
laboral.

## Estado del arte y qué falta

Revisado el 15 de septiembre de 2026.

| Sistema | Qué aporta | De dónde saca el estado | Trabajadores | Defensa de privacidad |
|---|---|---|---|---|
| Manager Agent / MA-Gym (2510.02557) | Formalización POSG, banco de 20 flujos | Informes de estado | **Simulados** | No aplica |
| Survey orquestación MAS (FI 18(6) 326) | Taxonomía centralizada / descentralizada / jerárquica | Mensajes entre agentes | Agentes | No |
| CollabSim (2606.06399) | Competencia colaborativa con base CSCW | Experimento controlado | Agentes | No |
| Simulating Teams (2510.08242) | Entornos 2D para dinámicas humano-IA | Simulación | Simulados | No |
| PiSAs (2607.05318) | Integridad contextual multiusuario | Escenarios sintéticos | 4-10, sintéticos | **Solo mide, no defiende** |
| AgentLeak (2602.11510) | Fuga por canales internos: 68,8 % frente a 27,2 % en salidas | Trazas | Agentes | Solo mide |
| Asana AI Teammates | Agentes con permiso de edición en el flujo | **El tablero de Asana** | Reales | Producto |
| Atlassian Rovo | Teamwork Graph sobre Jira/Confluence/Teams | **El ticket y el documento** | Reales | Producto |
| Este diseño | Estado derivado de evidencia observada | **Sondas en la máquina de cada miembro** | Reales | Vocabulario cerrado, por diseño |

Las tres cosas que nadie hace y que este diseño aborda:

1. **Estado del equipo derivado de observación, no de declaración.** Es el
   límite que el Manager Agent declara de sí mismo. Nadie lo ha cruzado porque
   nadie tenía un agente en la máquina del trabajador.
2. **Una arquitectura de coste que hace viable observar en continuo.** Un
   coordinador con el modelo en el bucle no es asumible: cinco minutos de
   cadencia son 288 llamadas diarias por persona, haya pasado algo o no.
3. **Coordinación por observación que no es vigilancia laboral.** No es un
   añadido ético al final: es la restricción que decide el vocabulario, la
   topología y quién arranca cada sonda.

Y hay un cuarto punto que conecta con lo ya hecho en Vibi: el reto abierto nº 3
que el Manager Agent declara sin resolver —*«coordinación en equipos ad hoc: la
inferencia rápida de capacidades de nuevos compañeros a partir de interacción
limitada carece de soluciones completas»*— es literalmente
`2026-08-26-especializacion-por-usuario`. El perfil ya infiere de qué sabe cada
uno mirando la máquina.

## Decisiones tomadas

**El coordinador recibe señales sobre el trabajo, nunca sobre la persona.** Esta
es la regla que manda sobre todas las demás. De las cinco sondas que existen,
`archivo`, `proceso` y `web` miran al trabajo; `ventana` y `actividad` miran a
la persona. Las dos últimas **se quedan en el nodo, al servicio de su dueño, y
no publican nada hacia arriba**. La sonda que más diría de alguien es
precisamente la única que el coordinador no recibe.

La única excepción es `presencia`, que sí es sobre la persona: pero es binaria,
derivada, y existe para **evitar** interrupciones, no para permitirlas. Es lo
que ya hace `presencia.py`.

**El nodo publica; el coordinador nunca tira.** Se invierte la arquitectura
habitual de monitorización de empleados. El Vibi personal es el abogado del
miembro, no el ojo de la empresa: decide qué publica y puede callarse. Encaja
con lo que el nodo ya es —marca hacia fuera, corre con el usuario del sistema, y
es de quien lo instaló—.

**Lo que se publica es un vocabulario cerrado de señales tipadas, no texto
libre.** Es la disciplina de `vigilancias.SONDAS` —un `frozenset` validado en
los dos lados «para que un servidor comprometido no invente sondas»— aplicada un
nivel más arriba. Y no es purismo: es la defensa contra el hallazgo de
AgentLeak, que midió que los canales internos entre agentes filtran al 68,8 %
frente al 27,2 % de las salidas finales. Si los Vibis personales se mandan texto
generado por modelos, se hereda esa tasa entera. Lo que no está en el
vocabulario no viaja.

**Topología jerárquica, no entre pares.** Los Vibis personales no se hablan
entre ellos. Hablan hacia arriba y el coordinador reparte. El motivo es
concreto: `nodes.py` dice que *«el agente abre la conexión hacia Vibi, nunca al
revés: así no hay puertos que abrir ni NAT que atravesar»*. Para que dos nodos
se hablasen habría que aceptar conexiones entrantes en la máquina de cada
miembro —puertos abiertos en casa, NAT que atravesar, autenticación N×N—, y se
tiraría justo la propiedad que hace que Vibi se pueda instalar detrás de un
router doméstico. Además, sin un sitio único donde viva el modelo del equipo hay
N vistas divergentes de quién hace qué, que es lo que un coordinador no puede
permitirse.

**El estado del equipo es una hipótesis, no un hecho.** Cada creencia lleva de
dónde salió y cuánta confianza tiene, igual que las afirmaciones del perfil. Y
la misma regla: cuando la observación contradice lo declarado, **gana la
observación**. Lo que se hace pesa más que lo que se dijo.

**La iniciativa tiene presupuesto.** Un asistente que habla cada vez que tiene
algo que decir se convierte en ruido y acaba silenciado. El dato está medido en
`avisos_silencio.py`: en el primer vistazo a un equipo real había ocho
notificaciones acumuladas y ninguna era una persona escribiendo. El coordinador
puede interrumpir a lo sumo N veces por persona y día, y si tiene cinco cosas y
dos fichas, gasta las dos mejores.

**El coordinador propone la vigilancia; el miembro la aprueba.** Nada se pone a
mirar sin que su dueño diga que sí. Es la regla de la entrevista del perfil
—«nada se instala sin aprobación»— y es también la respuesta legal.

**Lo periódico es lo tonto, y lo tonto es gratis.** Ver «Los tres relojes».

## Arquitectura

```
   máquina de Ana            máquina de Bruno           máquina de Dani
  ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
  │ sondas       │          │ sondas       │          │ sondas       │
  │ archivo      │          │ archivo      │          │ archivo      │
  │ proceso      │          │ proceso      │          │ proceso      │
  │ web          │          │ web          │          │ web          │
  │ ─────────────│          │ ─────────────│          │ ─────────────│
  │ ventana      │ no sube  │ ventana      │ no sube  │ ventana      │
  │ actividad    │ ✗        │ actividad    │ ✗        │ actividad    │
  └──────┬───────┘          └──────┬───────┘          └──────┬───────┘
         │ señales tipadas         │                         │
         │ (vocabulario cerrado)   │                         │
         └────────────┬────────────┴─────────────────────────┘
                      ▼
            ┌───────────────────────┐
            │      coordinador      │   creencias con confianza
            │  (core, un solo sitio)│   y procedencia
            └───────────┬───────────┘
                        │
                  iniciativa
             presupuesto + presencia
                        │
                        ▼
              la cara / el chat de quien toque
```

### Archivos nuevos

| Archivo | Responsabilidad |
|---|---|
| `app/equipo.py` | Modelo de datos: equipos, miembros, tareas y creencias con confianza. |
| `app/equipo_senales.py` | El vocabulario cerrado. Validación y normalización, en los dos lados. |
| `app/equipo_coordinador.py` | Qué hacer con una señal. Es donde entra el modelo, una vez por cambio. |
| `app/equipo_iniciativa.py` | Presupuesto de fichas, cola de prioridad y puerta de presencia. Función pura. |

### Archivos que se tocan

| Archivo | Cambio |
|---|---|
| `app/db.py` | Cuatro tablas nuevas. |
| `app/vigilancias.py` | Una vigilancia puede tener destinatario `equipo` además de su dueño. |
| `app/nodes.py` | El nodo publica señales, no solo responde órdenes. |
| `app/presencia.py` | Consulta de disponibilidad desde el coordinador, no solo desde el turno. |
| `app/perfil.py` | Exponer competencias como señal `competencia`. |
| `app/api.py` | Alta de equipo, propuesta y aprobación de vigilancias, panel del coordinador. |
| `agent/` | Publicación de señales derivadas; las sondas ya existen. |

## El vocabulario de señales

Es la pieza central del trabajo. Nueve señales de partida, todas derivables de
sondas que ya existen, y ninguna lleva contenido.

| Señal | Sonda | Parámetros | Qué dice |
|---|---|---|---|
| `avance` | `archivo` | tarea, ruta | Hubo cambios bajo la ruta de la tarea. |
| `sin_avance` | `archivo` | tarea, horas | No hubo cambios en N horas de trabajo. |
| `entregado` | `archivo` | tarea, ruta | Apareció el artefacto que se esperaba. |
| `fallo_repetido` | `proceso` | tarea, veces | El mismo comando falla con el mismo sello de error N veces. |
| `tarea_larga` | `proceso` | tarea, minutos | Un proceso lleva más de lo previsto. |
| `revision_pendiente` | `web` | tarea, url | Algo espera a otra persona. |
| `integracion_rota` | `web` | url | La integración continua está en rojo. |
| `competencia` | — (`perfil`) | área, confianza | De qué sabe cada miembro. |
| `disponible` | — (`presencia`) | — | A quién se puede interrumpir ahora. |

**Lo que una señal nunca lleva:** contenido de archivos, texto de la pantalla,
títulos de ventana, nombres de archivo, pulsaciones, tiempo delante del
ordenador, ni nada que permita reconstruir qué estaba mirando alguien. Una
señal dice *qué le pasa al trabajo*, no *qué está haciendo la persona*.

Ejemplo de lo que sube el nodo de Dani:

```json
{"tarea": 14, "senal": "fallo_repetido", "veces": 15, "desde": 1789..., "nodo": "..."}
```

Y no: *«Dani lleva rato peleándose con un build que no compila»*.

**El tamaño del vocabulario es la variable interesante del trabajo.** A más
señales, mejor coordina y peor privacidad. Nueve es el punto de partida; que sea
el correcto es justo lo que mide el experimento.

## Modelo de datos

```sql
CREATE TABLE IF NOT EXISTS equipos (
    id          TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    creado_en   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS equipo_miembros (
    equipo_id   TEXT NOT NULL REFERENCES equipos(id),
    user_id     TEXT NOT NULL REFERENCES users(id),
    alta_en     REAL NOT NULL,
    PRIMARY KEY (equipo_id, user_id)
);

CREATE TABLE IF NOT EXISTS equipo_tareas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id   TEXT NOT NULL REFERENCES equipos(id),
    titulo      TEXT NOT NULL,
    asignada_a  TEXT REFERENCES users(id),
    abierta_en  REAL NOT NULL,
    cerrada_en  REAL
);

CREATE TABLE IF NOT EXISTS equipo_creencias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id    TEXT NOT NULL REFERENCES equipos(id),
    tarea_id     INTEGER REFERENCES equipo_tareas(id),
    user_id      TEXT REFERENCES users(id),
    clase        TEXT NOT NULL CHECK (clase IN
                     ('estado', 'bloqueo', 'competencia', 'disponibilidad')),
    valor        TEXT NOT NULL,
    procedencia  TEXT NOT NULL CHECK (procedencia IN
                     ('observacion', 'declaracion', 'inferencia')),
    confianza    REAL NOT NULL CHECK (confianza >= 0 AND confianza <= 1),
    vista_en     REAL NOT NULL,
    caduca_en    REAL NOT NULL
);
```

`procedencia` es lo que permite la comparación del experimento: el mismo periodo
de trabajo produce creencias `observacion` y creencias `declaracion`, y se mide
cuál estuvo equivocada más tiempo.

### Umbrales

Números de partida, para ajustar con la primera semana real y no para ser
definitivos:

| Concepto | Valor |
|---|---|
| Presupuesto de iniciativa | 4 fichas por persona y día |
| `sin_avance` | 8 h de reloj descontando la noche del nodo (00:00-08:00 locales) |
| `fallo_repetido` | 5 repeticiones del mismo sello de error |
| `tarea_larga` | 3× la mediana de ese comando en ese nodo |
| Confianza de una creencia por observación | 0,8 |
| Confianza de una creencia por declaración | 0,5 |
| Confianza de una creencia por inferencia | 0,4 |
| Caducidad de una creencia sin refresco | 24 h |
| Cadencia de las sondas | la de `vigilancias.INTERVALO_MINIMO`, nunca menor |

Que la observación entre con 0,8 y la declaración con 0,5 es la regla del
perfil: gana lo que se hace sobre lo que se dice.

## Los tres relojes

La respuesta a «¿esto funciona con acciones periódicas?» es: sí, pero lo
periódico es gratis.

**Reloj 1 — la sonda del nodo. Gratis.** Cada N segundos el nodo mira y compara
un sello con el de la vuelta anterior. Si no cambió, no dice nada: ni modelo, ni
red, ni base de datos. Seis máquinas ocho horas con todo quieto cuestan cero.

**Reloj 2 — el cambio. Barato.** El sello cambió, el nodo publica la señal, el
core la guarda y mira si alguna vigilancia la esperaba. Sigue sin haber modelo:
es un `if`.

**Reloj 3 — el modelo. Ya no es periódico.** Entra en tres casos y solo en tres:
un cambio que alguien esperaba, la revisión periódica —el patrón de
`perfil_observador.py`, unas cuatro llamadas al mes—, o alguien pregunta.

Es el mismo reparto de `avisos.py` y `vigilancias.py`, y por el mismo motivo:
vigilar algo quieto dos horas cuesta cero llamadas; ponerle el modelo al bucle
costaría 1.440.

## La iniciativa

Lo anterior es la parte barata. Lo que hace que el coordinador se sienta vivo es
que hable primero, y ese es el problema de diseño difícil. Cuatro frenos, y tres
ya existen:

1. **Presupuesto diario** por persona (`equipo_iniciativa.py`, nuevo). Cola de
   prioridad; si hay cinco candidatas y quedan dos fichas, salen las dos
   mejores.
2. **Puerta de presencia** (`presencia.py`, hecho). No habla si la persona está
   en una conversación de voz o escribiendo.
3. **Cola de un turno** (`avisos.py`, hecho). Agy lleva una conversación a la
   vez, así que los avisos hacen cola en vez de pisarse.
4. **Lista negra que converge** (`avisos_silencio.py`, hecho). El primer día es
   ruidoso y en unos días queda en unos pocos «esto no me lo digas más».

La estética es la de `vigilancias.py`: **quedarse mirando algo y callarse hasta
que pase**. Estar vivo es sobre todo estar callado; la ilusión no viene de
hablar mucho, sino de que la vez que habla acierte.

### El camino entero, con Dani

1. La sonda `proceso` en el nodo de Dani mira el resultado del build cada 60 s.
   Sello: código de salida más hash de la última línea de error. Idéntico quince
   veces. **Cero llamadas, cero red.**
2. A la vez 15 se cruza el umbral. El nodo publica `fallo_repetido`. **Cero
   modelo.**
3. El coordinador mira presencia: Dani está escribiendo. Espera.
4. Dani para y queda una ficha. Ahora entra el modelo, **una vez**, y decide
   entre las tres salidas que ya tiene `vigilancias.py`: contar, callar o
   intervenir.
5. La cara del companion gira y dice: «llevas quince intentos con el mismo
   error; Carla tocó esto la semana pasada y ahora está libre, ¿le pregunto?».

Nadie escribió un estado, nadie movió un ticket, nadie vio la pantalla de Dani.

## Quién arranca una vigilancia de equipo

**El coordinador propone, el miembro aprueba.** Al abrirse una tarea, el
coordinador deduce qué sondas la seguirían —`archivo` sobre su ruta, `proceso`
sobre su comando de build— y se lo propone a quien la tiene asignada, con la
justificación en una línea y diciendo **qué señal concreta va a publicar**. El
miembro acepta, recorta o rechaza. Una sonda que su dueño no aprobó no corre.

La alternativa —que el coordinador las arranque solo— se descarta: es
exactamente la diferencia entre una herramienta de equipo y una de vigilancia, y
además hace inaplicable el consentimiento que exige el marco legal.

## Seguridad, privacidad y marco legal

**Esto es un sistema de IA de gestión de trabajadores.** El Reglamento de IA de
la UE lo clasifica como **alto riesgo** (Anexo III, punto 4). En España aplican
además el art. 20.3 del Estatuto de los Trabajadores y los arts. 87-90 de la
LOPDGDD. No es una nota al pie: es lo que decide el diseño.

Las cinco restricciones que salen de ahí y que ya están arriba:

- El coordinador recibe señales sobre el trabajo, nunca sobre la persona.
  `ventana` y `actividad` no publican.
- El vocabulario es cerrado y tipado. Lo que no está en él no viaja.
- El nodo publica, el coordinador nunca tira.
- Cada sonda la aprueba su dueño, y puede retirarla.
- El miembro puede leer todo lo que su nodo ha publicado sobre él. Una creencia
  que no se puede ver no se puede corregir; es la regla del perfil.

**Lo que este sistema no puede hacer, por construcción y no por política:** medir
tiempo delante del ordenador, reconstruir qué aplicación usó alguien, puntuar
productividad, comparar miembros entre sí. No hay señal en el vocabulario que lo
permita.

El marco teórico es la **integridad contextual** (Nissenbaum), que es sobre lo
que PiSAs construye su banco de pruebas: qué señal puede cruzar de un miembro al
coordinador, y de ahí a otro miembro.

## Errores

| Situación | Comportamiento |
|---|---|
| El nodo de un miembro se desconecta | Sus creencias caducan a las 24 h y el coordinador dice que no sabe, en vez de asumir el último estado. |
| Un miembro retira una sonda | La creencia asociada baja a `declaracion` si la hay, o desaparece. Nunca se reactiva sola. |
| El nodo publica una señal fuera del vocabulario | Se descarta y se registra. Es el mismo trato que una sonda inventada en `vigilancias.py`. |
| Señal sin tarea asociada | Se guarda sin `tarea_id`; sirve para disponibilidad y competencia, no para estado. |
| El presupuesto de iniciativa se agota | Lo pendiente espera al día siguiente, salvo `integracion_rota`, que es de equipo y no de persona. |
| Equipo de un solo miembro | Vibi funciona como hoy. Es el baseline del experimento. |
| El coordinador falla al juzgar un cambio | La señal queda guardada sin creencia. Un estado viejo es peor que uno actual y mucho mejor que uno inventado. |

## Pruebas

- **`equipo_senales`**: vocabulario cerrado, tabla de casos. Señal válida, señal
  fuera del vocabulario, señal con parámetros de más, señal con contenido
  prohibido. Sin base de datos ni red.
- **`equipo_iniciativa`**: función pura. Presupuesto agotado, presencia ocupada,
  cola con empate, prioridad de equipo sobre prioridad personal.
- **`equipo_coordinador`**: base de datos sembrada con señales sintéticas; se
  comprueba que las confianzas y las caducidades se mueven como marcan los
  umbrales. **Contra una base de pruebas, nunca contra la real** — ya ocurrió
  que 600 de 683 filas del histórico las escribió pytest.
- **Prueba de no fuga**: se recorre el vocabulario entero y se comprueba que
  ninguna señal puede transportar contenido. Es la prueba que defiende la
  afirmación de privacidad, así que es la que no puede faltar.

## Evaluación

Esta sección existe porque el trabajo es también un TFG y la evaluación es la
contribución, no un añadido.

**Hipótesis:**

- **H1** — El estado derivado de observación está equivocado **menos tiempo**
  que el declarado por las personas. Se mide el desfase: minutos en que la
  creencia registrada no coincidía con lo que realmente pasaba, reconstruido a
  posteriori.
- **H2** — Coordinar por observación reduce las **interrupciones por persona y
  día** frente a coordinar preguntando, para el mismo número de bloqueos
  resueltos.
- **H3** — El coste en llamadas al modelo por equipo y día crece con **el número
  de cambios**, no con el número de miembros ni con el tiempo transcurrido.

H3 es la que no necesita equipo real: se mide con trazas y es una afirmación de
sistemas, comprobable sola. Es también el seguro del trabajo si el estudio de
campo se complica.

**Métricas:** desfase del estado (minutos), interrupciones por persona y día,
llamadas al modelo por equipo y día, y tasa de aceptación de las vigilancias
propuestas —esta última reutiliza `perfil_metricas.tasa_de_aceptacion` tal
cual—.

**Ablación**, con la estructura de la del perfil: sistema completo / sin
observación (solo auto-informe, que es el baseline de Asana y del Manager
Agent) / sin presupuesto de iniciativa / sin puerta de presencia. Que
`equipo_iniciativa` sea puro hace que cada configuración sea un parámetro y no
una rama de código.

**Diseño experimental.** Tres salidas, de más barata a más cara:

1. **Reproducción.** Se instrumenta trabajo individual real, se capturan las
   trazas y se reproducen contra los dos coordinadores. Da H1 y H3. No da H2.
2. **Simulación con trazas reales.** El enfoque de MA-Gym pero alimentando el
   simulador con trazas de escritorio capturadas, en vez de con trabajadores
   sintéticos. Es en sí una crítica metodológica al banco de referencia.
3. **Campo.** Equipo pequeño real, 3-5 personas, 2-3 semanas, con
   consentimiento informado. Es la única que da H2 de verdad, y el
   consentimiento produce además el material del capítulo legal.

Se planifica sobre 1 y 3, con 2 como respaldo si no hay equipo disponible.

## Fases

| Fase | Qué entra | Qué se puede medir al acabarla |
|---|---|---|
| 1 | `equipo_senales.py` y las cuatro tablas. Vocabulario puro y testeado. | Nada todavía; es el cimiento. |
| 2 | El nodo publica. `vigilancias.py` con destinatario `equipo`. | Coste: H3 ya es medible. |
| 3 | `equipo_coordinador.py`: creencias con confianza y caducidad. | Desfase del estado: H1. |
| 4 | `equipo_iniciativa.py`: presupuesto, cola y presencia. | Interrupciones: H2. |
| 5 | Panel del coordinador y aprobación de sondas en la interfaz. | Tasa de aceptación. |
| 6 | Instrumentación del experimento y estudio de campo. | Todo, con ablación. |

Las fases 1 a 3 no necesitan equipo real y valen por sí solas.

## Fuera de alcance

- **Sustituir a Jira o a Asana.** No se hace gestión de proyectos: no hay
  planificación, ni estimaciones, ni informes. El coordinador sostiene un estado
  y habla cuando toca.
- **Asignación automática de tareas.** El coordinador propone a quién preguntar;
  no reparte trabajo. Repartir es una decisión de personas.
- **Evaluación de desempeño.** Explícitamente y por construcción: no hay señal
  en el vocabulario que lo permita, y no se va a añadir.
- **Comunicación entre nodos.** Descartada arriba con argumento. La topología es
  jerárquica.
- **Coordinación entre equipos.** Un equipo, un coordinador.
- **La sonda `ventana` al servicio del coordinador.** Sigue existiendo para su
  dueño y no publica.

## Riesgos conocidos

**La evaluación necesita un equipo real y puede no haberlo.** Es el riesgo
principal del trabajo, no un detalle. Mitigado por el reparto de hipótesis: H3
se mide sola, H1 se mide por reproducción, y solo H2 exige campo. Si no hay
equipo, el trabajo se sostiene con dos hipótesis de tres y lo dice.

**El vocabulario cerrado puede resultar demasiado pobre para coordinar.** Nueve
señales sin contenido quizá no basten para que el coordinador diga algo útil.
Es una posibilidad real y **es justo lo que mide el experimento**: si sale que
no basta, el resultado es negativo, publicable y honesto, y acota cuánta
privacidad cuesta cuánta coordinación.

**El marco legal es alto riesgo y eso tiene consecuencias.** Un sistema de
gestión de trabajadores bajo el Anexo III del Reglamento de IA arrastra
obligaciones de documentación, transparencia y supervisión humana. Para un TFG
es material de capítulo, pero condiciona cualquier uso más allá del
experimento, y hay que decirlo en la memoria.

**`apps_con_receta` es global y no tiene `user_id`.** Ya está anotado como
límite en `perfil_observador.py`. Si la señal `competencia` se alimenta de
recetas, ese límite se hereda: habría que añadir la columna antes de la fase 3.

**El campo se mueve rápido.** El Manager Agent es de octubre de 2025 y MA-Gym
sigue creciendo; Asana y Rovo publican cada trimestre. La contribución se ancla
en la evaluación y en la restricción de privacidad, no en la novedad,
precisamente porque la novedad puede caerse y un experimento medido no.
