# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS build
WORKDIR /build
COPY backend/requirements.runtime.lock requirements.lock
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --prefix=/install -r requirements.lock

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 agent && useradd --uid 10001 --gid agent --no-create-home agent
COPY --from=build /install /usr/local
WORKDIR /app
COPY --chown=agent:agent backend/app ./app
COPY --chown=agent:agent backend/migrations ./migrations
COPY --chown=agent:agent backend/alembic.ini ./alembic.ini
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--proxy-headers"]
