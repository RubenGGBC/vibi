# El modelo de decisión: decidir sin gastar un turno

Vibi tiene una cosa cara y una cosa lenta, y son la misma: **pedirle a un
modelo de chat que piense**. Un turno de agy en este equipo son entre cuatro y
ocho segundos, y entre tres y ocho céntimos si acaba usando herramientas. Eso
está bien pagado cuando hay algo que pensar, y está tirado cuando lo único que
hay que hacer es **elegir una cosa de una lista corta**.

Esto documenta el otro camino, el que no genera texto.

## Qué es Jev

[TypeSafe](https://docs.typesafe.ai) vende exactamente eso: un modelo que
contesta una `Choice` sobre hasta 255 opciones con la distribución entera de
probabilidad y una **confianza calibrada**, en unos cientos de milisegundos.
Vibi lo llama a través de Opper —la API propia de TypeSafe está en lista de
espera y ésta no—, con el modelo `typesafe/jev-1.13.0`.

Medido el 2026-09-20 contra un turno de chat del mismo equipo:

| | Jev | un turno de agy |
|---|---|---|
| latencia | 0,5 s | 4–8 s |
| coste por decisión | 0,0003 $ | 0,03–0,08 $ |
| qué devuelve | una opción de la lista + confianza | texto libre |

## Las tres reglas

Todo lo que se apoya en Jev en Vibi cumple las mismas tres, y no son de
estilo: son lo que hace que se pueda enchufar en un camino que ya funcionaba
sin arriesgar nada.

**1. Nunca dice «no lo sé».** Le preguntes lo que le preguntes, contesta una
de las opciones. No es un fallo del modelo, es lo que es: un clasificador. Así
que **la confianza es el único freno**, y por debajo del umbral no se decide
nada y se sigue por donde se seguía antes.

Cuando hace falta que pueda abstenerse, la abstención se escribe como una
opción más —`ninguna` en `fast_actions`—. Si no está en la lista, no existe.

**2. `None` significa «decide tú».** Sin clave, sin red, con la respuesta a
medias, con una opción inventada o con poca confianza, todos los caminos
acaban en el mismo sitio: el comportamiento de antes. El peor caso de todo
esto es medio segundo perdido.

**3. Las opciones no se solapan.** La confianza mide concentración, así que
dos opciones que significan casi lo mismo siempre se leen como duda, y el
umbral frena por algo que no era una duda de verdad. Listas cortas y
mutuamente excluyentes.

## Dónde decide en Vibi

### En el nodo — `agent/vibi_node/decisor.py`

**Desempatar controles de una ventana.** Cuando `ui.buscar` deja varios
candidatos, antes eso paraba el lote entero: tres «Aceptar» son una pregunta,
no una opción por defecto. Ahora se le ofrecen los candidatos —no la ventana
entera, que sería preguntar otra cosa— descritos por `ui_tree.criterios`, y si
va seguro, el lote sigue.

Las descripciones se construyen para que **puedan distinguirse**, que es la
mitad del trabajo:

1. el rol, el nombre y el valor;
2. si dos coinciden, el contenedor con nombre más cercano (`en "Borrar todo"`);
3. si aún coinciden, dónde caen en la ventana (`abajo a la derecha`);
4. y cualquier fecha escrita, ya restada contra hoy (`dentro de 23 días`).

El cuarto punto es el que más cuesta entender y el que más rinde: ver
[`fechas.py`](../agent/vibi_node/fechas.py). Un modelo de decisión no hace
calendario. Si la opción dice «13 oct», elige a ciegas; si dice «13 oct —
2026-10-13 (dentro de 23 días)», compara números.

### En el servidor — `app/decisor.py`

**Abrir la aplicación que era** (`app/fast_actions.py`). En esta máquina
Discord sale tres veces y hay dos «chrome» de verdad. El catálogo contestaba
`ambiguous` y te devolvía la pregunta a ti, que solo querías abrir algo. Ahora
se resuelve con la frase que escribiste como estado. Y cuando el catálogo dice
`not_found` con coincidencias parciales —«abre chrom»—, lo que se ahorra es un
turno entero del motor de chat; ahí se le exige más confianza (0,90) y se le
ofrece decir `ninguna`, porque puede que la buena no esté en la lista.

**Triar los avisos antes de deliberar** (`app/avisos.py`). Es donde los
números están más a favor. Deliberar una tanda de notificaciones es un turno
de agy completo, y la mayoría de lo que le llega a un ordenador encendido no
necesita que nadie piense: una promoción, una compilación que acabó, un
recordatorio. El triaje elige entre `deliberar` y `contar`, y cuando hay una
vigilancia viva va además una segunda pregunta —¿puede esperar?— **en la misma
petición**, porque el estado se manda una vez.

Lo que **no** hay es una tercera opción para descartar. Que un modelo decida
no contarte que Ana ha escrito es justo el fallo del que ese módulo lleva
protegiéndose desde el principio. Lo que se decide no es si el aviso llega
—llega siempre—, sino si hace falta gastar un turno para entregarlo.

## Sobre el texto que viene de fuera

El cuerpo de una notificación es contenido externo, y el prompt de la
deliberación ya avisa a agy de que lo trate como un dato y no como una orden.
En el triaje eso importa menos, por una razón estructural que conviene tener
escrita: **un modelo de decisión no escribe, elige de una lista cerrada**. Lo
peor que puede conseguir una notificación maliciosa es que su tanda se cuente
en vez de deliberarse, o al revés. No hay ninguna frase que lo lleve a hacer
algo que no estuviera ya en la lista de opciones.

Es la propiedad más infravalorada de este camino: el espacio de salida es
finito y lo escribes tú.

## Configuración

Una variable, opcional:

```
OPPER_API_KEY=
```

Sin ella no falla nada. `decisor.disponible()` devuelve `False`, todo lo de
arriba se salta solo y Vibi se comporta exactamente como antes de que esto
existiera. El nodo la lee de su propio entorno; el servidor, del `.env`.

## De dónde sale

De [`awlevin/typesafe-computer-use`](https://github.com/awlevin/typesafe-computer-use),
un bucle de computer use construido entero alrededor de esta idea: leer la
pantalla de forma determinista, preguntarle a un clasificador qué acción toca
y no mandarle nunca una captura a un modelo grande.

Lo que se ha traído de ahí:

- **varias preguntas en una petición**, que es la idea que más rinde;
- **la abstención como opción escrita** (su `none`), porque no se abstiene solo;
- **el tope de 255 opciones** como un muro y no como un presupuesto;
- **la resta de fechas hecha fuera del modelo** (`dates.py` → `fechas.py`);
- **la zona de pantalla** como último recurso para distinguir dos cosas iguales;
- y su advertencia más honesta, que es la que ordena todo lo demás: *cada trozo
  de razonamiento que el modelo grande hace gratis hay que reconstruirlo aquí
  como estado determinista*.

Lo que **no** se ha traído: su capa de percepción. Aquel proyecto lee la
pantalla con OCR porque en macOS no tiene otra; Vibi ya tiene el árbol de
accesibilidad de las dos plataformas (`ui_tree`), que es una fuente mejor y más
barata. La caché de tiles y el recorte de la ventana resuelven un problema que
aquí no existe.
