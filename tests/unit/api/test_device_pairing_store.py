from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from newbro.api.public_auth import PublicAuthStore, PublicAuthError, USER_CODE_ALPHABET, _hash_secret


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


async def _make_user(store) -> str:
    await store.create_invite("invite-1")
    redeemed = await store.redeem_invite("invite-1")
    return redeemed.user.user_id


@pytest.mark.anyio
async def test_claim_links_user_and_mints_token(tmp_path):
    store = _store(tmp_path)
    user_id = await _make_user(store)
    pairing = await store.create_device_pairing()

    await store.claim_device_pairing(user_code=pairing.user_code, user_id=user_id)

    # The minted token authenticates as the claiming user.
    poll = await store.poll_device_pairing(device_code=pairing.device_code)
    assert poll.status == "claimed"
    assert poll.token
    user = await store.user_for_token(poll.token)
    assert user is not None and user.user_id == user_id


@pytest.mark.anyio
async def test_claim_unknown_code_raises(tmp_path):
    store = _store(tmp_path)
    user_id = await _make_user(store)

    with pytest.raises(PublicAuthError):
        await store.claim_device_pairing(user_code="ZZZZ", user_id=user_id)


@pytest.mark.anyio
async def test_claim_twice_raises(tmp_path):
    store = _store(tmp_path)
    user_id = await _make_user(store)
    pairing = await store.create_device_pairing()
    await store.claim_device_pairing(user_code=pairing.user_code, user_id=user_id)

    with pytest.raises(PublicAuthError):
        await store.claim_device_pairing(user_code=pairing.user_code, user_id=user_id)


@pytest.mark.anyio
async def test_claim_expired_code_raises(tmp_path):
    store = _store(tmp_path)
    user_id = await _make_user(store)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    # Insert an already-expired pending pairing directly.
    with sqlite3.connect(tmp_path / "public_auth.sqlite3") as conn:
        conn.execute(
            "INSERT INTO device_pairings (device_code_hash, user_code, status, created_at, expires_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (_hash_secret("dev-expired"), "EXPD", past, past),
        )

    with pytest.raises(PublicAuthError):
        await store.claim_device_pairing(user_code="EXPD", user_id=user_id)


@pytest.mark.anyio
async def test_poll_pending_then_claimed_once(tmp_path):
    store = _store(tmp_path)
    user_id = await _make_user(store)
    pairing = await store.create_device_pairing()

    first = await store.poll_device_pairing(device_code=pairing.device_code)
    assert first.status == "pending"
    assert first.token is None

    await store.claim_device_pairing(user_code=pairing.user_code, user_id=user_id)

    claimed = await store.poll_device_pairing(device_code=pairing.device_code)
    assert claimed.status == "claimed"
    assert claimed.token

    # Token is delivered exactly once; subsequent polls report claimed with no token.
    again = await store.poll_device_pairing(device_code=pairing.device_code)
    assert again.status == "claimed"
    assert again.token is None


@pytest.mark.anyio
async def test_poll_unknown_device_code_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(PublicAuthError):
        await store.poll_device_pairing(device_code="nope")


@pytest.mark.anyio
async def test_poll_expired_pending_raises(tmp_path):
    store = _store(tmp_path)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(tmp_path / "public_auth.sqlite3") as conn:
        conn.execute(
            "INSERT INTO device_pairings (device_code_hash, user_code, status, created_at, expires_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (_hash_secret("dev-expired-poll"), "EXPP", past, past),
        )
    with pytest.raises(PublicAuthError):
        await store.poll_device_pairing(device_code="dev-expired-poll")
