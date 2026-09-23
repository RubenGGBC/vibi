# Rediseño vectorial de Vibi para el companion local

**Fecha:** 2026-08-29  
**Estado:** diseño aprobado en conversación  
**Superficie:** companion local de Windows

## Objetivo

Reemplazar por completo el diseño visual actualmente implementado en el
companion por una figura SVG nueva, trazada desde la primera lámina aportada por
el usuario. La prioridad de esta fase es que Vibi se reconozca inmediatamente
como el personaje de esa referencia: una silueta asimétrica y ladeada, una
chistera roja dominante, antifaz negro, mandíbula blanca en media luna y un
fuego lateral fino.

El resultado no será una corrección incremental de la cara redonda actual. Ese
diseño no se utilizará como base visual. Se conservarán únicamente los contratos
de integración que ya conectan la cara con el estado de la aplicación, las
señales de voz y el puntero.

## Alcance

Esta fase afecta solo a `perfil === "companion"`. La cara de la consola web y
la del rail deben conservar su aspecto y comportamiento actuales.

La primera entrega implementará las ocho familias visuales presentes en la
lámina:

1. reposo;
2. recelo;
3. contenta;
4. trabajando;
5. duda;
6. hablando;
7. ejecutando;
8. buscando.

Vibi ya tiene más estados funcionales. En esta fase todos se asociarán de forma
determinista a una de las ocho familias. Diseñar gestos adicionales queda fuera
del alcance y se hará en una fase posterior.

También quedan fuera de alcance los cambios de la API de `VibiFace`, la lógica
de `useFaceMood`, la cara de la PWA y cualquier cambio de marca fuera del
companion.

## Dirección visual

### Silueta

La figura maestra debe reproducir la composición de la referencia, no solo su
paleta:

- cabeza inclinada y asimétrica, más ancha que alta;
- mandíbula blanca en media luna, con la punta inferior desplazada;
- antifaz negro amplio que ocupa la zona superior del rostro;
- copa alta, escorada y estrechándose hacia la base;
- ala larga que cruza el personaje en diagonal y termina en una punta marcada;
- fuego lateral formado por tres lenguas legibles, no por una única masa grande;
- ojos pequeños y separados, subordinados a la chistera y a la silueta.

La diagonal continua entre la copa, el ala, el rostro y el fuego será la firma
del personaje. Ningún estado podrá deformar esa composición hasta convertirla
en una cabeza redonda, vertical o simétrica.

### Paleta y acabado

La paleta se limita a rojo vivo, rojo profundo, negro violáceo, blanco y el
resplandor violeta del companion. El SVG puede emplear degradados y filtros para
reproducir el volumen suave de la lámina, pero no añadirá colores decorativos.

La sombra se calculará sobre la silueta completa. Los degradados del sombrero y
el fuego deben seguir el volumen de cada pieza; no se aplicará un único gradiente
genérico a toda la figura.

### Rig vectorial

La figura se divide en seis grupos SVG independientes:

- **chistera:** copa, pliegues y ala;
- **rostro:** silueta negra;
- **mandíbula:** media luna blanca;
- **ojos:** dos anclajes con formas sustituibles;
- **fuego:** tres lenguas superpuestas;
- **complementos:** interrogación, onda, flecha de terminal y lupa.

Todas las familias comparten esta figura maestra. Un estado cambia los ojos, el
complemento y su coreografía, pero no sustituye el cuerpo por otro dibujo.

## Lenguaje de movimiento

El motor nuevo utilizará movimiento continuo y transiciones físicas; no será
una colección de GIF ni ocho bucles independientes.

### Movimiento ambiental

- flotación mínima que no distraiga;
- parpadeo irregular;
- mirada suave que pueda seguir el puntero en el companion;
- titileo independiente de las tres lenguas del fuego;
- retraso ligero de la chistera respecto al movimiento de la cabeza.

### Transición común

Un cambio de familia tendrá anticipación corta, compresión y estiramiento
moderados y un asentamiento elástico. La chistera llegará con retraso para dar
peso al personaje. La transición no debe alterar la silueta durante tanto tiempo
que deje de reconocerse.

### Coreografía inicial por familia

- **Reposo:** respiración casi imperceptible, parpadeo y fuego vivo.
- **Recelo:** inclinación seca, ojos tensos y llama más afilada.
- **Contenta:** salto corto con aterrizaje elástico y seguimiento de la
  chistera.
- **Trabajando:** balanceo concentrado y sonrisa contenida.
- **Duda:** ladeo progresivo y aparición flotante de la interrogación.
- **Hablando:** onda ligada al nivel real de voz.
- **Ejecutando:** flecha de terminal con avance y pulso firme.
- **Buscando:** lupa recorriendo un arco y ojos siguiendo su recorrido.

Con `prefers-reduced-motion`, se eliminarán los bucles y las transiciones
amplias. Cada familia conservará una pose estática completa y legible.

## Correspondencia temporal de estados

La asignación inicial será:

| Familia | Estados actuales |
| --- | --- |
| Reposo | `idle`, `vigilando`, `cambiando`, `offline` |
| Recelo | `recelo`, `denegada`, `alert`, `fallo`, `perdida` |
| Contenta | `pleased`, `logro`, `vibing` |
| Trabajando | `working`, `reading`, `writing`, `noting`, `trastienda` |
| Duda | `thinking`, `waiting`, `arranque`, `vinculando` |
| Hablando | `listening`, `speaking` |
| Ejecutando | `hacking`, `handling`, `launching`, `sending`, `reaching` |
| Buscando | `searching`, `browsing`, `rummaging`, `peeking` |

La tabla cubre todos los valores de `ESTADOS`. Una prueba impedirá que un estado
nuevo quede sin asignar. Si llega un valor desconocido en tiempo de ejecución,
el companion mostrará reposo.

## Arquitectura

El motor del companion vivirá aislado bajo `frontend/src/lib/face/companion/`:

- `geometry.ts`: trazados, anclajes, degradados, filtros y proporciones;
- `states.ts`: ocho familias y correspondencia de `FaceState`;
- `motion.ts`: muelles, parpadeo, mirada, fuego y coreografías;
- `scene.ts`: montaje del SVG y aplicación de cada fotograma.

`frontend/src/lib/face/escena.ts` seguirá siendo la entrada pública y escogerá
la escena nueva únicamente para el perfil `companion`. El perfil `web`
continuará usando la implementación actual. `VibiFace` mantendrá su API y su
ciclo de vida.

El flujo de datos será:

`useFaceMood` → `VibiFace` → selector de perfil → escena del companion → familia
visual → rig SVG y movimiento.

Las señales existentes de voz, actividad y puntero entrarán en la escena nueva
sin modificar sus productores.

## Ciclo de vida y recuperación

La escena dibujará un primer fotograma de forma síncrona para evitar un hueco al
abrir la ventana. Después utilizará `requestAnimationFrame` y limitará los
saltos de tiempo grandes para evitar explosiones físicas tras suspender el PC.

Al desmontarse, cancelará el fotograma pendiente y quitará sus listeners. Un
estado desconocido caerá en reposo. La ausencia temporal de señales de voz se
interpretará como nivel cero y no detendrá el resto del movimiento.

## Estrategia de pruebas

La implementación seguirá TDD.

### Pruebas automáticas

- el perfil `companion` monta el rig nuevo y el perfil `web` sigue montando el
  motor actual;
- el rig contiene los seis grupos y exactamente tres lenguas de fuego;
- la tabla de familias cubre todos los valores de `ESTADOS`;
- cada una de las ocho familias produce ojos y complemento coherentes;
- el primer fotograma no contiene `NaN` ni deja el lienzo vacío;
- voz, puntero y cambio de estado modifican el fotograma;
- `dispose` cancela el bucle y los listeners;
- movimiento reducido conserva las ocho poses sin coreografía amplia.

### Revisión visual

Se generará una lámina de ocho estados con un lienzo, escala y fondo constantes.
Se comparará junto a la primera imagen aportada. La revisión comprobará, por
este orden:

1. silueta general y diagonal dominante;
2. proporción y posición de la chistera;
3. mandíbula y antifaz;
4. tamaño y colocación de ojos;
5. tamaño, separación y dirección del fuego;
6. accesorios;
7. sombras, degradados y resplandor;
8. legibilidad a tamaño real dentro del companion.

No se dará por terminada la fase únicamente porque pasen las pruebas. La figura
de reposo debe aprobar la comparación visual antes de pulir las demás familias.

## Criterios de aceptación

- A primera vista, la figura del companion reproduce la identidad y las
  proporciones de la primera lámina, sin conservar la cabeza cilíndrica de la
  implementación actual.
- Los ocho estados de la referencia son reconocibles sin texto.
- Todos los estados actuales de Vibi muestran una familia válida.
- Las animaciones nacen de la figura fiel y no ocultan defectos geométricos.
- La consola web y el rail no cambian.
- La cara se mantiene nítida y legible en los tamaños reales del companion.
- Las pruebas relevantes, el chequeo de TypeScript y la construcción del
  companion pasan sin errores.
