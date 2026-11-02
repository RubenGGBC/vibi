# Vibi en Android (versión de prueba)

App para hablar con Vibi desde el móvil con la voz de Codex y controlar la música, las notificaciones y otras apps. El diseño está en `docs/superpowers/specs/2026-11-02-vibi-movil-android-design.md`.

> **Control total y sin límites.** Esta versión no pide confirmación para nada. Un mensaje o una página pueden intentar que Vibi actúe en el móvil, bancos y contraseñas incluidos, o que ejecute comandos en tu PC. Úsala sabiéndolo y, si algo va mal, pulsa **Parar** o revoca el dispositivo desde Vibi.

## 1. Preparar el servidor

En el ordenador que hará de servidor:

```powershell
pip install -r requirements.txt   # añade ytmusicapi
codex login                       # si aún no hay sesión
tailscale serve --bg http://127.0.0.1:8000
```

Arranca Vibi con este código y anota la URL HTTPS de Tailscale. Sin el ordenador encendido, sin esa sesión de Codex o sin Tailscale en el móvil no hay voz.

## 2. Compilar e instalar

```powershell
cd android
.\gradlew.bat assembleDebug
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r app\build\outputs\apk\debug\app-debug.apk
```

También puedes copiar `app\build\outputs\apk\debug\app-debug.apk` al móvil y abrirlo. En el Galaxy A25, si One UI lo impide, desactiva el **Bloqueador automático** (Ajustes › Seguridad y privacidad).

## 3. Configurar el móvil

1. Abre Tailscale en el móvil y conéctalo.
2. Abre Vibi y entra con la URL HTTPS, tu usuario y tu contraseña. La contraseña no se guarda.
3. Pulsa cada botón de **Permisos** hasta que todos tengan ✓. Si Android dice «ajuste restringido»: Ajustes › Aplicaciones › Vibi › ⋮ › Permitir ajustes restringidos.
4. Pon música en tu APK de YouTube Music y pulsa **Usar esta app de música**.
5. Pulsa **Encender**. Debe aparecer «conectada al servidor».

Si cambias el micrófono o los activadores, pulsa **Parar** y **Encender** para aplicarlos.

## 4. Activar a Vibi

- **Hablar:** el botón de la notificación fija. Siempre funciona.
- **Cascos:** marca «Botón de los cascos» y prueba la pulsación larga. Si tus TWS piden el asistente de voz, Android debería preguntarte qué app usar: elige Vibi. Es posible que tus cascos o One UI no lo permitan.
- **Palabra «Vibi»:** márcala y pulsa **Encender**. La primera vez descarga un modelo de unos 40 MB.

## 5. Lista de pruebas

| Prueba | Cómo | Objetivo |
|---|---|---|
| Voz | «Hablar» y una pregunta cualquiera, con Maple | Suena Maple |
| Bloqueado | Repetir con la pantalla apagada | Funciona |
| Música | Pausa, sigue, siguiente, «¿qué suena?», volumen | < 2 s |
| Canción concreta | «Pon…», desbloqueado y bloqueado | < 4 s |
| Notificaciones | Mandarte un mensaje, leerlo, responderlo, descartarlo | Funciona bloqueado, salvo si la app exige desbloquear |
| Otra app | «Abre Ajustes y entra en Batería» | Funciona desbloqueado; bloqueado, Vibi explica por qué no |
| PC | Pedir una tarea en el ordenador | Llega y avisa al móvil al terminar |
| Escritorio | Decir «Vibi» al PC durante una llamada del móvil | La llamada sigue |
| Red | Cambiar de wifi a datos durante una llamada | Cuelga limpio y la música vuelve |
| Fin de llamada | Quedarse callado | Cuelga a los 10 s |
| Micrófono | Comparar cascos y móvil con música | Anotar calidad de música y si te oye |
| Palabra | Una sesión con música y ruido | Anotar falsos despertares |
| Batería | Una hora de gimnasio | Anotar el consumo |

Tiempos objetivo: activación a «ping» < 300 ms; activación a escuchar < 2 s.

Al terminar, pulsa **Copiar medidas** y pégalas en la conversación: incluyen los tiempos de cada paso de cada activación.

Con el móvil conectado, las medidas también salen en `adb logcat -s VibiLlamada`.

## Tests

```powershell
.\gradlew.bat test
```

Para el emulador x86_64 (acepta HTTP solo hacia `10.0.2.2`):

```powershell
.\gradlew.bat assembleDebug -Pabi=x86_64
```
