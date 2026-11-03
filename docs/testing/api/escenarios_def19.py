"""Regresion de DEF-19 contra RabbitMQ real: identidad del publicador por AMQP.

Necesita la API y el worker con `AMQP_SOURCE_CHECK=enforce` y
`AMQP_IDENTITIES` que vincule `CORE_AMQP_USER_A` con `CORE_MODULE_A` y otro
usuario con `CORE_MODULE_B`. El usuario A es un usuario restringido de
RabbitMQ: escribe solo en `muni.inbox`, sin configure ni read, y sin el tag
`impersonator`. La cuenta administrativa (`CORE_AMQP_URL_ADMIN`) solo se usa
para contar los mensajes de la cola de B.

    CORE_ROOT_URL=http://127.0.0.1:18090 CORE_ADMIN_PASSWORD=... \\
    CORE_AMQP_URL_ADMIN=amqp://guest:guest@127.0.0.1:5672/qa-def19 \\
    CORE_AMQP_URL_A=amqp://qa-def19-user-a:...@127.0.0.1:5672/qa-def19 \\
    CORE_AMQP_USER_A=qa-def19-user-a CORE_AMQP_USER_B=qa-def19-user-b \\
    CORE_MODULE_A=qa-def19-mod-a CORE_MODULE_B=qa-def19-mod-b \\
    python docs/testing/api/escenarios_def19.py

No imprime credenciales. Termina con codigo 1 si algun caso falla.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime

import aio_pika
import httpx

API = os.environ.get("CORE_ROOT_URL", "http://127.0.0.1:18090") + "/api/v1"
ADMIN_EMAIL = os.environ.get("CORE_ADMIN_EMAIL", "core@muni.uade.edu.ar")
MOD_A, MOD_B = os.environ["CORE_MODULE_A"], os.environ["CORE_MODULE_B"]
USER_A, USER_B = os.environ["CORE_AMQP_USER_A"], os.environ["CORE_AMQP_USER_B"]
TIPO = "qaDef19Flow"

resultados: list[tuple[str, str, str, str, bool]] = []


def caso(cid: str, titulo: str, esperado: str, observado, ok: bool) -> None:
    resultados.append((cid, titulo, esperado, str(observado), ok))
    print(f"{'PASS' if ok else 'FAIL'} {cid} {titulo}: {observado}", flush=True)


def sobre(source: str, event_id: str | None = None) -> dict:
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "eventType": TIPO,
        "eventVersion": "1.0",
        "occurredAt": datetime.now(UTC).isoformat(),
        "sourceModule": source,
        "data": {"marker": "def19"},
    }


async def main() -> int:
    async with httpx.AsyncClient(base_url=API, timeout=15) as http:
        login = await http.post(
            "/auth/login", json={"email": ADMIN_EMAIL, "password": os.environ["CORE_ADMIN_PASSWORD"]}
        )
        login.raise_for_status()
        admin = {"Authorization": f"Bearer {login.json()['accessToken']}"}

        tokens = {}
        for nombre in (MOD_A, MOD_B):
            alta = await http.post(
                "/modules", json={"name": nombre, "displayName": nombre, "team": "QA DEF-19"}, headers=admin
            )
            if alta.status_code == 409:  # quedo de una corrida anterior
                await http.patch(f"/modules/{nombre}", json={"active": True}, headers=admin)
                alta = await http.post(f"/modules/{nombre}/rotate-secret", headers=admin)
            alta.raise_for_status()
            token = await http.post("/auth/module-token", json={"module": nombre, "secret": alta.json()["secret"]})
            token.raise_for_status()
            tokens[nombre] = {"Authorization": f"Bearer {token.json()['accessToken']}"}
        (await http.post("/event-types", json={"name": TIPO, "ownerModule": MOD_A}, headers=tokens[MOD_A])).raise_for_status()
        (await http.post("/subscriptions", json={"eventType": TIPO}, headers=tokens[MOD_B])).raise_for_status()

        async def evento(event_id: str):
            r = await http.get(f"/events/{event_id}", headers=admin)
            return r.json() if r.status_code == 200 else None

        async def dead_letter(event_id: str):
            items = (await http.get("/dlq", params={"eventType": TIPO, "size": 200}, headers=admin)).json()["items"]
            return next((d for d in items if d["eventId"] == event_id), None)

        async def esperar(funcion, hasta: float = 10):
            limite = time.monotonic() + hasta
            while True:
                valor = await funcion()
                if valor or time.monotonic() > limite:
                    return valor
                await asyncio.sleep(0.5)

        admin_amqp = await aio_pika.connect_robust(os.environ["CORE_AMQP_URL_ADMIN"])
        canal_admin = await admin_amqp.channel()
        cola_b = f"q.{MOD_B}"

        async def vaciar_b() -> int:
            n = 0
            cola = await canal_admin.declare_queue(cola_b, passive=True)
            while (m := await cola.get(no_ack=False, fail=False)) is not None:
                await m.ack()
                n += 1
            return n

        await vaciar_b()
        conexion_a = await aio_pika.connect(os.environ["CORE_AMQP_URL_A"])

        async def publicar_como_a(cuerpo: dict, user_id: str | None):
            """Publica con el usuario restringido A. Devuelve el error del broker, si hubo."""
            canal = await conexion_a.channel()
            # Sin declarar: el usuario A no tiene permiso de configure.
            inbox = await canal.get_exchange("muni.inbox", ensure=False)
            try:
                await inbox.publish(
                    aio_pika.Message(json.dumps(cuerpo).encode(), content_type="application/json", user_id=user_id),
                    routing_key="",
                )
                await canal.close()
                return None
            except Exception as exc:  # el broker cierra el canal
                return type(exc).__name__

        # D19-01: publicador legitimo
        e1 = sobre(MOD_A)
        error = await publicar_como_a(e1, USER_A)
        ok1 = await esperar(lambda: evento(e1["eventId"]))
        await asyncio.sleep(1)
        caso("D19-01", "Usuario A publica como su modulo", "aceptado y entregado a B",
             (error, ok1 and ok1["status"], await vaciar_b()),
             error is None and bool(ok1) and ok1["status"] == "ROUTED")

        # D19-02: suplantacion con identidad propia
        e2 = sobre(MOD_B)
        error = await publicar_como_a(e2, USER_A)
        dl2 = await esperar(lambda: dead_letter(e2["eventId"]))
        detalle2 = dl2 and (await http.get(f"/dlq/{dl2['id']}", headers=admin)).json()
        caso("D19-02", "Usuario A declara sourceModule de B", "sin evento ni entrega; DLQ SOURCE_UNVERIFIED / SOURCE_MISMATCH",
             (await evento(e2["eventId"]), await vaciar_b(), detalle2 and (detalle2["reasonCode"], detalle2["details"][0]["code"])),
             await evento(e2["eventId"]) is None and await vaciar_b() == 0 and bool(detalle2)
             and detalle2["reasonCode"] == "SOURCE_UNVERIFIED" and detalle2["details"][0]["code"] == "SOURCE_MISMATCH")

        # D19-03: sin user_id
        e3 = sobre(MOD_A)
        error = await publicar_como_a(e3, None)
        dl3 = await esperar(lambda: dead_letter(e3["eventId"]))
        detalle3 = dl3 and (await http.get(f"/dlq/{dl3['id']}", headers=admin)).json()
        caso("D19-03", "Usuario A publica sin user_id", "sin evento ni entrega; DLQ IDENTITY_MISSING",
             (await evento(e3["eventId"]), await vaciar_b(), detalle3 and detalle3["details"][0]["code"]),
             await evento(e3["eventId"]) is None and bool(detalle3) and detalle3["details"][0]["code"] == "IDENTITY_MISSING")

        # D19-04: user_id ajeno, lo corta el broker
        e4 = sobre(MOD_B)
        error = await publicar_como_a(e4, USER_B)
        await asyncio.sleep(2)
        caso("D19-04", "Usuario A usa el user_id de B", "el broker rechaza la publicacion; sin evento",
             (error, await evento(e4["eventId"]), await dead_letter(e4["eventId"])),
             error is not None and await evento(e4["eventId"]) is None and await dead_letter(e4["eventId"]) is None)

        # D19-05: el rechazo no se reintenta
        retry = dl2 and await http.post(f"/dlq/{dl2['id']}/retry", headers=admin)
        caso("D19-05", "Reintentar el rechazo por identidad", "409, sigue sin evento",
             retry and retry.status_code, bool(retry) and retry.status_code == 409 and await evento(e2["eventId"]) is None)

        # D19-06: el modulo suplantado ve el intento
        propias = (await http.get("/dlq", params={"eventType": TIPO}, headers=tokens[MOD_B])).json()["items"]
        caso("D19-06", "B ve el intento de suplantacion en su DLQ", "dead letter de D19-02 visible para B",
             e2["eventId"] in [d["eventId"] for d in propias], e2["eventId"] in [d["eventId"] for d in propias])

        # D19-07: el eventId rechazado no queda reservado
        error = await publicar_como_a({**e3, "occurredAt": datetime.now(UTC).isoformat()}, USER_A)
        ok7 = await esperar(lambda: evento(e3["eventId"]))
        await asyncio.sleep(1)
        caso("D19-07", "Reenvio legitimo con el eventId de D19-03", "aceptado y entregado una vez",
             (error, ok7 and ok7["status"], await vaciar_b()), error is None and bool(ok7) and ok7["status"] == "ROUTED")

        # D19-08: equivalente por HTTP
        http_spoof = await http.post("/events", json=sobre(MOD_B), headers=tokens[MOD_A])
        caso("D19-08", "Por HTTP, A no puede publicar como B", "403", http_spoof.status_code, http_spoof.status_code == 403)

        await conexion_a.close()
        await admin_amqp.close()
        for nombre in (MOD_A, MOD_B):
            await http.patch(f"/modules/{nombre}", json={"active": False}, headers=admin)

    print("\n| Caso | Escenario | Esperado | Observado | Resultado |")
    print("| --- | --- | --- | --- | --- |")
    for cid, titulo, esperado, observado, ok in resultados:
        print(f"| {cid} | {titulo} | {esperado} | `{observado}` | {'PASS' if ok else 'FAIL'} |")
    return 0 if all(r[4] for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
