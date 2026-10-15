"""Search functionality tests."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession



class TestSearch:
    """Search endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_search_requires_auth(self, async_client: AsyncClient):
        """Test creating search without auth fails."""
        response = await async_client.post(
            "/api/search",
            json={"title": "Test", "description": "A test search description that is long enough", "count": 5},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_search_success(self, async_client: AsyncClient, authenticated_user):
        """Test successful search creation."""
        client, token = authenticated_user
        response = await client.post(
            "/api/search",
            json={"title": "Python Developer", "description": "We are looking for a Python backend developer with experience in FastAPI, REST APIs, PostgreSQL and Docker.", "count": 5},
        )
        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["title"] == "Python Developer"
        assert data["status"] == "queued"
        assert data["progress"] == 0

    @pytest.mark.asyncio
    async def test_create_search_validation(self, async_client: AsyncClient, authenticated_user):
        """Test search creation validation."""
        client, token = authenticated_user
        # Too short title
        response = await client.post(
            "/api/search",
            json={"title": "A", "description": "A test search description that is long enough", "count": 5},
        )
        assert response.status_code == 422

        # Too short description
        response = await client.post(
            "/api/search",
            json={"title": "Python Developer", "description": "Short", "count": 5},
        )
        assert response.status_code == 422

        # Invalid count
        response = await client.post(
            "/api/search",
            json={"title": "Python Developer", "description": "A test search description that is long enough", "count": 100},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_search_own(self, async_client: AsyncClient, authenticated_user, db_session: AsyncSession):
        """Test getting own search."""
        client, token = authenticated_user
        # Create search
        create_resp = await client.post(
            "/api/search",
            json={"title": "Python Developer", "description": "We are looking for a Python backend developer with experience in FastAPI, REST APIs, PostgreSQL and Docker.", "count": 5},
        )
        search_id = create_resp.json()["id"]

        # Get search
        response = await client.get(f"/api/search/{search_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == search_id
        assert data["title"] == "Python Developer"

    @pytest.mark.asyncio
    async def test_get_search_not_found(self, async_client: AsyncClient, authenticated_user):
        """Test getting non-existent search returns 404."""
        client, token = authenticated_user
        response = await client.get("/api/search/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_search_other_user(self, async_client: AsyncClient, authenticated_user, db_session: AsyncSession):
        """Test getting another user's search returns 404."""
        client, token = authenticated_user
        # Create search as first user
        create_resp = await client.post(
            "/api/search",
            json={"title": "Python Developer", "description": "We are looking for a Python backend developer with experience in FastAPI, REST APIs, PostgreSQL and Docker.", "count": 5},
        )
        search_id = create_resp.json()["id"]

        # Register second user
        await async_client.post(
            "/api/auth/register",
            json={"name": "Other User", "email": "other@example.com", "password": "securepass123"},
        )
        login = await async_client.post(
            "/api/auth/login",
            json={"email": "other@example.com", "password": "securepass123"},
        )
        other_token = login.json()["token"]
        other_client = AsyncClient(transport=async_client._transport, base_url="http://test", headers={"Authorization": f"Bearer {other_token}"})

        # Try to access first user's search
        response = await other_client.get(f"/api/search/{search_id}")
        assert response.status_code == 404
        await other_client.aclose()

    @pytest.mark.asyncio
    async def test_dashboard_empty(self, async_client: AsyncClient, authenticated_user):
        """Test dashboard with no searches."""
        client, token = authenticated_user
        response = await client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["candidates_found"] == 0
        assert data["stats"]["searches_completed"] == 0
        assert data["recent_searches"] == []

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client: AsyncClient):
        """Test health endpoint is public."""
        response = await async_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "providers" in data
        assert "storage" in data

    @pytest.mark.asyncio
    async def test_search_isolation(self, async_client: AsyncClient, authenticated_user, db_session: AsyncSession):
        """Test that users only see their own searches."""
        client, token = authenticated_user

        # Create two searches
        await client.post(
            "/api/search",
            json={"title": "Search 1", "description": "Description for search one that is long enough", "count": 5},
        )
        await client.post(
            "/api/search",
            json={"title": "Search 2", "description": "Description for search two that is long enough", "count": 5},
        )

        # Dashboard should show both
        response = await client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["searches_completed"] == 0  # Not completed yet
        assert len(data["recent_searches"]) == 2

        # Create second user
        await async_client.post(
            "/api/auth/register",
            json={"name": "Other User", "email": "other@example.com", "password": "securepass123"},
        )
        login = await async_client.post(
            "/api/auth/login",
            json={"email": "other@example.com", "password": "securepass123"},
        )
        other_token = login.json()["token"]
        other_client = AsyncClient(transport=async_client._transport, base_url="http://test", headers={"Authorization": f"Bearer {other_token}"})

        # Second user's dashboard should be empty
        response = await other_client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["searches_completed"] == 0
        assert data["recent_searches"] == []
        await other_client.aclose()
