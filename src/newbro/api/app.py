from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from newbro.api.logging import install_access_log_filters
from newbro.api.paths import API_PREFIX, api_path
from newbro.api.public_auth import PublicAuthStore
from newbro.api.routes.auth import router as auth_router
from newbro.api.routes.commands import router as commands_router
from newbro.api.routes.drafts import router as drafts_router
from newbro.api.routes.executor_nodes import router as executor_nodes_router
from newbro.api.routes.health import router as health_router
from newbro.api.routes.interaction_requests import router as interaction_requests_router
from newbro.api.routes.messages import router as messages_router
from newbro.api.routes.personas import router as personas_router
from newbro.api.routes.sessions import router as sessions_router
from newbro.api.ws.executors import router as executor_control_router
from newbro.api.ws.stream import router as stream_router
from newbro.runtime.bootstrap import build_runtime_container
from newbro.runtime.config import Settings


def create_app(*, settings: Settings | None = None) -> FastAPI:
    container = build_runtime_container(settings=settings)
    app = FastAPI(
        title="Newbro v2",
        openapi_url=api_path("/openapi.json"),
        docs_url=api_path("/docs"),
        redoc_url=api_path("/redoc"),
    )
    app.state.runtime_container = container
    app.state.public_auth_store = PublicAuthStore()

    install_access_log_filters(container.settings)
    if container.settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(container.settings.cors_allowed_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(sessions_router, prefix=API_PREFIX)
    app.include_router(messages_router, prefix=API_PREFIX)
    app.include_router(commands_router, prefix=API_PREFIX)
    app.include_router(drafts_router, prefix=API_PREFIX)
    app.include_router(interaction_requests_router, prefix=API_PREFIX)
    app.include_router(personas_router, prefix=API_PREFIX)
    app.include_router(executor_nodes_router, prefix=API_PREFIX)
    app.include_router(stream_router, prefix=API_PREFIX)
    app.include_router(executor_control_router, prefix=API_PREFIX)

    return app


app = create_app()
