"""Catalogos globales: barrios, zonas y listas de referencia.

El enunciado le asigna al Core "barrios, zonas y catalogos globales" (seccion
10, modulo 9). Lo que importa de estas pruebas: que el catalogo sea legible por
todos, escribible solo por el admin, y que los identificadores no se reusen.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------
# Lectura: la comparten los nueve modulos
# ----------------------------------------------------------------------
async def test_cualquier_modulo_lee_el_catalogo_de_barrios(client, auth):
    """Un catalogo compartido no sirve si cada equipo ve uno distinto."""
    for modulo in ("obras", "atencion-ciudadana", "core"):
        response = await client.get("/api/v1/catalogos/barrios", headers=await auth(modulo))
        assert response.status_code == 200
        assert len(response.json()) > 0


async def test_el_barrio_trae_un_identificador_estable_y_su_zona(client, auth):
    response = await client.get("/api/v1/catalogos/barrios", headers=await auth("obras"))
    barrio = next(b for b in response.json() if b["codigo"] == "villa-elisa")

    assert barrio["nombre"] == "Villa Elisa"
    assert barrio["zona"] == "norte"
    assert barrio["activo"] is True
    # Los dos identificadores que un modulo puede guardar en su propio dato.
    assert barrio["id"]
    assert barrio["codigo"] == "villa-elisa"


async def test_se_filtra_por_zona_y_se_busca_por_nombre(client, auth):
    headers = await auth("obras")

    por_zona = await client.get("/api/v1/catalogos/barrios?zona=ribera", headers=headers)
    assert {b["codigo"] for b in por_zona.json()} == {"puerto-viejo", "costanera", "isla-verde"}

    buscados = await client.get("/api/v1/catalogos/barrios?q=villa", headers=headers)
    assert [b["codigo"] for b in buscados.json()] == ["villa-elisa"]


async def test_las_zonas_dicen_cuantos_barrios_agrupan(client, auth):
    response = await client.get("/api/v1/catalogos/zonas", headers=await auth("obras"))
    zonas = {z["codigo"]: z for z in response.json()}
    assert zonas["ribera"]["barrios"] == 3
    assert zonas["centro"]["nombre"] == "Centro"


async def test_sin_token_no_se_lee_el_catalogo(client):
    assert (await client.get("/api/v1/catalogos/barrios")).status_code == 401


# ----------------------------------------------------------------------
# Escritura: solo el admin
# ----------------------------------------------------------------------
async def test_un_modulo_comun_no_puede_tocar_el_catalogo(client, auth):
    """Lo que un equipo corrige, otro lo pisa. El catalogo tiene un solo dueno."""
    comun = await auth("obras")

    crear = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": "barrio-propio", "nombre": "Barrio Propio"},
        headers=comun,
    )
    assert crear.status_code == 403

    editar = await client.patch(
        "/api/v1/catalogos/barrios/villa-elisa", json={"nombre": "Otro"}, headers=comun
    )
    assert editar.status_code == 403


async def test_el_admin_crea_un_barrio_y_queda_visible_para_todos(client, auth):
    admin = await auth("core")
    creado = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": "nueva-esperanza", "nombre": "Nueva Esperanza", "zona": "oeste"},
        headers=admin,
    )
    assert creado.status_code == 201
    assert creado.json()["zona"] == "oeste"

    visto = await client.get(
        "/api/v1/catalogos/barrios/nueva-esperanza", headers=await auth("obras")
    )
    assert visto.json()["nombre"] == "Nueva Esperanza"


async def test_no_se_puede_repetir_un_codigo(client, auth):
    admin = await auth("core")
    response = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": "villa-elisa", "nombre": "Otro Villa Elisa"},
        headers=admin,
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "codigo", ["Villa Elisa", "villa_elisa", "VILLA-ELISA", "", "villa--elisa"]
)
async def test_se_rechaza_un_codigo_que_no_es_slug(client, auth, codigo):
    """El codigo es un identificador estable: se valida, no se auto-corrige.

    Si el Core lo reescribiera por su cuenta, el modulo que lo mando guardaria
    uno distinto del que quedo.
    """
    response = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": codigo, "nombre": "X"},
        headers=await auth("core"),
    )
    assert response.status_code == 422


# ----------------------------------------------------------------------
# Lo que no se puede perder
# ----------------------------------------------------------------------
async def test_dar_de_baja_un_barrio_lo_desactiva_pero_no_lo_borra(client, auth):
    """Hay eventos historicos que lo referencian: el identificador no se reusa."""
    admin = await auth("core")
    baja = await client.patch(
        "/api/v1/catalogos/barrios/isla-verde", json={"activo": False}, headers=admin
    )
    assert baja.status_code == 200
    assert baja.json()["activo"] is False

    # Sigue siendo consultable, que es lo que permite resolver un evento viejo.
    assert (
        await client.get("/api/v1/catalogos/barrios/isla-verde", headers=admin)
    ).status_code == 200

    # Y no aparece cuando se piden solo los vigentes.
    vigentes = await client.get("/api/v1/catalogos/barrios?soloActivos=true", headers=admin)
    assert "isla-verde" not in {b["codigo"] for b in vigentes.json()}


async def test_no_se_puede_reusar_el_codigo_de_un_barrio_dado_de_baja(client, auth):
    admin = await auth("core")
    await client.patch("/api/v1/catalogos/barrios/costanera", json={"activo": False}, headers=admin)

    repetido = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": "costanera", "nombre": "Costanera Nueva"},
        headers=admin,
    )
    assert repetido.status_code == 409


# ----------------------------------------------------------------------
# Catalogos genericos
# ----------------------------------------------------------------------
async def test_las_listas_de_referencia_vienen_ordenadas(client, auth):
    """`orden` existe para que los nueve modulos las muestren igual."""
    response = await client.get(
        "/api/v1/catalogos/prioridades/items", headers=await auth("atencion-ciudadana")
    )
    assert [i["codigo"] for i in response.json()] == ["baja", "media", "alta", "urgente"]


async def test_se_pueden_descubrir_los_catalogos_disponibles(client, auth):
    response = await client.get("/api/v1/catalogos", headers=await auth("obras"))
    assert {"categorias-reclamo", "prioridades", "tipos-documento"} <= set(response.json())


async def test_no_se_puede_crear_un_catalogo_que_pise_una_ruta_propia(client, auth):
    """`/catalogos/zonas` ya significa otra cosa."""
    response = await client.post(
        "/api/v1/catalogos/zonas/items",
        json={"codigo": "x", "nombre": "X"},
        headers=await auth("core"),
    )
    assert response.status_code == 422


# ----------------------------------------------------------------------
# Alta y mantenimiento de zonas
# ----------------------------------------------------------------------
async def test_el_admin_crea_y_renombra_una_zona(client, auth):
    admin = await auth("core")

    creada = await client.post(
        "/api/v1/catalogos/zonas",
        json={"codigo": "noroeste", "nombre": "Zona Noroeste", "descripcion": "Nueva"},
        headers=admin,
    )
    assert creada.status_code == 201
    assert creada.json() == {
        "id": creada.json()["id"],
        "codigo": "noroeste",
        "nombre": "Zona Noroeste",
        "descripcion": "Nueva",
        "activo": True,
        "barrios": 0,
    }

    renombrada = await client.patch(
        "/api/v1/catalogos/zonas/noroeste", json={"nombre": "Noroeste"}, headers=admin
    )
    assert renombrada.json()["nombre"] == "Noroeste"


async def test_no_se_puede_repetir_el_codigo_de_una_zona(client, auth):
    response = await client.post(
        "/api/v1/catalogos/zonas",
        json={"codigo": "centro", "nombre": "Otro Centro"},
        headers=await auth("core"),
    )
    assert response.status_code == 409


async def test_dar_de_baja_una_zona_no_borra_sus_barrios(client, auth):
    """La zona es una agrupacion: si desaparece, los barrios siguen existiendo."""
    admin = await auth("core")
    await client.patch("/api/v1/catalogos/zonas/sur", json={"activo": False}, headers=admin)

    barrio = await client.get("/api/v1/catalogos/barrios/las-quintas", headers=admin)
    assert barrio.status_code == 200
    assert barrio.json()["activo"] is True


async def test_un_barrio_puede_no_tener_zona(client, auth):
    admin = await auth("core")
    creado = await client.post(
        "/api/v1/catalogos/barrios", json={"codigo": "sin-zona", "nombre": "Sin Zona"},
        headers=admin,
    )
    assert creado.status_code == 201
    assert creado.json()["zona"] is None

    # Y se le puede asignar una despues.
    asignado = await client.patch(
        "/api/v1/catalogos/barrios/sin-zona", json={"zona": "centro"}, headers=admin
    )
    assert asignado.json()["zona"] == "centro"

    # Y sacarsela sin borrar el barrio.
    sacada = await client.patch(
        "/api/v1/catalogos/barrios/sin-zona", json={"zona": ""}, headers=admin
    )
    assert sacada.json()["zona"] is None


async def test_crear_un_barrio_en_una_zona_que_no_existe_falla(client, auth):
    response = await client.post(
        "/api/v1/catalogos/barrios",
        json={"codigo": "fantasma", "nombre": "Fantasma", "zona": "no-existe"},
        headers=await auth("core"),
    )
    assert response.status_code == 404


async def test_pedir_un_barrio_que_no_existe_da_404(client, auth):
    response = await client.get("/api/v1/catalogos/barrios/no-existe", headers=await auth("obras"))
    assert response.status_code == 404


# ----------------------------------------------------------------------
# Mantenimiento de los catalogos genericos
# ----------------------------------------------------------------------
async def test_se_agrega_un_item_a_un_catalogo_existente(client, auth):
    admin = await auth("core")
    creado = await client.post(
        "/api/v1/catalogos/prioridades/items",
        json={"codigo": "critica", "nombre": "Critica", "orden": 50},
        headers=admin,
    )
    assert creado.status_code == 201

    items = await client.get("/api/v1/catalogos/prioridades/items", headers=admin)
    assert [i["codigo"] for i in items.json()][-1] == "critica"


async def test_un_catalogo_nuevo_nace_con_su_primer_item(client, auth):
    admin = await auth("core")
    await client.post(
        "/api/v1/catalogos/tipos-via/items",
        json={"codigo": "calle", "nombre": "Calle"},
        headers=admin,
    )
    disponibles = await client.get("/api/v1/catalogos", headers=admin)
    assert "tipos-via" in disponibles.json()


async def test_dar_de_baja_un_item_lo_saca_de_los_vigentes(client, auth):
    admin = await auth("core")
    await client.patch(
        "/api/v1/catalogos/categorias-reclamo/items/otros",
        json={"activo": False},
        headers=admin,
    )
    vigentes = await client.get(
        "/api/v1/catalogos/categorias-reclamo/items?soloActivos=true", headers=admin
    )
    assert "otros" not in {i["codigo"] for i in vigentes.json()}


async def test_no_se_puede_repetir_un_item_dentro_del_mismo_catalogo(client, auth):
    response = await client.post(
        "/api/v1/catalogos/prioridades/items",
        json={"codigo": "alta", "nombre": "Alta otra vez"},
        headers=await auth("core"),
    )
    assert response.status_code == 409


async def test_el_mismo_codigo_puede_existir_en_dos_catalogos_distintos(client, auth):
    """La unicidad es por catalogo, no global."""
    response = await client.post(
        "/api/v1/catalogos/estados-tramite/items",
        json={"codigo": "alta", "nombre": "Alta"},
        headers=await auth("core"),
    )
    assert response.status_code == 201


async def test_modificar_un_item_que_no_existe_da_404(client, auth):
    response = await client.patch(
        "/api/v1/catalogos/prioridades/items/no-existe",
        json={"nombre": "X"},
        headers=await auth("core"),
    )
    assert response.status_code == 404
