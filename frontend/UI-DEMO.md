# Vibi · UI demo 003

Demo navegable de la nueva interfaz: blanco o negro como color principal, detalles secundarios invertidos y acentos rojos. Utiliza los sprites originales del zorro de `vibiNewDesign/` mediante el cargador de transparencias y animaciones existente.

## Abrir

Desde `frontend/`:

```sh
npm run dev:ui
```

Vite abre `/ui-demo.html`. No requiere iniciar sesión ni arrancar el backend.

Para compilar:

```sh
npm run build:ui
```

La salida está en `frontend/dist-ui/`. Un servidor estático debe servir esa carpeta; la entrada es `/ui-demo.html`.

## Recorrido

| Sección | Interacciones de la demo |
| --- | --- |
| Ahora | Mensaje rápido, contexto adjunto, resumen de encargos, proyectos, actividad y mascota animada. |
| Hilo | Conversación simulada, adjuntos, lectura en voz alta con el navegador y prueba de entrada de voz con frase de ejemplo. |
| Proyectos | Crear, editar, abrir contexto, continuar en el hilo y consultar encargos vinculados. Los cambios de nombre actualizan sus encargos. |
| Encargos | Crear, filtrar, consultar progreso, iniciar, pausar, completar y eliminar. |
| Estudio | Tema editable, mapa conceptual y explicación paso a paso con escena ilustrativa de aprendizaje. |
| Equipos | Crear equipos, editar miembros, abrir encargos y activar o revocar la observación de ejemplo. |
| Dispositivos | Vinculación de ejemplo, conexión/desconexión y vistas simuladas de pantalla, terminal y navegador. |
| Taller · Skills | Crear, editar, activar, probar en el hilo, exportar Markdown y eliminar. |
| Taller · Herramientas | Bancos de pruebas ilustrativos de archivos, terminal, navegador, escritorio, vigilancias y forja. |
| Taller · Archivos | Subir archivos, buscar, leer texto, adjuntar, descargar, eliminar y simular transferencias a nodos. |
| Taller · Actividad / Perfil | Historial local, nombre, preferencias y capacidades activas. |
| Taller · Mascota | Gestos originales y animaciones de internet, terminal y error. |
| Ajustes | Apariencia, motor/modelo de ejemplo, preferencias de voz/activación/notificaciones y restablecimiento. |

El buscador global (`⌘K` / `Ctrl+K`) encuentra secciones, proyectos, encargos y archivos. La navegación móvil se abre con el botón de menú. Las ventanas usan el diálogo nativo con cierre por `Esc` y foco contenido.

## Datos y alcance

Los cambios se guardan en `localStorage`, con claves propias (`vibi-ui-demo-v1` y `vibi-ui-theme`). Para volver al estado inicial: **Ajustes → Restablecer demo**.

Es un prototipo de interacción independiente: los turnos de IA, el control de dispositivos, las transferencias, la observación, las vigilancias y los bancos de herramientas están simulados y se identifican en pantalla. No ejecuta comandos ni accede a la pantalla o al micrófono. La lectura en voz alta sí usa la síntesis de voz del navegador al pulsar «Escuchar».

La subida conserva el contenido de archivos de texto de hasta 1 MB en el almacenamiento del navegador. Para binarios solo conserva nombre y tamaño.

## Verificación

Compilación TypeScript/Vite y ESLint de los archivos de la demo. Comprobación en Chromium de ambos temas, renderizado real de sprites, creación de proyectos, ciclo de encargos, respuesta de chat simulada, persistencia tras recargar, búsqueda global, secciones del Taller y navegación móvil sin desbordamiento horizontal.
