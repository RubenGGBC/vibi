# Rediseño integral de la aplicación local de Vibi

**Fecha:** 2026-08-30  
**Estado:** dirección derivada del companion aprobado por el usuario  
**Superficie:** consola local/PWA empaquetada con Tauri

## Objetivo

Unificar toda la interfaz local con la identidad del nuevo companion. La app
debe sentirse como el espacio de trabajo del mismo personaje: oscura, gráfica,
afilada y precisa, con rojo Vibi reservado para acción y actividad. Se conservan
las rutas, contratos de datos, nombres de destinos y flujos funcionales.

## Sistema visual

### Color

- **Void — `#07050c`:** fondo de aplicación.
- **Velvet — `#110817`:** rail y superficies profundas.
- **Vibi red — `#ff1026`:** acción primaria, foco y actividad.
- **Flame white — `#fff8f5`:** texto principal y controles activos.
- **Ash — `#9c919f`:** texto secundario.
- **Ember — `#ff9b64`:** permisos y avisos que requieren atención.

El violeta queda sólo como una neblina ambiental muy tenue que conecta con el
halo del companion. No se usa como color de interacción.

### Tipografía

- **Titulares:** `Barlow Condensed Variable`, peso 650–800, mayúsculas sólo en
  etiquetas cortas y títulos de destino.
- **Cuerpo:** `Manrope Variable`.
- **Datos y estado:** `JetBrains Mono Variable`.

### Forma y composición

La app adopta esquinas recortadas, bordes finos y superficies casi planas. La
firma visual es el **corte de ala**: una línea roja inclinada que aparece en el
rail, la navegación activa y el borde superior de superficies importantes. Es
una traducción estructural del ala de la chistera, no decoración repetida.

## Shell

El rail crece para dar presencia real a Vibi. Arriba muestra la marca local,
después la cara activa dentro de una cámara sin círculo, y debajo los cinco
destinos con indicador rojo lateral. El usuario y los accesos de sistema quedan
anclados al pie. El área central se enmarca como un tablero continuo y conserva
el scroll de cada página.

En anchos estrechos el rail reduce anchura pero no cambia la jerarquía; la app
está optimizada para la ventana local de escritorio.

## Superficies y controles

- Botones primarios: rojo sólido, texto blanco y esquina recortada.
- Campos: fondo negro, borde ceniza y foco rojo visible.
- Cards: fondos velvet, borde tenue y una sola señal activa roja.
- Pills y tabs: geometría compacta; el seleccionado es blanco o rojo según sea
  navegación o acción.
- Estados: rojo para trabajo vivo, verde suave para éxito, ember para permiso,
  gris para inactivo y rosa rojizo para error.
- Modales: panel oscuro con corte superior rojo y backdrop profundo.

## Pantallas

- **Acceso:** composición dividida; Vibi grande a la izquierda y formulario
  compacto a la derecha.
- **Ahora:** turno como protagonista, pasos en forma de ledger y columna de
  vigilancia/equipos como instrumentación secundaria.
- **Hilo:** conversación sin burbujas genéricas; mensajes de Vibi se anclan con
  una marca roja y los del usuario con un plano blanco atenuado.
- **Encargos y Equipos:** filas densas de operaciones, no tarjetas flotantes.
- **Taller:** pestañas como selector técnico y todos sus catálogos bajo el mismo
  vocabulario de superficie, formulario y estado.
- **Configuración, Perfil y modales:** misma jerarquía tipográfica y mismos
  tokens, manteniendo los controles actuales.

## Movimiento y accesibilidad

La única animación ambiental nueva es un barrido lento del corte de ala y pulsos
de estado ya existentes. Hover y focus son breves y legibles. Con
`prefers-reduced-motion: reduce` se eliminan barridos, flotación y transiciones
no esenciales. Todo botón conserva foco visible y todo texto secundario mantiene
contraste suficiente sobre Void/Velvet.

## Arquitectura

`vibi-ui.css`, importado al final de `main.tsx`, es la capa canónica del nuevo
sistema y sobrescribe de forma deliberada los estilos históricos sin reescribir
la lógica de cada página. `AppShell` incorpora la marca y el estado local;
`LoginPage` reutiliza el rig SVG existente en perfil companion para que el acceso
presente al personaje real. No se cambia ninguna API.

## Pruebas y aceptación

- Pruebas de componentes verifican la nueva marca estructural del shell y la
  presencia del companion real en acceso.
- Las pruebas de páginas existentes deben seguir pasando sin cambiar contratos.
- TypeScript, ESLint y builds web/companion deben terminar sin errores.
- Revisión visual en navegador local de acceso, shell, Ahora, Hilo, Encargos,
  Equipos, Taller y Configuración a 1440×900.
- La interfaz terminada no conserva acciones principales lavanda ni titulares
  serif; Vibi y el rojo del companion son reconocibles en cualquier ruta.

