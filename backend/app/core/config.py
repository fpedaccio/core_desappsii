"""Configuracion de la aplicacion, leida de variables de entorno."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

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

    # --- Seguridad --------------------------------------------------------
    # RS256 para que los otros 8 modulos validen tokens offline via JWKS.
    # Si no se configuran claves, se genera un par efimero al arrancar (solo dev).
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_kid: str = "core-key-1"
    jwt_issuer: str = "muni-core"
    jwt_audience: str = "muni-platform"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    cors_origins: Annotated[list[str], NoDecode] = Field(default=["http://localhost:3000"])

    # Usuario administrador inicial creado por el seed.
    seed_admin_email: str = "admin@muni.uade.edu.ar"
    seed_admin_password: str = "Admin123!"

    # --- Notificaciones ---------------------------------------------------
    # Sin credenciales SMTP los envios de email caen al canal mock y quedan
    # registrados igual, para poder demostrar el flujo sin servidor de correo.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@muni.uade.edu.ar"
    smtp_use_tls: bool = True

    # --- Monitoreo --------------------------------------------------------
    health_poll_interval_seconds: int = 60
    health_poll_timeout_seconds: float = 5.0

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

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
