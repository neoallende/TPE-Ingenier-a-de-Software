# ADR-017: Algoritmo content-based y perfil híbrido de usuario

- **Estado:** Aceptado para el diseño.
- **Iteración:** ADD-6.
- **Relacionado con:** ADR-015.

## Contexto

ADD-4 definió un subsistema de recomendaciones desacoplado mediante `RecommendationProvider`, pero dejó pendiente la selección del algoritmo.

Se requiere generar recomendaciones personalizadas utilizando información propia de cada usuario, evitando dependencias de datos colaborativos entre usuarios.

También es necesario definir cómo se construye el perfil y cómo se calcula la relevancia de los elementos recomendados.

## Drivers

- RF-20, RF-21 y RF-22.
- QA-P5.
- QA-SE3.
- QA-E3.
- CRN-10.

## Alternativas

1. Filtrado basado en contenido.
2. Filtrado colaborativo.
3. Estrategia híbrida entre filtrado colaborativo y basado en contenido.

## Decisión

Se selecciona **Content-Based Filtering**.

El perfil del usuario será híbrido y combinará:

- Preferencias explícitas.
- Preferencias inferidas del historial.
- Ajustes derivados del feedback.

Las preferencias explícitas marcadas como obligatorias actuarán como filtros previos a la puntuación.

La relevancia se calculará mediante representación vectorial y similitud coseno.

Las características del usuario y de los elementos deberán representarse en espacios compatibles.

El historial se obtendrá mediante una abstracción que consume proyecciones CQRS autorizadas.

## Consecuencias

**Positivas:**

- No requiere utilizar perfiles de otros usuarios.
- Permite explicar la relación entre preferencias y resultados.
- Mantiene el algoritmo desacoplado del dominio transaccional.
- Facilita incorporar nuevas categorías de recomendaciones.

**Negativas y riesgos:**

- Depende de la calidad de las características disponibles.
- Puede generar recomendaciones poco diversas.
- Los usuarios con poco historial pueden tener perfiles incompletos.
- Requiere definir normalización y ponderaciones de características.

## Alcance del prototipo

Se implementará la representación vectorial y la similitud coseno para alojamientos. Las categorías de transporte y destinos quedarán contempladas en la arquitectura, pero no se implementarán.

## Trazabilidad

ADD-4, ADD-6, ADR-015, RF-20–RF-22, QA-P5, QA-SE3 y QA-E3.
