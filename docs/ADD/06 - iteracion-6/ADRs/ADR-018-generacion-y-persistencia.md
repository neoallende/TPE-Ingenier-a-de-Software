# ADR-018: Generación periódica y persistencia de recomendaciones

- **Estado:** Aceptado para el diseño.
- **Iteración:** ADD-6.
- **Relacionado con:** ADR-015 y ADR-016.

## Contexto

El recomendador necesita generar resultados sin introducir cálculos costosos en las solicitudes interactivas.

También debe tolerar fallos del proceso de generación y evitar que una indisponibilidad del subsistema afecte las funciones principales de Trotamundos.

## Drivers

- QA-P2.
- QA-P5.
- QA-A1.
- QA-E3.
- CRN-10.

## Alternativas

1. Generación bajo demanda durante cada consulta.
2. Generación precalculada y periódica.
3. Generación por eventos ante cada modificación del perfil.

## Decisión

Se selecciona la **generación precalculada y periódica**.

Un proceso de fondo ejecutará el algoritmo y persistirá los resultados en PostgreSQL.

La API consultará las recomendaciones almacenadas sin ejecutar el algoritmo durante la solicitud.

El feedback se procesará asincrónicamente mediante RabbitMQ y actualizará el perfil del usuario. La modificación del perfil no provocará una regeneración inmediata.

La evaluación y revisión del algoritmo se realizarán separadamente del procesamiento individual del feedback.

Se conservarán las últimas recomendaciones válidas ante fallos de generación.

Se aplicará un TTL configurable. Cuando los resultados superen ese límite y no existan nuevos resultados válidos, la API devolverá una lista vacía.

## Persistencia

Se utilizará PostgreSQL, con separación lógica de las estructuras del recomendador.

Se contemplan entidades conceptuales para:

- Perfiles de recomendación.
- Recomendaciones.
- Elementos recomendados.
- Feedback.

No se duplicará el historial de viajes, que se consultará desde las proyecciones CQRS.

## Consecuencias

**Positivas:**

- Reduce el trabajo de la API durante las consultas.
- Permite aislar los cálculos en procesos de fondo.
- Mantiene disponibilidad parcial ante fallos.
- Permite controlar la vigencia de los resultados.

**Negativas y riesgos:**

- Introduce consistencia eventual.
- Las recomendaciones pueden no reflejar inmediatamente un cambio de preferencias.
- Requiere administrar ciclos de generación, reintentos y vigencia.
- El almacenamiento puede acumular resultados históricos que requieran una política de retención.

## Alcance del prototipo

Se implementará generación periódica de recomendaciones de alojamiento, persistencia en PostgreSQL y consulta con control de TTL.

## Trazabilidad

ADD-5, ADD-6, ADR-015, ADR-016, QA-P2, QA-P5 y QA-A1.
