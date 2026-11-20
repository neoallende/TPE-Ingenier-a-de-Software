# ADD-6 — Refinamiento del subsistema de recomendaciones

- **Estado:** Diseño propuesto.
- **Objetivo:** Refinar la arquitectura del subsistema de recomendaciones de Trotamundos, definiendo su algoritmo, gestión de perfiles, generación, persistencia, evaluación y mecanismos de resiliencia.
- **Iteración anterior:** ADD-4 (definición del subsistema y contrato inicial).
- **Base tecnológica:** ADD-5 (FastAPI, PostgreSQL, RabbitMQ y CQRS).
- **Alcance del prototipo:** Recomendaciones de alojamiento.

## 1. Propósito

ADD-6 profundiza el diseño del recomendador definido en ADD-4, que hasta ADD-5 permanecía como un subsistema lógico sin algoritmo ni implementación tecnológica seleccionados.

El objetivo es disponer de una arquitectura capaz de generar recomendaciones personalizadas a partir de las características de los elementos turísticos y del perfil individual de cada usuario.

Se mantiene el desacoplamiento mediante el puerto `RecommendationProvider`, evitando introducir dependencias directas entre el algoritmo y el dominio transaccional.

## 2. Drivers arquitectónicos

- RF-20: recomendaciones personalizadas.
- RF-21: interacción y feedback sobre recomendaciones.
- RF-22: ajustes y mejora de las recomendaciones.
- QA-P2: tiempo de respuesta de la aplicación web.
- QA-P5: comportamiento y rendimiento del módulo de recomendaciones.
- QA-A1: disponibilidad y tolerancia a fallos.
- QA-SE3: protección de información personal.
- QA-E3: evolución del sistema y posibilidad de sustituir el algoritmo.
- CRN-10: desacoplamiento del recomendador.

## 3. Alcance

La arquitectura contempla tres categorías de recomendaciones:

1. Alojamientos.
2. Transportes.
3. Destinos y rutas.

Sin embargo, el prototipo implementará únicamente recomendaciones de alojamiento. El contrato permitirá incorporar las otras categorías sin modificar la interfaz general del subsistema.

## 4. Decisiones de diseño

### 4.1. Estrategia de recomendación

Se selecciona **Content-Based Filtering**.

El sistema genera recomendaciones a partir de las características de los elementos disponibles y de las preferencias del usuario.

No se utilizará filtrado colaborativo ni se dependerá de las preferencias de otros usuarios para calcular recomendaciones individuales.

### 4.2. Perfil de usuario

Se define un perfil híbrido compuesto por:

- Preferencias explícitas configuradas por el usuario.
- Preferencias inferidas a partir de su historial de viajes.
- Ajustes derivados del feedback recibido.

Las preferencias explícitas pueden actuar como restricciones obligatorias o como preferencias de puntuación.

Las restricciones obligatorias se aplican como filtros previos al cálculo de similitud. Las preferencias restantes contribuyen a construir el vector de características del usuario.

El historial se obtiene mediante una abstracción de acceso a las proyecciones de lectura CQRS, sin consultar directamente las tablas transaccionales.

### 4.3. Algoritmo de puntuación

Se selecciona una representación vectorial de las características del usuario y de los elementos recomendables.

La similitud se calcula mediante similitud coseno:

\[
\operatorname{sim}(u,i)=
\frac{u\cdot i}{\|u\|\|i\|}
\]

Donde:

- \(u\) representa el vector de preferencias del usuario.
- \(i\) representa el vector de características del elemento.

El procedimiento general es:

1. Obtener el perfil autorizado del usuario.
2. Obtener los elementos candidatos.
3. Aplicar las restricciones obligatorias.
4. Representar los elementos elegibles mediante vectores.
5. Calcular la similitud coseno.
6. Ordenar los resultados por puntuación.
7. Persistir las recomendaciones generadas.

La definición concreta de características, normalización y ponderaciones se considera parte del refinamiento de implementación del algoritmo.

### 4.4. Generación de recomendaciones

Se selecciona una estrategia de generación precalculada.

Un proceso de fondo ejecuta periódicamente el algoritmo y almacena los resultados en PostgreSQL.

La API de consulta no ejecuta el algoritmo en tiempo real: recupera las recomendaciones previamente generadas.

El feedback se procesa asincrónicamente mediante RabbitMQ. La actualización del perfil no provoca una regeneración inmediata: los nuevos resultados se obtienen en el siguiente ciclo periódico.

La evaluación del algoritmo y sus posibles revisiones se realizan separadamente del procesamiento individual de feedback.

### 4.5. Persistencia

Se utiliza el PostgreSQL existente, con separación lógica de las estructuras del recomendador.

Se contemplan las siguientes entidades conceptuales:

- Perfil de recomendaciones del usuario.
- Recomendación generada.
- Elementos asociados a cada recomendación.
- Feedback de recomendaciones.

Los nombres físicos de tablas y sus atributos definitivos corresponden al diseño del esquema de implementación.

No se duplicará el historial de viajes: se consultarán las proyecciones CQRS mediante la abstracción correspondiente.

### 4.6. Contrato de recomendaciones

Se conserva el contrato estable definido por ADR-015, refinándolo mediante un modelo común con extensiones tipadas.

El contrato común contempla:

- Identificador de recomendación.
- Identificador del usuario.
- Puntuación.
- Fecha de generación.
- Versión del modelo o algoritmo.
- Contenido específico de la recomendación.

Las extensiones contemplan información particular de alojamiento, transporte o destino.

El prototipo implementará únicamente la extensión de alojamiento.

### 4.7. Despliegue

El recomendador se implementará inicialmente como un módulo interno de la aplicación FastAPI existente.

Se mantienen límites lógicos claros entre:

- Gestión del perfil.
- Obtención de características.
- Motor de recomendación.
- Generación y persistencia.
- Consulta de recomendaciones.
- Registro y procesamiento de feedback.

Esta organización permite una extracción futura a un servicio independiente sin modificar el contrato público.

### 4.8. Evaluación

Se adopta una estrategia combinada:

- Feedback del usuario: aceptación, rechazo y calificaciones.
- Métricas de ranking: Precision@K, Recall@K y NDCG@K, cuando existan datos de referencia.
- Cobertura y diversidad de recomendaciones.

La disponibilidad de datos de referencia condiciona la aplicación de las métricas de ranking.

### 4.9. Seguridad y privacidad

Se establece aislamiento estricto por usuario.

La identidad se obtiene del contexto autenticado y no de un identificador arbitrario enviado por el cliente.

Los administradores autorizados pueden acceder a perfiles para soporte, auditoría y diagnóstico, mediante permisos específicos y registro de accesos.

El recomendador no debe utilizar perfiles de otros usuarios para generar recomendaciones individuales.

### 4.10. Resiliencia y vigencia

Se conservan las últimas recomendaciones válidas cuando una generación falla.

Se define un tiempo máximo de vigencia (TTL) configurable.

- Mientras las recomendaciones estén vigentes, se podrán consultar aunque falle una generación posterior.
- Si vencen y no existen resultados nuevos, la API devolverá una lista vacía.
- Los fallos del recomendador no deben impedir la consulta de viajes y reservas.
- Los procesos de generación deberán poder reintentarse sin duplicar efectos.

## 5. Vista de componentes

La vista detallada se encuentra en `Vistas/Vista-Recomendador-ADD6.md`.

Componentes principales:

1. API de recomendaciones.
2. Puerto `RecommendationProvider`.
3. Gestor de perfiles.
4. Proveedor de características basado en proyecciones CQRS.
5. Motor de recomendación basado en contenido.
6. Generador periódico.
7. Repositorio de recomendaciones.
8. Consumidor de eventos de feedback.
9. RabbitMQ.

## 6. Flujo principal

1. El generador periódico inicia un ciclo.
2. Obtiene los usuarios que deben procesarse.
3. Recupera los perfiles y las características autorizadas.
4. Aplica restricciones obligatorias.
5. Calcula la similitud entre perfiles y alojamientos.
6. Persiste los resultados y su fecha de generación.
7. La API recupera las recomendaciones vigentes cuando el usuario las solicita.

En paralelo, las interacciones del usuario se registran y publican como eventos de feedback. Un consumidor actualiza el perfil de manera asíncrona.

## 7. Atributos de calidad

| Atributo | Decisión arquitectónica |
|---|---|
| Rendimiento | Generación precalculada y consulta de resultados persistidos. |
| Disponibilidad | Últimos resultados válidos y degradación controlada. |
| Resiliencia | Procesamiento asíncrono y reintentos. |
| Seguridad | Aislamiento por usuario y autorización administrativa. |
| Evolución | Contrato estable y extensiones tipadas. |
| Mantenibilidad | Separación lógica de responsabilidades. |
| Evaluabilidad | Feedback y métricas de calidad del ranking. |

Estas decisiones contribuyen a los atributos de calidad, pero no demuestran por sí mismas el cumplimiento de los objetivos cuantitativos de producción.

## 8. Alcance del prototipo

Se implementará:

- Perfil híbrido de usuario.
- Obtención de características desde proyecciones CQRS.
- Recomendaciones de alojamiento.
- Representación vectorial y similitud coseno.
- Aplicación de restricciones obligatorias.
- Generación periódica mediante proceso de fondo.
- Persistencia en PostgreSQL.
- Procesamiento asíncrono de feedback mediante RabbitMQ.
- Consulta de recomendaciones con control de vigencia.
- Conservación de resultados anteriores ante fallos.

Quedan fuera de la implementación del prototipo:

- Recomendaciones de transporte.
- Recomendaciones de destinos y rutas.
- Extracción del recomendador a un microservicio independiente.
- Validación de objetivos de escala de producción.
- Demostración de disponibilidad mensual de producción.

## 9. Riesgos y asuntos pendientes

- La calidad de las recomendaciones depende de la disponibilidad y calidad de las características.
- La consistencia entre feedback, perfil y recomendaciones es eventualmente consistente.
- Los perfiles con pocos datos pueden generar recomendaciones poco precisas.
- Las características de cada categoría deberán normalizarse de manera compatible con su representación vectorial.
- La frecuencia de generación y el TTL deberán configurarse y validarse mediante pruebas.
- Los accesos administrativos requieren una política de autorización y auditoría verificable.

## 10. Criterio de salida

ADD-6 se considerará validada cuando el prototipo permita:

1. Obtener un perfil híbrido desde fuentes autorizadas.
2. Generar recomendaciones de alojamiento mediante similitud coseno.
3. Aplicar restricciones obligatorias.
4. Persistir y consultar recomendaciones precalculadas.
5. Procesar feedback asincrónicamente.
6. Mantener resultados válidos ante fallos de generación.
7. Respetar el aislamiento por usuario.
8. Aplicar el TTL configurado.

La validación deberá distinguir entre comportamientos comprobados mediante pruebas y objetivos que continúan pendientes de evaluación en un entorno representativo de producción.

## 11. Trazabilidad

- ADD-4: definición del subsistema de recomendaciones.
- ADR-015: contrato estable del recomendador.
- ADD-5: tecnologías y técnicas del prototipo integrado.
- ADR-016: stack y técnicas del prototipo.
- ADD-6: refinamiento específico del recomendador.
- ADR-017: algoritmo y perfil de usuario.
- ADR-018: generación, persistencia y resiliencia.
- ADR-019: seguridad y acceso a perfiles.
