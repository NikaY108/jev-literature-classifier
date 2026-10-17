import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, update_model_env
from app.core.database import get_session
from app.models.entities import (
    Category,
    ClassificationResult,
    ClassificationRun,
    Document,
    SchemeCandidate,
    Taxonomy,
    ZoteroSyncRecord,
)
from app.schemas.api import (
    CategoryResponse,
    ClassificationResultResponse,
    ClassificationRunRequest,
    ClassificationRunResponse,
    DocumentMetadataUpdate,
    DocumentResponse,
    HealthResponse,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    ReviewRequest,
    SchemeGenerateRequest,
    SchemeGenerateResponse,
    TaxonomyCreate,
    TaxonomyResponse,
    ZoteroPreviewItem,
    ZoteroPreviewRequest,
    ZoteroPreviewResponse,
    ZoteroStatusResponse,
    ZoteroWriteRequest,
    ZoteroWriteResponse,
)
from app.services.classification import run_classification_job
from app.services.generator import (
    GenerationNotConfiguredError,
    TaxonomyGenerator,
    build_selected_corpus_profile,
)
from app.services.jev import check_jev_connection
from app.services.pdf_parser import parse_pdf, requires_metadata_review
from app.services.zotero import (
    ZoteroClient,
    ZoteroError,
    classification_collection_path,
    classification_tag,
    collection_key,
    collection_parent,
    find_attachment,
    item_candidate,
    item_data,
    item_key,
    match_document,
    replace_classification_tag,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def document_response(document: Document, duplicate: bool = False) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        original_name=document.original_name,
        content_hash=document.content_hash,
        size_bytes=document.size_bytes,
        parse_status=document.parse_status,
        parse_error=document.parse_error,
        title=document.title,
        abstract=document.abstract,
        keywords=json.loads(document.keywords_json or "[]"),
        extracted_title=document.extracted_title,
        extracted_abstract=document.extracted_abstract,
        extracted_keywords=json.loads(document.extracted_keywords_json or "[]"),
        metadata_status=document.metadata_status,
        quality_warnings=json.loads(document.quality_warnings_json or "[]"),
        created_at=document.created_at,
        duplicate=duplicate,
    )


def taxonomy_response(session: Session, taxonomy: Taxonomy) -> TaxonomyResponse:
    categories = list(
        session.scalars(
            select(Category)
            .where(Category.taxonomy_id == taxonomy.id)
            .order_by(Category.sort_order)
        )
    )
    return TaxonomyResponse(
        id=taxonomy.id,
        parent_id=taxonomy.parent_id,
        name=taxonomy.name,
        objective=taxonomy.objective,
        mode=taxonomy.mode,
        version=taxonomy.version,
        status=taxonomy.status,
        created_at=taxonomy.created_at,
        categories=[
            CategoryResponse(
                id=category.id,
                code=category.code,
                name=category.name,
                definition=category.definition,
                inclusion=category.inclusion,
                exclusion=category.exclusion,
                sort_order=category.sort_order,
            )
            for category in categories
        ],
    )


def run_response(session: Session, run: ClassificationRun) -> ClassificationRunResponse:
    taxonomy = session.get(Taxonomy, run.taxonomy_id)
    return ClassificationRunResponse(
        id=run.id,
        taxonomy_id=run.taxonomy_id,
        taxonomy_name=taxonomy.name if taxonomy else "已删除的分类体系",
        taxonomy_version=taxonomy.version if taxonomy else 0,
        status=run.status,
        model_name=run.model_name,
        total_documents=run.total_documents,
        completed_documents=run.completed_documents,
        failed_documents=run.failed_documents,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        error_message=run.error_message,
        created_at=run.created_at,
    )


def result_response(session: Session, result: ClassificationResult) -> ClassificationResultResponse:
    document = session.get(Document, result.document_id)
    categories = list(
        session.scalars(select(Category).where(Category.taxonomy_id == result.taxonomy_id))
    )
    labels = {category.code: category.name for category in categories}
    labels["none_of_above"] = "不属于以上类别"
    is_unclassified = result.review_status in {"unclassified", "propose_new"}
    reviewed_category_code = (
        "none_of_above" if is_unclassified else result.reviewed_category_code
    )
    category_name = labels.get(reviewed_category_code or result.category_code or "")
    return ClassificationResultResponse(
        id=result.id,
        run_id=result.run_id,
        document_id=result.document_id,
        document_title=document.title if document else "",
        document_name=document.original_name if document else "",
        taxonomy_id=result.taxonomy_id,
        category_code=result.category_code,
        category_name=category_name,
        probabilities=json.loads(result.probabilities_json or "{}"),
        probability_labels=labels,
        confidence=result.confidence,
        top_gap=result.top_gap,
        input_level=result.input_level,
        model_version=result.model_version,
        review_status="unclassified" if is_unclassified else result.review_status,
        reviewed_category_code=reviewed_category_code,
        review_note=result.review_note,
        error_message=result.error_message,
        created_at=result.created_at,
    )


def zotero_result_category(
    result: ClassificationResult,
    category_labels: dict[str, str],
) -> str:
    category_name: str | None = None
    if not result.error_message and result.review_status not in {
        "deferred",
        "unclassified",
        "propose_new",
    }:
        category_code = result.reviewed_category_code or result.category_code
        category_name = category_labels.get(category_code or "")
    return category_name or "未分类"


def zotero_result_tag(
    result: ClassificationResult,
    taxonomy: Taxonomy,
    category_labels: dict[str, str],
) -> str:
    return classification_tag(
        taxonomy.name, zotero_result_category(result, category_labels)
    )


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        jev_configured=bool(settings.typesafe_api_key),
        jev_connection_status=(
            "unverified" if settings.typesafe_api_key else "unconfigured"
        ),
        generation_configured=bool(settings.generation_api_key and settings.generation_model),
        model=settings.typesafe_model,
    )


@router.get("/zotero/status", response_model=ZoteroStatusResponse)
def zotero_status() -> ZoteroStatusResponse:
    with ZoteroClient() as client:
        return ZoteroStatusResponse(**client.status())


def model_settings_response(
    settings: Settings,
    jev_connection_status: str | None = None,
) -> ModelSettingsResponse:
    return ModelSettingsResponse(
        typesafe_api_key_configured=bool(settings.typesafe_api_key),
        typesafe_model=settings.typesafe_model,
        jev_connection_status=(
            jev_connection_status
            or ("unverified" if settings.typesafe_api_key else "unconfigured")
        ),
        generation_api_key_configured=bool(settings.generation_api_key),
        generation_base_url=settings.generation_base_url,
        generation_model=settings.generation_model,
    )


@router.get("/settings/models", response_model=ModelSettingsResponse)
def get_model_settings(settings: SettingsDep) -> ModelSettingsResponse:
    return model_settings_response(settings)


@router.put("/settings/models", response_model=ModelSettingsResponse)
async def update_model_settings(payload: ModelSettingsUpdate) -> ModelSettingsResponse:
    values = {
        "TYPESAFE_MODEL": payload.typesafe_model,
        "GENERATION_BASE_URL": payload.generation_base_url,
        "GENERATION_MODEL": payload.generation_model,
    }
    if payload.typesafe_api_key:
        values["TYPESAFE_API_KEY"] = payload.typesafe_api_key
    if payload.generation_api_key:
        values["GENERATION_API_KEY"] = payload.generation_api_key
    try:
        update_model_env(values)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存模型配置失败：{exc}") from exc
    get_settings.cache_clear()
    settings = get_settings()
    return model_settings_response(settings, await check_jev_connection(settings))


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(session: SessionDep) -> list[DocumentResponse]:
    documents = list(session.scalars(select(Document).order_by(Document.created_at.desc())))
    return [document_response(document) for document in documents]


@router.post("/documents/upload", response_model=list[DocumentResponse])
async def upload_documents(
    files: Annotated[list[UploadFile], File()],
    session: SessionDep,
    settings: SettingsDep,
) -> list[DocumentResponse]:
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一个 PDF 文件")
    responses: list[DocumentResponse] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    for upload in files:
        filename = Path(upload.filename or "document.pdf").name
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=415, detail=f"{filename} 不是 PDF 文件")
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"{filename} 是空文件")
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{filename} 超过 {settings.max_upload_mb} MB 的大小限制",
            )
        digest = hashlib.sha256(content).hexdigest()
        existing = session.scalar(select(Document).where(Document.content_hash == digest))
        if existing:
            responses.append(document_response(existing, duplicate=True))
            continue

        storage_path = settings.uploads_dir / f"{digest}.pdf"
        storage_path.write_bytes(content)
        document = Document(
            original_name=filename,
            storage_path=str(storage_path),
            content_hash=digest,
            mime_type=upload.content_type or "application/pdf",
            size_bytes=len(content),
        )
        try:
            parsed = parse_pdf(content, filename)
            document.title = parsed.title
            document.abstract = parsed.abstract
            document.keywords_json = json.dumps(parsed.keywords, ensure_ascii=False)
            document.extracted_title = parsed.title
            document.extracted_abstract = parsed.abstract
            document.extracted_keywords_json = json.dumps(parsed.keywords, ensure_ascii=False)
            document.quality_warnings_json = json.dumps(parsed.warnings, ensure_ascii=False)
            document.metadata_status = (
                "pending" if requires_metadata_review(parsed.warnings) else "confirmed"
            )
            document.extracted_text = parsed.text
            document.parse_status = "ready"
        except Exception as exc:
            document.title = Path(filename).stem
            document.extracted_title = document.title
            document.quality_warnings_json = json.dumps(
                ["PDF 文本解析失败，请手动填写元数据"], ensure_ascii=False
            )
            document.metadata_status = "pending"
            document.parse_status = "error"
            document.parse_error = str(exc)[:2000]
        session.add(document)
        session.commit()
        session.refresh(document)
        responses.append(document_response(document))
    return responses


@router.patch("/documents/{document_id}", response_model=DocumentResponse)
def update_document_metadata(
    document_id: str,
    payload: DocumentMetadataUpdate,
    session: SessionDep,
) -> DocumentResponse:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="未找到文献")
    document.title = payload.title.strip()
    document.abstract = payload.abstract.strip()
    document.keywords_json = json.dumps(payload.keywords, ensure_ascii=False)
    document.metadata_status = "confirmed"
    document.parse_status = "ready"
    document.parse_error = None
    session.commit()
    session.refresh(document)
    return document_response(document)


@router.get("/taxonomies", response_model=list[TaxonomyResponse])
def list_taxonomies(session: SessionDep) -> list[TaxonomyResponse]:
    taxonomies = list(
        session.scalars(
            select(Taxonomy)
            .where(Taxonomy.status != "deleted")
            .order_by(Taxonomy.created_at.desc())
        )
    )
    return [taxonomy_response(session, taxonomy) for taxonomy in taxonomies]


def _add_categories(session: Session, taxonomy_id: str, payload: TaxonomyCreate) -> None:
    for index, category_input in enumerate(payload.categories):
        session.add(
            Category(
                taxonomy_id=taxonomy_id,
                code=category_input.code,
                name=category_input.name,
                definition=category_input.definition,
                inclusion=category_input.inclusion,
                exclusion=category_input.exclusion,
                sort_order=index,
            )
        )


@router.post("/taxonomies", response_model=TaxonomyResponse, status_code=201)
def create_taxonomy(
    payload: TaxonomyCreate,
    session: SessionDep,
) -> TaxonomyResponse:
    taxonomy = Taxonomy(
        name=payload.name,
        objective=payload.objective,
        mode=payload.mode,
    )
    session.add(taxonomy)
    session.flush()
    _add_categories(session, taxonomy.id, payload)
    session.commit()
    session.refresh(taxonomy)
    return taxonomy_response(session, taxonomy)


@router.post(
    "/taxonomies/{taxonomy_id}/versions",
    response_model=TaxonomyResponse,
    status_code=201,
)
def create_taxonomy_version(
    taxonomy_id: str,
    payload: TaxonomyCreate,
    session: SessionDep,
) -> TaxonomyResponse:
    current = session.get(Taxonomy, taxonomy_id)
    if not current:
        raise HTTPException(status_code=404, detail="未找到分类体系")
    if current.status != "active":
        raise HTTPException(status_code=409, detail="只能基于当前版本创建新版本")

    successor = Taxonomy(
        parent_id=current.id,
        name=payload.name,
        objective=payload.objective,
        mode=payload.mode,
        version=current.version + 1,
    )
    session.add(successor)
    session.flush()
    _add_categories(session, successor.id, payload)
    current.status = "superseded"
    session.commit()
    session.refresh(successor)
    return taxonomy_response(session, successor)


@router.delete("/taxonomies/{taxonomy_id}", status_code=204)
def delete_taxonomy(taxonomy_id: str, session: SessionDep) -> Response:
    taxonomy = session.get(Taxonomy, taxonomy_id)
    if not taxonomy:
        raise HTTPException(status_code=404, detail="未找到分类体系")

    taxonomies = list(session.scalars(select(Taxonomy)))
    by_id = {item.id: item for item in taxonomies}

    def root_id(item: Taxonomy) -> str:
        visited: set[str] = set()
        while item.parent_id and item.parent_id in by_id and item.id not in visited:
            visited.add(item.id)
            item = by_id[item.parent_id]
        return item.id

    family_root_id = root_id(taxonomy)
    family = [item for item in taxonomies if root_id(item) == family_root_id]
    family_ids = [item.id for item in family]
    runs = list(
        session.scalars(
            select(ClassificationRun).where(ClassificationRun.taxonomy_id.in_(family_ids))
        )
    )
    if any(run.status in {"queued", "running"} for run in runs):
        raise HTTPException(
            status_code=409,
            detail="该分类体系仍有任务正在运行，请等待任务结束后再删除",
        )

    run_ids = [run.id for run in runs]
    if run_ids:
        result_ids = list(
            session.scalars(
                select(ClassificationResult.id).where(
                    ClassificationResult.run_id.in_(run_ids)
                )
            )
        )
        if result_ids:
            session.execute(
                delete(ZoteroSyncRecord).where(
                    ZoteroSyncRecord.classification_result_id.in_(result_ids)
                )
            )
        session.execute(
            delete(ClassificationResult).where(ClassificationResult.run_id.in_(run_ids))
        )
    for run in runs:
        session.delete(run)
    session.execute(delete(Category).where(Category.taxonomy_id.in_(family_ids)))
    session.flush()
    for item in sorted(family, key=lambda value: value.version, reverse=True):
        session.delete(item)
        session.flush()
    session.commit()
    return Response(status_code=204)


@router.post("/schemes/generate", response_model=SchemeGenerateResponse)
async def generate_schemes(
    payload: SchemeGenerateRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> SchemeGenerateResponse:
    documents = list(
        session.scalars(select(Document).where(Document.id.in_(payload.document_ids)))
    )
    if len(documents) != len(set(payload.document_ids)):
        raise HTTPException(status_code=404, detail="一个或多个所选文献不存在")
    if any(document.metadata_status != "confirmed" for document in documents):
        raise HTTPException(status_code=409, detail="所选文献中存在尚未确认的元数据")
    profile = build_selected_corpus_profile(documents)
    try:
        objective_interpretation, schemes = await TaxonomyGenerator(settings).generate(
            profile=profile,
            objective=payload.objective,
            category_count=payload.category_count,
            scheme_count=payload.scheme_count,
        )
    except GenerationNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"生成分类方案失败：{exc}") from exc

    for scheme in schemes:
        session.add(
            SchemeCandidate(
                objective=payload.objective,
                category_count=payload.category_count,
                name=scheme.name,
                description=scheme.description,
                categories_json=json.dumps(
                    [category.model_dump() for category in scheme.categories], ensure_ascii=False
                ),
            )
        )
    session.commit()
    return SchemeGenerateResponse(
        corpus_document_count=len(documents),
        profile_terms=list(profile["top_terms"]),
        objective_interpretation=objective_interpretation,
        schemes=schemes,
    )


@router.post("/classifications/run", response_model=ClassificationRunResponse, status_code=202)
def start_classification(
    payload: ClassificationRunRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
) -> ClassificationRunResponse:
    if not settings.typesafe_api_key:
        raise HTTPException(
            status_code=503,
            detail="尚未配置 TYPESAFE_API_KEY，请填写 .env 后重启服务。",
        )
    taxonomy = session.get(Taxonomy, payload.taxonomy_id)
    if not taxonomy:
        raise HTTPException(status_code=404, detail="未找到分类体系")
    if taxonomy.status != "active":
        raise HTTPException(status_code=409, detail="请选择分类体系的当前版本")
    documents = list(
        session.scalars(select(Document).where(Document.id.in_(payload.document_ids)))
    )
    found_ids = {document.id for document in documents}
    requested_ids = list(dict.fromkeys(payload.document_ids))
    if found_ids != set(requested_ids):
        raise HTTPException(status_code=404, detail="一个或多个所选文献不存在")
    if any(document.metadata_status != "confirmed" for document in documents):
        raise HTTPException(status_code=409, detail="所选文献中存在尚未确认的元数据")
    run = ClassificationRun(
        taxonomy_id=taxonomy.id,
        model_name=settings.typesafe_model,
        total_documents=len(requested_ids),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    background_tasks.add_task(run_classification_job, run.id, requested_ids)
    return run_response(session, run)


@router.get("/classifications/runs", response_model=list[ClassificationRunResponse])
def list_runs(session: SessionDep) -> list[ClassificationRunResponse]:
    runs = list(
        session.scalars(select(ClassificationRun).order_by(ClassificationRun.created_at.desc()))
    )
    return [run_response(session, run) for run in runs]


@router.get("/classifications/runs/{run_id}", response_model=ClassificationRunResponse)
def get_run(run_id: str, session: SessionDep) -> ClassificationRunResponse:
    run = session.get(ClassificationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="未找到分类任务")
    return run_response(session, run)


@router.delete("/classifications/runs/{run_id}", status_code=204)
def delete_run(run_id: str, session: SessionDep) -> Response:
    run = session.get(ClassificationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="未找到分类任务")
    if run.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="分类任务仍在运行，暂时不能删除整批结果")

    result_ids = list(
        session.scalars(
            select(ClassificationResult.id).where(ClassificationResult.run_id == run.id)
        )
    )
    if result_ids:
        session.execute(
            delete(ZoteroSyncRecord).where(
                ZoteroSyncRecord.classification_result_id.in_(result_ids)
            )
        )
        session.execute(
            delete(ClassificationResult).where(ClassificationResult.run_id == run.id)
        )
    session.delete(run)
    session.commit()
    return Response(status_code=204)


@router.get("/classifications/results", response_model=list[ClassificationResultResponse])
def list_results(
    session: SessionDep,
    run_id: str | None = None,
) -> list[ClassificationResultResponse]:
    query = select(ClassificationResult).order_by(ClassificationResult.created_at.desc())
    if run_id:
        query = query.where(ClassificationResult.run_id == run_id)
    results = list(session.scalars(query))
    return [result_response(session, result) for result in results]


@router.post("/zotero/preview", response_model=ZoteroPreviewResponse)
def preview_zotero_import(
    payload: ZoteroPreviewRequest,
    session: SessionDep,
) -> ZoteroPreviewResponse:
    run = session.get(ClassificationRun, payload.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="未找到分类任务")
    if run.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="请等待本次分类任务结束后再导入 Zotero")
    taxonomy = session.get(Taxonomy, run.taxonomy_id)
    if not taxonomy:
        raise HTTPException(status_code=404, detail="未找到分类体系")
    results = list(
        session.scalars(
            select(ClassificationResult)
            .where(ClassificationResult.run_id == run.id)
            .order_by(ClassificationResult.created_at)
        )
    )
    if not results:
        raise HTTPException(status_code=409, detail="本次运行没有可导入的分类结果")

    categories = list(
        session.scalars(select(Category).where(Category.taxonomy_id == taxonomy.id))
    )
    category_labels = {category.code: category.name for category in categories}
    result_ids = [result.id for result in results]
    try:
        with ZoteroClient() as client:
            top_items, attachments, server_id = client.library_items()
    except ZoteroError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    all_items = {item_key(item): item for item in [*top_items, *attachments]}
    sync_records = list(
        session.scalars(
            select(ZoteroSyncRecord).where(
                ZoteroSyncRecord.classification_result_id.in_(result_ids),
                ZoteroSyncRecord.server_id == server_id,
            )
        )
    )
    sync_by_result = {record.classification_result_id: record for record in sync_records}
    preview_items: list[ZoteroPreviewItem] = []
    needs_choice = 0
    for result in results:
        document = session.get(Document, result.document_id)
        if not document:
            continue
        proposed_tag = zotero_result_tag(result, taxonomy, category_labels)
        status, selected_key, candidates = match_document(
            document.title,
            document.original_name,
            top_items,
            attachments,
        )
        record = sync_by_result.get(result.id)
        if record and record.item_key in all_items:
            linked_item = all_items[record.item_key]
            linked_candidate = item_candidate(linked_item, "此前已由本工具关联")
            candidates = [linked_candidate, *[
                candidate
                for candidate in candidates
                if candidate["item_key"] != record.item_key
            ]]
            status = "linked"
            selected_key = record.item_key

        default_action: str | None
        needs_change: bool | None
        if status in {"linked", "matched"} and selected_key:
            default_action = "reuse"
            current_data = item_data(all_items[selected_key])
            _, needs_change = replace_classification_tag(
                list(current_data.get("tags") or []), taxonomy.name, proposed_tag
            )
        elif status == "unmatched":
            default_action = "create"
            needs_change = True
        else:
            default_action = None
            needs_change = None
            needs_choice += 1
        preview_items.append(
            ZoteroPreviewItem(
                result_id=result.id,
                document_title=document.title,
                document_name=document.original_name,
                proposed_tag=proposed_tag,
                proposed_collection_path=classification_collection_path(
                    taxonomy.name, zotero_result_category(result, category_labels)
                ),
                match_status=status,
                default_action=default_action,
                selected_item_key=selected_key,
                needs_change=needs_change,
                candidates=candidates,
            )
        )
    return ZoteroPreviewResponse(
        run_id=run.id,
        taxonomy_name=taxonomy.name,
        server_id=server_id,
        ready_count=len(preview_items) - needs_choice,
        needs_choice_count=needs_choice,
        items=preview_items,
    )


@router.post("/zotero/import", response_model=ZoteroWriteResponse)
def import_to_zotero(
    payload: ZoteroWriteRequest,
    session: SessionDep,
) -> ZoteroWriteResponse:
    run = session.get(ClassificationRun, payload.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="未找到分类任务")
    if run.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="分类任务仍在运行")
    taxonomy = session.get(Taxonomy, run.taxonomy_id)
    if not taxonomy:
        raise HTTPException(status_code=404, detail="未找到分类体系")
    if not payload.write_tags and not payload.write_collections:
        raise HTTPException(status_code=422, detail="请至少选择导出标签或导出目录")
    if len({selection.result_id for selection in payload.selections}) != len(payload.selections):
        raise HTTPException(status_code=422, detail="同一分类结果不能重复导入")
    reused_keys = [
        selection.item_key for selection in payload.selections if selection.action == "reuse"
    ]
    if any(not key for key in reused_keys) or len(set(reused_keys)) != len(reused_keys):
        raise HTTPException(status_code=422, detail="复用 Zotero 条目时必须选择互不重复的条目")

    results = list(
        session.scalars(
            select(ClassificationResult).where(
                ClassificationResult.run_id == run.id,
                ClassificationResult.id.in_(
                    [selection.result_id for selection in payload.selections]
                ),
            )
        )
    )
    result_by_id = {result.id: result for result in results}
    if len(result_by_id) != len(payload.selections):
        raise HTTPException(status_code=422, detail="一个或多个分类结果不属于所选运行")
    categories = list(
        session.scalars(select(Category).where(Category.taxonomy_id == taxonomy.id))
    )
    category_labels = {category.code: category.name for category in categories}

    client = ZoteroClient()
    try:
        top_items, attachments, server_id = client.library_items(payload.server_id)
        collections = client.library_collections(server_id) if payload.write_collections else []
    except ZoteroError as exc:
        client.close()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    all_items = {item_key(item): item for item in [*top_items, *attachments]}
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    attachment_count = 0
    collection_count = 0
    failed_count = 0
    errors: list[str] = []
    item_outcomes: list[dict[str, str]] = []
    try:
        for index, selection in enumerate(payload.selections):
            result = result_by_id[selection.result_id]
            document = session.get(Document, result.document_id)
            if not document:
                failed_count += 1
                errors.append("一篇文献已从本地数据库中删除")
                item_outcomes.append(
                    {
                        "result_id": selection.result_id,
                        "status": "failed",
                        "message": "本地文献已删除",
                    }
                )
                continue
            category_name = zotero_result_category(result, category_labels)
            tag = classification_tag(taxonomy.name, category_name)
            try:
                target_collection_key: str | None = None
                taxonomy_collection_key = ""
                if payload.write_collections:
                    target_collection_key, taxonomy_collection_key = (
                        client.ensure_collection_path(
                            server_id,
                            collections,
                            classification_collection_path(taxonomy.name, category_name),
                        )
                    )
                taxonomy_child_keys = {
                    collection_key(collection)
                    for collection in collections
                    if collection_parent(collection) == taxonomy_collection_key
                }
                if selection.action == "create":
                    item = client.create_document(
                        server_id,
                        title=document.title,
                        abstract=document.abstract,
                        keywords=json.loads(document.keywords_json or "[]"),
                        tag=tag if payload.write_tags else None,
                        collection_key=target_collection_key,
                    )
                    created_count += 1
                    if target_collection_key:
                        collection_count += 1
                    output_names = [
                        name
                        for enabled, name in (
                            (payload.write_tags, "分类标签"),
                            (payload.write_collections, "分类目录"),
                        )
                        if enabled
                    ]
                    change_message = f"已新建 Zotero 文献并写入{'和'.join(output_names)}"
                else:
                    if selection.item_key not in all_items or selection.item_version is None:
                        raise ZoteroError("所选 Zotero 条目已不存在，请重新生成预览。")
                    item = all_items[selection.item_key]
                    data = item_data(item)
                    current_version = int(data.get("version") or item.get("version") or 0)
                    if current_version != selection.item_version:
                        raise ZoteroError("所选 Zotero 条目已发生变化，请重新生成预览。")
                    fields: dict[str, object] = {}
                    changed_names: list[str] = []
                    if payload.write_tags:
                        updated_tags, tags_changed = replace_classification_tag(
                            list(data.get("tags") or []), taxonomy.name, tag
                        )
                        if tags_changed:
                            fields["tags"] = updated_tags
                            changed_names.append("分类标签")
                    if payload.write_collections and target_collection_key:
                        current_collections = [
                            str(key) for key in data.get("collections") or []
                        ]
                        updated_collections = [
                            key
                            for key in current_collections
                            if key not in taxonomy_child_keys
                            or key == target_collection_key
                        ]
                        if target_collection_key not in updated_collections:
                            updated_collections.append(target_collection_key)
                        if updated_collections != current_collections:
                            fields["collections"] = updated_collections
                            changed_names.append("分类目录")
                    if fields:
                        item = client.update_item(
                            server_id,
                            selection.item_key,
                            current_version,
                            fields,
                        )
                        updated_count += 1
                        if "分类目录" in changed_names:
                            collection_count += 1
                        change_message = f"已更新{'和'.join(changed_names)}"
                    else:
                        unchanged_count += 1
                        output_names = [
                            name
                            for enabled, name in (
                                (payload.write_tags, "分类标签"),
                                (payload.write_collections, "分类目录"),
                            )
                            if enabled
                        ]
                        change_message = f"{'和'.join(output_names)}无需修改"

                key = item_key(item)
                data = item_data(item)
                version = int(data.get("version") or item.get("version") or 0)
                record = session.scalar(
                    select(ZoteroSyncRecord).where(
                        ZoteroSyncRecord.classification_result_id == result.id,
                        ZoteroSyncRecord.server_id == server_id,
                    )
                )
                if not record:
                    record = ZoteroSyncRecord(
                        classification_result_id=result.id,
                        server_id=server_id,
                        item_key=key,
                        item_version=version,
                        tag=tag,
                    )
                    session.add(record)
                else:
                    record.item_key = key
                    record.item_version = version
                    record.tag = tag
                session.commit()

                item_is_pdf = item_data(item).get("itemType") == "attachment"
                attachment_message = "PDF 已存在"
                existing_attachment = find_attachment(
                    key, document.original_name, attachments
                )
                if not item_is_pdf and (
                    not existing_attachment or not item_data(existing_attachment).get("md5")
                ):
                    file_path = Path(document.storage_path)
                    if not file_path.is_file():
                        raise ZoteroError("本地 PDF 文件不存在，文献条目已创建但附件未导入。")
                    if existing_attachment:
                        attachment_key = item_key(existing_attachment)
                        client.upload_file(
                            server_id, attachment_key, file_path, document.original_name
                        )
                    else:
                        attachment_key = client.create_attachment(
                            server_id, key, file_path, document.original_name
                        )
                    attachment_count += 1
                    attachment_message = "PDF 已导入"
                    if not existing_attachment:
                        attachments.append(
                            {
                                "data": {
                                    "key": attachment_key,
                                    "parentItem": key,
                                    "filename": document.original_name,
                                    "itemType": "attachment",
                                    "contentType": "application/pdf",
                                    "md5": document.content_hash,
                                }
                            }
                        )
                item_outcomes.append(
                    {
                        "result_id": result.id,
                        "status": "success",
                        "message": f"{change_message}，{attachment_message}",
                    }
                )
            except (OSError, ValueError, ZoteroError) as exc:
                session.rollback()
                failed_count += 1
                message = str(exc)
                errors.append(f"{document.title or document.original_name}：{message}")
                item_outcomes.append(
                    {
                        "result_id": result.id,
                        "status": "failed",
                        "message": message,
                    }
                )
                if "拒绝写入授权" in str(exc):
                    remaining = len(payload.selections) - index - 1
                    failed_count += remaining
                    if remaining:
                        errors.append(f"用户取消授权，另有 {remaining} 篇未处理")
                        item_outcomes.extend(
                            {
                                "result_id": pending.result_id,
                                "status": "failed",
                                "message": "用户取消授权，未执行导入",
                            }
                            for pending in payload.selections[index + 1 :]
                        )
                    break
    finally:
        client.close()

    return ZoteroWriteResponse(
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        attachment_count=attachment_count,
        collection_count=collection_count,
        failed_count=failed_count,
        errors=errors,
        items=item_outcomes,
    )


@router.delete("/classifications/results/{result_id}", status_code=204)
def delete_result(result_id: str, session: SessionDep) -> Response:
    result = session.get(ClassificationResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="未找到分类结果")
    run = session.get(ClassificationRun, result.run_id)
    if run and run.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="分类任务仍在运行，暂时不能删除结果")

    remaining = list(
        session.scalars(
            select(ClassificationResult).where(
                ClassificationResult.run_id == result.run_id,
                ClassificationResult.id != result.id,
            )
        )
    )
    session.execute(
        delete(ZoteroSyncRecord).where(
            ZoteroSyncRecord.classification_result_id == result.id
        )
    )
    session.delete(result)
    if run:
        if remaining:
            run.total_documents = len(remaining)
            run.failed_documents = sum(bool(item.error_message) for item in remaining)
            run.completed_documents = len(remaining) - run.failed_documents
        else:
            session.delete(run)
    session.commit()
    return Response(status_code=204)


@router.post(
    "/classifications/results/{result_id}/review",
    response_model=ClassificationResultResponse,
)
def review_result(
    result_id: str,
    payload: ReviewRequest,
    session: SessionDep,
) -> ClassificationResultResponse:
    result = session.get(ClassificationResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="未找到分类结果")
    valid_codes = set(
        session.scalars(
            select(Category.code).where(Category.taxonomy_id == result.taxonomy_id)
        ).all()
    )
    valid_codes.add("none_of_above")
    if payload.action == "correct":
        if not payload.category_code or payload.category_code not in valid_codes:
            raise HTTPException(status_code=422, detail="请选择有效的修正类别")
        result.reviewed_category_code = payload.category_code
        result.review_status = "corrected"
    elif payload.action == "confirm":
        result.reviewed_category_code = result.category_code
        result.review_status = "confirmed"
    elif payload.action == "defer":
        result.review_status = "deferred"
    else:
        result.reviewed_category_code = "none_of_above"
        result.review_status = "unclassified"
    result.review_note = payload.note
    result.reviewed_at = datetime.now(UTC)
    session.commit()
    session.refresh(result)
    return result_response(session, result)


@router.get("/exports/results.{format}")
def export_results(
    format: str,
    session: SessionDep,
    run_id: str | None = None,
) -> Response:
    if format not in {"json", "csv"}:
        raise HTTPException(status_code=404, detail="导出格式必须是 json 或 csv")
    query = select(ClassificationResult).order_by(ClassificationResult.created_at)
    if run_id:
        query = query.where(ClassificationResult.run_id == run_id)
    rows = [
        result_response(session, result).model_dump(mode="json")
        for result in session.scalars(query)
    ]
    if format == "json":
        return Response(
            content=json.dumps(rows, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="classifications.json"'},
        )

    output = io.StringIO()
    fieldnames = [
        "document_title",
        "document_name",
        "category_code",
        "category_name",
        "confidence",
        "top_gap",
        "review_status",
        "reviewed_category_code",
        "input_level",
        "model_version",
        "probabilities",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(row[key], ensure_ascii=False)
                if key == "probabilities"
                else row.get(key, "")
                for key in fieldnames
            }
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="classifications.csv"'},
    )
