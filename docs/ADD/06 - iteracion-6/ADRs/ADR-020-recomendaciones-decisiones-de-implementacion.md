# ADR-020: Decisiones de implementación del módulo de recomendaciones (Iteración 6)

- **Estado:** Propuesto
- **Fecha:** 2026-11-20
- **Relacionado con:** ADR-019 (identidad y auditoría), ADD-5 (identidad fuera de alcance), Iteración 6 (recomendaciones)

> Nota: la numeración (020) y la ubicación del archivo son supuestas; ajustarlas a la convención del repositorio.

## 1. Contexto

La documentación de la Iteración 6 define la estrategia de recomendación, los flujos de generación y feedback, el TTL con lista vacía al vencer, la conservación de las últimas recomendaciones válidas y el puerto `RecommendationProvider` con el recomendador dentro de FastAPI. Delega a la "implementación" ocho cuestiones que bloquean el desarrollo:

1. de dónde salen los alojamientos candidatos;
2. cómo se construye el vector de características;
3. cómo el feedback modifica el perfil;
4. cómo se infiere el perfil desde el historial;
5. cómo se obtiene la identidad y los roles;
6. cuál es la API concreta y el esquema de datos;
7. cuáles son los parámetros operativos y qué es un perfil con pocos datos;
8. casos límite (cero candidatos, reintentos, métricas).

Las proyecciones CQRS del prototipo guardaban solo `hotel_name`, fechas y estado, por `reservation_id` y sin `user_id`; no existía catálogo de alojamientos.

## 2. Decisión

### D1. Catálogo propio detrás de un puerto
Se crea la tabla `accommodations` (id, nombre, zona, tipo, estrellas, precio por noche, amenities), cargada con 40 alojamientos de ejemplo por un script de seed determinístico. El recomendador accede al catálogo a través del repositorio, por lo que una fuente real puede reemplazarlo sin tocar el dominio. El puerto `RecommendationProvider` (`get_recommendations`, `submit_feedback`) se mantiene como única dependencia del resto del sistema.

### D2. Vector de características
Cada alojamiento se codifica como vector de dimensión 21:

| Bloque | Codificación |
|---|---|
| Estrellas | `(estrellas − 1) / 4` ∈ [0, 1] |
| Precio por noche | min–max sobre el catálogo ∈ [0, 1] |
| Zona (6) | one-hot |
| Tipo (5) | one-hot |
| Amenities (8) | multi-hot |

Cada bloque se multiplica por un peso configurable (`RECO_WEIGHTS`, por defecto 1). La afinidad se mide con **similitud coseno** entre el perfil y el vector del alojamiento; el desempate es por `id` para que el resultado sea determinístico.

### D3. Historial y perfil inferido
La reserva incorpora `user_id` y `accommodation_id`, y la proyección CQRS los conserva. El perfil inferido es el **promedio de los vectores** de los alojamientos con reservas en estado válido (`confirmed`, `completed`; configurable). Mientras el perfil provenga del historial se recalcula en cada ciclo; una vez que recibe feedback pasa a ser incremental (`source = feedback`) y deja de recalcularse.

### D4. Feedback
Cada feedback lleva un `feedback_id` provisto por el cliente. El efecto sobre el perfil `p` con el vector del ítem `v` es:

`p' = p + α · s · (v − p)`, con α = 0,3 por defecto y componentes recortados a ≥ 0.

| Acción | Señal `s` |
|---|---|
| aceptar | +1 |
| rechazar | −1 |
| calificación `r` ∈ {1…5} | `(r − 3) / 2` ∈ [−1, 1] |

Un alojamiento cuyo último feedback sea negativo se excluye de futuras listas de ese usuario. **Idempotencia:** `(user_id, feedback_id)` es clave primaria; el alta del feedback y la actualización del perfil ocurren en una única transacción, y un reenvío del mismo `feedback_id` no produce efectos.

### D5. Identidad y roles (mecanismo mínimo y provisional)
Tokens JWT HS256 firmados con HMAC, con claims `sub`, `role` (`user` | `admin`), `iat` y `exp`, en el mismo estilo que la firma del webhook. La identidad se toma **siempre del token**: ningún endpoint de usuario recibe un `user_id` por parámetro, lo que garantiza el aislamiento entre usuarios. Se rechaza `alg` distinto de HS256, firma inválida, token vencido o claims inválidos. No hay login real: `POST /dev/token` emite tokens y solo se habilita con `RECO_DEV_TOKEN_ENDPOINT=true`. Esto **no reabre** la decisión de ADD-5; es el mínimo para cumplir ADR-019 y debe reemplazarse cuando se incorpore un proveedor de identidad.

### D6. Auditoría de accesos de administrador
Cada acceso de un admin al perfil de otro usuario se registra en `profile_access_audit` (admin, usuario consultado, acción, instante) **antes** de devolver el dato; si el registro falla, el acceso falla. Los usuarios sin rol admin reciben 403 y no generan registros.

### D7. Parámetros por defecto (variables de entorno)
Ciclo cada **60 s**, TTL de **10 min** (600 s), **top-10**, umbral de perfil **2 interacciones**, 3 reintentos con backoff exponencial desde 0,5 s. Un perfil es de **cold start** si tiene menos interacciones que el umbral (reservas válidas + feedbacks) o vector nulo; en ese caso se ordena por popularidad (reservas válidas por alojamiento), luego estrellas, luego menor precio.

### D8. Casos límite
- **Cero candidatos tras las restricciones obligatorias:** se guarda una lista vacía con `reason = no_candidates` y TTL nuevo. Las restricciones obligatorias nunca se relajan.
- **Reintentabilidad sin duplicar efectos:** la generación es un *upsert* por `user_id`, por lo que repetirla es seguro. Los reintentos son por usuario, y el fallo de uno no afecta a los demás.
- **Fallo de generación:** no se escribe nada; la lista previa se conserva y vence por su propio TTL. Vencido el TTL, la lectura devuelve lista vacía (`status = expired`).
- **Métricas (punto 4.8):** se implementan Precision@K y NDCG@K de forma offline, tomando como referencia el feedback del propio usuario (positivo = relevante, ganancia = señal). Sin una muestra externa de relevancia no se calculan métricas agregadas.

### D9. Esquema y API
Tablas: `accommodations`, `reservation_projection` (con `user_id`, `accommodation_id`), `user_constraints`, `user_profiles`, `feedback`, `recommendation_sets`, `profile_access_audit`.

| Endpoint | Rol |
|---|---|
| `GET /recommendations/me` | user / admin |
| `POST /feedback` | user / admin |
| `GET`, `PUT /me/constraints` | user / admin |
| `GET /me/profile` | user / admin |
| `GET /admin/users/{id}/profile` | admin (auditado) |
| `GET /admin/audit` | admin |
| `POST /dev/token` | solo desarrollo |

El generador corre como proceso aparte (`reco-generator` en Docker Compose) y comparte la base con la API.

## 3. Alternativas consideradas

| Decisión | Alternativa | Motivo del descarte |
|---|---|---|
| Catálogo | Fuente externa real (API de terceros) | Fuera de alcance del prototipo; el puerto permite incorporarla luego |
| Similitud | Factorización matricial / filtrado colaborativo | Requiere volumen de interacciones que el prototipo no tiene; el enfoque basado en contenido funciona con un solo usuario |
| Feedback | Recalcular todo el perfil desde cero | Costoso y pierde el efecto de rechazos; la regla incremental es simple y explicable |
| Identidad | Proveedor OAuth/OIDC | Contradice ADD-5 (identidad fuera de alcance) |
| Cero candidatos | Relajar restricciones | Violaría restricciones obligatorias |

## 4. Consecuencias

**Positivas:** decisiones explícitas y verificables; el dominio es puro y testeable; aislamiento por construcción; auditoría exigida por ADR-019 cubierta; fuente de catálogo e identidad reemplazables.

**Negativas / deudas conocidas:**
- Requiere cambiar el comando, el evento y la proyección de reservas (`user_id`, `accommodation_id`).
- El vector depende del rango de precios del catálogo: si cambia, los perfiles ya guardados deben recalcularse.
- Un perfil que ya recibió feedback no incorpora automáticamente reservas posteriores.
- Los datos del catálogo son sintéticos; la calidad de las recomendaciones no está validada con usuarios reales.
- SQLite es suficiente para el prototipo; producción requiere migrar a PostgreSQL.
- La identidad es provisional y sin gestión de usuarios.

## 5. Verificación

Los tests automáticos (`prototype/recommender/tests/test_reco.py`) cubren estos comportamientos. Alinear la numeración con los 8 puntos del criterio de salida del documento de la iteración.

| Comportamiento | Tests |
|---|---|
| Similitud coseno y vector normalizado | `test_cosine`, `test_vector_normalised_and_sized` |
| Restricciones obligatorias y cero candidatos | `test_mandatory_constraints_never_violated`, `test_zero_candidates_yields_empty_with_reason` |
| TTL con lista vacía al vencer | `test_ttl_expires_to_empty_list` |
| Aislamiento entre usuarios | `test_users_are_isolated` |
| Idempotencia del feedback | `test_feedback_is_idempotent` |
| Conservación de resultados ante fallos y reintentos | `test_last_valid_set_kept_when_generation_fails`, `test_retry_recovers_without_duplicating_state` |
| Regla de feedback y cold start | `test_accept_moves_closer_and_reject_moves_away`, `test_cold_start_when_few_data` |
| Identidad y auditoría | `test_token_roundtrip_and_failures`, `test_alg_none_rejected`, `test_admin_access_is_audited_and_user_denied` |
| Métricas | `test_precision_and_ndcg`, `test_evaluate_user` |
