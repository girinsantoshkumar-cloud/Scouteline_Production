from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import DatabaseNotConfigured, SessionLocal, dispose_engine, get_db, get_engine, settings
from models import AuthToken, Search, User

logger = logging.getLogger("scoutline")


def _run_migrations() -> None:
    """Apply Alembic migrations to head using the configured DATABASE_URL."""
    from alembic import command
    from alembic.config import Config

    base_dir = os.path.dirname(os.path.abspath(__file__))
    config = Config(os.path.join(base_dir, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Bring the schema up to date on startup when a database is configured.
    if settings.database_url and settings.auto_migrate:
        try:
            await asyncio.to_thread(_run_migrations)
        except Exception:  # pragma: no cover - startup safety
            logger.exception("database migration failed")
    elif not settings.database_url:
        logger.warning("DATABASE_URL is not set; API endpoints that need the database will return 503")
    yield
    await dispose_engine()


app = FastAPI(title="Scoutline API", version="0.2.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=20, max_length=10000)
    count: int = Field(default=10, ge=5, le=20)
    location: str = ""
    experience: str = ""
    required_technologies: list[str] = []
    preferred_technologies: list[str] = []


class SearchRecord(BaseModel):
    id: str
    title: str
    description: str
    count: int
    status: str = "queued"
    stage: str = "Queued"
    progress: int = 0
    events: list[str] = []
    requirements: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    error: str | None = None
    created_at: str


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterRequest(Credentials):
    name: str = Field(min_length=2, max_length=120)


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    created_at: str


class UserPublic(BaseModel):
    user: UserOut
    token: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def search_to_record(search: Search) -> SearchRecord:
    return SearchRecord(id=search.id, title=search.title, description=search.description, count=search.count, status=search.status, stage=search.stage, progress=search.progress, events=list(search.events or []), requirements=search.requirements or {}, candidates=list(search.candidates or []), error=search.error, created_at=search.created_at.isoformat() if search.created_at else now())


def user_to_out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email, created_at=user.created_at.isoformat() if user.created_at else now())


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value.strip())
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def extract_json(content: str) -> dict[str, Any]:
    """Return the first complete JSON object embedded in ``content``."""
    start = content.find("{")
    if start == -1:
        raise ValueError("AI response did not contain JSON")
    try:
        value, _ = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError as error:
        raise ValueError("AI response did not contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("AI response did not contain a JSON object")
    return value


async def groq_json(system: str, prompt: str) -> dict[str, Any]:
    if not settings.groq_api_key:
        raise RuntimeError("AI analysis unavailable: GROQ_API_KEY is not configured.")
    headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": settings.groq_model,
        "temperature": 0.1,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        if response.is_error:
            # Include Groq's own message (e.g. "model has been decommissioned") instead of a bare status code.
            raise httpx.HTTPStatusError(
                f"Groq returned {response.status_code} for model '{settings.groq_model}': {response.text[:300]}",
                request=response.request,
                response=response,
            )
        return extract_json(response.json()["choices"][0]["message"]["content"])


def heuristic_requirements(request: SearchRequest) -> dict[str, Any]:
    """Keyword-based requirements used when no AI provider is configured or available."""
    terms = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", request.description)
    known = {term.lower(): term for term in terms if len(term) > 2}
    tech = [known[key] for key in ["python", "fastapi", "postgresql", "docker", "aws", "kubernetes", "typescript", "react", "java", "go"] if key in known]
    required = [term for term in tech if term.lower() in request.description.lower()]
    return {
        "role": request.title,
        "required_skills": unique(request.required_technologies + required),
        "preferred_skills": unique(request.preferred_technologies),
        "technologies": unique(tech),
        "frameworks": [],
        "experience_requirements": [],
        "role_requirements": [],
        "project_requirements": [],
        "search_queries": [f"{request.title} GitHub", f"{request.title} developer portfolio"],
    }


async def extract_requirements(request: SearchRequest) -> tuple[dict[str, Any], str | None]:
    """Return ``(requirements, warning)``; ``warning`` is set when the AI step failed and keywords were used."""
    if not settings.groq_api_key:
        return heuristic_requirements(request), None
    prompt = f"""Analyze this recruiting brief. Return JSON only with keys: role, required_skills, preferred_skills, technologies, frameworks, experience_requirements, role_requirements, project_requirements, search_queries. Each skill/query is a short string. Do not invent requirements that are not supported by the brief.
TITLE: {request.title}
DESCRIPTION: {request.description}"""
    try:
        data = await groq_json("You are an evidence-first recruiting analyst. Prefer precise, deduplicated terms.", prompt)
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        logger.warning("Groq analysis failed, using keyword extraction: %s", error)
        return heuristic_requirements(request), f"AI analysis unavailable ({error}); used keyword extraction instead"

    def terms(key: str) -> list[str]:
        raw = data.get(key) or []
        return unique([str(item) for item in raw]) if isinstance(raw, list) else []

    return {
        "role": data.get("role") or request.title,
        "required_skills": unique(request.required_technologies + terms("required_skills")),
        "preferred_skills": unique(request.preferred_technologies + terms("preferred_skills")),
        "technologies": terms("technologies"),
        "frameworks": terms("frameworks"),
        "experience_requirements": terms("experience_requirements"),
        "role_requirements": terms("role_requirements"),
        "project_requirements": terms("project_requirements"),
        "search_queries": terms("search_queries")[:6],
    }, None


async def serp_search(query: str, count: int) -> list[dict[str, Any]]:
    if not settings.serpapi_key:
        raise RuntimeError("Web search temporarily unavailable: SERPAPI_KEY is not configured.")
    params = {"engine": "google", "q": query, "api_key": settings.serpapi_key, "num": min(count, 10)}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://serpapi.com/search.json", params=params)
        response.raise_for_status()
        return response.json().get("organic_results", [])


async def github_search(query: str, count: int) -> list[dict[str, Any]]:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://api.github.com/search/users", params={"q": query, "per_page": min(count, 20)}, headers=headers)
        response.raise_for_status()
        return response.json().get("items", [])


async def github_profile(login: str) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    async with httpx.AsyncClient(timeout=30) as client:
        profile_response, repo_response = await asyncio.gather(
            client.get(f"https://api.github.com/users/{login}", headers=headers),
            client.get(f"https://api.github.com/users/{login}/repos", params={"sort": "updated", "per_page": 8}, headers=headers),
        )
        profile_response.raise_for_status()
        repo_response.raise_for_status()
        return {"profile": profile_response.json(), "repos": repo_response.json()}


def score_candidate(profile: dict[str, Any], requirements: dict[str, Any]) -> dict[str, Any]:
    repos = profile.get("repos", [])
    corpus = " ".join([profile.get("profile", {}).get("bio", "") or ""] + [f"{r.get('name', '')} {r.get('description', '') or ''} {' '.join((r.get('topics') or []))} {' '.join((r.get('language') or '',))}" for r in repos]).lower()
    required = requirements.get("required_skills", [])
    preferred = requirements.get("preferred_skills", [])
    checks = []
    for skill in required:
        found = skill.lower() in corpus
        checks.append({"name": skill, "status": "verified" if found else "unverified", "evidence": f"Public GitHub profile or repository text mentions {skill}." if found else "Not verified from public GitHub evidence."})
    preferred_checks = [{"name": skill, "status": "partial" if skill.lower() in corpus else "unverified", "evidence": f"Public repository evidence mentions {skill}." if skill.lower() in corpus else "Not verified from public evidence."} for skill in preferred]
    required_verified = sum(item["status"] == "verified" for item in checks)
    preferred_verified = sum(item["status"] == "partial" for item in preferred_checks)
    denominator = max(1, len(checks) * 2 + len(preferred_checks))
    points = required_verified * 2 + preferred_verified
    project_count = len([r for r in repos if r.get("description") or r.get("language")])
    match = round(points / denominator * 100)
    return {"match": match, "skills": checks + preferred_checks, "evidence_coverage": round((required_verified + preferred_verified) / max(1, len(checks) + len(preferred_checks)) * 100), "relevant_projects": project_count, "repositories": repos[:6]}


def candidate_from_github(data: dict[str, Any], requirements: dict[str, Any]) -> dict[str, Any]:
    profile = data["profile"]
    scoring = score_candidate(data, requirements)
    return {"id": profile.get("login"), "name": profile.get("name") or profile.get("login"), "login": profile.get("login"), "avatar_url": profile.get("avatar_url"), "profile_url": profile.get("html_url"), "github_url": profile.get("html_url"), "bio": profile.get("bio"), "location": profile.get("location"), "public_repos": profile.get("public_repos", 0), "role": "Public role not verified", "match": scoring["match"], "evidence_coverage": scoring["evidence_coverage"], "skills": scoring["skills"], "repositories": scoring["repositories"], "sources": [{"label": "GitHub profile", "url": profile.get("html_url")}], "experience": [], "summary": "Summary is limited to publicly available GitHub evidence. No employment claim is made without a public source."}


async def _progress(db: AsyncSession, record: Search, stage: str, progress: int, event: str) -> None:
    """Persist a progress update so the UI can poll it."""
    record.stage = stage
    record.progress = progress
    record.events = (record.events or []) + [event]
    await db.commit()


async def run_search(search_id: str, request: SearchRequest) -> None:
    # The background task opens its own session so progress persists as it runs.
    try:
        session = SessionLocal()
    except DatabaseNotConfigured:
        logger.error("run_search skipped: DATABASE_URL is not configured")
        return
    async with session as db:
        record = await db.get(Search, search_id)
        if record is None:
            return
        try:
            record.status = "running"
            await _progress(db, record, "Analyzing job description", 12, "Job description analyzed")
            record.requirements, warning = await extract_requirements(request)
            if warning:
                record.events = (record.events or []) + [warning[:300]]
            await _progress(db, record, "Generating search strategy", 25, "Search queries generated")
            if not settings.github_token and not settings.serpapi_key:
                record.status = "blocked"
                record.error = "Add SERPAPI_KEY and/or GITHUB_TOKEN to run live public-web research. No candidates were fabricated."
                await _progress(db, record, "Awaiting live integrations", 25, "Live research paused because provider keys are missing")
                return
            queries = record.requirements.get("search_queries", [])[:4] or [f"{request.title} GitHub"]
            await _progress(db, record, "Searching public web", 38, "Searching public sources")
            web_results: list[dict[str, Any]] = []
            if settings.serpapi_key:
                for query in queries[:2]:
                    web_results.extend(await serp_search(query, request.count))
            await _progress(db, record, "Searching GitHub", 54, "Searching GitHub public profiles")
            github_items: list[dict[str, Any]] = []
            if settings.github_token:
                for query in queries[:2]:
                    github_items.extend(await github_search(query, request.count))
            logins = unique([item.get("login", "") for item in github_items if item.get("login")])[: request.count]
            candidates: list[dict[str, Any]] = []
            for index, login in enumerate(logins):
                progress = 58 + round((index + 1) / max(1, len(logins)) * 35)
                await _progress(db, record, f"Investigating candidate {index + 1}/{len(logins)}", progress, f"Investigating {login}: GitHub projects and skills")
                try:
                    candidates.append(candidate_from_github(await github_profile(login), record.requirements))
                except httpx.HTTPError:
                    continue
            if not candidates and web_results:
                record.events = (record.events or []) + [f"{len(web_results)} public web results discovered; no GitHub identity could be verified"]
            record.candidates = sorted(candidates, key=lambda item: (item["match"], item["evidence_coverage"]), reverse=True)
            record.status = "completed"
            await _progress(db, record, "Research complete", 100, f"{len(record.candidates)} candidate profiles verified from public GitHub evidence")
        except httpx.HTTPError as error:
            logger.warning("research provider error: %s", error)
            record.status = "error"
            record.error = f"Research provider error: {error}"
            await _progress(db, record, "Provider error", record.progress, "A provider request failed; no fallback candidates were created")
        except Exception as error:
            logger.exception("research failed")
            record.status = "error"
            record.error = str(error)
            await _progress(db, record, "Research error", record.progress, "Research stopped safely without inventing evidence")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()


async def _current_user(authorization: str | None, db: AsyncSession) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required.")
    token = authorization.split(" ", 1)[1].strip()
    result = await db.execute(select(AuthToken).where(AuthToken.token == token))
    auth_token = result.scalar_one_or_none()
    if auth_token is None:
        raise HTTPException(401, "Session is not valid. Please sign in again.")
    result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "Session is not valid. Please sign in again.")
    return user


async def current_user_dep(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)) -> User:
    return await _current_user(authorization, db)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "providers": {"groq": bool(settings.groq_api_key), "serpapi": bool(settings.serpapi_key), "github": bool(settings.github_token)}, "storage": "postgresql" if settings.database_url else "database not configured (set DATABASE_URL)"}


@app.get("/live", include_in_schema=False)
async def live() -> dict[str, bool]:
    """Process liveness probe; does not depend on external services."""
    return {"ok": True}


@app.get("/ready", include_in_schema=False)
async def ready() -> dict[str, Any]:
    """Readiness probe that verifies the configured PostgreSQL connection."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        async with get_engine().begin() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:
        logger.warning("database readiness check failed: %s", str(error).split("DETAIL:", 1)[0])
        raise HTTPException(status_code=503, detail="database is not ready") from error
    return {"ok": True, "database": "ready"}


@app.post("/api/auth/register", status_code=201, response_model=UserPublic)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserPublic:
    email = request.email.strip().lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, "An account with this email already exists. Try signing in.")
    salt = secrets.token_hex(16)
    password_hash = await asyncio.to_thread(_hash_password, request.password, salt)
    user = User(name=request.name.strip(), email=email, salt=salt, password_hash=password_hash)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "An account with this email already exists. Try signing in.") from error
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token=token, user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return UserPublic(user=user_to_out(user), token=token)


@app.post("/api/auth/login", response_model=UserPublic)
async def login(request: Credentials, db: AsyncSession = Depends(get_db)) -> UserPublic:
    email = request.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "Incorrect email or password.")
    candidate_hash = await asyncio.to_thread(_hash_password, request.password, user.salt)
    if not secrets.compare_digest(user.password_hash, candidate_hash):
        raise HTTPException(401, "Incorrect email or password.")
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token=token, user_id=user.id))
    await db.commit()
    return UserPublic(user=user_to_out(user), token=token)


@app.get("/api/auth/me", response_model=UserOut)
async def me(current: User = Depends(current_user_dep)) -> UserOut:
    return user_to_out(current)


@app.post("/api/auth/logout", status_code=204)
async def logout(current: User = Depends(current_user_dep), authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if authorization:
        token = authorization.split(" ", 1)[1].strip()
        result = await db.execute(select(AuthToken).where(AuthToken.token == token))
        auth_token = result.scalar_one_or_none()
        if auth_token is not None:
            await db.delete(auth_token)
            await db.commit()


@app.get("/api/dashboard")
async def dashboard(current: User = Depends(current_user_dep), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(Search).where(Search.user_id == current.id))
    items = list(result.scalars().all())
    candidate_total = sum(len(item.candidates or []) for item in items)
    coverage_values = [candidate.get("evidence_coverage", 0) for item in items for candidate in (item.candidates or [])]
    recent = sorted(items, key=lambda item: item.created_at, reverse=True)[:8]
    return {"stats": {"candidates_found": candidate_total, "searches_completed": sum(item.status == "completed" for item in items), "candidates_investigated": candidate_total, "average_evidence_coverage": round(sum(coverage_values) / max(1, len(coverage_values)))}, "recent_searches": [search_to_record(item).model_dump() for item in recent]}


@app.post("/api/search", status_code=202)
async def create_search(request: SearchRequest, background_tasks: BackgroundTasks, current: User = Depends(current_user_dep), db: AsyncSession = Depends(get_db)) -> SearchRecord:
    search = Search(user_id=current.id, title=request.title, description=request.description, count=request.count, status="queued", stage="Queued", progress=0, events=[], requirements={}, candidates=[])
    db.add(search)
    await db.commit()
    await db.refresh(search)
    background_tasks.add_task(run_search, search.id, request)
    return search_to_record(search)


@app.get("/api/search/{search_id}")
async def get_search(search_id: str, current: User = Depends(current_user_dep), db: AsyncSession = Depends(get_db)) -> SearchRecord:
    result = await db.execute(select(Search).where(Search.id == search_id, Search.user_id == current.id))
    search = result.scalar_one_or_none()
    if search is None:
        raise HTTPException(404, "Search not found")
    return search_to_record(search)


@app.get("/api/search/{search_id}/candidates")
async def get_candidates(search_id: str, current: User = Depends(current_user_dep), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(select(Search).where(Search.id == search_id, Search.user_id == current.id))
    search = result.scalar_one_or_none()
    if search is None:
        raise HTTPException(404, "Search not found")
    return search.candidates or []


@app.get("/api/candidates/{candidate_id}")
async def get_candidate(candidate_id: str, current: User = Depends(current_user_dep), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(Search).where(Search.user_id == current.id))
    for search in result.scalars().all():
        for candidate in (search.candidates or []):
            if candidate["id"] == candidate_id:
                return candidate
    raise HTTPException(404, "Candidate not found")
