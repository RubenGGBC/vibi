# Motor Antigravity por la API del language server

**Fecha:** 6 de agosto de 2026
**Estado:** diseño aprobado, pendiente de implementar

## El problema

Morgana habla con Gemini pilotando la CLI `agy` dentro de un pseudoterminal.
Funciona, pero arrastra tres pegas que vienen todas del mismo sitio: que
estamos fingiendo ser una persona delante de un terminal.

1. **`agy` exige un terminal de verdad.** Por eso hace falta ConPTY, y por eso
   el motor solo corre en Windows: `pywinpty` no existe en Linux ni en Mac.
2. **La CLI no avisa de cuándo termina.** El turno se da por cerrado tras
   `TURN_QUIET_SECONDS` sin novedades en pantalla ni en disco. Es un peaje que
   se paga en cada respuesta, y aun así puede cortar a media frase.
3. **No hay streaming.** La respuesta se lee del SQLite de `agy`, donde el
   texto aparece de golpe al terminar. La cara se queda muda hasta entonces.

A eso se suma que `agy_trajectory.py` recorre a mano el protobuf sin esquema
de un SQLite interno de Google, que es lo más frágil del motor.

La vía obvia —`agy -p`, su modo para scripts— no sirve: cuesta **39 s por
turno**, de los cuales 30,5 s son un refresco de cuota forzado
(`doRefreshQuota`) que se paga en cada arranque del proceso. `--conversation`
preserva el contexto pero paga el peaje igual.

## El hallazgo

`agy.exe` no es un programa monolítico: **levanta dentro de sí un language
server** que escucha en `localhost`, y la interfaz de terminal es solo un
cliente suyo. Ese servidor habla **Connect RPC con JSON plano y sin
autenticación**.

Es decir: se puede hablar con Gemini desde Python con un `POST` normal, sin
fingir un terminal, sin parsear pantallas y sin tocar el SQLite.

### Lo verificado

| Método | Para qué |
|---|---|
| `StartCascade` | Crea la conversación y devuelve `cascadeId` |
| `SendUserCascadeMessage` | Manda el turno |
| `StreamAgentStateUpdates` | Streaming del texto, deltas cada ~100 ms |
| `GetCascadeTrajectorySteps` | Pasos con `type` y `status` (fin de turno) |
| `ForceStopCascadeTree` | Corta la respuesta en curso |
| `GetAvailableModels` | Modelos de la cuenta, con su cuota |

### Lo medido

Con `agy` vivo y la sesión caliente, usando `gemini-3.6-flash-low`:

| | Hoy (PTY + SQLite) | Diseño nuevo | Haiku |
|---|---|---|---|
| Arranque | 28 s | **~5,5 s**, una vez | 3,4 s |
| Turno completo | 1,7 – 2,2 s | **1,1 s** | 1,4 – 2,3 s |
| Fin de turno | sondeo de silencio | estado explícito | explícito |
| Streaming | no | sí, deltas ~100 ms | sí, ~75 ms |

**El time to first token no está medido.** Los intentos dieron 1,05 s clavado
en todas las variantes, lo que delata el método: el stream vuelca su estado al
abrirse y al primer tick, así que lo que se cronometraba era la respuesta del
turno anterior. Para medirlo de verdad hay que comparar el texto entrante
contra el previo y cronometrar el primer trozo **distinto**. Queda pendiente,
y es el número que más importa para la voz.

Cuidado también con el modelo: medir con Gemini 2.5 Flash da 4–5,6 s por turno
y lleva a conclusiones equivocadas. Las medidas válidas son con el modelo real
del usuario.

## La arquitectura

El PTY **se queda, pero degradado a encender el motor**. Ya no es el canal de
conversación, que era lo frágil. Mantiene un proceso `agy` vivo para que el
language server exista; todo lo demás va por HTTP.

```
chat.py  ──elige motor──>  antigravity_chat.py
                                │
                    ┌───────────┴───────────┐
                    │                       │
              agy_process.py           agy_client.py
         (arranca y vigila agy)   (Connect-JSON al servidor)
                    │                       │
              PTY: winpty (Win)        StartCascade
                   pty (Unix)          SendUserCascadeMessage
                    │                  StreamAgentStateUpdates
                    └──> localhost:<puerto aleatorio> <──┘
```

### Componentes

**`agy_process.py`** — el proceso vivo. Lanza `agy` en un pseudoterminal,
vacía su salida para que no se bloquee, y saca el puerto del language server
del `--log-file`. Expone `puerto()` y poco más. No sabe nada de conversaciones.
En Windows usa `winpty`; en Linux y Mac, el módulo `pty` de la biblioteca
estándar, que es más simple.

**`agy_client.py`** — el cliente de la API. Una función por método usado, más
el consumo del server-stream de Connect (sobres de 1 byte de banderas + 4 de
longitud + JSON). No sabe nada de Morgana: recibe un puerto y devuelve datos.

**`antigravity_chat.py`** — el motor, que ya cumple el contrato `ChatEngine`.
Se queda con la gestión de sesiones por conversación, el candado, y la
traducción de los pasos de Cascade a eventos de Morgana (`fragmento_chat`,
`progreso_chat`). Pierde todo el código de tecleo y de espera por silencio.

**`agy_trajectory.py`** — **se borra entero.** Con él, el parseo del protobuf
sin esquema y la dependencia del formato del SQLite.

### El turno, de principio a fin

1. Si no hay sesión para la conversación, se arranca `agy` y se espera al
   puerto (~3,3 s). El precalentado al arrancar el servidor sigue teniendo
   sentido y ahora cuesta mucho menos.
2. La conversación la crea la CLI con el primer turno tecleado. Su `cascadeId`
   se obtiene con `GetAllCascadeTrajectories`.
3. Se abre `StreamAgentStateUpdates` **antes** de mandar el turno.
4. **El turno se teclea por el PTY**, no se manda por la API.
5. Del stream van llegando trozos en
   `…stepsUpdate.steps[N].plannerResponse.modifiedResponse`. Cada crecimiento
   se emite como `fragmento_chat`, y la cara puede locutar sobre la marcha.
6. El turno se cierra cuando el paso pasa a `DONE`. Sin sondear silencios.

#### Por qué se teclea en vez de usar `SendUserCascadeMessage`

Medido en la misma sesión y conversación, alternando ambos caminos con los
mismos prompts:

| Vía de envío | Coste del envío | Turno completo |
|---|---|---|
| `SendUserCascadeMessage` | 2,07 s (8 muestras, 2,05–2,09) | 3,1 – 3,2 s |
| Tecleado por el PTY | 0,00 s | **1,1 s** |

`SendUserCascadeMessage` cuesta dos segundos fijos que no se han conseguido
quitar: no es el modelo, no es la red y **no es el campo `blocking`**, que se
probó a `false` sin ningún efecto. Como el PTY hace falta igualmente para
mantener el proceso vivo, teclear sale gratis.

La API se sigue usando para todo lo demás: leer la respuesta, saber cuándo
termina y cortar un turno (`ForceStopCascadeTree`).

**Lo que esto conserva del problema original:** el tecleo mantiene el fallo
intermitente del arranque, cuando la CLI aún inicializa y se come los
caracteres. Se mitiga esperando a que el language server responda antes de
escribir, en vez de contar segundos de silencio.

### El modelo

Va en `cascadeConfig.plannerConfig.planModel`, y **tiene que ser el enum**, no
el nombre legible: `plannerConfig.modelName` con `gemini-3.6-flash-low` arranca
el turno pero no produce texto.

El mapeo nombre→enum no se puede sacar del binario. Se resuelve al vuelo: se
manda un turno, se lee `modelUsage.model` del paso ejecutado y se cachea.
Conocido de antemano: `gemini-3.6-flash-low` = `MODEL_PLACEHOLDER_M73`.

Ajustes guarda el nombre legible (los que da `agy models`), que es lo que el
usuario entiende.

### Cuando algo falla

Se mantiene el `_run_with_fallback` que ya existe: si el motor se cae, contesta
Claude y se avisa en el mensaje. Los casos nuevos que hay que cubrir:

- `agy` no instalado o sin login → `AntigravityUnavailable`, contesta Claude.
- El puerto no aparece en el plazo → se mata el proceso y se reintenta una vez.
- El proceso muere a media conversación → se detecta al fallar la llamada, se
  reabre la sesión y se reintenta el turno una sola vez.
- Un método cambia de forma tras una actualización de `agy` → la llamada
  devuelve 4xx/5xx con mensaje legible; se registra y se cae a Claude.

Este último es el riesgo asumido: es una API interna y `agy` se actualiza solo.
El cliente y el servidor viajan en el mismo binario, así que no se
desincronizan entre sí, pero un cambio de campos llega sin avisar.

## Pruebas

- `agy_client.py` se prueba contra un servidor HTTP de mentira que devuelve
  respuestas grabadas de las reales, incluidos los sobres del stream. Sin
  tocar `agy`.
- `agy_process.py` se prueba con un ejecutable falso que escribe un log con la
  línea del puerto y se queda vivo.
- El motor se prueba con el cliente sustituido, comprobando que los deltas se
  convierten en `fragmento_chat` y que el turno cierra en `DONE`.
- Los tests existentes de `test_antigravity_chat.py` se reescriben: los que
  cubren tecleo y espera por silencio dejan de tener sentido.

Nada de esto necesita red ni la CLI instalada.

## Lo que apareció al implementarlo

Tres cosas que el diseño no preveía y que solo salieron al probar contra el
`agy` real. Las tres estaban a punto de llegar a producción:

1. **El stream vuelca el estado al abrirse**, con la respuesta anterior ya
   marcada como `DONE`. Como el cliente cortaba al primer `DONE`, el turno se
   cerraba antes de empezar y devolvía lo que Morgana ya había dicho. Se
   descarta pasando `skip_text` con la respuesta previa, y el descarte va en
   el cliente: hacerlo en el motor no llegaba a tiempo, porque el generador ya
   había terminado.

2. **Ese estado trae todos los turnos de la conversación**, no solo el último.
   Quedarse con el primer paso de respuesta devolvía siempre la presentación.
   Hay que recorrer los pasos del final hacia el principio.

3. **El orden importa**: si se teclea antes de abrir el stream, la respuesta
   se pierde. Por eso el stream se conecta al llamar a `stream_updates`, y no
   perezosamente al primer `next`, y el turno se teclea después.

Y una cuarta que confirma lo frágil que es el arranque: **el puerto aparece
antes de que la interfaz acepte entrada**. La CLI sigue resolviendo el modelo
un par de segundos más y se come lo que se teclee. Se espera a que el log deje
de crecer, que es señal más fiable que el silencio en pantalla, pero como el
arranque no siempre tarda lo mismo hay además una red: si la conversación no
aparece a media espera, se vuelve a teclear.

### Medido ya con el motor montado

Tres turnos seguidos contra el `agy` real, con `gemini-3.6-flash-low`:

| Turno | Primer trozo | Turno completo | Caracteres |
|---|---|---|---|
| 1 | 1,61 s | 1,62 s | 263 |
| 2 | 0,92 s | 0,94 s | 272 |
| 3 | 0,99 s | 1,05 s | 383 |

Arranque hasta poder hablar: **~13 s** (10,9 s el proceso y la espera a que la
interfaz esté lista, más la presentación).

Un matiz sobre el streaming: los trozos llegan, pero **muy juntos al final**
—entre el primero y el último pasan centésimas—. O sea que en respuestas
cortas la cara no gana gran cosa por locutar sobre la marcha; el streaming se
nota en las largas. Lo que sí se gana siempre es el fin de turno explícito.

## Fuera de alcance

- **Docker y Mac.** El binario de Linux existe, pero el login sale hoy del
  keyring de Windows. La vía a explorar es `JETSKI_OAUTH_TOKEN`, que aparece
  en el binario. Queda para después: no bloquea nada de lo de arriba, y el
  diseño ya no depende de ConPTY.
- **Las tools de Morgana** con este motor. Requiere exponerlas por MCP.
- **Sustituir el PTY por un modo servidor.** No hay ejecutable suelto del
  language server ni flag conocido que lo arranque solo.
