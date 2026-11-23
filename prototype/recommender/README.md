# Módulo de recomendaciones – Iteración 6

Implementa el ADR-020. Núcleo en Python estándar; solo la capa HTTP usa FastAPI/Pydantic v2.

## Puesta en marcha integrada

Desde `prototype/`, levantar todos los servicios (reservas + recomendador) con:

```bash
docker compose up --build -d
```

El Compose principal inicia automáticamente la API de recomendaciones, carga el catálogo y los datos demo, y luego inicia el generador periódico. No ejecutar `docker-compose.reco.yml` por separado: el recomendador ya forma parte de `docker-compose.yml`.

Detener todo:

```bash
docker compose down
```

Borrar también los datos persistidos:

```bash
docker compose down -v
```

## Probar la API

Token de desarrollo (solo con `RECO_DEV_TOKEN_ENDPOINT=true`):

```bash
TOKEN=$(curl -s -X POST localhost:8100/dev/token -H 'content-type: application/json' \
  -d '{"sub":"demo-lujo","role":"user"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s localhost:8100/recommendations/me -H "authorization: Bearer $TOKEN"
```

Swagger: http://localhost:8100/docs

## Tests

```bash
cd recommender && python -m unittest discover -s tests -t . -v
```

## Integración de datos pendiente

La ejecución conjunta de los contenedores no implica todavía integración de datos. El recomendador usa SQLite y un catálogo/reservas demo propios; el prototipo de reservas usa PostgreSQL. Para que las recomendaciones se calculen con reservas reales todavía hay que agregar `user_id` y `accommodation_id` al contrato/evento de reserva y alimentar la proyección del recomendador desde el consumidor o migrar su persistencia a PostgreSQL.

## Variables de entorno

| Variable | Default | Significado |
|---|---|---|
| `RECO_DB_PATH` | `reco.db` | archivo SQLite |
| `RECO_JWT_SECRET` | `dev-secret-change-me` | clave HMAC de los tokens (cambiar fuera de desarrollo) |
| `RECO_TOKEN_TTL_SECONDS` | 3600 | vigencia de tokens de desarrollo |
| `RECO_DEV_TOKEN_ENDPOINT` | false | habilita `POST /dev/token` |
| `RECO_CYCLE_SECONDS` | 60 | frecuencia del generador |
| `RECO_TTL_SECONDS` | 600 | TTL de cada lista |
| `RECO_TOP_K` | 10 | tamaño de la lista |
| `RECO_MIN_PROFILE_INTERACTIONS` | 2 | umbral para dejar de ser cold start |
| `RECO_FEEDBACK_ALPHA` | 0.3 | tasa de aprendizaje del feedback |
| `RECO_MAX_RETRIES` / `RECO_RETRY_BACKOFF_SECONDS` | 3 / 0.5 | reintentos por usuario |
| `RECO_WEIGHTS` | todos 1 | pesos de las características |
| `RECO_VALID_RESERVATION_STATUSES` | `confirmed,completed` | estados que cuentan como historial |

## Endpoints

| Método y ruta | Rol | Descripción |
|---|---|---|
| `GET /recommendations/me` | user/admin | lista vigente (`status`: `fresh`, `expired`, `none`) |
| `POST /feedback` | user/admin | registrar aceptación, rechazo o puntuación |
| `GET/PUT /me/constraints` | user/admin | restricciones obligatorias |
| `GET /me/profile` | user/admin | perfil propio |
| `GET /admin/users/{id}/profile` | admin | perfil ajeno, auditado |
| `GET /admin/audit` | admin | registro de accesos |
| `POST /dev/token` | – | solo desarrollo |
