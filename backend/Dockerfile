FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements-deploy.lock ./
COPY app ./app
RUN pip install --no-cache-dir -r requirements-deploy.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home core
COPY container_entrypoint.py /app/container_entrypoint.py
RUN chmod -R a+rX /app/app && chmod a+r /app/container_entrypoint.py
USER core
EXPOSE 8000
ENTRYPOINT ["python", "/app/container_entrypoint.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
