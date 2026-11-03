"""Configuracion de la aplicacion, leida de variables de entorno."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Aplicacion -------------------------------------------------------
    app_name: str = "Municipalidad UADE - Core"
    module_name: str = "core"
    environment: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"

    # --- Base de datos ----------------------------------------------------
    # El Core tiene su propia base. Ningun otro modulo la accede (requisito 6.3).
    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/muni_core"

    @field_validator("database_url", mode="after")
    @classmethod
    def _driver_async(cls, valor: str) -> str:
        """Completa el driver async si la URL viene sin el.

        Railway, Render, Heroku y Neon entregan la URL como `postgresql://` (y
        algunos todavia como `postgres://`). SQLAlchemy la lee como sincronica,
        busca psycopg2 —que no esta instalado, porque el Core es async— y falla
        con `No module named 'psycopg2'`, que no dice nada del problema real.

        Copiar y pegar la URL del panel es lo primero que hace cualquiera, asi
        que se arregla aca en vez de ponerlo como advertencia en un documento.
        """
        if valor.startswith("postgres://"):
            return valor.replace("postgres://", "postgresql+asyncpg://", 1)
        if valor.startswith("postgresql://"):
            return valor.replace("postgresql://", "postgresql+asyncpg://", 1)
        return valor
    db_echo: bool = False

    # --- Broker -----------------------------------------------------------
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    # Si el broker no esta disponible el Core arranca igual y sirve la API:
    # un error de infraestructura no debe tirar el modulo (regla 7).
    broker_required: bool = False

    exchange_inbox: str = "muni.inbox"
    exchange_events: str = "muni.events"
    exchange_retry: str = "muni.retry"
    exchange_dlx: str = "muni.dlx"
    queue_inbox: str = "core.inbox"
    queue_dlq: str = "q.dlq"

    # Backoff de reintentos en segundos. Agotados todos, el mensaje va a la DLQ.
    # NoDecode: sin esto pydantic-settings intentaria parsear la variable de
    # entorno como JSON antes de que corra el validador que acepta CSV.
    retry_delays: Annotated[list[int], NoDecode] = Field(default=[5, 30, 120, 600])

    # Identidad del publicador por AMQP (DEF-19). Por HTTP el modulo sale del
    # token; por AMQP, del usuario de la conexion, que llega en la propiedad
    # `user_id` del mensaje (ver app/services/source_identity.py).
    #   off     no se comprueba.
    #   warn    se registra la discrepancia y el evento se acepta: DEF-19 sigue
    #           sin mitigar, sirve solo como transicion acordada.
    #   enforce se rechaza a la DLQ (SOURCE_UNVERIFIED), sin entregas.
    amqp_source_check: Literal["off", "warn", "enforce"] = "warn"
    # Vinculo usuario AMQP -> modulo, como CSV `usuario=modulo` o JSON. Un
    # usuario sin entrada no identifica a ningun modulo.
    amqp_identities: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)

    # --- Seguridad --------------------------------------------------------
    # Sin claves configuradas se genera un par efimero al arrancar (solo dev):
    # los tokens dejan de valer al reiniciar. En produccion es obligatoria.
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_issuer: str = "muni-core"
    jwt_audience: str = "muni-platform"
    # El token del dashboard. Sin refresh: cuando expira se vuelve a loguear.
    access_token_ttl_minutes: int = 15

    cors_origins: Annotated[list[str], NoDecode] = Field(default=["http://localhost:3000"])

    # Con `true`, el servidor de la API tambien consume de core.inbox y q.dlq en
    # su propio loop, en vez de necesitar `python -m app.workers.inbox_worker`
    # aparte. Es la diferencia entre desplegar un proceso y desplegar dos, que
    # en un plan gratuito suele ser la diferencia entre poder y no poder.
    #
    # El costo: los consumidores comparten el event loop con las peticiones
    # HTTP, no se escalan por separado, y si uno se cae se cae todo. Para el
    # volumen de este TP no se nota; para algo serio, van separados.
    run_worker: bool = False

    # Con `true`, el arranque corre el seed si hace falta. Es idempotente, asi
    # que no duplica nada ni rota secrets ya generados. Sirve para desplegar sin
    # tener que entrar por consola a correr un comando a mano.
    #
    # Los secrets de maquina NO se imprimen en este modo: terminarian en los
    # logs de la plataforma. Se obtienen con rotate-secret.
    seed_on_startup: bool = False

    @field_validator("cors_origins", "retry_delays", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Permite pasar listas como CSV en la variable de entorno."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value  # JSON, lo parsea pydantic
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("amqp_identities", mode="before")
    @classmethod
    def _parse_identities(cls, value: object) -> object:
        """Acepta `usuario=modulo,otro=modulo` ademas de JSON."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{"):
                return {u.strip(): str(m).strip().lower() for u, m in json.loads(stripped).items()}
            pares = {}
            for item in stripped.split(","):
                if not item.strip():
                    continue
                usuario, separador, modulo = item.partition("=")
                if not separador or not usuario.strip() or not modulo.strip():
                    raise ValueError(f"AMQP_IDENTITIES espera usuario=modulo, no '{item.strip()}'.")
                pares[usuario.strip()] = modulo.strip().lower()
            return pares
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
