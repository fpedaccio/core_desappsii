# Imagen del Core. Un solo proceso: con RUN_WORKER=true la API tambien consume
# de core.inbox y q.dlq, asi el deploy es un contenedor y no dos.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Las dependencias primero, que cambian mucho menos que el codigo: asi editar
# un .py no reinstala fastapi.
#
# `pip install .` sin `app/` presente instala solo las dependencias (el paquete
# queda vacio, porque no hay nada que empaquetar). El codigo se copia despues y
# se importa desde el WORKDIR. Verificado: con asyncpg la app levanta sus 56
# endpoints sin tener el paquete en site-packages.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app

# La plataforma inyecta $PORT. 8000 es solo el default para correrlo local.
ENV PORT=8000
EXPOSE 8000

# El healthcheck pega a /health/live, que no toca la base: responde aunque
# Postgres este arrancando todavia.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/health/live')"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
