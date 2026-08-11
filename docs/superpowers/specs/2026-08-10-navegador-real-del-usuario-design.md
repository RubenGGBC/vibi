# Morgana navega en el navegador del usuario

Fecha: 2026-08-10

## El problema

Morgana ya navega delante del usuario, pero navega como una desconocida.

`browser_mcp.py` levanta el MCP de Playwright con `--browser chrome
--user-data-dir <morgana-playwright>`: un Chrome recién estrenado, con un perfil
propio que se creó en agosto y que no ha iniciado sesión en nada. Cada vez que
hay que entrar en un sitio —el correo, un panel, cualquier cosa detrás de un
login— la sesión no está, y Morgana se queda en la puerta.

El perfil aparte no fue capricho. Chrome no deja dos instancias sobre el mismo
directorio de perfil, así que compartir el de diario significaba no poder
navegar mientras Morgana navega. La consecuencia no buscada es que Morgana
trabaja en un navegador que no es el del usuario, en una ventana que no es la
suya, sin nada de lo que él ya tiene abierto.

Lo que se pide es lo contrario: que abra una pestaña en **su** navegador, con
**su** usuario, o que lo abra si estaba cerrado, y que haga ahí lo que se le ha
dicho.

## Qué se construye

Playwright deja de **lanzar y poseer** un navegador y pasa a **engancharse** al
del usuario por CDP.

El agente de nodo se asegura de que Opera GX está en pie con un puerto de
depuración, y arranca el servidor MCP con `--cdp-endpoint` en vez de
`--browser`/`--user-data-dir`. A partir de ahí Playwright ve las pestañas
reales, abre las suyas al lado y trabaja con las sesiones que el usuario ya
tiene iniciadas.

Cambia también el reparto de vidas. Hoy el navegador es de Morgana y muere con
la sesión MCP —de ahí el viejo síntoma de «no hay ventana, parecerá que va en
headless»—. A partir de ahora el navegador es del usuario y sobrevive a todo;
lo único de Morgana es el servidor MCP.

### Por qué Opera GX y no el navegador por defecto

El navegador por defecto del usuario es Zen, un derivado de Firefox. Firefox no
habla CDP y Playwright no puede engancharse a una instancia suya en marcha, así
que el navegador que se pilota es el secundario, Opera GX, y va **declarado en
configuración, no autodetectado**. Detectarlo del registro daría Zen y no habría
forma de cumplir la promesa.

### Alternativas descartadas

- **Apuntar `--user-data-dir` al perfil real de Opera.** Choca con el bloqueo de
  perfil de Chromium: con Opera abierto, el lanzamiento falla. Es justo el
  problema que hizo nacer el perfil aparte.
- **Copiar el perfil a un directorio propio.** Arranca con las sesiones
  iniciadas y sin conflicto, pero es una foto fija: los logins nuevos y los
  marcadores no se reflejan, y sigue sin ser la ventana del usuario.
- **Modo `--extension` de Playwright.** Es el camino que Microsoft recomienda
  para esto y no exige reabrir el navegador, pero solo está soportado en Chrome
  y Edge; en Opera obliga a instalar antes el complemento «Install Chrome
  Extensions», y probablemente a confirmar la conexión con un clic en cada
  sesión. Queda como plan B si el CDP diera problemas.

## Lo que se midió antes de diseñar

Todo esto está comprobado contra el Opera GX del usuario, no supuesto:

- **Opera GX 133 es Chromium 149 y aun así abre el puerto de depuración sobre el
  perfil por defecto.** Chromium bloquea eso desde la 136; Opera no aplica la
  restricción. Es la premisa de la que cuelga el diseño entero, y sin
  comprobarla no habría diseño.
- **Enganchado a Opera, el MCP responde en centenares de milisegundos**: 224 ms
  en conectar, 197 ms en abrir pestaña nueva, 192 ms en navegar. La pestaña
  nueva se abre al lado de las del usuario sin tocar ninguna.
- **Una pestaña sin renderizador cuelga la conexión entera durante 30 s.** Dos
  de las siete pestañas abiertas no contestaban a ningún comando CDP —ni
  `Page.enable`, ni `Runtime.enable`, ni `Network.enable`— y con eso bastaba
  para que `connectOverCDP` no terminara nunca. No es configuración: en
  `CRBrowser.connect`, Playwright cierra con
  `await browser._waitForAllPagesToBeInitialized()`, sin excepción ni opción
  para saltárselo. Al despertar esas dos pestañas, la conexión pasó de 30 s de
  timeout a 224 ms.

De por qué esas dos pestañas estaban mudas no hay certeza. El limitador de RAM
de Opera GX está desactivado (`gx.limiters.ram.enabled = false`), así que la
hibernación de GX queda descartada; lo más probable es la restauración perezosa
de sesión de Chromium, que crea la pestaña sin cargar su renderizador hasta que
se activa. El remedio es el mismo en los dos casos, así que la incertidumbre no
bloquea: se cubre despertándolas.

## Piezas

### `agent/morgana_node/navegador_real.py`

Módulo nuevo. Una sola responsabilidad: **dejar el navegador del usuario en pie
con CDP listo y decir dónde escucha**. No sabe nada de MCP ni de Playwright.

```
asegurar(puerto, ejecutable, timeout) -> {"endpoint": str, "arrancado_ahora": bool}
```

Pasos:

1. ¿Contesta `http://127.0.0.1:<puerto>/json/version`? Si sí, ya está: se
   reaprovecha, igual que ya se hace con el puerto del servidor MCP.
2. Si no contesta y **no** hay proceso del navegador, se lanza con
   `--remote-debugging-port=<puerto>`, desligado de este proceso, y se espera a
   que el endpoint responda.
3. Si no contesta y **sí** hay proceso, es un navegador que el usuario abrió por
   su cuenta y no tiene puerto. Se cierra y se reabre con puerto (ver abajo).
4. Pre-vuelo de pestañas.

Errores tipados —`NavegadorNoEncontrado`, `NavegadorNoArranca`— para que
`capabilities.py` los traduzca a mensajes que el usuario entienda, como ya hace
con `BrowserMCPError`.

Se puede probar entero sin navegador: solo depende de un puerto, una ruta de
ejecutable y unas respuestas HTTP.

### Cerrar y reabrir Opera cuando le falta el puerto

Decisión del usuario, tomada sabiendo el coste: Morgana cierra Opera y lo vuelve
a abrir con el puerto, en vez de limitarse a avisar.

Dos cautelas que van en el código, no en la documentación:

- **Cierre limpio, nunca forzado.** Se pide el cierre de las ventanas y se
  espera; nada de matar el proceso. Un cierre limpio deja que Opera guarde la
  sesión y la restaure al reabrir. Si a los ~15 s sigue vivo, se abandona con un
  error claro en vez de forzar: un `kill` aquí se lleva por delante lo que el
  usuario tuviera a medias.
- **Solo cuando hace falta.** El reinicio se dispara al pedir el navegador para
  una sesión, no al arrancar el agente ni por mantenimiento.

Aun con cierre limpio, lo que no sobrevive es lo que no está en la sesión: un
vídeo a medias, un formulario sin enviar. Queda escrito aquí para que dentro de
seis meses no parezca un descuido.

### Pre-vuelo de pestañas

`/json/list`, y para cada objetivo de tipo `page` un `/json/activate/<id>`;
al terminar se devuelve el foco a la pestaña que estaba delante. Todo por HTTP
plano: no hacen falta WebSockets ni dependencias nuevas en el agente.

Es la pieza menos obvia del diseño y la que más falta hace. Sin ella, el fallo
que ve el usuario es que Morgana «no navega» y tarda 30 s en decirlo, con un
error de Playwright que no señala a ninguna pestaña concreta.

### `agent/morgana_node/browser_mcp.py`

Cambia poco y a propósito: sigue siendo el módulo que mantiene el servidor MCP
en pie.

- `comando()` acepta un modo. En `cdp` emite `--cdp-endpoint <endpoint>` y no
  emite `--browser` ni `--user-data-dir`. En `perfil` emite lo de hoy.
- `--output-dir` y `--allowed-hosts` no cambian: las capturas siguen yendo al
  directorio de Morgana y el 403 por `Host` desconocido sigue siendo el mismo
  riesgo de siempre.
- El directorio `morgana-playwright` deja de ser un perfil de navegación y se
  queda como lo que ya era además: el sitio de `servidor.log` y de las salidas.

### El interruptor de modo

`PLAYWRIGHT_MCP_MODE` con dos valores, `cdp` (por defecto) y `perfil` (el
comportamiento actual). El modo viejo se mantiene entero como repliegue: si un
día Opera cambia de opinión sobre el puerto de depuración, se cambia una
variable y se sigue navegando.

Configuración nueva en `app/config.py` y `.env.example`:

- `PLAYWRIGHT_MCP_MODE=cdp`
- `PLAYWRIGHT_MCP_CDP_PORT=9333`
- `PLAYWRIGHT_MCP_BROWSER_PATH=` — ruta al `opera.exe` del usuario.

Viajan del servidor al nodo por la capacidad `browser.mcp`, por el mismo camino
por el que ya viajan `puerto`, `navegador`, `hosts` y `bind`.

### Reglas del prompt

`REGLAS_NAVEGADOR` en `antigravity_chat.py` describe hoy un navegador anónimo.
Pasa a decir tres cosas que cambian lo que el modelo hace:

- Es el navegador del usuario, con sus sesiones ya iniciadas: no hay que buscar
  formularios de login ni pedir credenciales.
- Se abre pestaña nueva para trabajar.
- No se cierran las pestañas del usuario.

### Procedencia

`playwright` se añade a `SERVIDORES_EXTERNOS` en `agy_mcp_config.py`, junto a
Exa y el MCP del ordenador.

El texto de una web siempre lo escribió un desconocido, pero hasta ahora ese
desconocido hablaba con un navegador sin sesiones y lo peor que podía conseguir
era engañar al modelo con contenido. Con el perfil real, una instrucción colada
en una página se ejecuta dentro de las cuentas del usuario. La marca de
procedencia es lo que ya se le aplica a un correo o a un PDF descargado; el
salto al perfil real es lo que la hace necesaria aquí.

## Seguridad

Hay que decirlo claro porque es un salto real respecto a lo de hoy: el puerto de
depuración escucha en `127.0.0.1` y **no pide credenciales**, y quien lo alcance
controla el navegador del usuario con todas sus sesiones iniciadas. Antes, quien
alcanzara el puerto del MCP se encontraba un Chrome vacío; ahora se encuentra su
correo.

Se acepta a sabiendas, en la misma línea que el resto del sistema, y con la
misma frontera: `127.0.0.1`, sin exponer a la red. Cualquier proceso local
llega; las páginas web no, y eso depende de una cosa concreta.

**`--remote-allow-origins=*` no se pasa nunca.** Chromium rechaza por defecto
los WebSocket de CDP que llegan con un `Origin` de página, y ese rechazo es
justo lo que impide que una web que estés visitando se ponga a pilotar tu
navegador. El comodín lo desactiva para todos los orígenes. Durante el diseño se
lanzó Opera con `--remote-allow-origins=*` y por eso el enganche está probado
solo con el comodín puesto; queda por confirmar en implementación que Playwright
conecta sin él, cosa que debería, porque conecta desde Node y no manda `Origin`.
Si resultara que hace falta, va el origen exacto, nunca `*`.

## Pruebas

- **`navegador_real`, con un servidor HTTP falso** que imite `/json/version`,
  `/json/list` y `/json/activate`. Cubre: puerto ya en pie se reaprovecha;
  puerto ausente y sin proceso lanza el ejecutable; pre-vuelo activa cada
  pestaña y devuelve el foco a la original; ejecutable inexistente da
  `NavegadorNoEncontrado`.
- **`browser_mcp.comando`**, que ya se prueba así: que en modo `cdp` aparezca
  `--cdp-endpoint` y no aparezcan `--browser` ni `--user-data-dir`, y que en
  modo `perfil` no cambie nada respecto a hoy.
- **`tests/test_agy_playwright.py`**, al día con los argumentos nuevos de la
  capacidad.
- **Procedencia**, que `playwright` cuente como servidor externo y aparezca en
  las reglas del prompt.

Lo que no se prueba automáticamente es el enganche a Opera de verdad: hace falta
un navegador con ventana. Se verifica a mano con el arnés que ya se usó para
diseñar esto, hablando MCP por stdio contra `--cdp-endpoint`.

## Fuera de alcance

- El modo `--extension`, que queda documentado como plan B.
- Autodetectar el navegador por defecto: hoy daría Zen, que no sirve.
- Firefox y Zen. Mientras no hablen CDP, no entran.
- Que el modo `cdp` funcione con un nodo en otra máquina distinta de la del
  contenedor. El puerto de depuración se queda en `127.0.0.1` y punto.
