"""Admin JSON API (cookie or bearer authenticated)."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from .config import Settings
from .db import read_session
from .deps import get_settings, require_admin_dep
from .generation import GenerationService
from .materials import (
    admin_material_dict,
    list_materials,
    save_material,
)
from .providers import (
    PROVIDER_NAMES,
    provider_status,
    update_provider_settings,
)
from .questions import (
    create_question,
    get_question,
    list_questions,
    list_recent_revisions,
    list_revisions,
    question_admin_dict,
    revision_admin_dict,
    set_status,
    update_question,
)
from .sessions import list_sessions, session_detail

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_dep)],
)


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------


class QuestionCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=500)
    type: str = "word_image"
    lang: str = "zh"
    imageId: str | None = None
    options: list[Any] | None = None
    explanation: str = ""
    difficulty: int = 1
    status: str = "draft"
    meta: dict[str, Any] | None = None


class QuestionUpdateRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=500)
    type: str | None = None
    lang: str | None = None
    imageId: str | None = None
    options: list[Any] | None = None
    explanation: str | None = None
    difficulty: int | None = None
    status: str | None = None
    meta: dict[str, Any] | None = None
    changeNote: str | None = None


class QuestionStatusRequest(BaseModel):
    status: str
    note: str | None = None


class GenerateRequest(BaseModel):
    materialId: str
    provider: str | None = None
    lang: str = "zh"
    count: int = Field(default=5, ge=1, le=20)


class ProviderUpdateRequest(BaseModel):
    baseUrl: str | None = None
    model: str | None = None
    authHeader: str | None = None


class ProviderSettingsRequest(BaseModel):
    defaultProvider: str | None = None
    aiJudgeEnabled: bool | None = None


# ---------------------------------------------------------------------------
# stats / materials
# ---------------------------------------------------------------------------


@router.get("/stats")
def stats(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    with read_session(settings) as conn:
        question_counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM questions GROUP BY status"
            ).fetchall()
        }
        material_count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        job_counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM generation_jobs GROUP BY status"
            ).fetchall()
        }
        session_count = conn.execute("SELECT COUNT(*) FROM quiz_sessions").fetchone()[0]
    return {
        "questions": question_counts,
        "materials": material_count,
        "generationJobs": job_counts,
        "sessions": session_count,
    }


@router.get("/materials")
def get_materials(
    kind: str | None = None,
    limit: int = 100,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    items = [
        admin_material_dict(settings, material)
        for material in list_materials(settings, kind=kind, limit=limit)
    ]
    return {"items": items}


@router.post("/materials", status_code=201)
def upload_material(
    response: Response,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    data = file.file.read(settings.image_max_mb * 1024 * 1024 + 1)
    material, created = save_material(
        settings,
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        data=data,
        title=title,
    )
    if not created:
        response.status_code = 200
    return {
        "material": admin_material_dict(settings, material),
        "deduplicated": not created,
    }


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------


@router.get("/questions")
def get_questions(
    status: str | None = None,
    type: str | None = None,
    lang: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    items, total = list_questions(
        settings,
        status_value=status,
        question_type=type,
        lang=lang,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [question_admin_dict(settings, item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/questions", status_code=201)
def create_question_endpoint(
    payload: QuestionCreateRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    question = create_question(
        settings,
        prompt=payload.prompt,
        answer=payload.answer,
        question_type=payload.type,
        lang=payload.lang,
        image_id=payload.imageId,
        options=payload.options,
        explanation=payload.explanation,
        difficulty=payload.difficulty,
        status_value=payload.status,
        source="manual",
        meta=payload.meta,
        changed_by="admin",
        change_note="created in admin",
    )
    return {"question": question_admin_dict(settings, question)}


@router.get("/questions/{question_id}")
def get_question_endpoint(
    question_id: int, settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    question = get_question(settings, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="question not found")
    revisions = list_revisions(settings, question_id)
    return {
        "question": question_admin_dict(settings, question),
        "revisions": [revision_admin_dict(item) for item in revisions],
    }


@router.patch("/questions/{question_id}")
def update_question_endpoint(
    question_id: int,
    payload: QuestionUpdateRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    fields = payload.model_dump(exclude_unset=True)
    note = fields.pop("changeNote", "") or "edited in admin"
    question = update_question(
        settings,
        question_id,
        fields=fields,
        changed_by="admin",
        change_note=note,
    )
    return {"question": question_admin_dict(settings, question)}


@router.post("/questions/{question_id}/status")
def set_question_status(
    question_id: int,
    payload: QuestionStatusRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    question = set_status(
        settings,
        question_id,
        payload.status,
        changed_by="admin",
        change_note=payload.note or f"status -> {payload.status}",
    )
    return {"question": question_admin_dict(settings, question)}


@router.get("/questions/{question_id}/revisions")
def get_question_revisions(
    question_id: int, settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    question = get_question(settings, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="question not found")
    revisions = list_revisions(settings, question_id)
    return {
        "questionId": question_id,
        "revisions": [revision_admin_dict(item) for item in revisions],
    }


@router.get("/history")
def history(limit: int = 50, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    revisions = list_recent_revisions(settings, limit=limit)
    return {"items": [revision_admin_dict(item) for item in revisions]}


# ---------------------------------------------------------------------------
# quiz sessions
# ---------------------------------------------------------------------------


@router.get("/sessions")
def get_sessions(
    limit: int = 50,
    offset: int = 0,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    items, total = list_sessions(settings, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: str, settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    detail = session_detail(settings, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session not found")
    return detail


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------


@router.post("/generate", status_code=202)
def trigger_generation(
    payload: GenerateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    service: GenerationService = request.app.state.generation
    job = service.create_job(
        material_id=payload.materialId,
        provider=payload.provider,
        lang=payload.lang,
        count=payload.count,
        requested_by="admin",
    )
    return {"job": job}


@router.get("/jobs")
def get_jobs(
    request: Request,
    limit: int = 50,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    service: GenerationService = request.app.state.generation
    return {"items": service.list_jobs(limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    service: GenerationService = request.app.state.generation
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": job}


# ---------------------------------------------------------------------------
# providers / settings
# ---------------------------------------------------------------------------


@router.get("/providers")
def get_providers(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return provider_status(settings)


@router.put("/providers/{provider_name}")
def put_provider(
    provider_name: str,
    payload: ProviderUpdateRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if provider_name not in PROVIDER_NAMES:
        raise HTTPException(status_code=404, detail="unknown provider")
    return update_provider_settings(
        settings,
        provider_name,
        base_url=payload.baseUrl,
        model=payload.model,
        auth_header=payload.authHeader,
    )


@router.put("/settings")
def put_settings(
    payload: ProviderSettingsRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    updated = provider_status(settings)
    name = payload.defaultProvider or updated["defaultProvider"]
    update_provider_settings(
        settings,
        name,
        default=payload.defaultProvider,
        ai_judge_enabled=payload.aiJudgeEnabled,
    )
    return provider_status(settings)
