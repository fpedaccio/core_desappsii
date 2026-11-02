"""DEF-18: ETag e If-Match en PUT /event-types/{name}/schema (eje C del PDF de testing).

Esperado: GET devuelve ETag; un PUT con If-Match desactualizado responde 412
(Problem Details) y no aplica el cambio. Sin If-Match se comporta como antes.
"""

from __future__ import annotations

import pytest

from app.core.etag import if_match_satisfied, strong_etag

pytestmark = pytest.mark.asyncio

URL = "/api/v1/event-types/tipoDeObras"
SCHEMA_A = {"jsonSchema": {"type": "object", "required": ["obraId"]}}
SCHEMA_B = {"jsonSchema": {"type": "object", "required": ["otroCampo"]}}


async def _tipo_de_obras(client, auth):
    obras = await auth("obras")
    created = await client.post("/api/v1/event-types", json={"name": "tipoDeObras"}, headers=obras)
    assert created.status_code == 201, created.text
    return obras


async def test_e1_el_get_devuelve_un_etag_fuerte(client, auth):
    obras = await _tipo_de_obras(client, auth)
    response = await client.get(URL, headers=obras)
    assert response.status_code == 200
    etag = response.headers.get("etag")
    assert etag and etag.startswith('"') and etag.endswith('"') and not etag.startswith("W/")


async def test_e2_put_con_if_match_vigente_aplica_y_devuelve_el_etag_nuevo(client, auth):
    obras = await _tipo_de_obras(client, auth)
    etag = (await client.get(URL, headers=obras)).headers["etag"]

    response = await client.put(f"{URL}/schema", json=SCHEMA_A, headers={**obras, "If-Match": etag})

    assert response.status_code == 200
    assert response.json()["jsonSchema"] == SCHEMA_A["jsonSchema"]
    nuevo = response.headers["etag"]
    assert nuevo != etag
    assert (await client.get(URL, headers=obras)).headers["etag"] == nuevo


async def test_e3_put_con_if_match_desactualizado_da_412_y_no_aplica(client, auth):
    obras = await _tipo_de_obras(client, auth)
    viejo = (await client.get(URL, headers=obras)).headers["etag"]
    await client.put(f"{URL}/schema", json=SCHEMA_A, headers=obras)

    response = await client.put(
        f"{URL}/schema", json=SCHEMA_B, headers={**obras, "If-Match": viejo}
    )

    assert response.status_code == 412
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 412 and body["code"] == "PRECONDITION_FAILED"
    assert body["instance"] == f"{URL}/schema"
    assert (await client.get(URL, headers=obras)).json()["jsonSchema"] == SCHEMA_A["jsonSchema"]


async def test_e4_dos_usuarios_con_el_mismo_etag_el_segundo_recibe_412(client, auth):
    """El dueño y el admin leen la misma version y la cambian uno despues del otro."""
    obras = await _tipo_de_obras(client, auth)
    admin = await auth("core")
    etag = (await client.get(URL, headers=obras)).headers["etag"]
    assert (await client.get(URL, headers=admin)).headers["etag"] == etag

    primero = await client.put(f"{URL}/schema", json=SCHEMA_A, headers={**obras, "If-Match": etag})
    segundo = await client.put(f"{URL}/schema", json=SCHEMA_B, headers={**admin, "If-Match": etag})

    assert primero.status_code == 200
    assert segundo.status_code == 412
    assert (await client.get(URL, headers=admin)).json()["jsonSchema"] == SCHEMA_A["jsonSchema"]


async def test_e5_sin_if_match_se_comporta_como_antes(client, auth):
    obras = await _tipo_de_obras(client, auth)
    response = await client.put(f"{URL}/schema", json=SCHEMA_A, headers=obras)
    assert response.status_code == 200
    assert response.headers.get("etag")


async def test_if_match_asterisco_aplica_si_el_tipo_existe(client, auth):
    obras = await _tipo_de_obras(client, auth)
    response = await client.put(f"{URL}/schema", json=SCHEMA_A, headers={**obras, "If-Match": "*"})
    assert response.status_code == 200


async def test_un_etag_debil_no_cumple_if_match(client, auth):
    obras = await _tipo_de_obras(client, auth)
    etag = (await client.get(URL, headers=obras)).headers["etag"]
    response = await client.put(
        f"{URL}/schema", json=SCHEMA_A, headers={**obras, "If-Match": f"W/{etag}"}
    )
    assert response.status_code == 412


async def test_el_trafico_de_eventos_no_cambia_el_etag(client, auth, machine_auth, make_envelope):
    """Los contadores (totalReceived, lastSeenAt) no son estado editable: no deben dar 412."""
    admin = await auth("core")
    antes = (await client.get("/api/v1/event-types/ticketCreated", headers=admin)).headers["etag"]
    publicado = await client.post(
        "/api/v1/events", json=make_envelope(), headers=await machine_auth("atencion-ciudadana")
    )
    assert publicado.status_code == 202, publicado.text
    despues = await client.get("/api/v1/event-types/ticketCreated", headers=admin)
    assert despues.json()["totalReceived"] >= 1
    assert despues.headers["etag"] == antes


async def test_un_modulo_ajeno_recibe_403_antes_que_412(client, auth):
    """La autorizacion va primero: un 412 le confirmaria a un ajeno que el tipo cambio."""
    await _tipo_de_obras(client, auth)
    ajeno = await auth("atencion-ciudadana")
    response = await client.put(
        f"{URL}/schema", json=SCHEMA_A, headers={**ajeno, "If-Match": '"x"'}
    )
    assert response.status_code == 403


async def test_if_match_sobre_un_tipo_inexistente_da_404(client, auth):
    admin = await auth("core")
    response = await client.put(
        "/api/v1/event-types/noExiste/schema", json=SCHEMA_A, headers={**admin, "If-Match": '"x"'}
    )
    assert response.status_code == 404


async def test_el_412_figura_en_el_openapi(client):
    spec = (await client.get("/openapi.json")).json()
    put = spec["paths"]["/api/v1/event-types/{name}/schema"]["put"]
    assert "412" in put["responses"]
    assert any(p["name"] == "If-Match" and p["in"] == "header" for p in put["parameters"])
    # Acordado con el grupo: documentar que sin If-Match no hay proteccion.
    aviso = "Sin `If-Match` no hay proteccion contra actualizaciones concurrentes"
    assert aviso in put["description"]


async def test_if_match_admite_varios_etags_y_compara_fuerte():
    actual = strong_etag({"a": 1})
    assert if_match_satisfied(f'"otro", {actual}', actual)
    assert not if_match_satisfied('"otro"', actual)
    assert not if_match_satisfied(f"W/{actual}", actual)
    assert strong_etag({"b": 2, "a": 1}) == strong_etag({"a": 1, "b": 2})
