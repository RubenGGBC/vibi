# Alias acústico del wake word Vibi

## Problema

El modelo `vosk-model-small-es-0.42` no contiene `vibi` en su vocabulario y
descarta esa palabra al construir la gramática. Sí contiene `bibi`, que
representa la pronunciación española habitual de Vibi. Por ello el listener
actual puede abrir el micrófono, pero nunca producir un despertar.

## Diseño aprobado

- `vibi` sigue siendo la identidad canónica, el texto visible y el valor del
  evento `wake`.
- `bibi` se usa exclusivamente dentro del reconocimiento acústico de Vosk.
- Las dos etapas del detector aceptan la forma acústica: candidato restringido
  con confianza mínima y confirmación posterior con el vocabulario completo.
- La gramática restringida usa `bibi`; la confirmación acepta también `vivi`,
  porque el modelo completo transcribe sistemáticamente la pronunciación como
  «viví». Esta forma nunca se expone fuera del detector.
- No cambia el protocolo JSONL ni la integración Tauri.

## Verificación

Una prueba de regresión debe demostrar que una transcripción `bibi` confirmada
despierta y emite `{"type": "wake", "keyword": "vibi"}`. Las pruebas
existentes de confianza baja y falsos despertares deben seguir pasando. Tras
reconstruir e instalar el sidecar se comprobarán el proceso, el estado de
escucha y una activación real.
