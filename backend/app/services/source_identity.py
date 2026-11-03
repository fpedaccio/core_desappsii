"""Que el `sourceModule` de un evento por AMQP corresponda a quien lo publico (DEF-19).

Por HTTP el modulo sale del token y se compara con el sobre (403 si no
coincide). Por AMQP la unica identidad autenticada es el usuario de la conexion:
RabbitMQ rechaza la publicacion si el mensaje trae una propiedad `user_id`
distinta de ese usuario, pero no exige que venga. Por eso el Core:

1. exige `user_id`;
2. lo traduce a un modulo con un vinculo configurado explicitamente
   (`AMQP_IDENTITIES`), sin deducirlo del nombre: una cuenta compartida no
   identifica a ningun modulo;
3. compara ese modulo con el `sourceModule` declarado.

La garantia depende de que ningun usuario de modulo tenga el tag
`impersonator` de RabbitMQ, que permite publicar con un `user_id` ajeno.
"""

from __future__ import annotations

from dataclasses import dataclass

IDENTITY_MISSING = "IDENTITY_MISSING"
IDENTITY_UNKNOWN = "IDENTITY_UNKNOWN"
SOURCE_MISMATCH = "SOURCE_MISMATCH"


@dataclass(frozen=True)
class SourceCheck:
    ok: bool
    code: str | None = None
    message: str = ""
    authenticated_module: str | None = None


def check_source(
    user_id: str | None, source_module: str, *, identities: dict[str, str]
) -> SourceCheck:
    """Compara la identidad autenticada por RabbitMQ con el origen declarado."""
    if not user_id:
        return SourceCheck(
            ok=False,
            code=IDENTITY_MISSING,
            message=(
                "El mensaje no trae la propiedad user_id: no se puede comprobar que "
                f"lo haya publicado '{source_module}'."
            ),
        )

    module = identities.get(user_id)
    if module is None:
        return SourceCheck(
            ok=False,
            code=IDENTITY_UNKNOWN,
            message=f"El usuario AMQP '{user_id}' no esta vinculado a ningun modulo.",
        )

    if module != source_module.strip().lower():
        return SourceCheck(
            ok=False,
            code=SOURCE_MISMATCH,
            message=(
                f"El usuario AMQP '{user_id}' corresponde a '{module}' y el evento "
                f"declara sourceModule '{source_module}'."
            ),
            authenticated_module=module,
        )

    return SourceCheck(ok=True, authenticated_module=module)
