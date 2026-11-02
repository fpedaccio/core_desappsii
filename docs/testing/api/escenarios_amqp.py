"""Escenarios de ingesta AMQP y reintentos de la DLQ (tarea T6 de QA).

Necesita la API, el worker (`python -m app.workers.inbox_worker`) y RabbitMQ
reales. Crea su propia fixture (modulos qa-amqp-<run>-a/b) y al final la
desactiva. Uso, desde la raiz del repo y con el venv del backend:

    CORE_ROOT_URL=http://127.0.0.1:18090 \\
    CORE_AMQP_URL=amqp://guest:guest@127.0.0.1:5672/qa-t6 \\
    CORE_ADMIN_EMAIL=core@muni.uade.edu.ar \\
    CORE_ADMIN_PASSWORD=... \\
    python docs/testing/api/escenarios_amqp.py

Imprime una tabla Markdown con esperado/observado por caso. No imprime tokens,
secrets ni contrasenas. Termina con codigo 1 si algun caso falla.
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

ROOT = os.environ.get("CORE_ROOT_URL", "http://127.0.0.1:18090")
API = ROOT + "/api/v1"
AMQP_URL = os.environ["CORE_AMQP_URL"]
ADMIN_EMAIL = os.environ.get("CORE_ADMIN_EMAIL", "core@muni.uade.edu.ar")
ADMIN_PASSWORD = os.environ["CORE_ADMIN_PASSWORD"]

SCHEMA = {
    "type": "object",
    "required": ["marker", "quantity"],
    "properties": {"marker": {"type": "string"}, "quantity": {"type": "integer"}},
    "additionalProperties": False,
}

resultados: list[tuple[str, str, str, str, bool]] = []


def caso(cid: str, titulo: str, esperado: str, observado, ok: bool) -> None:
    resultados.append((cid, titulo, esperado, str(observado), ok))
    print(f"{'PASS' if ok else 'FAIL'} {cid} {titulo}: {observado}", flush=True)


async def esperar(funcion, *, hasta: float = 20, cada: float = 0.5):
    """Reintenta `funcion` hasta que devuelva algo truthy o venza el plazo."""
    limite = time.monotonic() + hasta
    while True:
        valor = await funcion()
        if valor or time.monotonic() > limite:
            return valor
        await asyncio.sleep(cada)


def sobre(event_id: str, event_type: str, source: str, data: dict) -> dict:
    return {
        "eventId": event_id,
        "eventType": event_type,
        "eventVersion": "1.0",
        "occurredAt": datetime.now(UTC).isoformat(),
        "sourceModule": source,
        "data": data,
    }


async def main() -> int:
    run = format(int(time.time()), "x")[-6:]
    mod_a, mod_b = f"qa-amqp-{run}-a", f"qa-amqp-{run}-b"
    tipo = f"qaAmqp{run}Flow"
    cola_b = f"q.{mod_b}"

    async with httpx.AsyncClient(base_url=API, timeout=15) as http:
        login = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        admin = {"Authorization": f"Bearer {login.json()['accessToken']}"}

        tokens = {}
        for nombre in (mod_a, mod_b):
            alta = await http.post(
                "/modules", json={"name": nombre, "displayName": nombre, "team": "QA T6"}, headers=admin
            )
            alta.raise_for_status()
            token = await http.post(
                "/auth/module-token", json={"module": nombre, "secret": alta.json()["secret"]}
            )
            token.raise_for_status()
            tokens[nombre] = {"Authorization": f"Bearer {token.json()['accessToken']}"}

        (await http.post(
            "/event-types", json={"name": tipo, "ownerModule": mod_a, "jsonSchema": SCHEMA}, headers=tokens[mod_a]
        )).raise_for_status()
        (await http.post(
            "/subscriptions", json={"eventType": tipo, "maxAttempts": 2}, headers=tokens[mod_b]
        )).raise_for_status()

        async def evento(event_id: str):
            r = await http.get(f"/events/{event_id}", headers=admin)
            return r.json() if r.status_code == 200 else None

        async def dlq(**filtros) -> dict:
            return (await http.get("/dlq", params=filtros, headers=admin)).json()

        conexion = await aio_pika.connect_robust(AMQP_URL)
        async with conexion:
            canal = await conexion.channel()
            inbox = await canal.get_exchange("muni.inbox")
            cola = await canal.declare_queue(cola_b, passive=True)

            async def publicar(cuerpo: bytes, message_id: str | None = None) -> None:
                await inbox.publish(
                    aio_pika.Message(
                        cuerpo,
                        content_type="application/json",
                        message_id=message_id,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key="",
                )

            async def tomar(hasta: float = 15):
                return await esperar(lambda: cola.get(no_ack=False, fail=False), hasta=hasta)

            async def mensajes_en_b() -> int:
                return (await canal.declare_queue(cola_b, passive=True)).declaration_result.message_count

            # AMQP-01: evento valido por muni.inbox
            id1 = str(uuid.uuid4())
            cuerpo1 = json.dumps(sobre(id1, tipo, mod_a, {"marker": "amqp-ok", "quantity": 1})).encode()
            await publicar(cuerpo1, id1)
            e1 = await esperar(lambda: evento(id1))
            caso("AMQP-01", "Evento valido publicado en muni.inbox se persiste por el canal AMQP",
                 "ingestionChannel AMQP, una entrega a B",
                 e1 and (e1["ingestionChannel"], [d["targetModule"] for d in e1["deliveries"]]),
                 bool(e1) and e1["ingestionChannel"] == "AMQP"
                 and [d["targetModule"] for d in e1["deliveries"]] == [mod_b])
            m1 = await tomar()
            h = dict(m1.headers) if m1 else {}
            caso("AMQP-02", "B recibe el mensaje con las cabeceras del Core",
                 "x-core-event-id = eventId, target B, attempt 1, mismo data",
                 m1 and {k: h.get(k) for k in ("x-core-event-id", "x-core-target-module", "x-core-attempt")},
                 bool(m1) and h.get("x-core-event-id") == id1 and h.get("x-core-target-module") == mod_b
                 and int(h.get("x-core-attempt", 0)) == 1
                 and json.loads(m1.body)["data"] == {"marker": "amqp-ok", "quantity": 1})
            if m1:
                await m1.ack()

            # AMQP-03: duplicado por AMQP
            await publicar(cuerpo1, id1)
            await asyncio.sleep(4)
            total = (await http.get("/events", params={"eventType": tipo}, headers=admin)).json()["total"]
            pendientes = await mensajes_en_b()
            caso("AMQP-03", "Reenvio del mismo eventId por AMQP no genera efectos",
                 "1 evento del tipo, 0 mensajes nuevos en la cola de B",
                 f"eventos={total}, cola B={pendientes}", total == 1 and pendientes == 0)

            # AMQP-04: cuerpo que no es JSON
            antes = (await dlq(reasonCode="MALFORMED_MESSAGE"))["total"]
            await publicar(b"{esto no es json", None)
            despues = await esperar(
                lambda: _mayor(dlq(reasonCode="MALFORMED_MESSAGE"), antes), hasta=15
            )
            caso("AMQP-04", "Mensaje que no es JSON queda como MALFORMED_MESSAGE",
                 "una dead letter MALFORMED_MESSAGE mas", f"antes={antes}, despues={despues}",
                 despues == antes + 1)

            # AMQP-05: data que no cumple el schema
            id2 = str(uuid.uuid4())
            await publicar(json.dumps(sobre(id2, tipo, mod_a, {"marker": "amqp-mal", "quantity": "uno"})).encode(), id2)
            e2 = await esperar(lambda: evento(id2))
            dl2 = await esperar(lambda: _items(dlq(eventType=tipo, reasonCode="SCHEMA_VIOLATION")))
            caso("AMQP-05", "data invalido por AMQP queda REJECTED y en la DLQ",
                 "REJECTED, SCHEMA_VIOLATION, sin entregas, cola B vacia",
                 e2 and (e2["status"], e2["rejectionCode"], len(e2["deliveries"]), await mensajes_en_b()),
                 bool(e2) and e2["status"] == "REJECTED" and e2["rejectionCode"] == "SCHEMA_VIOLATION"
                 and e2["deliveries"] == [] and bool(dl2) and await mensajes_en_b() == 0)

            # AMQP-06: por AMQP nadie contrasta sourceModule con la conexion
            id3 = str(uuid.uuid4())
            await publicar(json.dumps(sobre(id3, tipo, mod_b, {"marker": "amqp-origen", "quantity": 1})).encode(), id3)
            e3 = await esperar(lambda: evento(id3))
            caso("AMQP-06", "OBSERVACION: por AMQP se acepta un sourceModule cualquiera",
                 "aceptado (comportamiento actual: no se contrasta con el usuario de la conexion)",
                 e3 and (e3["sourceModule"], e3["status"]), bool(e3) and e3["sourceModule"] == mod_b)
            await asyncio.sleep(1)
            sobrante = await cola.get(no_ack=False, fail=False)
            while sobrante:
                await sobrante.ack()
                sobrante = await cola.get(no_ack=False, fail=False)

            # DLQ-R1: reintento exitoso de una SCHEMA_VIOLATION tras corregir el schema
            dl_id = dl2[0]["id"]
            (await http.put(
                f"/event-types/{tipo}/schema",
                json={"jsonSchema": {"type": "object", "required": ["marker"]}},
                headers=tokens[mod_a],
            )).raise_for_status()
            retry = await http.post(f"/dlq/{dl_id}/retry", headers=admin)
            e2b = await evento(id2)
            m2 = await tomar()
            audit = (await http.get(f"/dlq/{dl_id}/audit", headers=admin)).json()["items"]
            caso("DLQ-R1", "Tras corregir el schema, el reintento reprocesa y entrega",
                 "success, evento con entrega a B, B recibe el evento, auditoria MANUAL SUCCESS",
                 (retry.status_code, retry.json().get("success"), e2b and len(e2b["deliveries"]),
                  bool(m2), [(a["mode"], a["result"]) for a in audit]),
                 retry.status_code == 200 and retry.json().get("success") is True
                 and bool(e2b) and [d["targetModule"] for d in e2b["deliveries"]] == [mod_b]
                 and bool(m2) and m2.headers.get("x-core-event-id") == id2
                 and ("MANUAL", "SUCCESS") in [(a["mode"], a["result"]) for a in audit])
            if m2:
                await m2.ack()
            (await http.put(f"/event-types/{tipo}/schema", json={"jsonSchema": SCHEMA}, headers=tokens[mod_a])).raise_for_status()

            # DLQ-R2: el consumidor rechaza hasta agotar maxAttempts=2
            id4 = str(uuid.uuid4())
            (await http.post(
                "/events", json=sobre(id4, tipo, mod_a, {"marker": "rechazar", "quantity": 4}), headers=tokens[mod_a]
            )).raise_for_status()
            intentos = []
            for _ in range(2):
                m = await tomar(hasta=60)
                if not m:
                    break
                intentos.append((int(m.headers.get("x-core-attempt", 0)), m.headers.get("x-core-event-id") == id4,
                                 "x-core-last-error" in m.headers))
                await m.reject(requeue=False)
            caso("DLQ-R2", "Rechazo del consumidor: reintento con backoff y cabeceras",
                 "intentos 1 y 2 del mismo eventId; el 2 trae x-core-last-error",
                 intentos, [i[0] for i in intentos] == [1, 2] and all(i[1] for i in intentos) and intentos[1][2])

            dl4 = await esperar(lambda: _items(dlq(eventType=tipo, reasonCode="DELIVERY_FAILED")), hasta=30)
            e4 = await evento(id4)
            caso("DLQ-R3", "Agotados los intentos se abre una dead letter DELIVERY_FAILED",
                 "dead letter para B; entrega con 2 intentos",
                 (dl4 and (dl4[0]["targetModule"], dl4[0]["attempts"]),
                  e4 and [(d["status"], d["attempts"]) for d in e4["deliveries"]]),
                 bool(dl4) and dl4[0]["targetModule"] == mod_b and dl4[0]["eventId"] == id4
                 and bool(e4) and e4["deliveries"][0]["attempts"] == 2)

            await asyncio.sleep(1)
            sin_reentrega = await mensajes_en_b()
            caso("DLQ-R4", "Una vez abierta la dead letter no hay mas reentregas",
                 "cola B vacia", f"cola B={sin_reentrega}", sin_reentrega == 0)

            if dl4:
                retry4 = await http.post(f"/dlq/{dl4[0]['id']}/retry", headers=admin)
                m4 = await tomar()
                h4 = dict(m4.headers) if m4 else {}
                if m4:
                    await m4.ack()
                detalle = (await http.get(f"/dlq/{dl4[0]['id']}", headers=admin)).json()
                caso("DLQ-R5", "Reintento manual de DELIVERY_FAILED republica con contador reiniciado",
                     "success; B recibe el mismo eventId con attempt 1; dead letter RETRIED",
                     (retry4.json().get("success"), h4.get("x-core-event-id") == id4, h4.get("x-core-attempt"),
                      detalle.get("status")),
                     retry4.json().get("success") is True and h4.get("x-core-event-id") == id4
                     and int(h4.get("x-core-attempt", 0)) == 1 and detalle.get("status") == "RETRIED")

        for nombre in (mod_a, mod_b):
            await http.patch(f"/modules/{nombre}", json={"active": False}, headers=admin)

    print("\n| Caso | Escenario | Esperado | Observado | Resultado |")
    print("| --- | --- | --- | --- | --- |")
    for cid, titulo, esperado, observado, ok in resultados:
        print(f"| {cid} | {titulo} | {esperado} | `{observado}` | {'PASS' if ok else 'FAIL'} |")
    print(f"\nFixture: {mod_a}, {mod_b}; tipo {tipo}. Modulos desactivados al terminar.")
    return 0 if all(r[4] for r in resultados) else 1


async def _mayor(coro, antes: int):
    total = (await coro)["total"]
    return total if total > antes else None


async def _items(coro):
    return (await coro)["items"]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
