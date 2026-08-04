"""Carga los datos iniciales del Core.

    python -m app.seeds                 # crea tablas si faltan y siembra
    python -m app.seeds --no-clients    # sin cuentas de servicio de los modulos
    python -m app.seeds --drop          # recrea el esquema desde cero (destructivo)
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from app.core.config import settings
from app.core.database import Base, SessionFactory, engine
from app.core.logging import configure_logging
from app.seeds.bootstrap import seed_all

# Importa todos los modelos para que `Base.metadata` este completo.
import app.models  # noqa: F401  isort:skip

logger = structlog.get_logger(__name__)


async def main(*, drop: bool, create_clients: bool) -> int:
    configure_logging()

    if drop:
        if settings.is_production:
            print("ERROR: --drop esta deshabilitado en produccion.", file=sys.stderr)
            return 2
        confirmation = input(
            f"Se va a BORRAR el esquema completo de {_redact(settings.database_url)}.\n"
            "Escribi 'si' para confirmar: "
        )
        if confirmation.strip().lower() != "si":
            print("Cancelado.")
            return 1

    async with engine.begin() as connection:
        if drop:
            await connection.run_sync(Base.metadata.drop_all)
            logger.warning("schema_dropped")
        # `create_all` es idempotente: no toca las tablas que ya existen.
        await connection.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        report = await seed_all(session, create_api_clients=create_clients)

    print("\n=== Datos iniciales cargados ===")
    print(report.summary())

    if report.api_clients:
        print("\n=== Cuentas de servicio de los modulos ===")
        print("Guarda estos secrets: el Core solo conserva su hash.\n")
        for client_id, secret in sorted(report.api_clients.items()):
            print(f"  {client_id:22} {secret}")
        print(
            "\nCada equipo se autentica con:\n"
            "  POST /api/v1/auth/token  "
            '{"clientId": "<modulo>", "clientSecret": "<secret>"}'
        )

    print(f"\nAdministrador: {settings.seed_admin_email} / {settings.seed_admin_password}")
    print("Swagger: http://localhost:8000/docs\n")
    return 0


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***@{host}"


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            main(
                drop="--drop" in sys.argv,
                create_clients="--no-clients" not in sys.argv,
            )
        )
    )
