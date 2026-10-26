# Propuesta de Trabajo de Fin de Grado — Vibi Compute

> **Título provisional:** Diseño, implementación y evaluación de un sistema de orquestación inteligente y computación distribuida en entornos multidispositivo heterogéneos.
>
> **Titulación:** Grado en Ingeniería Informática  
> **Proyecto:** Vibi — Asistente personal multidispositivo  
> **Estado del documento:** Propuesta inicial para revisión con el tutor  
> **Fecha:** 26 de octubre de 2026

---

## 1. Resumen ejecutivo

Este TFG propone extender **Vibi**, un asistente personal con arquitectura cliente-servidor y agentes instalados en distintos ordenadores, mediante un subsistema de **orquestación inteligente de tareas y recursos computacionales**.

La finalidad es permitir que una persona solicite una operación desde cualquiera de sus dispositivos y que Vibi determine **dónde, cuándo y cómo ejecutarla**, considerando capacidades, disponibilidad, coste de comunicación y restricciones de seguridad. En tareas divisibles, el sistema podrá repartir unidades de trabajo entre varios ordenadores y reunir sus resultados. Ante desconexiones, deberá identificar el trabajo no confirmado y recuperarlo sin comprometer la corrección del resultado.

La contribución del TFG no será desarrollar un nuevo modelo de IA ni afirmar que se suman físicamente CPU, RAM o GPU. Consistirá en diseñar, implementar y **evaluar experimentalmente** una capa de planificación y ejecución distribuida integrada en un asistente personal.

## 2. Problema y motivación

Los usuarios pueden disponer de varios equipos con sistemas operativos, herramientas y capacidades de cómputo diferentes. Habitualmente, ejecutar un trabajo requiere saber en qué máquina están los datos y programas, conectarse a ella y gestionar manualmente la operación y sus resultados. Las herramientas de escritorio remoto, sincronización y ejecución distribuida resuelven partes del problema, pero no implican necesariamente una experiencia unificada de petición, planificación, seguimiento y recuperación.

**Problema de investigación:** ¿cómo coordinar de forma fiable recursos computacionales heterogéneos y parcialmente disponibles mediante una interfaz de lenguaje natural, y en qué condiciones resulta ventajoso distribuir la ejecución frente a utilizar un único dispositivo?

### 2.1. Objetivo general

Diseñar, implementar y evaluar un sistema capaz de descubrir recursos de diferentes ordenadores, seleccionar nodos adecuados, distribuir tareas compatibles y recuperarse de desconexiones, reutilizando la infraestructura multidispositivo de Vibi.

### 2.2. Objetivos específicos

1. **Inventario de recursos:** recopilar sistema operativo, CPU, memoria, capacidades de ejecución, disponibilidad y, cuando proceda, GPU de cada nodo.
2. **Planificación:** desarrollar un algoritmo que compare ejecución local, remota y distribuida en función de requisitos, ubicación de datos y costes estimados.
3. **Ejecución distribuida:** dividir tareas expresamente compatibles en unidades independientes, asignarlas a workers y agregar resultados verificables.
4. **Gestión de fallos:** mantener el estado persistente de los trabajos, detectar pérdidas de nodos y reintentar o reasignar unidades seguras.
5. **Integración con Vibi:** exponer las operaciones mediante herramientas autorizadas del asistente y mostrar el progreso desde diferentes clientes.
6. **Evaluación:** comparar el sistema con baselines sencillos y analizar rendimiento, sobrecarga, escalabilidad, corrección y resiliencia.

## 3. Punto de partida y contribución nueva

La documentación revisada de Vibi describe, entre otros componentes, un servidor **FastAPI + SQLite**, clientes web/escritorio, agentes locales conectados por **WebSocket**, direccionamiento de órdenes a nodos, transferencia de archivos a través del servidor, persistencia de algunas órdenes y reconexión.

**Importante:** estas capacidades proceden de documentación y lectura de código; **no están certificadas por pruebas entre máquinas** en el contexto aportado. La primera fase del trabajo consistirá en validarlas.

| Elemento | Base documentada de Vibi | Aportación propuesta del TFG |
|---|---|---|
| Identidad y conectividad de nodos | Agentes y conexiones WebSocket | Inventario computacional actualizado y disponibilidad operativa |
| Selección de máquina | Por ID/nombre y reglas sencillas | Planificador basado en requisitos y coste estimado |
| Ejecución | Órdenes enviadas a un nodo | Trabajos particionados, asignación, resultados y supervisión |
| Desconexiones | Reconexión y ciertas órdenes pendientes | Estados de trabajo, leases, caducidad y replanificación segura |
| Archivos | Transferencia intermediada por servidor | Distribución controlada de entradas y recolección de artefactos |
| Asistente | Interpretación de peticiones y acceso a herramientas | Solicitud, autorización y seguimiento de trabajos distribuidos |
| Seguridad | Credenciales de nodo e interruptor de ejecución remota | Políticas por operación, auditoría y aislamiento del worker |

## 4. Alcance funcional

### 4.1. Alcance obligatorio (MVP)

- Conexión y gestión de **al menos dos ordenadores** reales con agentes Vibi.
- Monitorización básica de recursos y compatibilidad de ejecución.
- API de trabajos con estados: `CREATED`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`.
- Planificación mediante **reparto uniforme** (baseline) y una **estrategia adaptativa propia**.
- Distribución de una carga CPU paralelizable, como conversión de imágenes por lotes o simulación Monte Carlo con semillas controladas.
- Consolidación y validación de resultados.
- Detección de desconexiones, reintentos limitados y reasignación de unidades no confirmadas.
- Seguimiento de progreso y consulta de resultados desde otro cliente.
- Restricciones de ejecución: tipos de tarea autorizados, límites de recursos y permisos explícitos.

### 4.2. Ampliaciones condicionadas al tiempo

- Segundo caso de uso: ejecución de pruebas de software independientes y compatibles por plataforma.
- Estimación calibrada de tiempos y tamaño de transferencias.
- Políticas de batería, carga del sistema y preferencia del usuario.
- Canal de datos directo y protegido entre nodos, si el servidor se convierte en cuello de botella.
- Reanudación desde checkpoints **a nivel de aplicación** para tareas compatibles.

### 4.3. Fuera de alcance

- Agregar físicamente memoria RAM o VRAM de equipos heterogéneos.
- Ejecutar un único LLM distribuido entre GPUs distintas como requisito del TFG.
- Migrar procesos arbitrarios entre Windows, macOS y Linux.
- Paralelizar automáticamente cualquier aplicación existente.
- Desarrollar un sistema operativo, sistema de archivos distribuido o infraestructura de cómputo de propósito universal.
- Garantizar ejecución exactamente una vez para operaciones arbitrarias con efectos secundarios.

## 5. Arquitectura propuesta

```text
         Usuario (móvil / escritorio / web)
                         |
             Interfaz de Vibi + IA
     (interpreta intención; no decide permisos)
                         |
               Vibi Compute API
                         |
         +---------------+---------------+
         |               |               |
    Resource Registry  Job Manager   Scheduler
         |          (estado SQLite)  (coste/capacidades)
         +---------------+---------------+
                         |
               Dispatcher de tareas
                         |
             Agentes Vibi / Workers
             /           |           \
         Windows       macOS         Linux
            \            |            /
              Resultados + verificación
                         |
            Estado, archivos y notificación
```

**Separación de responsabilidades:**

- **IA:** transforma una solicitud natural en una operación estructurada admitida y solicita aclaración si falta información crítica.
- **Scheduler determinista:** valida requisitos, disponibilidad, políticas y predice la conveniencia de distribuir.
- **Job Manager:** persiste trabajos, unidades, intentos, estados y resultados.
- **Worker:** ejecuta tipos de trabajo explícitamente autorizados en un entorno restringido.
- **Agregador:** comprueba integridad y compone una salida única.

Se priorizará ejecutar cerca de los datos para evitar transferencias innecesarias. El control puede mantenerse en el servidor de Vibi; el transporte de datos intensivo se evaluará aparte.

## 6. Diseño del planificador

El planificador deberá escoger entre:

1. **Local:** ejecutar en la máquina que contiene los datos cuando sea suficiente.
2. **Remoto:** delegar en un nodo más adecuado o con una dependencia necesaria.
3. **Distribuido:** repartir unidades cuando el trabajo sea divisible y la ganancia prevista compense el coste.
4. **Diferido:** esperar a recursos disponibles cuando no exista alternativa segura.

Una aproximación inicial al coste sería:

\[
T_{\mathrm{total}} \approx T_{\mathrm{preparacion}} + T_{\mathrm{transferencias}} + T_{\mathrm{computo}} + T_{\mathrm{agregacion}}
\]

En ejecución paralela, el tiempo de cómputo depende del **camino crítico y del worker más lento**, no de sumar los tiempos de todos los nodos. El modelo deberá calibrarse con mediciones; no se asumirán ganancias lineales.

**Baselines de comparación:** un solo nodo, reparto uniforme y, si es viable, reparto proporcional a una estimación simple de rendimiento. La estrategia propia combinará potencia observada, tamaño de unidades, estado de cada nodo y coste de comunicación.

## 7. Fiabilidad y seguridad

- Identificadores únicos de trabajo y unidad, con resultados vinculados a una versión de entrada.
- Heartbeats o señales equivalentes para detectar indisponibilidad, con umbrales explícitos.
- Reintentos con límite, caducidad y control de intentos concurrentes mediante **leases** o mecanismo equivalente.
- Posibilidad de ejecución **al menos una vez** en caso de fallo; aceptación de resultados idempotente y deduplicada.
- Para operaciones con efectos secundarios, confirmación adicional o exclusión del reintento automático.
- Registro de decisiones del planificador, autorizaciones, transferencias y cambios de estado.
- Workers con permisos mínimos y sin exposición de ejecución arbitraria de comandos del usuario a través del nuevo motor.
- Protección de canales y credenciales; revocación de un nodo y cancelación de trabajos.

La pérdida de conexión no implica necesariamente que el proceso remoto haya dejado de ejecutarse. La recuperación debe manejar resultados tardíos y evitar aceptar salidas inconsistentes.

## 8. Preguntas e hipótesis de investigación

**PI1.** ¿En qué tamaños de trabajo y condiciones de red mejora el tiempo total al repartir cómputo entre varios equipos?

**H1.** Para cargas CPU suficientemente grandes y divisibles, la ejecución distribuida reducirá el tiempo total frente a un nodo, aunque no necesariamente para cargas pequeñas.

**PI2.** ¿Mejora un planificador consciente de heterogeneidad y comunicación frente al reparto uniforme?

**H2.** En entornos heterogéneos y para determinadas cargas, la estrategia adaptativa logrará un menor tiempo total que el reparto uniforme.

**PI3.** ¿Qué coste tiene mantener la corrección de resultados ante la desconexión de un nodo?

**H3.** Para tareas idempotentes, la reasignación de unidades pendientes permitirá completar el trabajo sin errores de resultado, a costa de sobrecarga adicional.

Todas son **hipótesis por verificar**, no resultados anticipados.

## 9. Evaluación experimental

| Experimento | Configuración | Métricas |
|---|---|---|
| E1. Escalabilidad | 1, 2 y 3 nodos si el hardware lo permite | Tiempo total, speedup, eficiencia |
| E2. Planificación | Nodo único, reparto uniforme, adaptativo | Tiempo total, desequilibrio, overhead |
| E3. Tamaño de trabajo | Lotes pequeños, medianos y grandes | Umbral en el que distribuir compensa |
| E4. Redes | LAN y condiciones de mayor latencia/ancho de banda reducido | Datos transferidos, latencia, tiempo total |
| E5. Desconexión | Interrupción controlada de un worker en ejecución | Recuperación, trabajo repetido, corrección, tiempo extra |
| E6. Correctitud | Salidas de referencia y hashes | Resultados válidos, duplicados aceptados, pérdidas |
| E7. Experiencia | Pedido y seguimiento desde clientes distintos | Interacciones necesarias, éxito de la operación |

### 9.1. Métricas centrales

- **Speedup:** \(S(n)=T_1/T_n\).
- **Eficiencia paralela:** \(E(n)=S(n)/n\) como indicador orientativo; en equipos heterogéneos se complementará con capacidad relativa.
- **Sobrecarga:** diferencia entre tiempo total y tiempo útil de procesamiento.
- **Fiabilidad:** proporción de trabajos correctos finalizados y tasa de recuperación tras fallos inyectados.
- **Equidad/impacto local:** carga generada en equipos que el usuario puede estar utilizando.

Las pruebas deberán repetirse bajo condiciones controladas, indicando hardware, SO, red, parámetros y dispersión estadística. Se conservarán registros y scripts de reproducción. No se fijan cifras de mejora sin medirlas.

## 10. Caso de demostración para la defensa

1. El usuario solicita desde el móvil: **«Vibi, procesa este conjunto de archivos usando los equipos disponibles y avísame al terminar»**.
2. Vibi presenta los nodos detectados y justifica el plan de ejecución.
3. Los agentes ejecutan partes independientes del trabajo y muestran progreso.
4. Se desconecta deliberadamente uno de los nodos.
5. Vibi identifica unidades sin resultado confirmado, las reasigna de forma segura y evita aceptar resultados duplicados.
6. El trabajo finaliza; el usuario consulta el resumen y recupera artefactos desde otro dispositivo.
7. Se comparan las métricas con la misma tarea ejecutada en un solo equipo y con reparto uniforme.

Esta demostración deberá prepararse sobre un escenario **realmente validado y reproducible**; el guion no constituye prueba de que ya funcione.

## 11. Estado del arte a estudiar

Se compararán, con documentación primaria y versiones identificadas, las siguientes familias:

- **Orquestación y cómputo distribuido:** Dask, Ray y enfoques de colas de trabajo.
- **Planificación y tolerancia a fallos:** políticas de asignación, reintentos, idempotencia, heartbeats y recuperación.
- **Asistentes y control remoto:** agentes locales, automatización de escritorio y continuidad entre clientes.
- **Cómputo de IA entre equipos (trabajo futuro):** llama.cpp RPC, EXO y paralelismo de modelos.
- **Migración de procesos (trabajo futuro):** CRIU y DMTCP.

El estado del arte debe diferenciar capacidades publicadas, compatibilidad efectiva y limitaciones. **Esta propuesta no sustituye la revisión bibliográfica ni afirma novedad absoluta.**

## 12. Plan de trabajo orientativo

| Fase | Entregables |
|---|---|
| 1. Validación inicial | Pruebas de agentes, conexión, transferencias, reconexión y seguridad; inventario de carencias |
| 2. Modelo de trabajos | Esquema de datos, API, estados, logs y políticas de autorización |
| 3. Worker y planificador base | Ejecución de cargas permitidas, fragmentación, agregación y baseline uniforme |
| 4. Scheduler adaptativo | Monitor de recursos, estimación de costes y selección de nodos |
| 5. Recuperación ante fallos | Detección de desconexiones, reintentos y deduplicación |
| 6. Evaluación | Batería de benchmarks, métricas, análisis y límites del modelo |
| 7. Memoria y defensa | Redacción, reproducibilidad, demostración y conclusiones |

El calendario concreto y el alcance del segundo caso de uso se ajustarán con el tutor y al hardware disponible.

## 13. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Intentar abarcar demasiadas funcionalidades | Limitar el MVP a una carga CPU paralelizable y dos nodos |
| Rendimiento peor que un solo PC | Analizar el umbral de conveniencia; es un resultado experimental válido |
| Dependencias y diferencias entre SO | Usar una carga portable y validar entornos de ejecución |
| Transferencias lentas o servidor saturado | Medir el tráfico, reducir movimiento de datos y evaluar canal alternativo |
| Nodos suspendidos o apagados | Diferir o reasignar; no prometer encendido universal |
| Duplicación tras fallos de red | IDs, leases, operaciones idempotentes y aceptación única del resultado |
| Riesgo de ejecución remota | Permisos mínimos, lista de operaciones permitidas, auditoría y aprobación |
| Dependencia de respuestas del LLM | Planes estructurados, validación determinista y pruebas sin IA |

## 14. Criterios de éxito

El TFG se considerará técnicamente satisfactorio si:

1. Ejecuta una misma carga divisible en **al menos dos máquinas físicas** con resultados correctos.
2. Compara reproduciblemente **ejecución individual, reparto uniforme y planificación adaptativa**.
3. Mantiene un registro fiable de trabajos y resultados y recupera un escenario controlado de desconexión.
4. Explica con datos **cuándo distribuir mejora o empeora** la ejecución.
5. Integra solicitud, seguimiento y entrega del trabajo en la experiencia multidispositivo de Vibi.
6. Justifica las decisiones de seguridad, reconoce límites y documenta procedimientos repetibles.

**No se exige que distribuir siempre acelere la ejecución.** Un resultado negativo bien medido y explicado constituye una conclusión académicamente válida.

## 15. Contribución esperada y posicionamiento

El resultado previsto es una **arquitectura de orquestación de recursos personales** que integra tres áreas: asistentes basados en IA, sistemas distribuidos y entornos multidispositivo heterogéneos.

La aportación que se pretende evaluar es si un planificador basado en capacidades, estado y costes, integrado en un asistente, permite mejorar la ejecución y continuidad de trabajos respecto a mecanismos más simples. Se evitará afirmar que la computación distribuida o el control remoto mediante IA son novedades en sí mismos.

**Mensaje central para la defensa:**

> Vibi no busca simplemente controlar varios ordenadores. Busca coordinar sus capacidades para que el usuario formule un objetivo y el sistema seleccione los recursos adecuados, ejecute las tareas y se adapte a fallos de disponibilidad. Este trabajo diseña esa arquitectura y mide sus ventajas y limitaciones.

---

## 16. Decisiones pendientes para cerrar la propuesta con el tutor

- Número de ordenadores físicos y especificaciones de CPU, RAM, GPU, SO y conectividad.
- Duración y extensión exigidas por el TFG; rúbrica de evaluación de la titulación.
- Nivel real de funcionamiento de los agentes y transferencias de Vibi tras pruebas.
- Elección final de la carga principal: **conversión por lotes** (demostración intuitiva) o **simulación Monte Carlo** (benchmark controlable).
- Inclusión o no de tests de software como segundo escenario aplicado.
- Requisitos institucionales de protección de datos, experimentos y documentación.

**Recomendación:** comenzar verificando la infraestructura existente y construyendo un prototipo mínimo con dos workers y una tarea CPU idempotente. A partir de mediciones reales, incorporar planificación adaptativa y tolerancia a fallos antes de añadir nuevas funciones.
