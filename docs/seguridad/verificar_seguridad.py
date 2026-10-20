"""Bateria de verificacion de la matriz de criterios de seguridad — Clase 11.

Corre en proceso contra la app real (httpx + ASGITransport) sobre una COPIA
descartable de la base: uno de los tests bloquea una cuenta a proposito.

Cada criterio imprime VEREDICTO + la evidencia cruda que lo sostiene.
"""
import asyncio, json, os, sys, pathlib

AQUI = pathlib.Path(__file__).parent
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{AQUI}/pruebas.db"
os.environ["RABBITMQ_URL"] = "memory://"
os.environ["ENVIRONMENT"] = "development"

import httpx, jwt, sqlite3, uuid
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.main import app

BASE = "/api/v1"
PASS, FAIL = "CUMPLE", "NO CUMPLE"
resultados = []

def veredicto(sec, titulo, estado, evidencia):
    resultados.append({"id": sec, "titulo": titulo, "estado": estado, "evidencia": evidencia})
    marca = "✓" if estado == PASS else "✗"
    print(f"\n{'='*74}\n{marca} {sec} — {titulo}\n  VEREDICTO: {estado}\n{'-'*74}")
    for linea in evidencia:
        print(f"  {linea}")

async def token(c, email, pwd="Cambiala123"):
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pwd})
    if r.status_code != 200:
        return None, r
    return r.json()["accessToken"], r

async def main():
    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://core", timeout=30) as c:
        tk_rentas, _ = await token(c, "rentas@muni.uade.edu.ar")
        tk_admin, _ = await token(c, "core@muni.uade.edu.ar")
        H = lambda t: {"Authorization": f"Bearer {t}"}
        assert tk_rentas and tk_admin, "no se pudo autenticar para las pruebas"

        # ---------------- SEC-01 : aislamiento multi-tenant ----------------
        # Ojo: un modulo SI debe ver un evento ajeno que le fue entregado, porque
        # esta suscripto. El aislamiento se prueba con un modulo que no es ni
        # origen ni destinatario de ese evento.
        con0 = sqlite3.connect(f"{AQUI}/pruebas.db")
        destinos = {}
        for eid, src in con0.execute("select event_id, source_module from event_log"):
            tg = {r[0] for r in con0.execute(
                "select d.target_module from deliveries d join event_log e on e.id=d.event_log_id where e.event_id=?", (eid,))}
            destinos[eid] = (src, tg)
        modulos = [r[0] for r in con0.execute("select name from modules where is_admin=0")]
        intruso, eid_privado, duenio = None, None, None
        for eid, (src, tg) in destinos.items():
            for m in modulos:
                if m != src and m not in tg:
                    intruso, eid_privado, duenio = m, eid, src
                    break
            if intruso: break

        tk_intruso, _ = await token(c, f"{intruso}@muni.uade.edu.ar")
        ev = [f"'{intruso}' no es ni origen ni destinatario del evento {uuid.UUID(eid_privado)}, publicado por '{duenio}'"]
        r = await c.get(f"{BASE}/events", headers=H(tk_intruso), params={"size": 100})
        vistos = {e["eventId"].replace("-", "") for e in r.json()["items"]}
        ev.append(f"GET /events (token de {intruso}) -> HTTP {r.status_code}, {r.json()['total']} resultados")
        ev.append(f"  el evento privado aparece en el listado: {eid_privado in vistos}")
        # y forzando el filtro al modulo ajeno
        r2 = await c.get(f"{BASE}/events", headers=H(tk_intruso),
                         params={"sourceModule": duenio, "size": 100})
        ajenos2 = [e for e in r2.json()["items"] if e["eventId"].replace("-", "") == eid_privado]
        ev.append(f"GET /events?sourceModule={duenio} (forzando el filtro) -> {len(ajenos2)} eventos privados filtrados")
        r3 = await c.get(f"{BASE}/dashboard/modules/{duenio}", headers=H(tk_intruso))
        ev.append(f"GET /dashboard/modules/{duenio} -> HTTP {r3.status_code}")
        ok = (eid_privado not in vistos) and not ajenos2 and r3.status_code == 403
        veredicto("SEC-01", "Un modulo no accede al trafico en el que no participa", PASS if ok else FAIL, ev)

        # ---------------- SEC-02 : funciones de admin ----------------
        ev, bien = [], True
        for metodo, ruta in [("GET", "/dashboard/global"), ("POST", "/modules/obras/rotate-secret"),
                             ("POST", "/dlq/retry-bulk"), ("POST", "/topology/apply")]:
            r = await c.request(metodo, f"{BASE}{ruta}", headers=H(tk_rentas))
            bien &= r.status_code == 403
            ev.append(f"{metodo:5} {ruta:34} (rentas) -> HTTP {r.status_code}")
        r = await c.get(f"{BASE}/dashboard/global", headers=H(tk_admin))
        ev.append(f"GET   /dashboard/global              (admin)  -> HTTP {r.status_code}  (control positivo)")
        bien &= r.status_code == 200
        veredicto("SEC-02", "Las funciones de administracion rechazan a un modulo comun",
                  PASS if bien else FAIL, ev)

        # ---------------- SEC-03 : autenticacion y firma ----------------
        ev, bien = [], True
        r = await c.get(f"{BASE}/events"); bien &= r.status_code == 401
        ev.append(f"sin header Authorization            -> HTTP {r.status_code}")
        r = await c.get(f"{BASE}/events", headers=H("basura.no.es.un.jwt")); bien &= r.status_code == 401
        ev.append(f"token con formato invalido          -> HTTP {r.status_code}")
        # token valido en estructura pero firmado con OTRA clave, y con isAdmin elevado
        otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = otra.private_bytes(serialization.Encoding.PEM,
                                 serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode()
        falso = jwt.encode({"sub": "user:x", "module": "rentas", "isAdmin": True, "kind": "user",
                            "exp": int((datetime.now(timezone.utc)+timedelta(hours=1)).timestamp())},
                           pem, algorithm="RS256")
        r = await c.get(f"{BASE}/dashboard/global", headers=H(falso)); bien &= r.status_code == 401
        ev.append(f"token firmado con otra clave RSA    -> HTTP {r.status_code}  (intentaba isAdmin=true)")
        # manipular el payload de un token legitimo
        cab, cuerpo, firma = tk_rentas.split(".")
        import base64
        relleno = lambda s: s + "=" * (-len(s) % 4)
        datos = json.loads(base64.urlsafe_b64decode(relleno(cuerpo)))
        datos["isAdmin"] = True
        nuevo = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
        r = await c.get(f"{BASE}/dashboard/global", headers=H(f"{cab}.{nuevo}.{firma}"))
        bien &= r.status_code == 401
        ev.append(f"payload alterado a isAdmin=true     -> HTTP {r.status_code}  (firma RS256 no valida)")
        veredicto("SEC-03", "Sin credencial valida no se accede; la firma RS256 frena la manipulacion",
                  PASS if bien else FAIL, ev)

        # ---------------- SEC-05 : enumeracion de usuarios ----------------
        r1 = await c.post(f"{BASE}/auth/login", json={"email": "nadie@muni.uade.edu.ar", "password": "Loquesea1"})
        r2 = await c.post(f"{BASE}/auth/login", json={"email": "obras@muni.uade.edu.ar", "password": "ContrasenaMala1"})
        # El traceId es distinto en cada request por diseno: se compara el resto.
        firma = lambda r: (r.status_code, r.json().get("code"), r.json().get("message"))
        igual = firma(r1) == firma(r2)
        ev = [f"email inexistente        -> HTTP {r1.status_code}  code={r1.json().get('code')}  \"{r1.json().get('message')}\"",
              f"email real, clave mala   -> HTTP {r2.status_code}  code={r2.json().get('code')}  \"{r2.json().get('message')}\"",
              f"(se ignora traceId, que es distinto por request a proposito)",
              f"respuestas indistinguibles: {igual}"]
        veredicto("SEC-05", "El login no revela si un email existe", PASS if igual else FAIL, ev)

        # ---------------- SEC-06 : limite de tasa ----------------
        codigos = []
        for _ in range(40):
            r = await c.post(f"{BASE}/auth/login", json={"email": "inexistente@muni.uade.edu.ar", "password": "x"})
            codigos.append(r.status_code)
        frenados = sum(1 for s in codigos if s == 429)
        ev = [f"40 intentos de login seguidos contra un email inexistente",
              f"  respuestas: {sorted(set(codigos))}   HTTP 429 recibidos: {frenados}",
              f"  no hay middleware de rate limiting en la app (grep: slowapi/Limiter/rate_limit sin resultados)"]
        veredicto("SEC-06", "El login limita la tasa de intentos por origen", PASS if frenados > 0 else FAIL, ev)

        # ---------------- SEC-07 : contrato del sobre ----------------
        ev, bien = [], True
        sobre = {"eventId": str(uuid.uuid4()), "eventType": "paymentConfirmed", "eventVersion": "1.0",
                 "occurredAt": datetime.now(timezone.utc).isoformat(), "sourceModule": "rentas", "data": {"x": 1}}
        r = await c.post(f"{BASE}/events", headers=H(tk_rentas), json=sobre)
        ev.append(f"sobre bien formado                       -> HTTP {r.status_code}")
        bien &= r.status_code in (200, 201, 202)
        malo = dict(sobre, eventId=str(uuid.uuid4()), isAdmin=True, rolInterno="superusuario")
        r = await c.post(f"{BASE}/events", headers=H(tk_rentas), json=malo)
        ev.append(f"sobre + campos no previstos (isAdmin)    -> HTTP {r.status_code}")
        if r.status_code == 422:
            ev.append(f"   {[e.get('field') or e.get('loc') for e in (r.json().get('detail') or r.json().get('errors') or [])][:4]}")
        bien &= r.status_code == 422
        sin_tz = dict(sobre, eventId=str(uuid.uuid4()), occurredAt="2026-10-13T12:00:00")
        r = await c.post(f"{BASE}/events", headers=H(tk_rentas), json=sin_tz)
        ev.append(f"occurredAt sin zona horaria              -> HTTP {r.status_code}")
        bien &= r.status_code == 422
        veredicto("SEC-07", "El sobre rechaza campos no previstos y fechas ambiguas",
                  PASS if bien else FAIL, ev)

        # ---------------- SEC-08 : propiedad del JSON Schema ----------------
        ev = []
        r0 = await c.get(f"{BASE}/event-types/workOrderScheduled", headers=H(tk_rentas))
        duenio = r0.json().get("ownerModule") if r0.status_code == 200 else "?"
        ev.append(f"'workOrderScheduled' pertenece a: {duenio}")
        r = await c.put(f"{BASE}/event-types/workOrderScheduled/schema", headers=H(tk_rentas),
                        json={"jsonSchema": {"type": "object", "required": ["inyectadoPorRentas"]}})
        ev.append(f"PUT /event-types/workOrderScheduled/schema  (token de rentas) -> HTTP {r.status_code}")
        if r.status_code == 200:
            v = await c.get(f"{BASE}/event-types/workOrderScheduled", headers=H(tk_admin))
            ev.append(f"  schema quedo como: {json.dumps(v.json().get('jsonSchema'), ensure_ascii=False)}")
            ev.append(f"  -> rentas reescribio el contrato de un evento de obras")
        veredicto("SEC-08", "Solo el modulo duenio puede escribir el JSON Schema de su evento",
                  PASS if r.status_code == 403 else FAIL, ev)

        # ---------------- SEC-09 : payload de un evento ajeno ----------------
        eid_fmt = str(uuid.UUID(eid_privado))
        r = await c.get(f"{BASE}/events/{eid_fmt}", headers=H(tk_intruso))
        ra = await c.get(f"{BASE}/events/{eid_fmt}", headers=H(tk_admin))
        src_real = con0.execute("select source_module from event_log where event_id=?", (eid_privado,)).fetchone()[0]
        ev = [f"evento publicado por '{src_real}', en el que '{intruso}' no participa: {eid_fmt}",
              f"GET /events/{{id}}  (token de {intruso}) -> HTTP {r.status_code}",
              f"GET /events/{{id}}  (admin)              -> HTTP {ra.status_code}  (control positivo)"]
        if ra.status_code == 200:
            ev.append(f"  el admin si ve el data: {json.dumps(ra.json().get('envelope', {}).get('data'), ensure_ascii=False)[:90]}")
        ok = r.status_code in (403, 404) and ra.status_code == 200
        veredicto("SEC-09", "El contenido de un evento solo lo ven origen, destinatarios y el admin",
                  PASS if ok else FAIL, ev)

        # ---------------- SEC-10 : secretos ----------------
        ev, bien = [], True
        fila = con0.execute("select name, secret_hash from modules where name='obras'").fetchone()
        es_sha256 = fila[1] and len(fila[1]) == 64 and all(ch in "0123456789abcdef" for ch in fila[1])
        ev.append(f"modules.secret_hash de 'obras': {fila[1][:16]}...  ({len(fila[1])} chars, hex={es_sha256})")
        bien &= bool(es_sha256)
        r = await c.get(f"{BASE}/modules", headers=H(tk_admin))
        cuerpo = r.text.lower()
        filtra = ("secret" not in cuerpo) or ("secret_hash" not in cuerpo and "secrethash" not in cuerpo)
        ev.append(f"GET /modules (admin): el secreto NO viaja en la respuesta: {filtra}")
        bien &= filtra
        src = (pathlib.Path(__file__).parents[4] if False else pathlib.Path("/Users/facundopedaccio/Documents/desarrollodeapps2/backend"))
        fuga = (src / "app/services/event_hub_service.py").read_text()
        tiene_preview = 'preview=raw_body[:200]' in fuga
        ev.append(f"app/services/event_hub_service.py:371 escribe el cuerpo crudo en el log: {tiene_preview}")
        ev.append(f"   logger.warning(\"malformed_message\", queue=queue, preview=raw_body[:200])")
        ev.append(f"   -> si un modulo manda un mensaje malformado con datos de un ciudadano,")
        ev.append(f"      esos datos quedan en el log de la aplicacion.")
        bien &= not tiene_preview
        veredicto("SEC-10", "Los datos sensibles no quedan en claro ni en la base ni en los logs",
                  PASS if bien else FAIL, ev)

        # ---------------- SEC-04 : bloqueo por fuerza bruta (va ultimo: bloquea) ----------------
        ev = []
        objetivo = "ambiente@muni.uade.edu.ar"
        for i in range(5):
            r = await c.post(f"{BASE}/auth/login", json={"email": objetivo, "password": f"malaClave{i}"})
            ev.append(f"intento fallido {i+1}/5 -> HTTP {r.status_code} {r.json().get('code','')}")
        r = await c.post(f"{BASE}/auth/login", json={"email": objetivo, "password": "Cambiala123"})
        ev.append(f"ahora con la contrasena CORRECTA -> HTTP {r.status_code} {r.json().get('code','')}")
        ev.append(f"   {r.json().get('message','')}")
        bloqueada = r.status_code == 403 and r.json().get("code") == "ACCOUNT_INACTIVE"
        veredicto("SEC-04", "La cuenta se bloquea tras 5 intentos fallidos",
                  PASS if bloqueada else FAIL, ev)

    # ---------------- resumen ----------------
    print(f"\n\n{'='*74}\nRESUMEN\n{'='*74}")
    for r in sorted(resultados, key=lambda x: x["id"]):
        print(f"  {r['id']}  {'✓ CUMPLE   ' if r['estado']==PASS else '✗ NO CUMPLE'}  {r['titulo']}")
    cumplen = sum(1 for r in resultados if r["estado"] == PASS)
    print(f"\n  {cumplen}/{len(resultados)} criterios cumplen. {len(resultados)-cumplen} hallazgos.")
    (AQUI / "resultados.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2))

asyncio.run(main())
