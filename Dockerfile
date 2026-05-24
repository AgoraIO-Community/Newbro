FROM oven/bun:1.3.13-debian AS frontend

WORKDIR /app/src/newbro/ui

COPY src/newbro/ui/package.json src/newbro/ui/bun.lock ./
COPY src/newbro/ui/vendor ./vendor
RUN bun install --frozen-lockfile

COPY src/newbro/ui ./
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
COPY --from=frontend /app/src/newbro/ui/dist ./src/newbro/ui/dist

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"

CMD ["newbro", "start", "--host", "0.0.0.0", "--port", "8000"]
