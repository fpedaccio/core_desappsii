# Decisiones de arquitectura (ADR)

Un ADR por decisión que sería cara de revertir. Cada uno dice qué problema
concreto resolvía, qué se decidió y qué se perdió al decidirlo.

| ADR | Decisión | Patrón | Tipo |
|:---|:---|:---|:---|
| [ADR-001](ADR-001-state-ciclo-de-vida-de-la-entrega.md) | El ciclo de vida de una entrega es una máquina de estados explícita | State | GoF · comportamiento |
| [ADR-002](ADR-002-strategy-politica-de-reintentos.md) | La política de reintentos es una Strategy inyectable | Strategy | GoF · comportamiento |
| [ADR-003](ADR-003-adapter-broker-de-mensajeria.md) | El broker vive detrás de un Adapter | Adapter | GoF · estructural / integración |
| [ADR-004](ADR-004-grasp-fabricacion-pura-capa-de-repositorios.md) | La capa de repositorios es una fabricación pura | Pure Fabrication + Indirection | GRASP |

Los cuatro están fijados con pruebas en `backend/tests/test_patrones.py`: si
alguien deshace la decisión, la suite falla.
