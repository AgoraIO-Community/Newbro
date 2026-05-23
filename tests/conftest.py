from pathlib import Path
import os
import sys
from uuid import uuid4

from httpx import AsyncClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from newbro.runtime import config as config_module
from newbro.api import public_auth as public_auth_module


@pytest.fixture(autouse=True)
def isolate_test_runtime_env(monkeypatch, tmp_path: Path):
    for name in list(os.environ):
        if name.startswith(("SYNAPSE_", "OPENAI_")):
            monkeypatch.delenv(name, raising=False)

    # Tests should opt into local config explicitly instead of inheriting a developer's ~/.newbro env.
    monkeypatch.setattr(config_module, "LOCAL_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(public_auth_module, "PUBLIC_AUTH_DB", tmp_path / "public_auth.sqlite3")


@pytest.fixture(autouse=True)
def auto_login_legacy_api_clients(monkeypatch):
    """Keep pre-public-auth integration tests focused on their original surface.

    Dedicated public-auth tests opt out by filename and assert unauthenticated
    denial explicitly. Other legacy API tests get a throwaway invited user when
    they first hit a protected browser route.
    """

    current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    if "test_public_auth_onboarding.py" in current_test:
        return

    original_request = AsyncClient.request

    async def request_with_test_login(self, method, url, *args, **kwargs):
        response = await original_request(self, method, url, *args, **kwargs)
        path = str(url)
        if (
            response.status_code != 401
            or not path.startswith("/api/")
            or path.startswith("/api/auth/")
            or getattr(self, "_newbro_test_auth_ready", False)
        ):
            return response
        app = getattr(getattr(self, "_transport", None), "app", None)
        store = getattr(getattr(app, "state", None), "public_auth_store", None)
        if store is None:
            return response
        code = f"test-{uuid4().hex}"
        await store.create_invite(code)
        redeem = await original_request(
            self,
            "POST",
            "/api/auth/invites/redeem",
            json={"code": code},
        )
        if redeem.status_code != 200:
            return response
        session_cookie = self.cookies.get("newbro_session")
        if session_cookie:
            setattr(app.state, "_newbro_test_cookie_header", f"newbro_session={session_cookie}")
        setattr(self, "_newbro_test_auth_ready", True)
        return await original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(AsyncClient, "request", request_with_test_login)
