"""Carga los datos iniciales: los 9 modulos y los eventos del board de Miro.

Es idempotente: se puede correr cuantas veces se quiera. Con `--drop` recrea las
tablas desde cero.

    python -m app.seeds
    python -m app.seeds --drop
"""

from __future__ import annotations

import asyncio
import os
import sys

import structlog

from app.core.config import settings
from app.core.database import Base, SessionFactory, engine
from app.core.logging import configure_logging
from app.core.security import generate_opaque_token, hash_opaque_token, hash_password
from app.models.catalog import Barrio, ItemDeCatalogo, Zona
from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.models.users import User
from app.repositories.catalog_repository import (
    BarrioRepository,
    ItemDeCatalogoRepository,
    ZonaRepository,
)
from app.repositories.registry_repository import (
    EventTypeRepository,
    ModuleRepository,
    PublicationRepository,
    SubscriptionRepository,
    UserRepository,
)
from app.seeds.board_events import DESCRIPTIONS, MISMATCHES, MODULES
from app.seeds.territorio import BARRIOS, CATALOGOS, ZONAS

logger = structlog.get_logger(__name__)

SEED_PASSWORD = os.environ.get("SEED_INITIAL_PASSWORD", "Cambiala123")
"""Contrasena de las cuentas iniciales. Es de desarrollo: hay que cambiarla."""


async def run(*, drop: bool = False) -> None:
    configure_logging()
    if settings.is_production:
        if drop:
            raise RuntimeError("No se permite --drop en produccion.")
        if SEED_PASSWORD == "Cambiala123" or len(SEED_PASSWORD) < 16:
            raise RuntimeError(
                "Produccion requiere SEED_INITIAL_PASSWORD de al menos 16 caracteres."
            )

    async with engine.begin() as connection:
        if drop:
            await connection.run_sync(Base.metadata.drop_all)
            logger.warning("schema_dropped")
        await connection.run_sync(Base.metadata.create_all)

    secrets: dict[str, str] = {}
    counts = {
        "modules": 0,
        "users": 0,
        "event_types": 0,
        "subscriptions": 0,
        "publications": 0,
        "zonas": 0,
        "barrios": 0,
        "items_de_catalogo": 0,
    }

    async with SessionFactory() as session:
        module_repo = ModuleRepository(session)
        event_type_repo = EventTypeRepository(session)
        subscription_repo = SubscriptionRepository(session)
        publication_repo = PublicationRepository(session)
        user_repo = UserRepository(session)

        # --- tipos de evento ------------------------------------------
        all_types = sorted({e for _, _, _, pub, con in MODULES for e in pub + con})
        type_by_name: dict[str, EventType] = {}

        for name in all_types:
            existing = await event_type_repo.get_by_name(name)
            if existing is None:
                existing = EventType(
                    name=name,
                    description=DESCRIPTIONS.get(name, ""),
                    # El dueno se completa mas abajo, cuando se sabe quien publica.
                    owner_module=None,
                    discovered=False,
                    json_schema=None,
                    total_received=0,
                )
                event_type_repo.add(existing)
                counts["event_types"] += 1
            elif not existing.description:
                existing.description = DESCRIPTIONS.get(name, "")
            type_by_name[name] = existing
        await session.flush()

        # --- modulos --------------------------------------------------
        module_by_name: dict[str, ModuleAccount] = {}
        for name, display, team, published, _consumed in MODULES:
            module = await module_repo.get_by_name(name)
            if module is None:
                module = ModuleAccount(
                    name=name,
                    display_name=display,
                    team=team,
                    description="",
                    is_admin=(name == "core"),
                    active=True,
                    queue_name=f"q.{name}",
                )
                module_repo.add(module)
                counts["modules"] += 1

            # El secret se regenera solo si el modulo no tenia: correr el seed de
            # nuevo no invalida las credenciales que los equipos ya estan usando.
            if not module.secret_hash:
                secret = generate_opaque_token()
                module.secret_hash = hash_opaque_token(secret)
                secrets[name] = secret

            module_by_name[name] = module

            # El primero que declara publicar un tipo queda como su dueno.
            for event_name in published:
                event_type = type_by_name[event_name]
                if event_type.owner_module is None:
                    event_type.owner_module = name
        await session.flush()

        # --- publicaciones y suscripciones ----------------------------
        for name, _display, _team, published, consumed in MODULES:
            module = module_by_name[name]

            for event_name in published:
                event_type = type_by_name[event_name]
                if await publication_repo.find_pair(module.id, event_type.id) is None:
                    publication_repo.add(
                        Publication(module_id=module.id, event_type_id=event_type.id, active=True)
                    )
                    counts["publications"] += 1

            for event_name in consumed:
                event_type = type_by_name[event_name]
                if await subscription_repo.find_pair(module.id, event_type.id) is None:
                    subscription_repo.add(
                        Subscription(
                            module_id=module.id,
                            event_type_id=event_type.id,
                            max_attempts=4,
                            active=True,
                        )
                    )
                    counts["subscriptions"] += 1

        # Una cuenta inicial por equipo, para que puedan entrar y despues crear
        # las de sus integrantes desde el dashboard.
        for name in module_by_name:
            email = f"{name}@muni.uade.edu.ar"
            if await user_repo.get_by_email(email) is None:
                user_repo.add(
                    User(
                        email=email,
                        password_hash=hash_password(SEED_PASSWORD),
                        full_name=f"Cuenta inicial de {name}",
                        module_id=module_by_name[name].id,
                        active=True,
                        failed_login_attempts=0,
                    )
                )
                counts["users"] += 1

        # --- catalogos globales ---------------------------------------
        # El enunciado le asigna al Core "barrios, zonas y catalogos globales"
        # (seccion 10, modulo 9). Es dato de arranque: la lista real se carga
        # despues por la API, sin tocar codigo.
        zona_repo = ZonaRepository(session)
        barrio_repo = BarrioRepository(session)
        item_repo = ItemDeCatalogoRepository(session)

        zona_por_codigo: dict[str, Zona] = {}
        for codigo, nombre, descripcion in ZONAS:
            zona = await zona_repo.get_by_codigo(codigo)
            if zona is None:
                zona = Zona(codigo=codigo, nombre=nombre, descripcion=descripcion, activo=True)
                zona_repo.add(zona)
                counts["zonas"] += 1
            zona_por_codigo[codigo] = zona

        await session.flush()

        for codigo, nombre, zona_codigo in BARRIOS:
            if await barrio_repo.get_by_codigo(codigo) is None:
                barrio_repo.add(
                    Barrio(
                        codigo=codigo,
                        nombre=nombre,
                        zona_id=zona_por_codigo[zona_codigo].id,
                        metadatos={},
                        activo=True,
                    )
                )
                counts["barrios"] += 1

        for catalogo, items in CATALOGOS.items():
            for codigo, nombre, descripcion, orden in items:
                if await item_repo.get_by_codigo(catalogo, codigo) is None:
                    item_repo.add(
                        ItemDeCatalogo(
                            catalogo=catalogo,
                            codigo=codigo,
                            nombre=nombre,
                            descripcion=descripcion,
                            orden=orden,
                            metadatos={},
                            activo=True,
                        )
                    )
                    counts["items_de_catalogo"] += 1

        await session.commit()

    _report(counts, secrets)
    await engine.dispose()


def _report(counts: dict[str, int], secrets: dict[str, str]) -> None:
    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    logger.info("seed_completed", summary=summary)

    print("\n=== Datos cargados ===")
    print(summary or "nada nuevo: ya estaba todo cargado")

    print("\n=== Entrar al dashboard (personas) ===")
    if settings.is_production:
        print("Contraseña inicial: la configurada en SEED_INITIAL_PASSWORD (no se muestra).")
    else:
        print(f"Una cuenta inicial por equipo, todas con la contrasena {SEED_PASSWORD!r}:\n")
    print(
        '  POST /api/v1/auth/login  {"email": "<modulo>@muni.uade.edu.ar", '
        '"password": "<contraseña inicial>"}'
    )
    print("\nCambiala en el primer ingreso, y despues cada equipo crea las cuentas")
    print("de sus integrantes con POST /api/v1/users.")
    print("\nEl equipo 9 entra con core@muni.uade.edu.ar y ve el trafico de todos.")

    if secrets:
        print("\n=== Secrets de maquina (publicar eventos) ===")
        print("Van en la config del backend de cada equipo, no los usa ninguna")
        print("persona. Guardalos: el Core solo conserva su hash.\n")
        for name, secret in sorted(secrets.items()):
            print(f"  {name:22} {secret}")
        print("\nEl backend de cada equipo obtiene su token con:")
        print('  POST /api/v1/auth/module-token  {"module": "<nombre>", "secret": "<secret>"}')
    else:
        print("\nLos secrets de maquina ya estaban generados y no se tocaron.")
        print("Para rotar uno:  POST /api/v1/modules/{nombre}/rotate-secret")

    print("\n=== Desalineaciones detectadas en el board ===")
    print("Los nombres se transcribieron tal cual, con typos incluidos:")
    print("corregirlos aca no arreglaria nada, porque el evento igual no")
    print("encontraria destino. Aparecen en /api/v1/dashboard/integration-alerts.\n")
    for left, right, detail in MISMATCHES:
        print(f"  {left}")
        print(f"    vs {right}")
        print(f"    {detail}\n")

    print("Swagger: http://localhost:8000/docs")
    print("Admin (ve todos los modulos): core")


if __name__ == "__main__":
    asyncio.run(run(drop="--drop" in sys.argv))
