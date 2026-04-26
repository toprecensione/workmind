"""
Tests for 2FA TOTP endpoints.
Covers: setup, confirm, challenge (full login flow), disable.
Uses a dedicated user per test session to avoid contaminating other test state.
"""
from __future__ import annotations

import uuid
import hashlib

import pyotp
import pytest
import pytest_asyncio
from httpx import AsyncClient


TOTP_USER_ID = "00000000-0000-0000-0000-000000000099"


def _email_hash(email: str) -> str:
    import hashlib
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def totp_user(test_session_factory, test_org):
    """Dedicated user for 2FA tests. Reset totp state at start of session."""
    import bcrypt as _bcrypt
    from app.db.models import User

    async with test_session_factory() as session:
        uid = uuid.UUID(TOTP_USER_ID)
        existing = await session.get(User, uid)
        if existing:
            # Reset TOTP state so tests are idempotent across runs
            existing.totp_secret = None
            existing.totp_enabled = False
            await session.commit()
            return existing

        user = User(
            id=uid,
            org_id=test_org.id,
            email="totp_test@test.com",
            email_hash=_email_hash("totp_test@test.com"),
            display_name="TOTP Test User",
            role="admin",
            password_hash=_bcrypt.hashpw(b"testpass123", _bcrypt.gensalt()).decode(),
            is_active=True,
            totp_secret=None,
            totp_enabled=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture(scope="session")
def totp_auth_headers(totp_user) -> dict:
    """JWT auth headers for the dedicated TOTP test user."""
    import os
    from datetime import datetime, timezone, timedelta
    from jose import jwt as _jwt

    secret = os.environ.get("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(totp_user.id),
        "org_id": str(totp_user.org_id),
        "role": totp_user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=1440),
    }
    token = _jwt.encode(payload, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ── Helper ────────────────────────────────────────────────────────────────────

async def _reset_totp(test_session_factory, totp_user):
    """Reset TOTP state between tests that modify it."""
    async with test_session_factory() as session:
        from app.db.models import User
        user = await session.get(User, totp_user.id)
        if user:
            user.totp_secret = None
            user.totp_enabled = False
            await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTotpSetup:
    @pytest.mark.asyncio
    async def test_setup_returns_secret_and_qr(self, client: AsyncClient, totp_auth_headers):
        resp = await client.post("/api/auth/2fa/setup", headers=totp_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "secret" in data
        assert "uri" in data
        assert "qr_base64" in data
        assert len(data["secret"]) >= 16  # base32 secret
        assert "otpauth://" in data["uri"]

    @pytest.mark.asyncio
    async def test_setup_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/auth/2fa/setup")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_setup_when_already_enabled_returns_409(
        self, client: AsyncClient, totp_auth_headers, totp_user, test_session_factory
    ):
        """When 2FA is already active, setup must return 409."""
        # Force-enable 2FA on user
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            user.totp_secret = pyotp.random_base32()
            user.totp_enabled = True
            await session.commit()

        resp = await client.post("/api/auth/2fa/setup", headers=totp_auth_headers)
        assert resp.status_code == 409, resp.text

        # Cleanup
        await _reset_totp(test_session_factory, totp_user)


class TestTotpConfirm:
    @pytest.mark.asyncio
    async def test_confirm_enables_2fa(
        self, client: AsyncClient, totp_auth_headers, totp_user, test_session_factory
    ):
        """Full setup → confirm cycle enables 2FA."""
        # Setup
        setup_resp = await client.post("/api/auth/2fa/setup", headers=totp_auth_headers)
        assert setup_resp.status_code == 200, setup_resp.text
        secret = setup_resp.json()["secret"]

        # Confirm with valid code
        code = pyotp.TOTP(secret).now()
        confirm_resp = await client.post(
            "/api/auth/2fa/confirm",
            json={"code": code},
            headers=totp_auth_headers,
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        assert "2FA attivato" in confirm_resp.json().get("detail", "")

        # Verify DB: totp_enabled = True
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            assert user.totp_enabled is True

        # Cleanup
        await _reset_totp(test_session_factory, totp_user)

    @pytest.mark.asyncio
    async def test_confirm_invalid_code_returns_400(
        self, client: AsyncClient, totp_auth_headers, totp_user, test_session_factory
    ):
        # Setup
        setup_resp = await client.post("/api/auth/2fa/setup", headers=totp_auth_headers)
        assert setup_resp.status_code == 200

        confirm_resp = await client.post(
            "/api/auth/2fa/confirm",
            json={"code": "000000"},
            headers=totp_auth_headers,
        )
        assert confirm_resp.status_code == 400, confirm_resp.text

        # Cleanup
        await _reset_totp(test_session_factory, totp_user)

    @pytest.mark.asyncio
    async def test_confirm_without_setup_returns_400(
        self, client: AsyncClient, totp_auth_headers
    ):
        """No secret stored → confirm must fail with 400."""
        confirm_resp = await client.post(
            "/api/auth/2fa/confirm",
            json={"code": "123456"},
            headers=totp_auth_headers,
        )
        assert confirm_resp.status_code == 400, confirm_resp.text


class TestTotpChallenge:
    @pytest.mark.asyncio
    async def test_full_2fa_login_flow(
        self, client: AsyncClient, totp_user, test_session_factory
    ):
        """
        1. Enable 2FA on user (setup + confirm)
        2. Login → expect totp_required + temp_token
        3. Challenge with valid TOTP code → expect access/refresh tokens
        """
        # Step 1: enable 2FA
        setup_hdrs = await _get_totp_headers(totp_user)
        setup_resp = await client.post("/api/auth/2fa/setup", headers=setup_hdrs)
        assert setup_resp.status_code == 200
        secret = setup_resp.json()["secret"]

        code = pyotp.TOTP(secret).now()
        confirm_resp = await client.post(
            "/api/auth/2fa/confirm",
            json={"code": code},
            headers=setup_hdrs,
        )
        assert confirm_resp.status_code == 200

        # Refresh DB secret (setup stored it)
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            db_secret = user.totp_secret

        # Step 2: login — should return temp_token
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "totp_test@test.com", "password": "testpass123"},
        )
        assert login_resp.status_code == 200, login_resp.text
        login_data = login_resp.json()
        assert login_data.get("totp_required") is True, f"Expected totp_required=True, got {login_data}"
        temp_token = login_data["temp_token"]

        # Step 3: challenge
        fresh_code = pyotp.TOTP(db_secret).now()
        challenge_resp = await client.post(
            "/api/auth/2fa/challenge",
            json={"temp_token": temp_token, "code": fresh_code},
        )
        assert challenge_resp.status_code == 200, challenge_resp.text
        tokens = challenge_resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Cleanup
        await _reset_totp(test_session_factory, totp_user)

    @pytest.mark.asyncio
    async def test_challenge_invalid_code_returns_401(
        self, client: AsyncClient, totp_user, test_session_factory
    ):
        """Valid temp_token but wrong TOTP code → 401."""
        import os
        from datetime import datetime, timezone, timedelta
        from jose import jwt as _jwt

        secret_key = os.environ.get("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
        now = datetime.now(tz=timezone.utc)
        temp_token = _jwt.encode(
            {
                "sub": str(totp_user.id),
                "type": "totp_challenge",
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            secret_key,
            algorithm="HS256",
        )

        # Enable 2FA so challenge endpoint doesn't bail early
        totp_secret = pyotp.random_base32()
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            user.totp_secret = totp_secret
            user.totp_enabled = True
            await session.commit()

        resp = await client.post(
            "/api/auth/2fa/challenge",
            json={"temp_token": temp_token, "code": "000000"},
        )
        assert resp.status_code == 401, resp.text

        await _reset_totp(test_session_factory, totp_user)

    @pytest.mark.asyncio
    async def test_challenge_invalid_temp_token_returns_401(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/2fa/challenge",
            json={"temp_token": "this.is.not.valid", "code": "123456"},
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_challenge_wrong_token_type_returns_401(
        self, client: AsyncClient, totp_user
    ):
        """Token with type='access' (not 'totp_challenge') must be rejected."""
        import os
        from datetime import datetime, timezone, timedelta
        from jose import jwt as _jwt

        secret_key = os.environ.get("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
        now = datetime.now(tz=timezone.utc)
        bad_token = _jwt.encode(
            {
                "sub": str(totp_user.id),
                "type": "access",  # wrong type
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            secret_key,
            algorithm="HS256",
        )
        resp = await client.post(
            "/api/auth/2fa/challenge",
            json={"temp_token": bad_token, "code": "123456"},
        )
        assert resp.status_code == 401, resp.text


class TestTotpDisable:
    @pytest.mark.asyncio
    async def test_disable_with_valid_code(
        self, client: AsyncClient, totp_auth_headers, totp_user, test_session_factory
    ):
        # Enable 2FA
        totp_secret = pyotp.random_base32()
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            user.totp_secret = totp_secret
            user.totp_enabled = True
            await session.commit()

        import json as _json
        code = pyotp.TOTP(totp_secret).now()
        resp = await client.request(
            "DELETE",
            "/api/auth/2fa",
            content=_json.dumps({"code": code}),
            headers={**totp_auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200, resp.text
        assert "disabilitato" in resp.json().get("detail", "").lower()

        # Verify DB
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            assert user.totp_enabled is False
            assert user.totp_secret is None

    @pytest.mark.asyncio
    async def test_disable_wrong_code_returns_400(
        self, client: AsyncClient, totp_auth_headers, totp_user, test_session_factory
    ):
        import json as _json
        # Enable 2FA
        totp_secret = pyotp.random_base32()
        async with test_session_factory() as session:
            from app.db.models import User
            user = await session.get(User, totp_user.id)
            user.totp_secret = totp_secret
            user.totp_enabled = True
            await session.commit()

        resp = await client.request(
            "DELETE",
            "/api/auth/2fa",
            content=_json.dumps({"code": "000000"}),
            headers={**totp_auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400, resp.text

        await _reset_totp(test_session_factory, totp_user)

    @pytest.mark.asyncio
    async def test_disable_when_not_enabled_returns_400(
        self, client: AsyncClient, totp_auth_headers
    ):
        import json as _json
        resp = await client.request(
            "DELETE",
            "/api/auth/2fa",
            content=_json.dumps({"code": "123456"}),
            headers={**totp_auth_headers, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_disable_requires_auth(self, client: AsyncClient):
        import json as _json
        resp = await client.request(
            "DELETE",
            "/api/auth/2fa",
            content=_json.dumps({"code": "123456"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401


# ── Private helper (needs to be sync-compatible) ──────────────────────────────

async def _get_totp_headers(totp_user) -> dict:
    """Generate fresh JWT for totp_user without hitting HTTP."""
    import os
    from datetime import datetime, timezone, timedelta
    from jose import jwt as _jwt

    secret = os.environ.get("WORKMIND_SECRET_KEY", "test-secret-key-not-for-production")
    now = datetime.now(tz=timezone.utc)
    token = _jwt.encode(
        {
            "sub": str(totp_user.id),
            "org_id": str(totp_user.org_id),
            "role": totp_user.role,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=1440),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}
