FROM oven/bun:1.3.13-debian AS frontend

WORKDIR /app/clients/web

COPY clients/web/package.json clients/web/bun.lock ./
COPY clients/web/vendor ./vendor
RUN bun install --frozen-lockfile

COPY clients/web ./
RUN bun run build


FROM python:3.12-slim AS runtime

ENV HOME=/root \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY newbro ./newbro
COPY --from=frontend /app/clients/web/dist ./clients/web/dist

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"

CMD ["newbro", "start", "--host", "0.0.0.0", "--port", "8000"]
