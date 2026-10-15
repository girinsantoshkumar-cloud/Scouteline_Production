"""Authentication unit tests."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User, AuthToken


class TestAuth:
    """Authentication endpoint tests."""

    @pytest.mark.asyncio
    async def test_register_success(self, async_client: AsyncClient):
        """Test successful user registration."""
        response = await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "user" in data
        assert "token" in data
        assert data["user"]["email"] == "test@example.com"
        assert data["user"]["name"] == "Test User"
        assert len(data["token"]) > 20

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, async_client: AsyncClient):
        """Test registration with duplicate email fails."""
        await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        response = await async_client.post(
            "/api/auth/register",
            json={"name": "Another User", "email": "test@example.com", "password": "securepass123"},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, async_client: AsyncClient):
        """Test registration with invalid email fails."""
        response = await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "invalid", "password": "securepass123"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_short_password(self, async_client: AsyncClient):
        """Test registration with short password fails."""
        response = await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "123"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_success(self, async_client: AsyncClient):
        """Test successful login."""
        await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        response = await async_client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "securepass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert "token" in data
        assert data["user"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, async_client: AsyncClient):
        """Test login with wrong password fails."""
        await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        response = await async_client.post(
            "/api/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, async_client: AsyncClient):
        """Test login with nonexistent user fails."""
        response = await async_client.post(
            "/api/auth/login",
            json={"email": "nonexistent@example.com", "password": "securepass123"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_valid_token(self, async_client: AsyncClient):
        """Test /api/auth/me with valid token."""
        reg = await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        token = reg.json()["token"]
        response = await async_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"

    @pytest.mark.asyncio
    async def test_me_without_token(self, async_client: AsyncClient):
        """Test /api/auth/me without token fails."""
        response = await async_client.get("/api/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_invalid_token(self, async_client: AsyncClient):
        """Test /api/auth/me with invalid token fails."""
        response = await async_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_revokes_token(self, async_client: AsyncClient, db_session: AsyncSession):
        """Test logout revokes the token."""
        reg = await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        token = reg.json()["token"]

        # Token works before logout
        response = await async_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        # Logout
        response = await async_client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204

        # Token should be revoked
        response = await async_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

        # Verify token deleted from DB
        result = await db_session.execute(select(AuthToken).where(AuthToken.token == token))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_password_hashing(self, async_client: AsyncClient, db_session: AsyncSession):
        """Test that passwords are properly hashed, not stored in plain text."""
        await async_client.post(
            "/api/auth/register",
            json={"name": "Test User", "email": "test@example.com", "password": "securepass123"},
        )
        result = await db_session.execute(select(User).where(User.email == "test@example.com"))
        user = result.scalar_one()
        assert user.password_hash != "securepass123"
        assert user.salt is not None
        assert len(user.salt) == 32  # 16 bytes hex = 32 chars
        assert len(user.password_hash) == 64  # SHA256 hex = 64 chars
