"""Quien puede ver, auditar y reintentar una dead letter (HU-07, DEF-02 y DEF-10).

Regla: el administrador ve todas; un modulo, solo las que lo involucran (como
origen o como destino). Para cualquier otro modulo la dead letter "no existe":
responde 404 en el detalle, en la auditoria y en el reintento.

En los fixtures, `atencion-ciudadana` publica `ticketCreated` y `obras` lo
consume. Una violacion de schema deja una dead letter con origen
`atencion-ciudadana` y sin destino, asi que `obras` es un modulo ajeno.
"""

from __future__ import annotations


async def _dead_letter_por_schema(client, auth, make_envelope) -> str:
    """Publica un evento que no cumple el schema y devuelve el id de su dead letter.

    Despues relaja el schema, para que el reintento pueda reprocesarlo con exito.
    """
    admin = await auth("core")
    await client.put(
        "/api/v1/event-types/ticketCreated/schema",
        json={"jsonSchema": {"type": "object", "required": ["priority"]}},
        headers=admin,
    )
    origen = await auth("atencion-ciudadana")
    rechazo = await client.post("/api/v1/events", json=make_envelope(data={}), headers=origen)
    assert rechazo.status_code == 422
    await client.put(
        "/api/v1/event-types/ticketCreated/schema", json={"jsonSchema": None}, headers=admin
    )
    items = (await client.get("/api/v1/dlq", headers=admin)).json()["items"]
    assert len(items) == 1
    return items[0]["id"]


async def test_el_modulo_origen_puede_reintentar_su_dead_letter(client, auth, make_envelope):
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    origen = await auth("atencion-ciudadana")

    retry = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=origen)

    assert retry.status_code == 200, retry.text
    assert retry.json()["success"] is True
    detalle = await client.get(f"/api/v1/dlq/{dead_letter_id}", headers=origen)
    assert detalle.json()["status"] == "RETRIED"


async def test_el_reintento_del_representante_audita_a_esa_persona(client, auth, make_envelope):
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    origen = await auth("atencion-ciudadana")

    await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=origen)

    audit = await client.get(f"/api/v1/dlq/{dead_letter_id}/audit", headers=origen)
    assert audit.status_code == 200
    entries = audit.json()["items"]
    assert len(entries) == 1
    assert entries[0]["mode"] == "MANUAL"
    assert entries[0]["actor"] == "atencion-ciudadana@munitest.com"
    assert entries[0]["result"] == "SUCCESS"


async def test_el_backend_del_modulo_tambien_puede_reintentar(
    client, auth, machine_auth, make_envelope
):
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    maquina = await machine_auth("atencion-ciudadana")

    retry = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=maquina)

    assert retry.status_code == 200, retry.text
    admin = await auth("core")
    entries = (await client.get(f"/api/v1/dlq/{dead_letter_id}/audit", headers=admin)).json()[
        "items"
    ]
    assert entries[0]["actor"] == "module:atencion-ciudadana"


async def test_un_modulo_ajeno_no_puede_reintentar(client, auth, make_envelope):
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    ajeno = await auth("obras")

    retry = await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=ajeno)

    assert retry.status_code == 404
    # No tuvo ningun efecto: sigue abierta y sin intentos auditados.
    admin = await auth("core")
    detalle = await client.get(f"/api/v1/dlq/{dead_letter_id}", headers=admin)
    assert detalle.json()["status"] == "OPEN"
    audit = await client.get(f"/api/v1/dlq/{dead_letter_id}/audit", headers=admin)
    assert audit.json()["items"] == []


async def test_un_modulo_ajeno_no_ve_la_auditoria(client, auth, make_envelope):
    """DEF-10: antes respondia 200 con el email de quien reintento."""
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    admin = await auth("core")
    await client.post(f"/api/v1/dlq/{dead_letter_id}/retry", headers=admin)
    ajeno = await auth("obras")

    audit = await client.get(f"/api/v1/dlq/{dead_letter_id}/audit", headers=ajeno)

    assert audit.status_code == 404
    assert "core@munitest.com" not in audit.text


async def test_el_detalle_ajeno_sigue_dando_404(client, auth, make_envelope):
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    ajeno = await auth("obras")

    detalle = await client.get(f"/api/v1/dlq/{dead_letter_id}", headers=ajeno)

    assert detalle.status_code == 404


async def test_una_dead_letter_inexistente_da_404_al_reintentar(client, auth):
    origen = await auth("atencion-ciudadana")

    retry = await client.post(
        "/api/v1/dlq/00000000-0000-4000-8000-000000000000/retry", headers=origen
    )

    assert retry.status_code == 404


async def test_la_auditoria_de_una_dead_letter_inexistente_da_404(client, auth):
    """Tomado del PR #14: antes respondia 200 con la pagina vacia."""
    admin = await auth("core")

    audit = await client.get(
        "/api/v1/dlq/00000000-0000-4000-8000-000000000000/audit", headers=admin
    )

    assert audit.status_code == 404


async def test_descartar_sigue_siendo_solo_del_admin(client, auth, make_envelope):
    """El alcance de HU-07 es ver y reintentar; descartar no se habilita a los modulos."""
    dead_letter_id = await _dead_letter_por_schema(client, auth, make_envelope)
    origen = await auth("atencion-ciudadana")

    descarte = await client.post(
        f"/api/v1/dlq/{dead_letter_id}/discard", json={"reason": "prueba"}, headers=origen
    )

    assert descarte.status_code == 403
