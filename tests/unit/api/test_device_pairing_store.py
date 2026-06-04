from __future__ import annotations

import pytest

from newbro.api.public_auth import PublicAuthStore, USER_CODE_ALPHABET


def _store(tmp_path):
    return PublicAuthStore(path=tmp_path / "public_auth.sqlite3")


@pytest.mark.anyio
async def test_create_device_pairing_returns_codes(tmp_path):
    store = _store(tmp_path)

    pairing = await store.create_device_pairing()

    assert len(pairing.device_code) >= 20
    assert len(pairing.user_code) == 4
    assert all(ch in USER_CODE_ALPHABET for ch in pairing.user_code)
    assert pairing.interval == 2
    assert pairing.expires_at  # ISO-8601 string


@pytest.mark.anyio
async def test_create_device_pairing_user_codes_are_unique(tmp_path):
    store = _store(tmp_path)

    codes = {(await store.create_device_pairing()).user_code for _ in range(25)}

    assert len(codes) == 25
