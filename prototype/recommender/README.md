# Módulo de recomendaciones – Iteración 6

Implementa el ADR-020. Núcleo en Python estándar (sin dependencias); solo la capa HTTP usa FastAPI/Pydantic v2.

## Puesta en marcha
```bash
cd prototype
docker compose -f docker-compose.yml -f docker-compose.reco.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.reco.yml --profile seed run --rm reco-seed

# token de desarrollo (solo con RECO_DEV_TOKEN_ENDPOINT=true)
TOKEN=$(curl -s -X POST localhost:8100/dev/token -H 'content-type: application/json' \
  -d '{"sub":"demo-lujo","role":"user"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s localhost:8100/recommendations/me -H "authorization: Bearer $TOKEN"
```
Sin Docker: `pip install -r requirements.txt`, `export RECO_JWT_SECRET=...`, `python -m trotamundos_reco.seed --demo`,
`uvicorn trotamundos_reco.api:create_app --factory --port 8100` y, en otra terminal, `python -m trotamundos_reco.generator`.

## Tests
```bash
cd prototype/recommender && python -m unittest discover -s tests -t . -v
```

## Integración con el prototipo existente (puntos a revisar)
1. **Montar en el FastAPI actual** (opcional, en vez de `reco-api`):
   `app.include_router(create_router(RecommenderService(SqlStore(Database(path)), settings), settings))`.
2. **Reservas con `user_id` y `accommodation_id`** (ADR-020 D3). Hay que:
   - agregar ambos campos al comando/evento de creación de reserva y a la proyección;
   - si la proyección vive en PostgreSQL: `ALTER TABLE <tabla> ADD COLUMN user_id TEXT, ADD COLUMN accommodation_id INTEGER;`
   - alimentar la tabla `reservation_projection` de este módulo desde el handler de la proyección
     (`SqlStore.upsert_reservation`) o apuntar `SqlStore` a la tabla existente.
   Los estados contados como "reserva válida" se configuran con `RECO_VALID_RESERVATION_STATUSES`.
3. **Base de datos**: el prototipo usa SQLite (WAL) en un volumen. Para PostgreSQL hay que cambiar el
   driver, los placeholders (`?` → `%s`) e `INSERT OR IGNORE` → `INSERT ... ON CONFLICT DO NOTHING` (confinado en `db.py`).
4. **Secreto JWT**: `RECO_JWT_SECRET` es obligatorio; el endpoint `/dev/token` debe estar apagado fuera de desarrollo.

## Variables de entorno
| Variable | Default | Significado |
|---|---|---|
| `RECO_DB_PATH` | `reco.db` | archivo SQLite |
| `RECO_JWT_SECRET` | (obligatoria) | clave HMAC de los tokens |
| `RECO_TOKEN_TTL_SECONDS` | 3600 | vigencia de tokens de desarrollo |
| `RECO_DEV_TOKEN_ENDPOINT` | false | habilita `POST /dev/token` |
| `RECO_CYCLE_SECONDS` | 60 | frecuencia del generador |
| `RECO_TTL_SECONDS` | 600 | TTL de cada lista |
| `RECO_TOP_K` | 10 | tamaño de la lista |
| `RECO_MIN_PROFILE_INTERACTIONS` | 2 | umbral para dejar de ser cold start |
| `RECO_FEEDBACK_ALPHA` | 0.3 | tasa de aprendizaje del feedback |
| `RECO_MAX_RETRIES` / `RECO_RETRY_BACKOFF_SECONDS` | 3 / 0.5 | reintentos por usuario |
| `RECO_WEIGHTS` | todos 1 | p. ej. `stars=1,price=1.5,zone=1,type=0.5,amenities=1` |
| `RECO_VALID_RESERVATION_STATUSES` | `confirmed,completed` | estados que cuentan como historial |

## Endpoints
| Método y ruta | Rol | Descripción |
|---|---|---|
| `GET /recommendations/me` | user/admin | lista vigente (`status`: `fresh`, `expired`, `none`) |
| `POST /feedback` | user/admin | `{feedback_id, accommodation_id, kind: accept\|reject\|rating, rating?}` |
| `GET/PUT /me/constraints` | user/admin | restricciones obligatorias |
| `GET /me/profile` | user/admin | perfil propio |
| `GET /admin/users/{id}/profile` | admin | perfil ajeno, **auditado** |
| `GET /admin/audit` | admin | registro de accesos |
| `POST /dev/token` | – | solo desarrollo |

## Estado de verificación
Los 25 tests del núcleo (dominio, servicio, persistencia, auth) pasan. La capa `api.py` y los archivos de Docker
**no se ejecutaron** en el entorno donde se escribieron (sin red para instalar FastAPI ni Docker): compilan, pero
conviene probarlos una vez integrados.
