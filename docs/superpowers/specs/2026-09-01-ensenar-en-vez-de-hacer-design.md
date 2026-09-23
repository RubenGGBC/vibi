# Enseñar en vez de hacer — Diseño

**Fecha:** 2026-09-01
**Estado:** aprobado, pendiente de plan de implementación

## El problema

Vibi sabe hacer cosas en tu ordenador: lee el árbol de accesibilidad, pulsa,
escribe y encadena pasos con `devices_ui_batch`. Es una sola forma de ayudar, y
hay una petición muy común que no cubre: **«¿dónde está esto?»**.

Cuando alguien pregunta dónde se cambia el idioma de una aplicación, hoy sólo
hay dos respuestas posibles y ninguna es la buena:

- **Vibi lo hace.** Te toma el ratón, navega cuatro menús y lo cambia. El
  ajuste queda cambiado y tú sigues sin saber dónde estaba. La próxima vez
  vuelves a preguntar.
- **Vibi te lo cuenta por escrito.** «Menú Editar → Preferencias → General →
  Idioma». Es un camino escrito de memoria sobre una interfaz que el que
  pregunta tiene delante y Vibi no; si el menú se llama distinto en esa
  versión, la indicación manda a quien pregunta a buscar algo que no existe.

Falta la tercera, que es la que da una persona sentada al lado: **señalar**.
«Ahí, ese botón de arriba a la derecha», con el dedo puesto encima.

Y hay un motivo que va más allá de la comodidad. Un asistente que sólo sabe
hacer las cosas por ti te vuelve dependiente de él: cada vez sabes menos de tu
propio ordenador. Uno que sabe señalar te enseña. Es la diferencia entre pedir
que te hagan la gestión y que te digan dónde está la ventanilla.

## Qué se construye

Una herramienta más, hermana de las que ya hay y con la disciplina invertida:

| Herramienta | Qué hace | Quién mueve el ratón |
|---|---|---|
| `devices_ui_snapshot` | Lee la ventana como texto | Nadie |
| `devices_ui_batch` | Pulsa, escribe, navega | Vibi |
| **`devices_ui_guide`** | **Señala dónde hay que pulsar** | **Tú** |

La guía devuelve **una foto de tu pantalla con marcas encima**: un recuadro
numerado sobre cada elemento del que se está hablando, y una leyenda que dice
qué es cada número. Vibi escribe el texto —«el 1 es el menú Editar; ábrelo y
dentro verás Preferencias»— y tú haces el resto.

## Las decisiones

### 1. Las marcas salen del árbol, no de mirar la foto

Un modelo mirando un JPEG reescalado calcula el centro de un botón a ojo, y
falla con los pequeños. Aquí no hace falta: **el árbol de accesibilidad ya
publica el rectángulo exacto de cada elemento**, y la captura ya devuelve el
mapa que traduce escritorio a imagen (`origen_x`, `origen_y`, `ancho_real`,
`alto_real`, `ancho`, `alto` — `screen.py:_recordar_mapa`).

Con esas dos cosas, marcar es una multiplicación. La caja cae donde cae el
botón, con la precisión del sistema operativo y no la del ojo del modelo. Es la
misma razón por la que `ui.batch` acierta más que `screen.click`, aplicada a
señalar en vez de a pulsar.

**Consecuencia de coste, que es la parte bonita:** el modelo **no mira la
imagen**. Ya sabe lo que hay en la ventana, porque lo leyó en el árbol; para
señalar sólo dice qué elementos son. La foto viaja hacia el usuario y nunca
hacia el contexto. Una guía cuesta una captura y **cero tokens de imagen**,
mientras que la misma indicación por `devices_screenshot` costaría la imagen en
cada turno que la arrastre.

### 2. Se dibuja donde se ve, no donde se captura

Las marcas viajan como **geometría**, no como píxeles pintados: el nodo manda
el JPEG limpio y una lista de rectángulos en coordenadas de esa imagen, y quien
dibuja es la PWA, con un SVG por encima.

Tres motivos, en orden de peso:

1. **No añade dependencias al nodo.** Pillow sólo está declarado en Windows
   (`agent/requirements.txt`), y dibujar en el nodo dejaría la guía como una
   función de Windows por accidente, no por decisión.
2. **Se ve bien a cualquier zoom.** Un recuadro pintado dentro de un JPEG de
   1568 px se ve borroso en un móvil que lo amplía; un SVG por encima, no.
3. **Es reversible.** Cambiar el aspecto de una marca —color, grosor, un dedo
   en vez de un recuadro— no toca el agente que corre en la máquina del
   usuario, que es la pieza más cara de actualizar de todo el sistema.

### 3. La guía caduca, porque no es un documento

Una guía es una foto de tu pantalla. `screenshots.py` ya dejó escrito por qué
eso no se guarda en disco: *«no es un archivo tuyo: es lo que estabas mirando
en un instante concreto»*. La guía hereda esa regla entera y le cambia un
número.

Vive en memoria del servidor y se sirve por una URL propia
(`/api/guias/{id}/imagen`), autenticada y con comprobación de dueño. Caduca a
los **diez minutos**, no a los dos de una captura: una captura es un relevo
entre el nodo y el modelo que dura lo que dura el turno, y una guía la mira una
persona mientras sigue los pasos con las manos.

Al caducar, la imagen desaparece del chat. Es deliberado y hay que decirlo en
alto: **la guía no forma parte del transcript**. Recargar la conversación de
ayer no vuelve a enseñar lo que había en tu pantalla ayer, y ningún otro
dispositivo tuyo la recibe por el WebSocket. Lo que persiste es lo que Vibi
escribió; la foto era para el momento.

En el chat aparece como línea efímera —los `transientItems` que ya existen para
los archivos de una skill—, y llega hasta ahí **por el canal de eventos**, no
colgada de la respuesta del turno. Dos motivos, y el segundo es el que decide:

1. Con Antigravity, las herramientas se ejecutan fuera de proceso y el turno
   nunca ve su resultado. Una guía que viajara con la respuesta solo existiría
   con Claude, y el usuario del otro motor recibiría instrucciones numeradas
   sobre una foto que no ha visto nadie.
2. Quien pregunta puede estar preguntando **desde el móvil sobre lo que tiene
   en la pantalla del ordenador**. La guía tiene que aparecer en todas sus
   ventanas abiertas, y eso es lo que hace `events.manager.send`.

### 4. Señalar es leer, y el permiso lo dice

`ui.guide` entra en `CAPACIDADES_LECTURA` (`app/nodes.py`) junto a
`ui.snapshot` y `screen.capture`, y sus permisos son `devices:read:self`. No
hay ninguna vía por la que esta capacidad mueva el ratón, escriba una tecla ni
active una ventana: mira el árbol, hace una foto y devuelve rectángulos.

Y entra también en `CAPACIDADES_CON_CONTENIDO_AJENO`, por lo mismo que
`screen.capture`: en la pantalla puede haber cualquier cosa, y los nombres de
los elementos que vuelven en la leyenda los escribió quien programó esa
aplicación, no tú.

### 5. Ambiguo es una pregunta, no una elección

La resolución de objetivos es la de `ui.py` y no una nueva: por `ref` de la
última lectura, o por `{rol, nombre, dentro_de}`. Si una descripción casa con
tres elementos, la guía **no señala el primero**: devuelve los tres candidatos
para que el modelo acote, igual que hace un lote. Señalar el que no era es peor
aquí que en un lote, porque el usuario va a pulsar donde se le diga y va a
creer que el error lo cometió él.

Lo que sí cambia respecto al lote: la guía **no espera** a que aparezca algo
que todavía no está. Un lote puede señalar la opción de un menú que abrirá el
paso anterior; una guía sólo puede marcar lo que se ve ahora, porque la foto es
de ahora. Un elemento que no existe todavía se enseña en la guía siguiente,
después de que la persona abra el menú.

### 6. Un máximo de seis marcas

Más de seis recuadros sobre una captura dejan de ser una indicación y pasan a
ser un plano. El tope obliga a que cada guía diga una cosa, y a que un camino
de doce pasos se cuente en varias guías con la persona avanzando entre ellas
—que es como se enseña algo a alguien de verdad—.

## Arquitectura

```
Nodo (tu máquina)                  Servidor (Docker)              PWA
─────────────────                  ─────────────────              ───
guia.senalar()
  ui._mirar()      ─── árbol ──►
  resuelve ref/búsqueda → Rect
  screen.pantallas() → cuál
  screen.capturar() → jpeg+mapa
  proyecta Rect → px de imagen
        │
        ├── JPEG ──HTTP──────────► screenshots.recoger()
        │                          guias.publicar()
        └── marcas ──WS orden────► tools._device_ui_guide
                                     ├─ events.guia_lista ──WS──►    <img>
                                     │                              + <svg>
                                     └─ al modelo, sin imagen:       marcas
                                        qué número sobre qué
```

El JPEG sube por HTTP y no por el canal de órdenes por lo de siempre: el canal
descarta lo que pase de 200 KB. Se reutiliza el hueco de `screenshots.py` tal
cual —es el mismo tipo de imagen y el mismo tránsito—, y al recogerla se
republica en el almacén de guías, que es el que tiene TTL largo y URL propia.

## Lo que se prueba

Lo que no depende de tener Windows delante, que es casi todo lo que puede
salir mal:

- **La proyección.** Un rectángulo del escritorio con dos monitores y origen
  negativo tiene que caer donde toca en la imagen reducida. Es la cuenta que
  hace inútil o útil toda la feature.
- **El recorte.** Un elemento medio fuera de la pantalla se marca con lo que se
  ve; uno entero fuera no se marca y se dice por qué.
- **La resolución de objetivos.** Ref caducado, descripción ambigua,
  descripción que no casa con nada: los tres tienen que dar un error que se
  entienda, no una marca en el sitio equivocado.
- **El tope de marcas y la elección de pantalla.**
- **El almacén de guías.** Que caduca, que no sirve la guía de otro usuario y
  que la URL exige token.

Lo que sólo puede decir una máquina con ventanas de verdad —que UIA publique el
rectángulo correcto de un botón— queda fuera, como en el resto del árbol.

## Lo que no entra

- **Pasos encadenados con verificación.** Una guía de cinco pantallas que sepa
  por dónde vas y se actualice sola. Depende de que el usuario diga «ya», y eso
  es una conversación, que ya existe: se piden dos guías seguidas.
- **Telegram.** La guía se enseña en la PWA y en el companion. Mandarla por
  Telegram exigiría subir la foto de tu pantalla a los servidores de Telegram,
  y eso es una decisión distinta que nadie ha tomado.
- **Voz.** `/cara` puede locutar el texto de la guía, pero la imagen necesita
  pantalla. En un dispositivo sin ella, la guía se degrada a lo que Vibi diga.
