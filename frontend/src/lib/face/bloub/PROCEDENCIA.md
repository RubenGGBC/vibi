# bloub — código de terceros, vendorizado

Este directorio **no es código de Morgana**. Es el núcleo de
[bloub](https://github.com/jeremy-prt/bloub), de Jérémy Perret, copiado tal
cual desde `src/bot/` del repositorio original.

- **Licencia:** MIT. El texto está en `LICENSE`, junto a este archivo, y hay que
  conservarlo.
- **Copyright:** © 2026 Jérémy Perret.
- **Origen:** rama `main`, clonada el 2026-08-18.

## Por qué está aquí y no reescrito

La cara de Vibi se escribió primero a mano, con el mismo diseño —silueta de
radios en polar, ojos proyectados sobre una esfera— pero con **las proporciones
inventadas a ojo**. Quedó mal, y el motivo es que esa parte no se puede deducir:
las de bloub están medidas al píxel sobre el vídeo de referencia. Reescribirlas
sería volver a adivinarlas.

Lo que se toma es la geometría y el movimiento. Lo que Vibi pone encima —la
antena, los veintitrés gestos con significado, las señales vivas del turno—
vive fuera de esta carpeta.

## Reglas para tocarlo

**No se traduce ni se reformatea.** Los comentarios están en francés y los
identificadores mezclan francés e inglés; se quedan así. El día que haya que
traer un arreglo de arriba, un `diff` contra el original tiene que seguir siendo
legible, y eso vale más que la coherencia de idioma con el resto del repo.

Si hace falta cambiar algo, mejor hacerlo desde fuera —envolviendo— que editando
aquí dentro. Si no queda más remedio, dejar el cambio anotado con `MORGANA:`
para que salte a la vista en el próximo `diff`.

## Qué contiene

| Archivo | Qué es |
|---|---|
| `shape.ts` | el modelo polar: perfiles de radios, mezcla, contorno a `path` |
| `repere.ts` | el marco de la esfera sobre la que van los ojos |
| `face.ts` | las medidas del rostro: tamaño de ojo, separación, mirada de reposo |
| `states.ts` | las poses del referente |
| `engine.ts` | `BotEngine`: máquina de estados, transiciones, y `sample()` a un fotograma |
| `eyefit.ts` | resuelve cuánto desplazar la cara para que los ojos no se salgan |
| `decor.ts` | partículas, estelas y la insignia con muesca |
| `skins.ts` | catálogo de formas y colores |
| `expressions.ts`, `cycles.ts`, `profiles.ts`, `math.ts` | apoyo |

Sus tests vienen incluidos y corren con la suite de Morgana. Son la red que
avisa si una actualización de arriba rompe algo.
