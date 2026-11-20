# ADR-019: Aislamiento y acceso administrativo a perfiles de recomendación

- **Estado:** Aceptado para el diseño.
- **Iteración:** ADD-6.
- **Relacionado con:** ADR-015.

## Contexto

El recomendador utiliza preferencias explícitas, historial de viajes y feedback para construir perfiles individuales.

Estos datos pueden contener información personal y deben protegerse frente a accesos no autorizados.

Además, se requiere permitir tareas administrativas de soporte, auditoría y diagnóstico sin otorgar acceso indiscriminado a todos los perfiles.

## Drivers

- QA-SE3.
- QA-A1.
- QA-E3.
- CRN-10.

## Alternativas

1. Aislamiento estricto por usuario sin acceso administrativo.
2. Aislamiento por usuario con acceso administrativo controlado.
3. Perfiles anonimizados para análisis como estrategia adicional.

## Decisión

Se selecciona el aislamiento por usuario con acceso administrativo controlado.

Las reglas serán:

- Cada usuario podrá acceder únicamente a su propio perfil, feedback y recomendaciones.
- La identidad se obtendrá del contexto autenticado.
- No se confiará en identificadores de usuario proporcionados libremente por el cliente.
- Los administradores autorizados podrán acceder a perfiles para soporte, auditoría y diagnóstico.
- El acceso administrativo requerirá permisos específicos.
- Los accesos administrativos deberán quedar registrados para auditoría.

El recomendador utilizará únicamente los datos autorizados correspondientes al usuario cuya recomendación se está generando.

## Consecuencias

**Positivas:**

- Reduce el riesgo de exposición cruzada de perfiles.
- Mantiene la posibilidad de realizar soporte y diagnóstico.
- Permite controlar y auditar los accesos administrativos.

**Negativas y riesgos:**

- Requiere integración correcta con el mecanismo de identidad y autorización existente.
- Introduce responsabilidades adicionales de auditoría.
- Los permisos administrativos deben mantenerse actualizados y revisarse periódicamente.

## Alcance del prototipo

El prototipo deberá respetar el aislamiento por usuario y contemplar la autorización administrativa. La implementación concreta de roles, permisos y auditoría deberá integrarse con las capacidades de seguridad definidas en iteraciones anteriores.

## Trazabilidad

ADD-3, ADD-4, ADD-6, ADR-015, QA-SE3 y CRN-10.
