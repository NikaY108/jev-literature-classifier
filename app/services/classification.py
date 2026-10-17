import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Category, ClassificationResult, ClassificationRun, Document
from app.services.jev import JevClassifier


async def run_classification_job(run_id: str, document_ids: list[str]) -> None:
    settings = get_settings()
    classifier = JevClassifier(settings)
    with SessionLocal() as session:
        run = session.get(ClassificationRun, run_id)
        if not run:
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()
        categories = list(
            session.scalars(
                select(Category)
                .where(Category.taxonomy_id == run.taxonomy_id)
                .order_by(Category.sort_order)
            )
        )

    semaphore = asyncio.Semaphore(max(1, settings.classification_concurrency))

    async def classify_one(document_id: str) -> None:
        async with semaphore:
            with SessionLocal() as read_session:
                document = read_session.get(Document, document_id)
                if not document:
                    decision = None
                    error = "未找到文献"
                elif document.parse_status != "ready":
                    decision = None
                    error = document.parse_error or "文献尚未完成解析，无法分类"
                else:
                    try:
                        decision = await classifier.classify(document, categories)
                        error = None
                    except Exception as exc:
                        decision = None
                        error = str(exc)[:2000]

            with SessionLocal() as write_session:
                run_row = write_session.get(ClassificationRun, run_id)
                if not run_row:
                    return
                if decision:
                    ranked = sorted(decision.probabilities.values(), reverse=True)
                    top_gap = ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0]
                    result = ClassificationResult(
                        run_id=run_id,
                        document_id=document_id,
                        taxonomy_id=run_row.taxonomy_id,
                        category_code=decision.category_code,
                        probabilities_json=json.dumps(decision.probabilities),
                        confidence=decision.confidence,
                        top_gap=top_gap,
                        input_level=decision.input_level,
                        model_version=decision.model_version,
                    )
                    run_row.input_tokens += decision.input_tokens
                    run_row.output_tokens += decision.output_tokens
                    run_row.completed_documents += 1
                else:
                    result = ClassificationResult(
                        run_id=run_id,
                        document_id=document_id,
                        taxonomy_id=run_row.taxonomy_id,
                        error_message=error,
                    )
                    run_row.failed_documents += 1
                write_session.add(result)
                write_session.commit()

    await asyncio.gather(*(classify_one(document_id) for document_id in document_ids))
    with SessionLocal() as session:
        run = session.get(ClassificationRun, run_id)
        if run:
            run.status = "completed" if run.failed_documents == 0 else "completed_with_errors"
            if run.failed_documents == run.total_documents:
                run.status = "failed"
                run.error_message = "全部文献分类失败"
            run.completed_at = datetime.now(UTC)
            session.commit()
