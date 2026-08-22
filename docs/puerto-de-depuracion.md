# El puerto de depuración: hablarle a una aplicación por dentro

Casi todo el escritorio moderno es Chromium con un marco alrededor. Medido en
esta máquina: Discord y VS Code son Electron, WhatsApp y Raycast son WebView2,
Spotify es CEF, y el navegador es el navegador. Todos hablan el protocolo de
las herramientas de desarrollo, y por él se les puede preguntar y mandar hacer
cosas **con la ventana detrás, minimizada o tapada**, porque no pasa por el
ratón ni por el teclado ni por el foco.

Lo que se gana frente al árbol de accesibilidad, medido el 21 de agosto de 2026
contra WhatsApp:

| | Árbol (`ui.snapshot`) | Por dentro (`web.evaluar`) |
|---|---|---|
| Leer la ventana | 251 ms (mediana) | **31 ms** |
| Ida y vuelta completa | — | 47 ms |
| Le roba el foco | a veces | nunca |

Y lo que más importa no es la velocidad: por DOM se resuelve en **una** llamada
lo que por el árbol son cuatro turnos de modelo, a 4 s de mediana cada uno.

## El problema, y por qué no es el que parece

Un Chromium solo acepta esto si arrancó con `--remote-debugging-port`. El
puerto se abre al arrancar el proceso y **no se puede abrir después**. Hasta
aquí, la única vía era que Vibi lanzara la aplicación él mismo, lo que dejaba
fuera todo lo que el usuario ya tenía abierto.

Y las aplicaciones de la Microsoft Store —WhatsApp, Spotify— se lanzan por el
shell y **no admiten argumentos**, así que ni siquiera lanzándolas Vibi.

## La vía que funciona

El runtime de WebView2 no lee sus argumentos extra solo de la línea de
comandos: también los lee **del registro**. Con eso la aplicación arranca
escuchando la abra quien la abra, también la persona desde su menú de inicio.

```
HKCU\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments
  <nombre-del-ejecutable>   REG_SZ   --remote-debugging-port=0
```

Se aplica con `scripts/puerto_de_depuracion.ps1`. Sin argumentos lista qué
aplicaciones WebView2 están vivas y cuáles tienen ya el puerto:

```powershell
.\scripts\puerto_de_depuracion.ps1
.\scripts\puerto_de_depuracion.ps1 -Ejecutable WhatsApp.Root.exe
.\scripts\puerto_de_depuracion.ps1 -Ejecutable WhatsApp.Root.exe -Quitar
```

### Tres cosas que cuestan una tarde cada una

**El nombre del ejecutable no es el obvio.** Para WhatsApp no es
`WhatsApp.exe` sino `WhatsApp.Root.exe`. Con el nombre equivocado no pasa
nada, y no avisa. La fuente fiable es el propio runtime, que declara a quién
sirve:

```powershell
Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" |
  ForEach-Object { if ($_.CommandLine -match '--webview-exe-name=([^\s"]+)') { $Matches[1] } } |
  Sort-Object -Unique
```

**Escribir ahí exige elevación**, aunque sea HKCU: la rama `Policies` está
protegida por ACL. El script pide el UAC solo.

**La variable de entorno no vale para esto.** `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`
puesta a nivel de usuario no llega a una aplicación de la Store: las activa el
broker y no heredan el entorno del usuario. Probado y descartado.

## El puerto es efímero a propósito

Se pide `--remote-debugging-port=0`, no un número fijo. Uno fijo es adivinable
por cualquiera que pruebe los de siempre —9222, 9229—; este no se sabe hasta
leerlo. La aplicación lo publica al arrancar en su perfil:

```
%LOCALAPPDATA%\Packages\<paquete>\LocalCache\EBWebView\DevToolsActivePort
```

`web_apps.descubrir_webview2()` lo lee de ahí, y cuesta 16 ms escaneando los
160 paquetes de esta máquina.

## Qué tiene delante quien quiera entrar

Medido contra el puerto abierto, no supuesto:

| Vector | Resultado |
|---|---|
| Otra máquina de la red o la VPN | **No alcanzable** — escucha solo en `127.0.0.1` |
| Web con `fetch` al endpoint HTTP | Responde, pero **CORS impide leer** la respuesta |
| Web haciendo DNS rebinding (`Host:` falso) | **Rechazado, 500** |
| Web abriendo el WebSocket de CDP | **Rechazado, 403** por el `Origin` |
| Proceso local del propio usuario | **Permitido** |

El último es el riesgo que queda y no tiene arreglo dentro de CDP: el
protocolo no se autentica. Conviene ponerlo en perspectiva —un proceso que ya
corre como el usuario puede leerle el perfil entero de la aplicación, la sesión
incluida, sin pasar por aquí— pero no lo hace cero: por CDP es más fácil y más
silencioso. Es el precio de la vía rápida, y se paga por aplicación, solo en
las que compensa.

Por eso **no se abre el puerto a todo lo que se pueda**. `SearchHost.exe` es el
buscador del propio Windows y `vibi-companion.exe` es la ventana de Vibi: las
dos son WebView2 y a ninguna le hace falta, así que se quedan sin puerto.

## Cómo comprobar que sigue en pie

```powershell
.\scripts\puerto_de_depuracion.ps1     # qué hay puesto
```

```python
from vibi_node import web_apps
web_apps.descubrir_webview2()          # {'whatsappdesktop': 59500}
```

Si `descubrir_webview2()` vuelve vacío con la aplicación abierta: mira que el
nombre del ejecutable en el registro sea el que declara `--webview-exe-name`, y
que la aplicación se haya reiniciado después de ponerlo.
