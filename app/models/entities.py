import uuid
from datetime import UTC, datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Document(BaseModel):
    __tablename__ = "documents"

    original_name: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(1000), default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    extracted_title: Mapped[str] = mapped_column(String(1000), default="")
    extracted_abstract: Mapped[str] = mapped_column(Text, default="")
    extracted_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_status: Mapped[str] = mapped_column(String(32), default="pending")
    quality_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    extracted_text: Mapped[str] = mapped_column(Text, default="")


class Taxonomy(BaseModel):
    __tablename__ = "taxonomies"

    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("taxonomies.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="manual")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="active")


class Category(BaseModel):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("taxonomy_id", "code", name="uq_taxonomy_category_code"),)

    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomies.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(240))
    definition: Mapped[str] = mapped_column(Text)
    inclusion: Mapped[str] = mapped_column(Text, default="")
    exclusion: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ClassificationRun(BaseModel):
    __tablename__ = "classification_runs"

    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomies.id"))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    model_name: Mapped[str] = mapped_column(String(160))
    total_documents: Mapped[int] = mapped_column(Integer, default=0)
    completed_documents: Mapped[int] = mapped_column(Integer, default=0)
    failed_documents: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClassificationResult(BaseModel):
    __tablename__ = "classification_results"
    __table_args__ = (UniqueConstraint("run_id", "document_id", name="uq_run_document"),)

    run_id: Mapped[str] = mapped_column(ForeignKey("classification_runs.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    taxonomy_id: Mapped[str] = mapped_column(ForeignKey("taxonomies.id"))
    category_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    probabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_level: Mapped[str] = mapped_column(String(8), default="L1")
    model_version: Mapped[str] = mapped_column(String(160), default="")
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    reviewed_category_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ZoteroSyncRecord(BaseModel):
    __tablename__ = "zotero_sync_records"
    __table_args__ = (
        UniqueConstraint(
            "classification_result_id",
            "server_id",
            name="uq_zotero_sync_result_server",
        ),
    )

    classification_result_id: Mapped[str] = mapped_column(
        ForeignKey("classification_results.id", ondelete="CASCADE")
    )
    server_id: Mapped[str] = mapped_column(String(120))
    item_key: Mapped[str] = mapped_column(String(80))
    item_version: Mapped[int] = mapped_column(Integer)
    tag: Mapped[str] = mapped_column(String(1000))


class SchemeCandidate(BaseModel):
    __tablename__ = "scheme_candidates"

    objective: Mapped[str] = mapped_column(Text)
    category_count: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    categories_json: Mapped[str] = mapped_column(Text)
