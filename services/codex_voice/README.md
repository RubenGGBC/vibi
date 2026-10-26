# Voz de Codex para Vibi

Servicio local independiente con tres voces de prueba: Juniper, Maple y Breeze. Codex gestiona la conversación de voz. La herramienta `vibi_request` envía las peticiones a la API real de Vibi; conserva sus motores, historial y permisos. No cambia la configuración de Antigravity ni de Claude.

## Arranque

Desde la raíz del repositorio, con Python 3.11 o superior y Codex CLI en PATH:

```powershell
codex login
python -m services.codex_voice.server
```

Abrir http://127.0.0.1:8768. También hay un acceso «Voz de Vibi» en la cabecera de `Frontend TFG`.

El servicio no necesita dependencias Python adicionales. Usa la sesión local de ChatGPT que mantiene Codex, sin exportar OAuth ni usar una API key. La superficie de voz de app-server es experimental; la versión validada en este equipo es 0.164.0.

## Comparar voces

1. Elegir una voz y pulsar «Conversar con…»; el navegador solicita el micrófono.
2. Pulsar «Escuchar un saludo» o hablar directamente. Se puede interrumpir.
3. Elegir otra voz: se desconecta la anterior; pulsar conversar para probar la siguiente.

**Maple es la voz elegida para Vibi y la predeterminada**, tanto en el navegador como en el servicio. Juniper y Breeze siguen disponibles para comparar. Se han dejado de usar las preferencias provisionales del experimento anterior; los cambios explícitos se conservan en ese navegador.

### Probar en macOS

Desde el clon del proyecto, con una versión reciente de Codex CLI y Python 3.11 o superior:

```bash
git pull origin especializacion-por-usuario
codex login
python3 -m services.codex_voice.server
```

Abrir `http://127.0.0.1:8768`. Si Vibi sigue ejecutándose en el otro ordenador, indicar su dirección accesible antes de arrancar:

```bash
export VIBI_BACKEND_URL='https://TU-SERVIDOR-VIBI'
python3 -m services.codex_voice.server
```

Para instalar el CLI si falta: `npm install -g @openai/codex`. Usa la cuenta de ChatGPT del Mac; no es necesario copiar credenciales del PC. Si el navegador no puede grabar, revisar su permiso de micrófono en macOS. El código usa procesos POSIX en macOS y solo añade la opción de ventana oculta cuando existe en Windows. La ejecución en un Mac físico queda pendiente de esta prueba del usuario.

## Conectar al sistema real

Pulsar «Conectar cuenta» e iniciar sesión con el usuario y contraseña de Vibi. La contraseña se usa para el login y se descarta; el JWT se mantiene únicamente en memoria del servicio, separado por pestaña. Conectar la voz después del login para que Codex anuncie la herramienta de Vibi.

Se pueden pedir dispositivos, archivos, skills o trabajo de programación. El coordinador de Codex llama a `vibi_request`, que envía `/api/mensaje` y devuelve la respuesta. La programación se delega en el motor que ya tenga Vibi configurado; este servicio no lo sustituye por Codex. Las aprobaciones de acciones se siguen resolviendo en Vibi.

También hay un campo de texto para comprobar el puente sin dictar. Las peticiones enviadas aparecen en el historial de Vibi. Las charlas informales de la voz no se sincronizan todavía con ese historial. Desconectar el audio no cancela tareas ya enviadas al backend.

Por defecto el backend es `http://127.0.0.1:8000`. Se puede cambiar antes del arranque:

```powershell
$env:VIBI_BACKEND_URL = 'http://127.0.0.1:8000'
$env:VIBI_CODEX_VOICE_PORT = '8768'
python -m services.codex_voice.server
```

El backend es una configuración de confianza del operador, nunca una URL proporcionada por el modelo. Solo se aceptan orígenes HTTP(S) sin credenciales, rutas o consultas; se rechazan redirecciones para no reenviar credenciales a otro origen.

## Límites

- Escucha solo en loopback: esta versión es para el navegador del propio ordenador. No se ha publicado para acceso desde el móvil o Tailscale.
- Una llamada activa por servicio; otra pestaña no puede sustituirla ni cerrarla.
- Una pestaña que deja de enviar señales de vida durante 90 segundos pierde la sesión de voz. No hay reinicios automáticos de acciones tras errores o timeouts.
- No reemplaza el sistema de voz anterior, no proporciona un agente universal de escritorio y no instala autostart.
- Los permisos y herramientas de Vibi son la vía de ejecución prevista. El coordinador usa sandbox de solo lectura, shell y plugins deshabilitados y rechaza peticiones de herramientas dinámicas distintas de `vibi_request`. El sandbox de Codex no es un aislamiento completo de la cuenta del sistema operativo.
- El servicio no guarda grabaciones ni transcripciones en disco; las peticiones delegadas sí se guardan en el backend conforme a su funcionamiento habitual. La voz implica enviar audio a OpenAI y está sujeta a los límites de la cuenta.

## Verificación

```powershell
python -m unittest discover -s services/codex_voice -p 'test_*.py'
node --test services/codex_voice/web/transcript.test.mjs
```

Las pruebas cubren autenticación, errores, validación de voces, aislamiento entre pestañas, delegación sin cambiar proveedor y composición de transcripciones. Las pruebas de audio reales con micrófono sintético y los perfiles de navegador temporales se conservan fuera del código publicable, en `data/.voice-research/`.
