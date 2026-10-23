"""Estudio: el engine visual de Vibi.

El modelo no escribe código gráfico. Llama a herramientas de alto nivel
(`estudio.funcion`, `estudio.simulacion`, `estudio.recorrido`…) que validan los
argumentos, calculan lo que haya que calcular y dejan la escena descrita como
datos. La sección Estudio de la PWA solo pinta esos datos.

Esa separación es la tesis entera:

- **Lo que se ve está calculado por el engine**, no imaginado por el modelo: los
  términos de una sucesión, el periodo de un péndulo, el orden en que Dijkstra
  visita los nodos o la geometría de una molécula salen de aquí o de una fuente
  curada, y cada elemento lleva escrito de dónde viene (`procedencia`).
- **Lo que no se puede verificar se marca**: el texto de una explicación lo
  redacta el modelo, y la escena lo dice.
- **El modelo recibe los números de vuelta**, para narrar con ellos en vez de
  recordarlos mal.

Módulos:

- `expresiones`: un evaluador de fórmulas cerrado (sin `eval`), el mismo
  lenguaje que entiende el cliente.
- `escena`: el estado de cada usuario, su persistencia y su difusión.
- `fisica`, `algoritmos`, `moleculas`, `modelos`: el cálculo de cada dominio.
- `primitivas`: las herramientas que se publican al modelo.
- `api`: lo que pide la PWA.
"""
