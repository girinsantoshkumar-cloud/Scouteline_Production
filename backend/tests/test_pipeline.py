"""Research pipeline, scoring and validation tests (external providers are mocked)."""
import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import main
from models import Search

DESCRIPTION = "Looking for a Python backend developer with FastAPI, PostgreSQL, REST APIs and Docker experience."


class TestScoring:
    def test_score_candidate_verified_and_partial(self):
        profile = {
            "profile": {"bio": "Backend engineer who loves Python"},
            "repos": [{"name": "api", "description": "FastAPI service", "topics": ["docker"], "language": "Python"}],
        }
        requirements = {"required_skills": ["Python", "FastAPI", "Kubernetes"], "preferred_skills": ["Docker", "Rust"]}
        result = main.score_candidate(profile, requirements)
        statuses = {item["name"]: item["status"] for item in result["skills"]}
        assert statuses == {
            "Python": "verified",
            "FastAPI": "verified",
            "Kubernetes": "unverified",
            "Docker": "partial",
            "Rust": "unverified",
        }
        # (2 verified * 2 + 1 partial) / (3 required * 2 + 2 preferred)
        assert result["match"] == round(5 / 8 * 100)
        assert result["relevant_projects"] == 1

    def test_score_candidate_handles_missing_bio_and_repos(self):
        result = main.score_candidate({"profile": {"bio": None}, "repos": []}, {"required_skills": ["Python"]})
        assert result["match"] == 0
        assert result["evidence_coverage"] == 0


class TestExtractJson:
    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError):
            main.extract_json("here is {not valid json} text")

    def test_ignores_trailing_text_with_braces(self):
        assert main.extract_json('{"a": {"b": 1}} trailing {x}') == {"a": {"b": 1}}


class TestValidation:
    @pytest.mark.parametrize("email", ["invalid", "a@b", "a b@example.com", "@example.com"])
    async def test_login_rejects_malformed_email(self, async_client: AsyncClient, email: str):
        response = await async_client.post("/api/auth/login", json={"email": email, "password": "securepass123"})
        assert response.status_code == 422

    async def test_email_is_case_insensitive(self, async_client: AsyncClient):
        body = {"name": "Case User", "email": "Case@Example.com", "password": "securepass123"}
        assert (await async_client.post("/api/auth/register", json=body)).status_code == 201
        login = await async_client.post("/api/auth/login", json={"email": "case@example.com", "password": "securepass123"})
        assert login.status_code == 200
        assert login.json()["user"]["email"] == "case@example.com"

    async def test_ready_endpoint_reports_database(self, async_client: AsyncClient):
        response = await async_client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"ok": True, "database": "ready"}

    async def test_live_endpoint(self, async_client: AsyncClient):
        assert (await async_client.get("/live")).json() == {"ok": True}


async def _wait_for_status(client: AsyncClient, search_id: str, wanted: set[str]) -> dict[str, Any]:
    for _ in range(50):
        data = (await client.get(f"/api/search/{search_id}")).json()
        if data["status"] in wanted:
            return data
        await asyncio.sleep(0.1)
    raise AssertionError(f"search never reached {wanted}: {data}")


class TestRunSearch:
    async def test_blocked_without_provider_keys(self, authenticated_user, monkeypatch):
        client, _ = authenticated_user
        monkeypatch.setattr(main.settings, "github_token", "")
        monkeypatch.setattr(main.settings, "serpapi_key", "")
        created = await client.post("/api/search", json={"title": "Python Dev", "description": DESCRIPTION, "count": 5})
        data = await _wait_for_status(client, created.json()["id"], {"blocked", "completed", "error"})
        assert data["status"] == "blocked"
        assert data["candidates"] == []
        assert "SERPAPI_KEY" in data["error"]
        assert data["requirements"]["role"] == "Python Dev"

    async def test_completes_with_mocked_github(self, authenticated_user, monkeypatch):
        client, _ = authenticated_user
        monkeypatch.setattr(main.settings, "github_token", "test-token")
        monkeypatch.setattr(main.settings, "serpapi_key", "")

        async def fake_search(query: str, count: int):
            return [{"login": "octocat"}, {"login": "OctoCat"}, {"login": "hubot"}]

        async def fake_profile(login: str):
            return {
                "profile": {"login": login, "name": login.title(), "html_url": f"https://github.com/{login}", "bio": "Python and FastAPI", "public_repos": 3},
                "repos": [{"id": 1, "name": "svc", "description": "PostgreSQL service in Docker", "language": "Python", "topics": []}],
            }

        monkeypatch.setattr(main, "github_search", fake_search)
        monkeypatch.setattr(main, "github_profile", fake_profile)
        created = await client.post("/api/search", json={"title": "Python Dev", "description": DESCRIPTION, "count": 5})
        data = await _wait_for_status(client, created.json()["id"], {"completed", "error", "blocked"})
        assert data["status"] == "completed", data
        assert data["progress"] == 100
        # duplicate login (case-insensitive) is collapsed
        assert [c["login"] for c in data["candidates"]] == ["octocat", "hubot"]
        assert all(c["match"] > 0 for c in data["candidates"])

        candidates = await client.get(f"/api/search/{created.json()['id']}/candidates")
        assert len(candidates.json()) == 2
        detail = await client.get("/api/candidates/octocat")
        assert detail.status_code == 200
        assert (await client.get("/api/candidates/nobody")).status_code == 404

        dashboard = (await client.get("/api/dashboard")).json()
        assert dashboard["stats"]["searches_completed"] == 1
        assert dashboard["stats"]["candidates_found"] == 2

    async def test_provider_error_is_recorded(self, authenticated_user, monkeypatch, db_session: AsyncSession):
        import httpx

        client, _ = authenticated_user
        monkeypatch.setattr(main.settings, "github_token", "test-token")

        async def failing_search(query: str, count: int):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(main, "github_search", failing_search)
        created = await client.post("/api/search", json={"title": "Python Dev", "description": DESCRIPTION, "count": 5})
        data = await _wait_for_status(client, created.json()["id"], {"error", "completed", "blocked"})
        assert data["status"] == "error"
        assert "provider error" in data["error"].lower()
        row = (await db_session.execute(select(Search).where(Search.id == created.json()["id"]))).scalar_one()
        assert row.stage == "Provider error"


class TestGroqFallback:
    async def test_falls_back_to_keywords_when_groq_fails(self, monkeypatch):
        import httpx

        monkeypatch.setattr(main.settings, "groq_api_key", "test-key")

        async def failing_groq(system: str, prompt: str):
            raise httpx.ConnectError("groq down")

        monkeypatch.setattr(main, "groq_json", failing_groq)
        request = main.SearchRequest(title="Python Dev", description=DESCRIPTION)
        requirements, warning = await main.extract_requirements(request)
        assert warning and "keyword extraction" in warning
        assert "Python" in requirements["required_skills"]

    async def test_uses_configured_model_and_reports_groq_errors(self, monkeypatch):
        import httpx

        monkeypatch.setattr(main.settings, "groq_api_key", "test-key")
        monkeypatch.setattr(main.settings, "groq_model", "my/model")
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = request.content.decode()
            return httpx.Response(404, json={"error": {"message": "model decommissioned"}})

        real_client = httpx.AsyncClient
        monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
        with pytest.raises(httpx.HTTPStatusError) as info:
            await main.groq_json("sys", "prompt")
        assert "my/model" in seen["body"]
        assert "decommissioned" in str(info.value)
