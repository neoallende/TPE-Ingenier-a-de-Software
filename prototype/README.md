# Trotamundos prototype

## Levantar todo el sistema

Desde este directorio, un solo comando construye e inicia el prototipo de reservas y el recomendador:

```bash
docker compose up --build -d
```

Esto inicia PostgreSQL, RabbitMQ, la API de reservas, el relay Outbox, el consumidor CQRS, el simulador de proveedor, la API del recomendador, la carga de datos demo y el generador periódico.

No hace falta crear un archivo `.env`: las variables locales de desarrollo están declaradas en `docker-compose.yml`. Para cambiar el secreto JWT del recomendador, se puede exportar `RECO_JWT_SECRET` antes de ejecutar Compose.

## Detener el sistema

```bash
docker compose down
```

Esto detiene y elimina los contenedores y la red, pero conserva los datos de PostgreSQL y del recomendador en sus volúmenes.

Para borrar también todos los datos persistidos:

```bash
docker compose down -v
```

**Atención:** `down -v` elimina las bases de datos del prototipo y del recomendador.

## Interfaces

- API de reservas: http://localhost:8000/docs
- Simulador de proveedor: http://localhost:8001/docs
- API del recomendador: http://localhost:8100/docs
- RabbitMQ management: http://localhost:15672

El endpoint de token de desarrollo del recomendador está habilitado por defecto para la demo (`RECO_DEV_TOKEN_ENDPOINT=true`). No debe habilitarse en un despliegue productivo.

## Alcance de la integración actual

Los servicios se construyen, inician y detienen juntos con Docker Compose. El recomendador conserva su propia base SQLite y el seed carga un catálogo y reservas de demostración. **La proyección real de reservas de PostgreSQL todavía no alimenta el recomendador**; esa integración de datos requiere incorporar `user_id` y `accommodation_id` al contrato de reservas y conectar el consumidor/proyección con el almacenamiento del recomendador.

El flujo de reservas del prototipo se puede probar con `POST /simulate` en Swagger del simulador y consultar luego `GET /reservations/{reservation_id}` en la API. La proyección es asíncrona.

Esto es un prototipo, no está preparado para producción.
