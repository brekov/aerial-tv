"""Server-rendered admin pages (login + dashboard shell).

The dashboard is HTML rendered from SQLite plus a small amount of vanilla JS
that talks to the JSON API in :mod:`app.api_admin`.  No JS build step, no CDN.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth
from .config import Settings
from .db import read_session
from .materials import admin_material_dict, list_materials
from .providers import provider_status
from .questions import (
    list_questions,
    list_recent_revisions,
    question_admin_dict,
    revision_admin_dict,
)
from .sessions import list_sessions
from .util import iso

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["admin-ui"])


def _wants_json(request: Request) -> bool:
    content_type = request.headers.get("content-type", "").lower()
    accept = request.headers.get("accept", "").lower()
    return "application/json" in content_type or (
        "application/json" in accept and "text/html" not in accept
    )


def _cookie_secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _render_login(
    request: Request,
    settings: Settings,
    error: str = "",
    status_code: int = 200,
    next_url: str = "/admin",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "error": error,
            "next": next_url,
            "version": settings.version,
            "admin_configured": settings.admin_configured,
        },
        status_code=status_code,
    )


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, next: str = "/admin") -> HTMLResponse:
    settings: Settings = request.app.state.settings
    token = auth.admin_token_from_request(request, settings)
    if auth.verify_admin_token(settings, token):
        return RedirectResponse("/admin", status_code=303)
    return _render_login(request, settings, next_url=next)


@router.post("/admin/login", include_in_schema=False)
async def login_submit(request: Request) -> Any:
    settings: Settings = request.app.state.settings
    wants_json = _wants_json(request)
    if not settings.admin_configured:
        message = "admin is disabled: set ADMIN_PASSWORD in .env"
        if wants_json:
            return JSONResponse(status_code=503, content={"detail": message})
        return _render_login(request, settings, error=message, status_code=503)

    password = ""
    next_url = "/admin"
    if wants_json:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        password = str(body.get("password") or "")
        next_url = str(body.get("next") or "/admin")
    else:
        form = await request.form()
        password = str(form.get("password") or "")
        next_url = str(form.get("next") or "/admin")

    if not auth.check_admin_password(settings, password):
        message = "wrong password"
        if wants_json:
            return JSONResponse(status_code=401, content={"detail": message})
        return _render_login(request, settings, error=message, status_code=401, next_url=next_url)

    token, expires_at = auth.create_admin_token(settings)
    if wants_json:
        response: Any = JSONResponse(
            {"token": token, "expiresAt": iso(datetime.fromtimestamp(expires_at, tz=UTC))}
        )
    else:
        response = RedirectResponse(
            next_url if next_url.startswith("/") else "/admin", status_code=303
        )
    response.set_cookie(
        settings.admin_cookie_name,
        token,
        max_age=settings.admin_session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )
    return response


@router.post("/admin/logout", include_in_schema=False)
async def logout(request: Request) -> Any:
    settings: Settings = request.app.state.settings
    wants_json = _wants_json(request)
    response: Any
    if wants_json:
        response = JSONResponse({"ok": True})
    else:
        response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(settings.admin_cookie_name, path="/")
    return response


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request, status: str = "", search: str = "") -> Any:
    settings: Settings = request.app.state.settings
    token = auth.admin_token_from_request(request, settings)
    if not auth.verify_admin_token(settings, token):
        return RedirectResponse("/admin/login?next=/admin", status_code=303)

    status_filter = status if status in {"draft", "reviewed", "active", "disabled"} else None
    questions, total_questions = list_questions(
        settings,
        status_value=status_filter,
        search=search or None,
        limit=100,
    )
    with read_session(settings) as conn:
        counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM questions GROUP BY status"
            ).fetchall()
        }
        material_count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    materials = list_materials(settings, limit=100)
    jobs = request.app.state.generation.list_jobs(limit=20)
    sessions, session_total = list_sessions(settings, limit=20)
    revisions = [revision_admin_dict(item) for item in list_recent_revisions(settings, 30)]
    providers = provider_status(settings)
    asr_status = request.app.state.asr.status()

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "version": settings.version,
            "questions": [question_admin_dict(settings, item) for item in questions],
            "question_total": total_questions,
            "counts": counts,
            "materials": [admin_material_dict(settings, item) for item in materials],
            "material_count": material_count,
            "jobs": jobs,
            "sessions": sessions,
            "session_total": session_total,
            "revisions": revisions,
            "providers": providers,
            "asr": asr_status,
            "status_filter": status_filter or "all",
            "search": search,
            "device_auth": settings.device_auth_enabled,
            "questions_per_session": settings.questions_per_session,
        },
    )
