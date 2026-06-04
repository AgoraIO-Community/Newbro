# Cardputer Server Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OAuth-style device-pairing flow so a Cardputer (or any headless device) can obtain a `newbro_session` token by showing a short code that the user enters in the web UI.

**Architecture:** Three unauthenticated/authenticated endpoints under `/api/devices/pair/` backed by a new `device_pairings` table in the existing `PublicAuthStore`. `start` mints a device secret + a short human code; `claim` (called by the logged-in web user) links the pairing and mints an ordinary `browser_sessions` token; `poll` returns that token to the device exactly once. Because the issued token is a normal `browser_sessions` token, every existing auth check (`require_session_owner`, `user_for_websocket`) works unchanged.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite (via `PublicAuthStore`), Pytest (`anyio`), httpx `AsyncClient`; React + TypeScript + Vitest + Testing Library for the web claim affordance.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/newbro/api/public_auth.py` | Add `device_pairings` table, code constants, `DevicePairingStart`/`DevicePairingPoll` dataclasses, and `create_device_pairing` / `claim_device_pairing` / `poll_device_pairing` store methods | Modify |
| `src/newbro/api/routes/devices.py` | The three pairing routes + Pydantic request/response models | Create |
| `src/newbro/api/app.py` | Register the devices router | Modify |
| `tests/unit/api/test_device_pairing_store.py` | Unit tests for the store methods | Create |
| `tests/integration/api/test_device_pairing.py` | Endpoint integration tests | Create |
| `src/newbro/ui/src/lib/session-client.ts` | Add `claimDevice(userCode)` client function | Modify |
| `src/newbro/ui/src/lib/device-pairing.test.ts` | Unit test for `claimDevice` | Create |
| `src/newbro/ui/src/components/newbro/DevicePairingForm.tsx` | Self-contained claim form (code input → `onClaim`) | Create |
| `src/newbro/ui/src/components/newbro/DevicePairingForm.test.tsx` | Component test | Create |
| `src/newbro/ui/src/NewbroShell.tsx` | Mount `DevicePairingForm` in the executor-nodes/settings area, wired to `claimDevice` | Modify |

---

## Contract (authoritative)

- `POST /api/devices/pair/start` — unauthenticated. Body: none. Returns
  `{ "device_code": str, "user_code": str, "interval": int, "expires_at": str }`.
  `device_code` is the device's polling secret; `user_code` is the short code shown on the device screen; `interval` is seconds between polls; `expires_at` is ISO-8601.
- `POST /api/devices/pair/poll` — unauthenticated. Body: `{ "device_code": str }`.
  Returns `{ "status": "pending" }` while unclaimed, or `{ "status": "claimed", "token": str }` once claimed (token delivered exactly once). Unknown or expired `device_code` → `404`.
- `POST /api/devices/pair/claim` — authenticated (web cookie). Body: `{ "user_code": str }`.
  Links the pending pairing to the calling user and mints the token. Returns `{ "ok": true }`. Unknown/expired/already-claimed code → `404`.

**Constants:** pairing TTL = 10 minutes; poll `interval` = 2 seconds; `user_code` = 4 chars from the unambiguous alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `0/O/1/I`).

---

### Task 1: Store — `device_pairings` table + `create_device_pairing`

**Files:**
- Modify: `src/newbro/api/public_auth.py`
- Test: `tests/unit/api/test_device_pairing_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_device_pairing_store.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py -v`
Expected: FAIL with `ImportError`/`AttributeError` (no `USER_CODE_ALPHABET`, no `create_device_pairing`).

- [ ] **Step 3: Implement the table, constants, dataclass, and method**

In `src/newbro/api/public_auth.py`, extend the datetime import:

```python
from datetime import UTC, datetime, timedelta
```

Add module-level constants near the other constants (after `DEFAULT_BRO_BASE_PROMPT`):

```python
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USER_CODE_LENGTH = 4
DEVICE_PAIRING_TTL_SECONDS = 600
DEVICE_PAIRING_POLL_INTERVAL_SECONDS = 2
```

Add the dataclasses near `RedeemedSession`:

```python
@dataclass(slots=True)
class DevicePairingStart:
    device_code: str
    user_code: str
    interval: int
    expires_at: str


@dataclass(slots=True)
class DevicePairingPoll:
    status: str  # "pending" | "claimed"
    token: str | None = None
```

In `_init_db`'s `executescript`, add this table to the schema (alongside the others):

```sql
CREATE TABLE IF NOT EXISTS device_pairings (
    device_code_hash TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    user_id TEXT,
    issued_token TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    claimed_at TEXT
);
```

Add the method to `PublicAuthStore` (place it after `delete_browser_session`):

```python
    async def create_device_pairing(self) -> DevicePairingStart:
        async with self._lock:
            with self._connect() as conn:
                now = datetime.now(UTC)
                expires_at = (now + timedelta(seconds=DEVICE_PAIRING_TTL_SECONDS)).isoformat()
                device_code = secrets.token_urlsafe(32)
                for _ in range(10):
                    user_code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
                    try:
                        conn.execute(
                            """
                            INSERT INTO device_pairings
                                (device_code_hash, user_code, status, created_at, expires_at)
                            VALUES (?, ?, 'pending', ?, ?)
                            """,
                            (_hash_secret(device_code), user_code, now.isoformat(), expires_at),
                        )
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    raise PublicAuthError("Could not allocate a pairing code.")
        return DevicePairingStart(
            device_code=device_code,
            user_code=user_code,
            interval=DEVICE_PAIRING_POLL_INTERVAL_SECONDS,
            expires_at=expires_at,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/api/public_auth.py tests/unit/api/test_device_pairing_store.py
git commit -m "feat(pairing): add device_pairings store + create_device_pairing"
```

---

### Task 2: Store — `claim_device_pairing`

**Files:**
- Modify: `src/newbro/api/public_auth.py`
- Test: `tests/unit/api/test_device_pairing_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/api/test_device_pairing_store.py`:

```python
from newbro.api.public_auth import PublicAuthError


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py -v`
Expected: FAIL — `claim_device_pairing` / `poll_device_pairing` not defined.

- [ ] **Step 3: Implement `claim_device_pairing`**

Add to `PublicAuthStore` (after `create_device_pairing`):

```python
    async def claim_device_pairing(self, *, user_code: str, user_id: str) -> None:
        normalized = user_code.strip().upper()
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM device_pairings WHERE user_code = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    raise PublicAuthError("Invalid pairing code.")
                if row["status"] != "pending":
                    raise PublicAuthError("Pairing code already used.")
                if _is_expired(row["expires_at"]):
                    raise PublicAuthError("Pairing code expired.")
                now = _timestamp()
                raw_token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO browser_sessions (token_hash, user_id, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                    (_hash_secret(raw_token), user_id, now, now),
                )
                conn.execute(
                    """
                    UPDATE device_pairings
                    SET status = 'claimed', user_id = ?, issued_token = ?, claimed_at = ?
                    WHERE user_code = ?
                    """,
                    (user_id, raw_token, now, normalized),
                )
```

Add the `_is_expired` helper near `_timestamp` at module scope:

```python
def _is_expired(expires_at: str) -> bool:
    return datetime.fromisoformat(expires_at) <= datetime.now(UTC)
```

> Note: `poll_device_pairing` is implemented in Task 3; these claim tests call it to verify the minted token, so run Task 2's tests together with Task 3, or temporarily run only `test_claim_unknown_code_raises` after this step. The full file goes green at the end of Task 3.

- [ ] **Step 4: Run the claim-only tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py::test_claim_unknown_code_raises -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/api/public_auth.py tests/unit/api/test_device_pairing_store.py
git commit -m "feat(pairing): add claim_device_pairing"
```

---

### Task 3: Store — `poll_device_pairing` (single-delivery)

**Files:**
- Modify: `src/newbro/api/public_auth.py`
- Test: `tests/unit/api/test_device_pairing_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/api/test_device_pairing_store.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py -v`
Expected: FAIL — `poll_device_pairing` not defined.

- [ ] **Step 3: Implement `poll_device_pairing`**

Add to `PublicAuthStore` (after `claim_device_pairing`):

```python
    async def poll_device_pairing(self, *, device_code: str) -> DevicePairingPoll:
        device_code_hash = _hash_secret(device_code)
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM device_pairings WHERE device_code_hash = ?",
                    (device_code_hash,),
                ).fetchone()
                if row is None:
                    raise PublicAuthError("Unknown pairing.")
                if row["status"] == "pending":
                    if _is_expired(row["expires_at"]):
                        raise PublicAuthError("Pairing code expired.")
                    return DevicePairingPoll(status="pending")
                token = row["issued_token"]
                if token is not None:
                    conn.execute(
                        "UPDATE device_pairings SET issued_token = NULL WHERE device_code_hash = ?",
                        (device_code_hash,),
                    )
                return DevicePairingPoll(status="claimed", token=token)
```

- [ ] **Step 4: Run the full store test file to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_device_pairing_store.py -v`
Expected: PASS (all tests, including Task 2's claim tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/api/public_auth.py tests/unit/api/test_device_pairing_store.py
git commit -m "feat(pairing): add poll_device_pairing single-delivery"
```

---

### Task 4: Routes — `start` / `poll` / `claim` + registration

**Files:**
- Create: `src/newbro/api/routes/devices.py`
- Modify: `src/newbro/api/app.py`
- Test: `tests/integration/api/test_device_pairing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/api/test_device_pairing.py`:

```python
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from newbro.api.app import create_app
from newbro.api.public_auth import PublicAuthStore
from newbro.communication.models import ScriptedCommunicationModel
from newbro.communication.models.scripted import ScriptedPlan
from newbro.runtime import Settings
from newbro.runtime.container import RuntimeContainer


def _build_app(tmp_path):
    app = create_app()
    app.state.runtime_container = RuntimeContainer(
        communication_model=ScriptedCommunicationModel(
            {"__default__": ScriptedPlan(conversational_act="model_reply", reply_override="Noted.")}
        ),
        settings=Settings(),
    )
    app.state.public_auth_store = PublicAuthStore(path=tmp_path / "public_auth.sqlite3")
    return app


@pytest.mark.anyio
async def test_device_pairing_full_flow(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Device starts pairing.
        start = await client.post("/api/devices/pair/start")
        assert start.status_code == 200
        body = start.json()
        device_code, user_code = body["device_code"], body["user_code"]
        assert body["interval"] == 2

        # Unclaimed poll is pending.
        pending = await client.post("/api/devices/pair/poll", json={"device_code": device_code})
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"

        # A logged-in web user claims the code.
        await app.state.public_auth_store.create_invite("invite-1")
        assert (await client.post("/api/auth/invites/redeem", json={"code": "invite-1"})).status_code == 200
        claim = await client.post("/api/devices/pair/claim", json={"user_code": user_code})
        assert claim.status_code == 200

        # Device poll now returns a usable token.
        claimed = await client.post("/api/devices/pair/poll", json={"device_code": device_code})
        assert claimed.json()["status"] == "claimed"
        token = claimed.json()["token"]
        assert token

        # The token authenticates as the user (bootstrap succeeds with the cookie).
        boot = await client.get("/api/me/bootstrap", cookies={"newbro_session": token})
        assert boot.status_code == 200


@pytest.mark.anyio
async def test_claim_requires_auth(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        start = (await client.post("/api/devices/pair/start")).json()
        resp = await client.post("/api/devices/pair/claim", json={"user_code": start["user_code"]})
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_poll_unknown_code_is_404(tmp_path):
    app = _build_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/api/devices/pair/poll", json={"device_code": "bogus"})
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/api/test_device_pairing.py -v`
Expected: FAIL — routes return 404 because the router is not registered.

- [ ] **Step 3: Create the router**

Create `src/newbro/api/routes/devices.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from newbro.api.public_auth import PublicAuthError, PublicAuthStore, require_public_user

router = APIRouter()


class DevicePairStartResponse(BaseModel):
    device_code: str
    user_code: str
    interval: int
    expires_at: str


class DevicePairPollRequest(BaseModel):
    device_code: str


class DevicePairPollResponse(BaseModel):
    status: str
    token: str | None = None


class DevicePairClaimRequest(BaseModel):
    user_code: str


@router.post("/devices/pair/start", response_model=DevicePairStartResponse)
async def device_pair_start(request: Request) -> DevicePairStartResponse:
    store: PublicAuthStore = request.app.state.public_auth_store
    pairing = await store.create_device_pairing()
    return DevicePairStartResponse(
        device_code=pairing.device_code,
        user_code=pairing.user_code,
        interval=pairing.interval,
        expires_at=pairing.expires_at,
    )


@router.post("/devices/pair/poll", response_model=DevicePairPollResponse)
async def device_pair_poll(body: DevicePairPollRequest, request: Request) -> DevicePairPollResponse:
    store: PublicAuthStore = request.app.state.public_auth_store
    try:
        poll = await store.poll_device_pairing(device_code=body.device_code)
    except PublicAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DevicePairPollResponse(status=poll.status, token=poll.token)


@router.post("/devices/pair/claim")
async def device_pair_claim(body: DevicePairClaimRequest, request: Request) -> dict[str, bool]:
    user = await require_public_user(request)
    store: PublicAuthStore = request.app.state.public_auth_store
    try:
        await store.claim_device_pairing(user_code=body.user_code, user_id=user.user_id)
    except PublicAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
```

- [ ] **Step 4: Register the router**

In `src/newbro/api/app.py`, add the import next to the other route imports:

```python
from newbro.api.routes.devices import router as devices_router
```

And add the registration next to `auth_router`:

```python
    app.include_router(devices_router, prefix=API_PREFIX)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/api/test_device_pairing.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full backend suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/unit/api tests/integration/api -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newbro/api/routes/devices.py src/newbro/api/app.py tests/integration/api/test_device_pairing.py
git commit -m "feat(pairing): add /devices/pair start/poll/claim endpoints"
```

---

### Task 5: Web client — `claimDevice(userCode)`

**Files:**
- Modify: `src/newbro/ui/src/lib/session-client.ts`
- Test: `src/newbro/ui/src/lib/device-pairing.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/newbro/ui/src/lib/device-pairing.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { claimDevice } from "./session-client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("claimDevice", () => {
  it("POSTs the user code to the claim endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await claimDevice("7QF2");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/devices/pair/claim");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ user_code: "7QF2" });
  });

  it("throws on a non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid pairing code." }), { status: 404 }),
    );

    await expect(claimDevice("ZZZZ")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/newbro/ui && npx vitest run src/lib/device-pairing.test.ts`
Expected: FAIL — `claimDevice` is not exported.

- [ ] **Step 3: Implement `claimDevice`**

In `src/newbro/ui/src/lib/session-client.ts`, add this exported function (place it near the other `auth/*` helpers around line 200, following the same `buildHttpUrl` + `ensureOk` pattern used by `redeem_invite`):

```ts
export async function claimDevice(userCode: string): Promise<void> {
  const response = await fetch(buildHttpUrl(`${API_PREFIX}/devices/pair/claim`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_code: userCode.trim().toUpperCase() }),
  });
  await ensureOk(response);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/newbro/ui && npx vitest run src/lib/device-pairing.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/lib/session-client.ts src/newbro/ui/src/lib/device-pairing.test.ts
git commit -m "feat(pairing): add claimDevice web client"
```

---

### Task 6: Web component — `DevicePairingForm`

**Files:**
- Create: `src/newbro/ui/src/components/newbro/DevicePairingForm.tsx`
- Test: `src/newbro/ui/src/components/newbro/DevicePairingForm.test.tsx`

This component is presentational + self-contained: it takes an `onClaim` callback (so it has no direct coupling to network code) and renders an input, a submit button, and success/error text.

- [ ] **Step 1: Write the failing test**

Create `src/newbro/ui/src/components/newbro/DevicePairingForm.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DevicePairingForm } from "./DevicePairingForm";

describe("DevicePairingForm", () => {
  it("calls onClaim with the entered code and shows success", async () => {
    const onClaim = vi.fn().mockResolvedValue(undefined);
    render(<DevicePairingForm onClaim={onClaim} />);

    await userEvent.type(screen.getByLabelText(/device code/i), "7qf2");
    await userEvent.click(screen.getByRole("button", { name: /pair device/i }));

    expect(onClaim).toHaveBeenCalledWith("7QF2");
    expect(await screen.findByText(/device paired/i)).toBeInTheDocument();
  });

  it("shows an error message when onClaim rejects", async () => {
    const onClaim = vi.fn().mockRejectedValue(new Error("Invalid pairing code."));
    render(<DevicePairingForm onClaim={onClaim} />);

    await userEvent.type(screen.getByLabelText(/device code/i), "zzzz");
    await userEvent.click(screen.getByRole("button", { name: /pair device/i }));

    expect(await screen.findByText(/invalid pairing code/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/newbro/ui && npx vitest run src/components/newbro/DevicePairingForm.test.tsx`
Expected: FAIL — module `./DevicePairingForm` not found.

- [ ] **Step 3: Implement the component**

Create `src/newbro/ui/src/components/newbro/DevicePairingForm.tsx`:

```tsx
import { useState } from "react";

export interface DevicePairingFormProps {
  onClaim: (userCode: string) => Promise<void>;
}

type Status = { kind: "idle" } | { kind: "ok" } | { kind: "error"; message: string };

export function DevicePairingForm({ onClaim }: DevicePairingFormProps) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const userCode = code.trim().toUpperCase();
    if (!userCode || pending) return;
    setPending(true);
    setStatus({ kind: "idle" });
    try {
      await onClaim(userCode);
      setStatus({ kind: "ok" });
      setCode("");
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Pairing failed." });
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="nb-device-pairing">
      <label htmlFor="device-code">Device code</label>
      <input
        id="device-code"
        value={code}
        onChange={(event) => setCode(event.target.value)}
        autoComplete="off"
        maxLength={8}
        placeholder="e.g. 7QF2"
      />
      <button type="submit" disabled={pending}>
        {pending ? "Pairing…" : "Pair device"}
      </button>
      {status.kind === "ok" && <p role="status">Device paired.</p>}
      {status.kind === "error" && <p role="alert">{status.message}</p>}
    </form>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/newbro/ui && npx vitest run src/components/newbro/DevicePairingForm.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/components/newbro/DevicePairingForm.tsx src/newbro/ui/src/components/newbro/DevicePairingForm.test.tsx
git commit -m "feat(pairing): add DevicePairingForm component"
```

---

### Task 7: Mount `DevicePairingForm` in the settings/nodes area

**Files:**
- Modify: `src/newbro/ui/src/NewbroShell.tsx`

`NewbroShell.tsx` already manages executor nodes (see `setExecutorNodes` and the executor-nodes panel) and imports auth helpers from `session-client`. Mount the pairing form in that same settings/devices region so users have one place to connect external things.

- [ ] **Step 1: Locate the executor-nodes settings region**

Run: `cd src/newbro/ui && grep -n "executorNodes\|setExecutorNodes\|Executor node\|executor-nodes" src/NewbroShell.tsx`
Identify the JSX block that renders the executor-nodes panel/section. The pairing form will be added immediately after that block's heading.

- [ ] **Step 2: Add the import**

At the top of `src/NewbroShell.tsx`, add `claimDevice` to the existing `session-client` import and import the component:

```tsx
import { DevicePairingForm } from "./components/newbro/DevicePairingForm";
```

Add `claimDevice` to the destructured names in the existing `from "./lib/session-client"` (or `"@/lib/session-client"`) import statement.

- [ ] **Step 3: Render the form in the nodes/devices section**

Inside the executor-nodes settings JSX block located in Step 1, add a small subsection:

```tsx
<section className="nb-devices-section">
  <h3 className="nb-eyebrow">Devices</h3>
  <p className="nb-body-soft">Pair a Cardputer or other device using the code shown on its screen.</p>
  <DevicePairingForm onClaim={claimDevice} />
</section>
```

- [ ] **Step 4: Verify the build and existing tests still pass**

Run: `cd src/newbro/ui && npx tsc --noEmit && npx vitest run src/components/newbro/DevicePairingForm.test.tsx src/lib/device-pairing.test.ts`
Expected: type-check passes; targeted tests PASS.

> Per project memory, the full `App.test.tsx` suite is order/timing flaky — verify via the targeted test files above, not the whole-file UI suite.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/ui/src/NewbroShell.tsx
git commit -m "feat(pairing): surface device pairing in settings"
```

---

## Self-Review

**Spec coverage (against §4 of the design spec):**
- `POST /devices/pair/start` → Task 4 (route) + Task 1 (store). ✓
- `POST /devices/pair/poll` (pending → claimed, single delivery) → Task 4 (route) + Task 3 (store). ✓
- `POST /devices/pair/claim` (authenticated, mints token) → Task 4 (route) + Task 2 (store). ✓
- Reuses `browser_sessions` token model so existing auth works → verified by `test_device_pairing_full_flow` calling `/me/bootstrap` with the issued token. ✓
- Web UI "Settings · Devices" claim affordance → Tasks 5–7. ✓
- Code expiry + unknown/used-code handling → `test_claim_*`, `test_poll_unknown_*`. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Task 7 Step 1 is a deliberate locate step (the executor-nodes JSX is large and not reproduced here); the surrounding steps give exact imports and JSX to add.

**Type/name consistency:** `create_device_pairing`/`claim_device_pairing`/`poll_device_pairing`, `DevicePairingStart`/`DevicePairingPoll`, `USER_CODE_ALPHABET`, `_is_expired`, and `claimDevice`/`DevicePairingForm`/`onClaim` are used consistently across store, routes, tests, and web tasks. Endpoint paths match the contract section and the integration test. ✓
