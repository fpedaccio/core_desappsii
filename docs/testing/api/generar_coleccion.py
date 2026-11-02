"""Genera la coleccion Postman de API/contratos del Core (tarea T6 de QA).

Uso, desde la raiz del repo:

    python3 docs/testing/api/generar_coleccion.py deploy/.testing/openapi-qa.json

Lee el OpenAPI exportado de la candidata y escribe, junto a este archivo:

- core-api.postman_collection.json: los casos, con status esperado y, para cada
  respuesta 2xx, la validacion del cuerpo contra el schema que declara el OpenAPI.
- core-local.postman_environment.json: variables sin valores sensibles.
- casos.json: id, operacion y status esperado de cada caso, para contrastar
  despues lo observado contra lo que documenta el contrato.

El status esperado sale del codigo de la candidata (dependencias de auth, guardas
de los servicios y validaciones de Pydantic), no de una corrida previa.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
API = "/api/v1"

# Palabras de JSON Schema que se conservan al pasar el schema a la coleccion. Se
# descartan `format`, `title`, `description` y `examples`: el validador de
# Postman rechaza formatos que no conoce y el resto no valida nada.
PALABRAS = {
    "type", "properties", "required", "items", "anyOf", "oneOf", "allOf", "enum",
    "const", "additionalProperties", "minimum", "maximum", "minLength", "maxLength",
    "minItems", "maxItems", "pattern",
}

# Cuerpo de error que devuelve el Core para 401/403/404/409/422/429. No figura en
# el OpenAPI: se valida aparte y la diferencia queda en el informe de contrato.
SCHEMA_ERROR = {
    "type": "object",
    "required": ["code", "message", "details", "traceId"],
    "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": "array"},
        "traceId": {"type": ["string", "null"]},
    },
}


def resolver(schema, componentes):
    if isinstance(schema, list):
        return [resolver(s, componentes) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return resolver(componentes[schema["$ref"].split("/")[-1]], componentes)
    salida = {}
    for clave, valor in schema.items():
        if clave not in PALABRAS:
            continue
        if clave == "properties":
            salida[clave] = {k: resolver(v, componentes) for k, v in valor.items()}
        elif clave in ("items", "additionalProperties") and isinstance(valor, dict):
            salida[clave] = resolver(valor, componentes)
        elif clave in ("anyOf", "oneOf", "allOf"):
            salida[clave] = [resolver(v, componentes) for v in valor]
        else:
            salida[clave] = valor
    return salida


class Generador:
    def __init__(self, openapi: dict) -> None:
        self.openapi = openapi
        self.componentes = openapi["components"]["schemas"]
        self.carpetas: list[dict] = []
        self.casos: list[dict] = []

    def carpeta(self, nombre: str) -> None:
        self.carpetas.append({"name": nombre, "item": []})

    def schema_de(self, metodo: str, ruta: str, status: int):
        operacion = self.openapi["paths"].get(ruta, {}).get(metodo.lower())
        if operacion is None:
            raise SystemExit(f"{metodo} {ruta} no esta en el OpenAPI")
        respuesta = operacion["responses"].get(str(status), {})
        schema = respuesta.get("content", {}).get("application/json", {}).get("schema")
        return resolver(schema, self.componentes) if schema else None

    def caso(
        self,
        cid: str,
        titulo: str,
        metodo: str,
        ruta: str,
        *,
        token: str | None = None,
        cuerpo=None,
        query: dict | None = None,
        url: str | None = None,
        espera: int,
        codigo: str | None = None,
        pruebas: str = "",
        previo: str = "",
        schema_de: tuple[str, str, int] | None = None,
    ) -> None:
        """Agrega un caso.

        `ruta` es la plantilla del OpenAPI (con `{param}`); `url` la concreta con
        variables de Postman. `token` es el nombre de la variable con el Bearer,
        o un literal entre comillas para tokens invalidos. `schema_de` toma el
        schema de otra respuesta del OpenAPI cuando el codigo devuelve a proposito
        un cuerpo que no es el de error.
        """
        concreta = url or ruta
        texto_url = "{{rootUrl}}" + concreta
        if query:
            texto_url += "?" + "&".join(f"{k}={v}" for k, v in query.items())

        js = [f'pm.test("{cid} responde {espera}", () => pm.response.to.have.status({espera}));']
        if espera < 300 and espera != 204:
            schema = self.schema_de(metodo, ruta, espera)
            if schema:
                js.append(
                    f'pm.test("{cid} cuerpo cumple el schema {espera} del OpenAPI", '
                    f"() => pm.response.to.have.jsonSchema({json.dumps(schema)}));"
                )
        elif schema_de:
            js.append(
                f'pm.test("{cid} cuerpo cumple el schema {schema_de[2]} del OpenAPI", '
                f"() => pm.response.to.have.jsonSchema({json.dumps(self.schema_de(*schema_de))}));"
            )
        elif espera >= 400:
            js.append(
                f'pm.test("{cid} cuerpo de error del Core", '
                f"() => pm.response.to.have.jsonSchema({json.dumps(SCHEMA_ERROR)}));"
            )
            js.append(
                f'pm.test("{cid} el error no trae token", () => '
                "pm.expect(pm.response.text()).to.not.include('accessToken'));"
            )
            if codigo:
                js.append(
                    f'pm.test("{cid} code {codigo}", () => '
                    f'pm.expect(pm.response.json().code).to.eql("{codigo}"));'
                )
        if pruebas:
            js.append(pruebas.strip())

        cabeceras = []
        if token:
            valor = token.strip('"') if token.startswith('"') else "{{" + token + "}}"
            cabeceras.append({"key": "Authorization", "value": f"Bearer {valor}"})
        request = {"method": metodo, "header": cabeceras, "url": texto_url}
        if cuerpo is not None:
            cabeceras.append({"key": "Content-Type", "value": "application/json"})
            raw = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False, indent=2)
            request["body"] = {"mode": "raw", "raw": raw}

        eventos = [{"listen": "test", "script": {"type": "text/javascript", "exec": js}}]
        if previo:
            eventos.insert(
                0, {"listen": "prerequest", "script": {"type": "text/javascript", "exec": [previo.strip()]}}
            )
        self.carpetas[-1]["item"].append(
            {"name": f"{cid} {titulo}", "event": eventos, "request": request}
        )
        self.casos.append(
            {
                "id": cid,
                "titulo": titulo,
                "carpeta": self.carpetas[-1]["name"],
                "metodo": metodo,
                "ruta": ruta,
                "identidad": token or "sin token",
                "espera": espera,
            }
        )


def construir(g: Generador) -> None:
    ev = "{{evType}}"
    schema_flujo = {
        "type": "object",
        "required": ["marker", "quantity"],
        "properties": {"marker": {"type": "string"}, "quantity": {"type": "integer"}},
        "additionalProperties": False,
    }

    def guardar(var: str, expr: str) -> str:
        return f"pm.collectionVariables.set('{var}', {expr});"

    # ------------------------------------------------------------------
    g.carpeta("00 Preparacion de fixture")
    g.caso(
        "P01", "Login admin local", "POST", f"{API}/auth/login",
        cuerpo={"email": "{{adminEmail}}", "password": "{{adminPassword}}"},
        espera=200,
        previo="""
const v = pm.collectionVariables;
const run = Date.now().toString(36).slice(-6);
v.set('run', run);
['a', 'b', 'c'].forEach(x => v.set('mod' + x.toUpperCase(), `qa-t6-${run}-${x}`));
v.set('evType', `qaT6${run}Flow`);
v.set('userAEmail', `qa-t6-${run}-a@example.com`);
v.set('userA2Email', `qa-t6-${run}-a2@example.com`);
const clave = () => 'Qa' + Math.random().toString(36).slice(2, 12) + '7k';
v.set('userPwd', clave());
v.set('userPwd2', clave());
""",
        pruebas="""
pm.test("P01 es admin", () => pm.expect(pm.response.json().isAdmin).to.be.true);
pm.collectionVariables.set('tokenAdmin', pm.response.json().accessToken);
""",
    )
    for letra in "ABC":
        g.caso(
            f"P0{2 + 'ABC'.index(letra)}", f"Alta del modulo sintetico {letra}", "POST", f"{API}/modules",
            token="tokenAdmin",
            cuerpo={"name": "{{mod" + letra + "}}", "displayName": f"QA T6 {letra}", "team": "QA T6"},
            espera=201,
            pruebas=guardar(f"secret{letra}", "pm.response.json().secret"),
        )
    for letra in "ABC":
        g.caso(
            f"P0{5 + 'ABC'.index(letra)}", f"Token de maquina de {letra}", "POST", f"{API}/auth/module-token",
            cuerpo={"module": "{{mod" + letra + "}}", "secret": "{{secret" + letra + "}}"},
            espera=200,
            pruebas=f"""
pm.test("P0{5 + 'ABC'.index(letra)} kind module", () => pm.expect(pm.response.json().kind).to.eql('module'));
pm.test("P0{5 + 'ABC'.index(letra)} no es admin", () => pm.expect(pm.response.json().isAdmin).to.be.false);
{guardar('token' + letra, 'pm.response.json().accessToken')}
""",
        )
    g.caso(
        "P08", "Admin crea la cuenta humana de A", "POST", f"{API}/users",
        token="tokenAdmin",
        cuerpo={"email": "{{userAEmail}}", "fullName": "QA T6 A", "password": "{{userPwd}}", "module": "{{modA}}"},
        espera=201,
        pruebas="""
pm.test("P08 queda en el modulo A", () => pm.expect(pm.response.json().moduleName).to.eql(pm.collectionVariables.get('modA')));
pm.test("P08 no devuelve la contrasena", () => pm.expect(pm.response.text()).to.not.include(pm.collectionVariables.get('userPwd')));
pm.collectionVariables.set('userAId', pm.response.json().id);
""",
    )
    g.caso(
        "P09", "Login de la cuenta humana de A", "POST", f"{API}/auth/login",
        cuerpo={"email": "{{userAEmail}}", "password": "{{userPwd}}"},
        espera=200,
        pruebas="""
pm.test("P09 kind user", () => pm.expect(pm.response.json().kind).to.eql('user'));
pm.collectionVariables.set('tokenUserA', pm.response.json().accessToken);
""",
    )

    # ------------------------------------------------------------------
    g.carpeta("01 Autenticacion")
    g.caso("AUTH-01", "Contrasena incorrecta", "POST", f"{API}/auth/login",
           cuerpo={"email": "{{userAEmail}}", "password": "NoEsLaClave123"}, espera=401, codigo="INVALID_CREDENTIALS")
    g.caso("AUTH-02", "Login sin contrasena", "POST", f"{API}/auth/login",
           cuerpo={"email": "{{userAEmail}}"}, espera=422, codigo="VALIDATION_ERROR",
           pruebas="""
pm.test("AUTH-02 senala el campo password", () => pm.expect(pm.response.json().details.map(d => d.field)).to.include("password"));
pm.test("AUTH-02 hallazgo: el 422 real no tiene el `detail` de HTTPValidationError que declara el OpenAPI", () => pm.expect(pm.response.json()).to.not.have.property('detail'));
""")
    g.caso("AUTH-03", "Email con formato invalido", "POST", f"{API}/auth/login",
           cuerpo={"email": "no-es-un-email", "password": "Algo12345"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("AUTH-04", "Secret de modulo incorrecto", "POST", f"{API}/auth/module-token",
           cuerpo={"module": "{{modA}}", "secret": "secreto-que-no-es"}, espera=401, codigo="INVALID_CREDENTIALS")
    g.caso("AUTH-05", "Modulo inexistente responde igual que secret incorrecto", "POST", f"{API}/auth/module-token",
           cuerpo={"module": "qa-t6-{{run}}-nadie", "secret": "secreto-que-no-es"}, espera=401, codigo="INVALID_CREDENTIALS")
    g.caso("AUTH-06", "Me como admin", "GET", f"{API}/auth/me", token="tokenAdmin", espera=200,
           pruebas='pm.test("AUTH-06 isAdmin", () => pm.expect(pm.response.json().isAdmin).to.be.true);')
    g.caso("AUTH-07", "Me con token de maquina", "GET", f"{API}/auth/me", token="tokenA", espera=200,
           pruebas="""
const me = pm.response.json();
pm.test("AUTH-07 identifica al modulo A", () => pm.expect(me.module).to.eql(pm.collectionVariables.get('modA')));
pm.test("AUTH-07 kind module y sin admin", () => { pm.expect(me.kind).to.eql('module'); pm.expect(me.isAdmin).to.be.false; });
""")
    g.caso("AUTH-08", "Me con token de persona", "GET", f"{API}/auth/me", token="tokenUserA", espera=200,
           pruebas="""
const me = pm.response.json();
pm.test("AUTH-08 kind user con email", () => { pm.expect(me.kind).to.eql('user'); pm.expect(me.email).to.eql(pm.collectionVariables.get('userAEmail')); });
""")
    g.caso("AUTH-09", "Me sin token", "GET", f"{API}/auth/me", espera=401)
    g.caso("AUTH-10", "Me con token mal formado", "GET", f"{API}/auth/me", token='"abc.def.ghi"', espera=401)
    g.caso("AUTH-11", "Admin rota el secret de B", "POST", f"{API}/modules/{{module_name}}/rotate-secret",
           url=f"{API}/modules/{{{{modB}}}}/rotate-secret", token="tokenAdmin", espera=200,
           pruebas="""
const v = pm.collectionVariables;
v.set('secretBPrevio', v.get('secretB'));
v.set('tokenBPrevio', v.get('tokenB'));
pm.test("AUTH-11 el secret nuevo es distinto", () => pm.expect(pm.response.json().secret).to.not.eql(v.get('secretB')));
v.set('secretB', pm.response.json().secret);
""")
    g.caso("AUTH-12", "El secret anterior de B ya no emite tokens", "POST", f"{API}/auth/module-token",
           cuerpo={"module": "{{modB}}", "secret": "{{secretBPrevio}}"}, espera=401, codigo="INVALID_CREDENTIALS")
    g.caso("AUTH-13", "El secret nuevo de B emite token", "POST", f"{API}/auth/module-token",
           cuerpo={"module": "{{modB}}", "secret": "{{secretB}}"}, espera=200,
           pruebas=guardar("tokenB", "pm.response.json().accessToken"))
    g.caso("AUTH-14", "OBSERVACION: un JWT emitido antes de rotar sigue valido hasta vencer", "GET", f"{API}/auth/me",
           token="tokenBPrevio", espera=200)

    # ------------------------------------------------------------------
    g.carpeta("02 Modulos y usuarios")
    g.caso("MOD-01", "Un modulo comun lista los modulos", "GET", f"{API}/modules", token="tokenA", espera=200,
           pruebas="""
const nombres = pm.response.json().map(m => m.name);
pm.test("MOD-01 incluye A y B", () => pm.expect(nombres).to.include.members([pm.collectionVariables.get('modA'), pm.collectionVariables.get('modB')]));
pm.test("MOD-01 no expone secrets", () => pm.expect(pm.response.text()).to.not.include('secret'));
""")
    g.caso("MOD-02", "Un modulo comun no puede dar de alta modulos", "POST", f"{API}/modules", token="tokenA",
           cuerpo={"name": "qa-t6-{{run}}-x", "displayName": "No deberia existir"}, espera=403)
    g.caso("MOD-03", "Nombre de modulo repetido", "POST", f"{API}/modules", token="tokenAdmin",
           cuerpo={"name": "{{modA}}", "displayName": "Repetido"}, espera=409)
    g.caso("MOD-04", "Nombre de modulo demasiado corto", "POST", f"{API}/modules", token="tokenAdmin",
           cuerpo={"name": "x", "displayName": "Corto"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("MOD-05", "B no puede editar el modulo A", "PATCH", f"{API}/modules/{{module_name}}",
           url=f"{API}/modules/{{{{modA}}}}", token="tokenB", cuerpo={"displayName": "Editado por B"}, espera=403)
    g.caso("MOD-06", "Editar un modulo inexistente", "PATCH", f"{API}/modules/{{module_name}}",
           url=f"{API}/modules/qa-t6-{{{{run}}}}-nadie", token="tokenAdmin", cuerpo={"displayName": "Nadie"}, espera=404)
    g.caso("MOD-07", "Admin edita el nombre visible de C", "PATCH", f"{API}/modules/{{module_name}}",
           url=f"{API}/modules/{{{{modC}}}}", token="tokenAdmin", cuerpo={"displayName": "QA T6 C editado"}, espera=200,
           pruebas='pm.test("MOD-07 persiste el cambio", () => pm.expect(pm.response.json().displayName).to.eql("QA T6 C editado"));')

    g.caso("USR-01", "Una persona solo ve las cuentas de su modulo", "GET", f"{API}/users", token="tokenUserA", espera=200,
           pruebas="""
const modulos = [...new Set(pm.response.json().map(u => u.moduleName))];
pm.test("USR-01 todas son del modulo A", () => pm.expect(modulos).to.eql([pm.collectionVariables.get('modA')]));
""")
    g.caso("USR-02", "A no puede crear cuentas en B", "POST", f"{API}/users", token="tokenUserA",
           cuerpo={"email": "qa-t6-{{run}}-intruso@example.com", "fullName": "Intruso", "password": "{{userPwd2}}", "module": "{{modB}}"},
           espera=403)
    g.caso("USR-03", "Contrasena solo con letras", "POST", f"{API}/users", token="tokenUserA",
           cuerpo={"email": "qa-t6-{{run}}-debil@example.com", "fullName": "Debil", "password": "soloLetrasLargas"},
           espera=422)
    g.caso("USR-04", "Contrasena de menos de 8 caracteres", "POST", f"{API}/users", token="tokenUserA",
           cuerpo={"email": "qa-t6-{{run}}-corta@example.com", "fullName": "Corta", "password": "ab12345"},
           espera=422, codigo="VALIDATION_ERROR")
    g.caso("USR-05", "Email repetido", "POST", f"{API}/users", token="tokenAdmin",
           cuerpo={"email": "{{userAEmail}}", "fullName": "Repetida", "password": "{{userPwd2}}", "module": "{{modA}}"},
           espera=409)
    g.caso("USR-06", "A crea una segunda cuenta en su modulo", "POST", f"{API}/users", token="tokenUserA",
           cuerpo={"email": "{{userA2Email}}", "fullName": "QA T6 A2", "password": "{{userPwd2}}"},
           espera=201,
           pruebas="""
pm.test("USR-06 sin module explicito queda en A", () => pm.expect(pm.response.json().moduleName).to.eql(pm.collectionVariables.get('modA')));
pm.collectionVariables.set('userA2Id', pm.response.json().id);
""")
    g.caso("USR-07", "B no puede editar una cuenta de A", "PATCH", f"{API}/users/{{user_id}}",
           url=f"{API}/users/{{{{userA2Id}}}}", token="tokenB", cuerpo={"fullName": "Editada por B"}, espera=403)
    g.caso("USR-08", "Editar una cuenta inexistente", "PATCH", f"{API}/users/{{user_id}}",
           url=f"{API}/users/{{{{$guid}}}}", token="tokenAdmin", cuerpo={"fullName": "Nadie"}, espera=404)
    g.caso("USR-09", "A cambia la contrasena de su segunda cuenta", "PUT", f"{API}/users/{{user_id}}/password",
           url=f"{API}/users/{{{{userA2Id}}}}/password", token="tokenUserA", cuerpo={"password": "{{userPwd}}"}, espera=200)
    g.caso("USR-10", "Login con la contrasena nueva", "POST", f"{API}/auth/login",
           cuerpo={"email": "{{userA2Email}}", "password": "{{userPwd}}"}, espera=200)
    g.caso("USR-11", "Login con la contrasena anterior", "POST", f"{API}/auth/login",
           cuerpo={"email": "{{userA2Email}}", "password": "{{userPwd2}}"}, espera=401, codigo="INVALID_CREDENTIALS")
    g.caso("USR-12", "A borra su segunda cuenta", "DELETE", f"{API}/users/{{user_id}}",
           url=f"{API}/users/{{{{userA2Id}}}}", token="tokenUserA", espera=204)
    g.caso("USR-13", "No se puede borrar la unica cuenta activa del modulo", "DELETE", f"{API}/users/{{user_id}}",
           url=f"{API}/users/{{{{userAId}}}}", token="tokenUserA", espera=409)
    g.caso("USR-14", "Id de cuenta que no es UUID", "DELETE", f"{API}/users/{{user_id}}",
           url=f"{API}/users/no-es-uuid", token="tokenAdmin", espera=422, codigo="VALIDATION_ERROR")

    # ------------------------------------------------------------------
    g.carpeta("03 Tipos de evento")
    alta_tipo = {"name": ev, "ownerModule": "{{modA}}", "description": "Tipo sintetico QA T6", "jsonSchema": schema_flujo}
    g.caso("ET-01", "A declara su tipo con schema", "POST", f"{API}/event-types", token="tokenA",
           cuerpo=alta_tipo, espera=201,
           pruebas="""
const t = pm.response.json();
pm.test("ET-01 owner A, valida y no descubierto", () => { pm.expect(t.ownerModule).to.eql(pm.collectionVariables.get('modA')); pm.expect(t.validates).to.be.true; pm.expect(t.discovered).to.be.false; });
pm.collectionVariables.set('evTypeId', t.id);
""")
    g.caso("ET-02", "Redeclarar el mismo tipo es idempotente", "POST", f"{API}/event-types", token="tokenA",
           cuerpo=alta_tipo, espera=201,
           pruebas='pm.test("ET-02 mismo id", () => pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get("evTypeId")));')
    g.caso("ET-03", "B no puede adueniarse del tipo de A", "POST", f"{API}/event-types", token="tokenB",
           cuerpo={"name": ev, "ownerModule": "{{modB}}", "jsonSchema": {"type": "object"}}, espera=403)
    g.caso("ET-04", "B no puede declarar un tipo a nombre de A", "POST", f"{API}/event-types", token="tokenB",
           cuerpo={"name": "qaT6{{run}}Ajeno", "ownerModule": "{{modA}}"}, espera=403)
    g.caso("ET-05", "B no puede cambiar el schema del tipo de A", "PUT", f"{API}/event-types/{{name}}/schema",
           url=f"{API}/event-types/{ev}/schema", token="tokenB", cuerpo={"jsonSchema": None}, espera=403)
    g.caso("ET-06", "A actualiza su schema", "PUT", f"{API}/event-types/{{name}}/schema",
           url=f"{API}/event-types/{ev}/schema", token="tokenA", cuerpo={"jsonSchema": schema_flujo}, espera=200)
    g.caso("ET-07", "Schema que no es JSON Schema valido", "POST", f"{API}/event-types", token="tokenA",
           cuerpo={"name": "qaT6{{run}}Roto", "ownerModule": "{{modA}}", "jsonSchema": {"type": "no-existe"}}, espera=422)
    g.caso("ET-08", "C consulta el tipo de A", "GET", f"{API}/event-types/{{name}}",
           url=f"{API}/event-types/{ev}", token="tokenC", espera=200)
    g.caso("ET-09", "Tipo inexistente", "GET", f"{API}/event-types/{{name}}",
           url=f"{API}/event-types/qaT6{{{{run}}}}NoExiste", token="tokenA", espera=404)
    g.caso("ET-10", "Filtrar tipos por duenio", "GET", f"{API}/event-types", token="tokenA",
           query={"ownerModule": "{{modA}}"}, espera=200,
           pruebas='pm.test("ET-10 incluye el tipo de A", () => pm.expect(pm.response.json().items.map(t => t.name)).to.include(pm.collectionVariables.get("evType")));')
    g.caso("ET-11", "Pagina de tamanio 0", "GET", f"{API}/event-types", token="tokenA",
           query={"size": "0"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("ET-12", "Pagina mayor al maximo (200)", "GET", f"{API}/event-types", token="tokenA",
           query={"size": "201"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("ET-13", "Mapa de tipos", "GET", f"{API}/event-types/map", token="tokenA", espera=200)

    # ------------------------------------------------------------------
    g.carpeta("04 Publicaciones y suscripciones")
    g.caso("PUB-01", "A declara que publica su tipo", "POST", f"{API}/publications", token="tokenA",
           cuerpo={"eventType": ev}, espera=201, pruebas=guardar("pubId", "pm.response.json().id"))
    g.caso("PUB-02", "Redeclarar la publicacion es idempotente", "POST", f"{API}/publications", token="tokenA",
           cuerpo={"eventType": ev}, espera=201,
           pruebas='pm.test("PUB-02 mismo id", () => pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get("pubId")));')
    g.caso("PUB-03", "B no puede declarar publicaciones de A", "POST", f"{API}/publications", token="tokenB",
           cuerpo={"eventType": ev, "module": "{{modA}}"}, espera=403)
    g.caso("PUB-04", "Listar publicaciones", "GET", f"{API}/publications", token="tokenC", espera=200,
           pruebas='pm.test("PUB-04 incluye la de A", () => pm.expect(pm.response.json().map(p => p.id)).to.include(pm.collectionVariables.get("pubId")));')
    g.caso("PUB-05", "B no puede borrar la publicacion de A", "DELETE", f"{API}/publications/{{publication_id}}",
           url=f"{API}/publications/{{{{pubId}}}}", token="tokenB", espera=403)
    g.caso("PUB-06", "A borra su publicacion", "DELETE", f"{API}/publications/{{publication_id}}",
           url=f"{API}/publications/{{{{pubId}}}}", token="tokenA", espera=204)
    g.caso("PUB-07", "Borrarla otra vez", "DELETE", f"{API}/publications/{{publication_id}}",
           url=f"{API}/publications/{{{{pubId}}}}", token="tokenA", espera=404)
    g.caso("PUB-08", "A la vuelve a declarar", "POST", f"{API}/publications", token="tokenA",
           cuerpo={"eventType": ev}, espera=201)

    g.caso("SUB-01", "B se suscribe con maxAttempts 4", "POST", f"{API}/subscriptions", token="tokenB",
           cuerpo={"eventType": ev, "maxAttempts": 4}, espera=201,
           pruebas="""
const s = pm.response.json();
pm.test("SUB-01 queda activa para B", () => { pm.expect(s.moduleName).to.eql(pm.collectionVariables.get('modB')); pm.expect(s.active).to.be.true; pm.expect(s.maxAttempts).to.eql(4); });
pm.collectionVariables.set('subB', s.id);
""")
    g.caso("SUB-02", "Resuscribirse es idempotente", "POST", f"{API}/subscriptions", token="tokenB",
           cuerpo={"eventType": ev, "maxAttempts": 4}, espera=201,
           pruebas='pm.test("SUB-02 mismo id", () => pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get("subB")));')
    g.caso("SUB-03", "maxAttempts 0", "POST", f"{API}/subscriptions", token="tokenB",
           cuerpo={"eventType": ev, "maxAttempts": 0}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("SUB-04", "maxAttempts 11", "POST", f"{API}/subscriptions", token="tokenB",
           cuerpo={"eventType": ev, "maxAttempts": 11}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("SUB-05", "C no puede suscribir a B", "POST", f"{API}/subscriptions", token="tokenC",
           cuerpo={"eventType": ev, "module": "{{modB}}"}, espera=403)
    g.caso("SUB-06", "C no puede pausar la suscripcion de B", "POST", f"{API}/subscriptions/{{subscription_id}}/toggle",
           url=f"{API}/subscriptions/{{{{subB}}}}/toggle", query={"active": "false"}, token="tokenC", espera=403)
    g.caso("SUB-07", "Pausar sin indicar active", "POST", f"{API}/subscriptions/{{subscription_id}}/toggle",
           url=f"{API}/subscriptions/{{{{subB}}}}/toggle", token="tokenB", espera=422, codigo="VALIDATION_ERROR")
    g.caso("SUB-08", "B pausa su suscripcion", "POST", f"{API}/subscriptions/{{subscription_id}}/toggle",
           url=f"{API}/subscriptions/{{{{subB}}}}/toggle", query={"active": "false"}, token="tokenB", espera=200,
           pruebas='pm.test("SUB-08 inactiva", () => pm.expect(pm.response.json().active).to.be.false);')
    g.caso("SUB-09", "B la reactiva", "POST", f"{API}/subscriptions/{{subscription_id}}/toggle",
           url=f"{API}/subscriptions/{{{{subB}}}}/toggle", query={"active": "true"}, token="tokenB", espera=200,
           pruebas='pm.test("SUB-09 activa", () => pm.expect(pm.response.json().active).to.be.true);')
    g.caso("SUB-10", "B ve solo sus suscripciones", "GET", f"{API}/subscriptions", token="tokenB", espera=200,
           pruebas="""
const subs = pm.response.json();
pm.test("SUB-10 incluye la de B", () => pm.expect(subs.map(s => s.id)).to.include(pm.collectionVariables.get('subB')));
pm.test("SUB-10 todas son de B", () => pm.expect([...new Set(subs.map(s => s.moduleName))]).to.eql([pm.collectionVariables.get('modB')]));
""")
    g.caso("SUB-11", "C se suscribe", "POST", f"{API}/subscriptions", token="tokenC",
           cuerpo={"eventType": ev}, espera=201,
           pruebas="""
pm.test("SUB-11 maxAttempts por defecto 4", () => pm.expect(pm.response.json().maxAttempts).to.eql(4));
pm.collectionVariables.set('subC', pm.response.json().id);
""")
    g.caso("SUB-12", "B no puede borrar la suscripcion de C", "DELETE", f"{API}/subscriptions/{{subscription_id}}",
           url=f"{API}/subscriptions/{{{{subC}}}}", token="tokenB", espera=403)
    g.caso("SUB-13", "C borra su suscripcion", "DELETE", f"{API}/subscriptions/{{subscription_id}}",
           url=f"{API}/subscriptions/{{{{subC}}}}", token="tokenC", espera=204)
    g.caso("SUB-14", "Borrarla otra vez", "DELETE", f"{API}/subscriptions/{{subscription_id}}",
           url=f"{API}/subscriptions/{{{{subC}}}}", token="tokenC", espera=404)
    g.caso("TOP-01", "Topologia planificada", "GET", f"{API}/topology", token="tokenA", espera=200)
    g.caso("TOP-02", "Un modulo comun no aplica la topologia", "POST", f"{API}/topology/apply", token="tokenA", espera=403)

    # ------------------------------------------------------------------
    g.carpeta("05 Eventos")
    previo_ok = """
const v = pm.collectionVariables;
v.set('eventId1', pm.variables.replaceIn('{{$guid}}'));
v.set('correlationId1', pm.variables.replaceIn('{{$guid}}'));
v.set('occurredAt', new Date().toISOString());
"""
    sobre_ok = {
        "eventId": "{{eventId1}}", "eventType": ev, "eventVersion": "1.0", "occurredAt": "{{occurredAt}}",
        "sourceModule": "{{modA}}", "correlationId": "{{correlationId1}}",
        "data": {"marker": "qa-t6-positivo-01", "quantity": 1},
    }
    g.caso("EV-01", "A publica un evento valido", "POST", f"{API}/events", token="tokenA",
           cuerpo=sobre_ok, espera=202, previo=previo_ok,
           pruebas="""
const r = pm.response.json();
pm.test("EV-01 aceptado, no duplicado", () => { pm.expect(r.accepted).to.be.true; pm.expect(r.duplicate).to.be.false; });
pm.test("EV-01 ruteado a B y no a C", () => { pm.expect(r.routedTo).to.include(pm.collectionVariables.get('modB')); pm.expect(r.routedTo).to.not.include(pm.collectionVariables.get('modC')); });
""")
    g.caso("EV-02", "Reenvio del mismo eventId", "POST", f"{API}/events", token="tokenA",
           cuerpo=sobre_ok, espera=200,
           pruebas='pm.test("EV-02 duplicate true", () => pm.expect(pm.response.json().duplicate).to.be.true);')
    g.caso("EV-03", "A ve el detalle con una sola entrega a B", "GET", f"{API}/events/{{event_id}}",
           url=f"{API}/events/{{{{eventId1}}}}", token="tokenA", espera=200,
           pruebas="""
const e = pm.response.json();
pm.test("EV-03 una entrega, a B", () => { pm.expect(e.deliveries.length).to.eql(1); pm.expect(e.deliveries[0].targetModule).to.eql(pm.collectionVariables.get('modB')); });
pm.test("EV-03 conserva el sobre", () => pm.expect(e.envelope.data.marker).to.eql('qa-t6-positivo-01'));
""")
    g.caso("EV-04", "B (destino) ve el evento", "GET", f"{API}/events/{{event_id}}",
           url=f"{API}/events/{{{{eventId1}}}}", token="tokenB", espera=200)
    g.caso("EV-05", "C (ajeno) no ve el evento", "GET", f"{API}/events/{{event_id}}",
           url=f"{API}/events/{{{{eventId1}}}}", token="tokenC", espera=404)
    g.caso("EV-06", "A no puede publicar a nombre de B", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "{{$guid}}", "sourceModule": "{{modB}}"}, espera=403)
    g.caso("EV-07", "occurredAt sin zona horaria", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "{{eventIdSinZona}}", "occurredAt": "2026-11-02T10:00:00"},
           espera=422, codigo="VALIDATION_ERROR",
           previo="pm.collectionVariables.set('eventIdSinZona', pm.variables.replaceIn('{{$guid}}'));")
    g.caso("EV-08", "El sobre rechazado no se persiste", "GET", f"{API}/events/{{event_id}}",
           url=f"{API}/events/{{{{eventIdSinZona}}}}", token="tokenAdmin", espera=404)
    g.caso("EV-09", "Campo extra en el sobre", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "{{$guid}}", "campoExtra": "x"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("EV-10", "eventId que no es UUID", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "evento-1"}, espera=422, codigo="VALIDATION_ERROR")
    sin_origen = {k: v for k, v in sobre_ok.items() if k != "sourceModule"}
    g.caso("EV-11", "Sobre sin sourceModule", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sin_origen, "eventId": "{{$guid}}"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("EV-12", "data que no cumple el schema del tipo", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "{{eventIdInvalido}}", "data": {"marker": "qa-t6-negativo-01", "quantity": "uno"}},
           espera=422, schema_de=("POST", f"{API}/events", 202),
           previo="pm.collectionVariables.set('eventIdInvalido', pm.variables.replaceIn('{{$guid}}'));",
           pruebas="""
const r = pm.response.json();
pm.test("EV-12 REJECTED por SCHEMA_VIOLATION", () => { pm.expect(r.status).to.eql('REJECTED'); pm.expect(r.rejectionCode).to.eql('SCHEMA_VIOLATION'); });
pm.test("EV-12 no se rutea a nadie", () => pm.expect(r.routedTo).to.eql([]));
""")
    g.caso("EV-13", "El rechazo por schema si queda persistido", "GET", f"{API}/events/{{event_id}}",
           url=f"{API}/events/{{{{eventIdInvalido}}}}", token="tokenA", espera=200,
           pruebas="""
const e = pm.response.json();
pm.test("EV-13 REJECTED sin entregas", () => { pm.expect(e.status).to.eql('REJECTED'); pm.expect(e.deliveries).to.eql([]); });
""")
    g.caso("EV-14", "Tipo no declarado se acepta y se registra solo", "POST", f"{API}/events", token="tokenA",
           cuerpo={**sobre_ok, "eventId": "{{$guid}}", "eventType": "qaT6{{run}}Descubierto"}, espera=202,
           pruebas='pm.test("EV-14 eventTypeDiscovered", () => pm.expect(pm.response.json().eventTypeDiscovered).to.be.true);')
    g.caso("EV-15", "El tipo descubierto queda marcado", "GET", f"{API}/event-types/{{name}}",
           url=f"{API}/event-types/qaT6{{{{run}}}}Descubierto", token="tokenA", espera=200,
           pruebas='pm.test("EV-15 discovered", () => pm.expect(pm.response.json().discovered).to.be.true);')
    g.caso("EV-16", "A lista los eventos de su tipo", "GET", f"{API}/events", token="tokenA",
           query={"eventType": ev}, espera=200,
           pruebas='pm.test("EV-16 el valido y el rechazado", () => pm.expect(pm.response.json().total).to.eql(2));')
    g.caso("EV-17", "C no ve eventos de ese tipo", "GET", f"{API}/events", token="tokenC",
           query={"eventType": ev}, espera=200,
           pruebas='pm.test("EV-17 total 0", () => pm.expect(pm.response.json().total).to.eql(0));')
    g.caso("EV-18", "C no puede ampliar su alcance con filtros", "GET", f"{API}/events", token="tokenC",
           query={"sourceModule": "{{modA}}"}, espera=200,
           pruebas='pm.test("EV-18 total 0", () => pm.expect(pm.response.json().total).to.eql(0));')
    g.caso("EV-19", "Pagina mayor al maximo", "GET", f"{API}/events", token="tokenA",
           query={"size": "201"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("EV-20", "Recorrido por correlationId", "GET", f"{API}/events/journey/{{correlation_id}}",
           url=f"{API}/events/journey/{{{{correlationId1}}}}", token="tokenA", espera=200,
           pruebas='pm.test("EV-20 incluye el evento", () => pm.expect(pm.response.json().eventCount).to.be.at.least(1));')
    g.caso("EV-24", "C no ve el recorrido ajeno", "GET", f"{API}/events/journey/{{correlation_id}}",
           url=f"{API}/events/journey/{{{{correlationId1}}}}", token="tokenC", espera=200,
           pruebas='pm.test("EV-24 eventCount 0", () => pm.expect(pm.response.json().eventCount).to.eql(0));')
    g.caso("EV-21", "Schema del sobre es publico", "GET", f"{API}/events-meta/envelope-schema", espera=200)
    g.caso("EV-22", "B ve su entrega", "GET", f"{API}/deliveries", token="tokenB",
           query={"eventType": ev}, espera=200,
           pruebas='pm.test("EV-22 una entrega a B", () => { const r = pm.response.json(); pm.expect(r.total).to.eql(1); pm.expect(r.items[0].targetModule).to.eql(pm.collectionVariables.get("modB")); });')
    g.caso("EV-23", "C no ve entregas ajenas", "GET", f"{API}/deliveries", token="tokenC",
           query={"eventType": ev}, espera=200,
           pruebas='pm.test("EV-23 total 0", () => pm.expect(pm.response.json().total).to.eql(0));')

    # ------------------------------------------------------------------
    g.carpeta("06 DLQ")
    g.caso("DLQ-01", "A ve la dead letter de su rechazo", "GET", f"{API}/dlq", token="tokenA",
           query={"eventType": ev}, espera=200,
           pruebas="""
const r = pm.response.json();
pm.test("DLQ-01 una SCHEMA_VIOLATION", () => { pm.expect(r.total).to.eql(1); pm.expect(r.items[0].reasonCode).to.eql('SCHEMA_VIOLATION'); });
pm.collectionVariables.set('dlId', r.items[0].id);
""")
    g.caso("DLQ-02", "C no ve esa dead letter en el listado", "GET", f"{API}/dlq", token="tokenC",
           query={"eventType": ev}, espera=200,
           pruebas='pm.test("DLQ-02 total 0", () => pm.expect(pm.response.json().total).to.eql(0));')
    g.caso("DLQ-03", "C no ve el detalle", "GET", f"{API}/dlq/{{dead_letter_id}}",
           url=f"{API}/dlq/{{{{dlId}}}}", token="tokenC", espera=404)
    g.caso("DLQ-04", "A ve el detalle", "GET", f"{API}/dlq/{{dead_letter_id}}",
           url=f"{API}/dlq/{{{{dlId}}}}", token="tokenA", espera=200)
    g.caso("DLQ-05", "Un modulo comun no reintenta", "POST", f"{API}/dlq/{{dead_letter_id}}/retry",
           url=f"{API}/dlq/{{{{dlId}}}}/retry", token="tokenA", espera=403)
    g.caso("DLQ-06", "Un modulo comun no reintenta en lote", "POST", f"{API}/dlq/retry-bulk", token="tokenA",
           cuerpo={"deadLetterIds": ["{{dlId}}"]}, espera=403)
    g.caso("DLQ-07", "Reintento en lote vacio", "POST", f"{API}/dlq/retry-bulk", token="tokenAdmin",
           cuerpo={"deadLetterIds": []}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("DLQ-08", "Descartar con motivo demasiado corto", "POST", f"{API}/dlq/{{dead_letter_id}}/discard",
           url=f"{API}/dlq/{{{{dlId}}}}/discard", token="tokenAdmin", cuerpo={"reason": "x"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("DLQ-09", "Admin descarta con motivo", "POST", f"{API}/dlq/{{dead_letter_id}}/discard",
           url=f"{API}/dlq/{{{{dlId}}}}/discard", token="tokenAdmin",
           cuerpo={"reason": "QA T6: data invalido enviado a proposito"}, espera=200,
           pruebas='pm.test("DLQ-09 queda DISCARDED", () => pm.expect(pm.response.json().status).to.eql("DISCARDED"));')
    g.caso("DLQ-10", "Auditoria de la dead letter", "GET", f"{API}/dlq/{{dead_letter_id}}/audit",
           url=f"{API}/dlq/{{{{dlId}}}}/audit", token="tokenAdmin", espera=200,
           pruebas='pm.collectionVariables.set("auditTotal", pm.response.json().total);')
    # La lista y el detalle limitan la DLQ a origen/destino (DLQ-02, DLQ-03); la
    # auditoria es parte de la misma dead letter y deberia seguir la misma regla.
    g.caso("DLQ-13", "C no deberia ver la auditoria de una dead letter ajena", "GET", f"{API}/dlq/{{dead_letter_id}}/audit",
           url=f"{API}/dlq/{{{{dlId}}}}/audit", token="tokenC", espera=404)
    g.caso("DLQ-14", "Auditoria de una dead letter inexistente", "GET", f"{API}/dlq/{{dead_letter_id}}/audit",
           url=f"{API}/dlq/{{{{$guid}}}}/audit", token="tokenAdmin", espera=404)
    g.caso("DLQ-11", "Un modulo comun no procesa reintentos vencidos", "POST", f"{API}/deliveries/process-due-retries",
           token="tokenA", espera=403)
    g.caso("DLQ-12", "Admin procesa reintentos vencidos", "POST", f"{API}/deliveries/process-due-retries",
           token="tokenAdmin", espera=200)

    # ------------------------------------------------------------------
    g.carpeta("07 Dashboard")
    g.caso("DSH-01", "Tablero propio de A", "GET", f"{API}/dashboard", token="tokenA", espera=200)
    g.caso("DSH-02", "A no ve el tablero de B", "GET", f"{API}/dashboard/modules/{{module_name}}",
           url=f"{API}/dashboard/modules/{{{{modB}}}}", token="tokenA", espera=403)
    g.caso("DSH-03", "A ve su tablero por nombre", "GET", f"{API}/dashboard/modules/{{module_name}}",
           url=f"{API}/dashboard/modules/{{{{modA}}}}", token="tokenA", espera=200)
    g.caso("DSH-04", "Un modulo comun no ve el global", "GET", f"{API}/dashboard/global", token="tokenA", espera=403)
    g.caso("DSH-05", "Admin ve el global", "GET", f"{API}/dashboard/global", token="tokenAdmin", espera=200)
    g.caso("DSH-06", "windowHours 0", "GET", f"{API}/dashboard", token="tokenA",
           query={"windowHours": "0"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("DSH-07", "windowHours 721", "GET", f"{API}/dashboard", token="tokenA",
           query={"windowHours": "721"}, espera=422, codigo="VALIDATION_ERROR")
    g.caso("DSH-08", "Alertas de integracion", "GET", f"{API}/dashboard/integration-alerts", token="tokenA", espera=200)

    # ------------------------------------------------------------------
    g.carpeta("08 Catalogos")
    g.caso("CAT-01", "Zonas: las 15 comunas", "GET", f"{API}/catalogos/zonas", token="tokenA", espera=200,
           pruebas="""
const comunas = pm.response.json().filter(z => /^comuna-\\d+$/.test(z.codigo));
pm.test("CAT-01 quince comunas", () => pm.expect(comunas.length).to.eql(15));
""")
    g.caso("CAT-02", "Barrios activos de CABA", "GET", f"{API}/catalogos/barrios", token="tokenA", espera=200,
           pruebas='pm.test("CAT-02 al menos 48", () => pm.expect(pm.response.json().length).to.be.at.least(48));')
    g.caso("CAT-03", "Palermo pertenece a la comuna 14", "GET", f"{API}/catalogos/barrios/{{codigo}}",
           url=f"{API}/catalogos/barrios/palermo", token="tokenA", espera=200,
           pruebas='pm.test("CAT-03 comuna-14", () => pm.expect(pm.response.json().zona).to.eql("comuna-14"));')
    g.caso("CAT-04", "Barrios de la comuna 4", "GET", f"{API}/catalogos/barrios", token="tokenA",
           query={"zona": "comuna-4"}, espera=200,
           pruebas="""
pm.test("CAT-04 cuatro barrios", () => pm.expect(pm.response.json().map(b => b.codigo).sort()).to.eql(['barracas', 'la-boca', 'nueva-pompeya', 'parque-patricios']));
""")
    g.caso("CAT-05", "Barrio inexistente", "GET", f"{API}/catalogos/barrios/{{codigo}}",
           url=f"{API}/catalogos/barrios/no-existe", token="tokenA", espera=404)
    g.caso("CAT-06", "Un modulo comun no crea zonas", "POST", f"{API}/catalogos/zonas", token="tokenA",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "No deberia existir"}, espera=403)
    g.caso("CAT-07", "Admin crea una zona sintetica", "POST", f"{API}/catalogos/zonas", token="tokenAdmin",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "Zona QA T6"}, espera=201)
    g.caso("CAT-08", "Codigo de zona repetido", "POST", f"{API}/catalogos/zonas", token="tokenAdmin",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "Repetida"}, espera=409)
    g.caso("CAT-14", "Un modulo comun no crea barrios", "POST", f"{API}/catalogos/barrios", token="tokenA",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "No deberia existir", "zona": "qa-t6-{{run}}"}, espera=403)
    g.caso("CAT-15", "Admin crea un barrio sintetico en su zona", "POST", f"{API}/catalogos/barrios", token="tokenAdmin",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "Barrio QA T6", "zona": "qa-t6-{{run}}"}, espera=201,
           pruebas='pm.test("CAT-15 queda en la zona sintetica", () => pm.expect(pm.response.json().zona).to.eql("qa-t6-" + pm.collectionVariables.get("run")));')
    g.caso("CAT-16", "Barrio con zona inexistente", "POST", f"{API}/catalogos/barrios", token="tokenAdmin",
           cuerpo={"codigo": "qa-t6-{{run}}-x", "nombre": "Sin zona valida", "zona": "qa-t6-{{run}}-nadie"}, espera=404)
    g.caso("CAT-17", "Admin da de baja el barrio sintetico", "PATCH", f"{API}/catalogos/barrios/{{codigo}}",
           url=f"{API}/catalogos/barrios/qa-t6-{{{{run}}}}", token="tokenAdmin", cuerpo={"activo": False}, espera=200,
           pruebas='pm.test("CAT-17 inactivo", () => pm.expect(pm.response.json().activo).to.be.false);')
    g.caso("CAT-09", "Admin da de baja la zona sintetica", "PATCH", f"{API}/catalogos/zonas/{{codigo}}",
           url=f"{API}/catalogos/zonas/qa-t6-{{{{run}}}}", token="tokenAdmin", cuerpo={"activo": False}, espera=200,
           pruebas='pm.test("CAT-09 inactiva", () => pm.expect(pm.response.json().activo).to.be.false);')
    g.caso("CAT-10", "Catalogos genericos", "GET", f"{API}/catalogos", token="tokenA", espera=200,
           pruebas="pm.collectionVariables.set('catalogo', pm.response.json()[0]);")
    g.caso("CAT-11", "Items de un catalogo", "GET", f"{API}/catalogos/{{catalogo}}/items",
           url=f"{API}/catalogos/{{{{catalogo}}}}/items", token="tokenA", espera=200)
    g.caso("CAT-12", "Un modulo comun no crea items", "POST", f"{API}/catalogos/{{catalogo}}/items",
           url=f"{API}/catalogos/{{{{catalogo}}}}/items", token="tokenA",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "No deberia existir"}, espera=403)
    g.caso("CAT-18", "Admin agrega un item sintetico", "POST", f"{API}/catalogos/{{catalogo}}/items",
           url=f"{API}/catalogos/{{{{catalogo}}}}/items", token="tokenAdmin",
           cuerpo={"codigo": "qa-t6-{{run}}", "nombre": "Item QA T6"}, espera=201)
    g.caso("CAT-19", "Admin da de baja el item sintetico", "PATCH", f"{API}/catalogos/{{catalogo}}/items/{{codigo}}",
           url=f"{API}/catalogos/{{{{catalogo}}}}/items/qa-t6-{{{{run}}}}", token="tokenAdmin",
           cuerpo={"activo": False}, espera=200,
           pruebas='pm.test("CAT-19 inactivo", () => pm.expect(pm.response.json().activo).to.be.false);')
    g.caso("CAT-20", "Editar un item inexistente", "PATCH", f"{API}/catalogos/{{catalogo}}/items/{{codigo}}",
           url=f"{API}/catalogos/{{{{catalogo}}}}/items/qa-t6-{{{{run}}}}-nadie", token="tokenAdmin",
           cuerpo={"activo": False}, espera=404)
    g.caso("CAT-13", "Catalogos sin token", "GET", f"{API}/catalogos/zonas", espera=401)

    # ------------------------------------------------------------------
    g.carpeta("09 Salud")
    g.caso("SAL-01", "Liveness", "GET", "/health/live", espera=200)
    g.caso("SAL-02", "Readiness con base y broker", "GET", "/health/ready", espera=200,
           pruebas='pm.test("SAL-02 base arriba", () => pm.expect(pm.response.json().checks.database.status).to.eql("up"));')

    # ------------------------------------------------------------------
    g.carpeta("10 Limite de autenticacion")
    g.caso("RL-01", "Diez intentos por identidad y endpoint; el undecimo es 429", "POST", f"{API}/auth/login",
           cuerpo={"email": "qa-t6-{{run}}-limite@example.com", "password": "NoEsLaClave123"},
           espera=401,
           pruebas="""
const v = pm.collectionVariables;
const n = Number(v.get('rlIntento') || 0) + 1;
v.set('rlIntento', n);
if (n < 10) { postman.setNextRequest(pm.info.requestName); }
""")
    g.caso("RL-02", "Intento 11 de la misma identidad", "POST", f"{API}/auth/login",
           cuerpo={"email": "qa-t6-{{run}}-limite@example.com", "password": "NoEsLaClave123"},
           espera=429, codigo="RATE_LIMITED",
           pruebas="""
pm.test("RL-02 informa Retry-After", () => pm.expect(Number(pm.response.headers.get('Retry-After'))).to.be.above(0));
pm.test("RL-02 fueron 10 intentos previos", () => pm.expect(Number(pm.collectionVariables.get('rlIntento'))).to.eql(10));
""")
    g.caso("RL-03", "Otra identidad no queda bloqueada", "POST", f"{API}/auth/login",
           cuerpo={"email": "qa-t6-{{run}}-otra@example.com", "password": "NoEsLaClave123"}, espera=401)

    # ------------------------------------------------------------------
    g.carpeta("99 Limpieza")
    for i, letra in enumerate("ABC", start=1):
        g.caso(f"CLN-0{i}", f"Desactivar el modulo {letra}", "PATCH", f"{API}/modules/{{module_name}}",
               url=f"{API}/modules/{{{{mod{letra}}}}}", token="tokenAdmin", cuerpo={"active": False}, espera=200,
               pruebas=f'pm.test("CLN-0{i} active false", () => pm.expect(pm.response.json().active).to.be.false);')
    g.caso("CLN-04", "Un modulo desactivado no obtiene tokens nuevos", "POST", f"{API}/auth/module-token",
           cuerpo={"module": "{{modA}}", "secret": "{{secretA}}"}, espera=403)
    g.caso("CLN-05", "Su cuenta humana tampoco entra", "POST", f"{API}/auth/login",
           cuerpo={"email": "{{userAEmail}}", "password": "{{userPwd}}"}, espera=403)
    g.caso("CLN-06", "OBSERVACION: el JWT ya emitido de A sigue valido hasta vencer", "GET", f"{API}/auth/me",
           token="tokenA", espera=200)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    openapi = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    g = Generador(openapi)
    construir(g)

    variables = [
        "run", "modA", "modB", "modC", "evType", "evTypeId", "userAEmail", "userA2Email",
        "userPwd", "userPwd2", "userAId", "userA2Id", "secretA", "secretB", "secretC",
        "secretBPrevio", "tokenAdmin", "tokenA", "tokenB", "tokenC", "tokenBPrevio",
        "tokenUserA", "pubId", "subB", "subC", "eventId1", "correlationId1", "occurredAt",
        "eventIdSinZona", "eventIdInvalido", "dlId", "auditTotal", "catalogo", "rlIntento",
    ]
    coleccion = {
        "info": {
            "name": "Core - API y contratos (T6)",
            "description": (
                "Casos de API del Core contra la candidata de QA. Crea su propia fixture "
                "(modulos qa-t6-<run>-a/b/c) y al final la desactiva. Necesita las variables "
                "de entorno rootUrl, adminEmail y adminPassword (esta ultima privada). "
                "Generada por docs/testing/api/generar_coleccion.py desde el OpenAPI "
                f"version {openapi['info']['version']}."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": g.carpetas,
        "variable": [{"key": k, "value": ""} for k in variables],
    }
    entorno = {
        "name": "Core local (candidata QA)",
        "values": [
            {"key": "rootUrl", "value": "http://127.0.0.1:18090", "type": "default", "enabled": True},
            {"key": "adminEmail", "value": "core@muni.uade.edu.ar", "type": "default", "enabled": True},
            {"key": "adminPassword", "value": "", "type": "secret", "enabled": True},
        ],
    }
    (AQUI / "core-api.postman_collection.json").write_text(
        json.dumps(coleccion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (AQUI / "core-local.postman_environment.json").write_text(
        json.dumps(entorno, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (AQUI / "casos.json").write_text(json.dumps(g.casos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(g.casos)} casos en {len(g.carpetas)} carpetas")


if __name__ == "__main__":
    main()
