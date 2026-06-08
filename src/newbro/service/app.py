from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from newbro.api.paths import SERVICE_RESERVED_ROUTE_PREFIXES
from newbro.api.app import create_app as create_api_app
from newbro.connectors.host.app import include_enabled_connector_routes
from newbro.connectors.host.config import ConnectorHostSettings, load_connector_host_settings
from newbro.runtime.config import Settings


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FRONTEND_DIST_DIR = ROOT / "clients" / "web" / "dist"


def create_app(
    *,
    settings: Settings | None = None,
    frontend_dist: Path | None = None,
    connector_settings: ConnectorHostSettings | None = None,
) -> FastAPI:
    app = create_api_app(settings=settings)
    include_enabled_connector_routes(app, connector_settings or load_connector_host_settings())
    _install_frontend_routes(app, frontend_dist or DEFAULT_FRONTEND_DIST_DIR)
    return app


def _install_frontend_routes(app: FastAPI, frontend_dist: Path) -> None:
    resolved_frontend_dist = Path(frontend_dist)

    @app.api_route(
        "/{path:path}",
        methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def frontend_non_get(path: str) -> Response:
        raise HTTPException(status_code=404, detail="Not found.")

    @app.get("/", include_in_schema=False)
    async def frontend_root() -> Response:
        return _frontend_response(resolved_frontend_dist, "")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_entrypoint(path: str) -> Response:
        if _is_reserved_path(path):
            raise HTTPException(status_code=404, detail="Not found.")
        return _frontend_response(resolved_frontend_dist, path)


def _frontend_file_response(path: Path) -> Response:
    media_type, _ = mimetypes.guess_type(path.name)
    if path.suffix == ".html":
        media_type = "text/html; charset=utf-8"
    return Response(
        content=path.read_bytes(),
        media_type=media_type or "application/octet-stream",
    )


def _resolve_frontend_asset(frontend_dist: Path, frontend_path: str) -> Path | None:
    dist_dir = frontend_dist.resolve()
    candidate = (dist_dir / frontend_path).resolve()
    try:
        candidate.relative_to(dist_dir)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def _frontend_response(frontend_dist: Path, frontend_path: str) -> Response:
    index_path = frontend_dist / "index.html"
    if frontend_path:
        asset = _resolve_frontend_asset(frontend_dist, frontend_path)
        if asset is not None:
            return _frontend_file_response(asset)
        if "." in frontend_path.split("/")[-1]:
            raise HTTPException(status_code=404, detail="Not found.")

    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Frontend build is missing.")
    return _frontend_file_response(index_path)


def _is_reserved_path(path: str) -> bool:
    if not path:
        return False
    return path.split("/", 1)[0] in SERVICE_RESERVED_ROUTE_PREFIXES


app = create_app()
