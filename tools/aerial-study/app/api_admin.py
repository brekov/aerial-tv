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
from .admin_views import material_view, question_view, questions_view
from .materials import (
    admin_material_dict,
    delete_material,
    list_materials,
    save_material,
)
from .material_scan import ScanError, scan_directory
from .taxonomy import (
    TaxonomyError,
    all_taxonomy,
    create_item,
    update_item,
    update_question_type,
)
from .maintenance import cleanup_non_active, cleanup_seed
from .upload_tokens import create_token
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
    soft_delete_question,
    update_question,
)
from .sessions import question_attempts as load_question_attempts
from .sessions import list_sessions, question_attempts, session_detail, wrong_questions

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
    ageGroupId: int | None = None
    subjectId: int | None = None
    answerMode: str | None = None


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
    ageGroupId: int | None = None
    subjectId: int | None = None
    answerMode: str | None = None
    changeNote: str | None = None


class QuestionStatusRequest(BaseModel):
    status: str
    note: str | None = None


class GenerateRequest(BaseModel):
    materialId: str | None = None
    materialIds: list[str] | None = None
    questionType: str = "word_image"
    ageGroupId: int | None = None
    subjectId: int | None = None
    answerMode: str | None = None
    provider: str | None = None
    lang: str = "zh"
    count: int = Field(default=5, ge=1, le=20)
    params: dict[str, Any] | None = None


class ProviderUpdateRequest(BaseModel):
    baseUrl: str | None = None
    model: str | None = None
    authHeader: str | None = None


class ProviderSettingsRequest(BaseModel):
    defaultProvider: str | None = None
    aiJudgeEnabled: bool | None = None


class TaxonomyItemRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    parentId: int | None = None
    sortOrder: int | None = None
    active: bool | None = None


class QuestionTypeUpdateRequest(BaseModel):
    name: str | None = None
    answerMode: str | None = None
    requiresImage: bool | None = None
    requiresMaterial: bool | None = None
    minOptions: int | None = None
    maxOptions: int | None = None
    active: bool | None = None


class ScanRequest(BaseModel):
    root: str
    categoryId: int | None = None
    ageGroupId: int | None = None
    subjectId: int | None = None
    recursive: bool = True


class MaintenanceRequest(BaseModel):
    dryRun: bool = True
    confirm: bool = False


class UploadTokenRequest(BaseModel):
    categoryId: int | None = None
    ageGroupId: int | None = None
    subjectId: int | None = None
    maxUploads: int = 10
    minutes: int = 10


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
    categoryId: int | None = None,
    ageGroupId: int | None = None,
    subjectId: int | None = None,
    source: str | None = None,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    maps = None
    items = []
    from .admin_views import taxonomy_maps
    maps = taxonomy_maps(settings)
    for material in list_materials(
        settings, kind=kind, limit=limit, category_id=categoryId,
        age_group_id=ageGroupId, subject_id=subjectId, source=source,
    ):
        items.append(material_view(settings, material, maps))
    return {"items": items}


class MaterialUpdateRequest(BaseModel):
    title: str | None = None
    categoryId: int | None = None
    ageGroupId: int | None = None
    subjectId: int | None = None


@router.patch("/materials/{sha256}")
def patch_material(sha256: str, payload: MaterialUpdateRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    from .db import session as db_session
    from .materials import get_material
    from .taxonomy import age_group_exists, parse_category, subject_exists
    from .util import iso, utcnow
    material = get_material(settings, sha256)
    if not material:
        raise HTTPException(status_code=404, detail="material not found")
    if payload.ageGroupId is not None and not age_group_exists(settings, payload.ageGroupId):
        raise HTTPException(status_code=404, detail="age group not found")
    if payload.subjectId is not None and not subject_exists(settings, payload.subjectId):
        raise HTTPException(status_code=404, detail="subject not found")
    if payload.categoryId is not None:
        parse_category(settings, payload.categoryId)
    fields: list[str] = []
    values: list[Any] = []
    if payload.title is not None:
        fields.append("title = ?"); values.append(payload.title.strip())
    if payload.categoryId is not None:
        fields.append("category_id = ?"); values.append(payload.categoryId)
    if payload.ageGroupId is not None:
        fields.append("age_group_id = ?"); values.append(payload.ageGroupId)
    if payload.subjectId is not None:
        fields.append("subject_id = ?"); values.append(payload.subjectId)
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    fields.append("updated_at = ?"); values.append(iso(utcnow())); values.append(sha256)
    with db_session(settings) as conn:
        conn.execute(f"UPDATE materials SET {', '.join(fields)} WHERE sha256 = ?", values)
    updated = get_material(settings, sha256)
    return {"material": material_view(settings, updated or material)}


@router.post("/maintenance/cleanup-seed")
def cleanup_seed_endpoint(payload: MaintenanceRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if not payload.dryRun and not payload.confirm:
        raise HTTPException(status_code=422, detail="confirm=true is required to delete seed data")
    return cleanup_seed(settings, dry_run=payload.dryRun)


@router.post("/maintenance/cleanup-non-active")
def cleanup_non_active_endpoint(payload: MaintenanceRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if not payload.dryRun and not payload.confirm:
        raise HTTPException(status_code=422, detail="confirm=true is required to delete questions")
    return cleanup_non_active(settings, dry_run=payload.dryRun)


@router.delete("/materials/{sha256}", status_code=204)
def remove_material(sha256: str, settings: Settings = Depends(get_settings)) -> Response:
    delete_material(settings, sha256)
    return Response(status_code=204)


@router.get("/taxonomies")
def get_taxonomies(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return all_taxonomy(settings)


@router.post("/age-groups", status_code=201)
def create_age_group(payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": create_item(settings, "age-groups", payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/age-groups/{item_id}")
def patch_age_group(item_id: int, payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": update_item(settings, "age-groups", item_id, payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/subjects", status_code=201)
def create_subject(payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": create_item(settings, "subjects", payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/subjects/{item_id}")
def patch_subject(item_id: int, payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": update_item(settings, "subjects", item_id, payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/material-categories", status_code=201)
def create_category(payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": create_item(settings, "material-categories", payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/material-categories/{item_id}")
def patch_category(item_id: int, payload: TaxonomyItemRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": update_item(settings, "material-categories", item_id, payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.patch("/question-types/{code}")
def patch_question_type(code: str, payload: QuestionTypeUpdateRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return {"item": update_question_type(settings, code, payload.model_dump(exclude_unset=True))}
    except TaxonomyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/upload-tokens")
def create_upload_token(payload: UploadTokenRequest, request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    base = settings.public_base_url or str(request.base_url).rstrip("/")
    try:
        token = create_token(
            settings,
            category_id=payload.categoryId,
            age_group_id=payload.ageGroupId,
            subject_id=payload.subjectId,
            created_by="admin",
            base_url=base,
            max_uploads=payload.maxUploads,
            minutes=payload.minutes,
        )
    except Exception as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=getattr(exc, "message", str(exc))) from exc
    return {"token": token}


@router.post("/materials/scan")
def scan_materials(payload: ScanRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return scan_directory(
            settings,
            root=payload.root,
            category_id=payload.categoryId,
            age_group_id=payload.ageGroupId,
            subject_id=payload.subjectId,
            recursive=payload.recursive,
        )
    except (ScanError, Exception) as exc:
        code = getattr(exc, "status_code", 400)
        raise HTTPException(status_code=code, detail=getattr(exc, "message", str(exc))) from exc


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
    ageGroupId: int | None = None,
    subjectId: int | None = None,
    answerMode: str | None = None,
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
        age_group_id=ageGroupId,
        subject_id=subjectId,
        answer_mode=answerMode,
        limit=limit,
        offset=offset,
    )
    return {
        "items": questions_view(settings, items),
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
        age_group_id=payload.ageGroupId,
        subject_id=payload.subjectId,
        answer_mode=payload.answerMode,
        changed_by="admin",
        change_note="created in admin",
    )
    return {"question": question_admin_dict(settings, question)}


@router.delete("/questions/{question_id}", status_code=204)
def delete_question_endpoint(question_id: int, settings: Settings = Depends(get_settings)) -> Response:
    soft_delete_question(settings, question_id)
    return Response(status_code=204)


@router.get("/questions/{question_id}")
def get_question_endpoint(
    question_id: int, settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    question = get_question(settings, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="question not found")
    revisions = list_revisions(settings, question_id)
    return {
        "question": question_view(settings, question),
        "revisions": [revision_admin_dict(item) for item in revisions],
        "attempts": load_question_attempts(settings, question_id, limit=30),
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


@router.get("/wrong-questions")
def get_wrong_questions(
    ageGroupId: int | None = None,
    subjectId: int | None = None,
    type: str | None = None,
    minWrong: int = 1,
    limit: int = 100,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from .admin_views import STATUS_LABELS, taxonomy_maps
    maps = taxonomy_maps(settings)
    items = wrong_questions(
        settings,
        age_group_id=ageGroupId,
        subject_id=subjectId,
        question_type_code=type,
        min_wrong=minWrong,
        limit=limit,
    )
    for item in items:
        item["imageUrl"] = f"/api/v1/images/{item['image_id']}" if item.get("image_id") else None
        item["typeLabel"] = (maps["type"].get(item.get("type")) or {}).get("name") or item.get("type")
        item["ageGroup"] = {"id": item.get("age_group_id"), "name": maps["age"].get(item.get("age_group_id"), "未分类")}
        item["subject"] = {"id": item.get("subject_id"), "name": maps["subject"].get(item.get("subject_id"), "未分类")}
        item["statusLabel"] = STATUS_LABELS.get(item.get("status"), item.get("status"))
    return {"items": items}


@router.get("/records")
def get_records(limit: int = 50, offset: int = 0, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    items, total = list_sessions(settings, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/records/{session_id}")
def get_record(session_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    detail = session_detail(settings, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="record not found")
    return detail


@router.get("/questions/{question_id}/attempts")
def get_question_attempts(question_id: int, limit: int = 100, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {"items": question_attempts(settings, question_id, limit=limit)}


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
    material_id = payload.materialId or (payload.materialIds[0] if payload.materialIds else None)
    job = service.create_job(
        material_id=material_id,
        provider=payload.provider,
        lang=payload.lang,
        count=payload.count,
        requested_by="admin",
        question_type_code=payload.questionType,
        age_group_id=payload.ageGroupId,
        subject_id=payload.subjectId,
        answer_mode=payload.answerMode,
        params=payload.params,
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
