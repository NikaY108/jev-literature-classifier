import json
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database() -> None:
    from app.models.entities import BaseModel, Document  # noqa: F401
    from app.services.pdf_parser import requires_metadata_review

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        columns = {column["name"] for column in inspect(engine).get_columns("documents")}
        additions = {
            "extracted_title": "VARCHAR(1000) NOT NULL DEFAULT ''",
            "extracted_abstract": "TEXT NOT NULL DEFAULT ''",
            "extracted_keywords_json": "TEXT NOT NULL DEFAULT '[]'",
            "metadata_status": "VARCHAR(32) NOT NULL DEFAULT 'confirmed'",
            "quality_warnings_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        missing = [name for name in additions if name not in columns]
        if missing:
            with engine.begin() as connection:
                for name in missing:
                    connection.execute(
                        text(f"ALTER TABLE documents ADD COLUMN {name} {additions[name]}")
                    )
                connection.execute(
                    text(
                        "UPDATE documents SET extracted_title = title, "
                        "extracted_abstract = abstract, extracted_keywords_json = keywords_json"
                    )
                )

        taxonomy_columns = {
            column["name"] for column in inspect(engine).get_columns("taxonomies")
        }
        if "parent_id" not in taxonomy_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE taxonomies ADD COLUMN parent_id VARCHAR(36)")
                )

    with SessionLocal() as session:
        pending_documents = session.scalars(
            select(Document).where(
                Document.parse_status == "ready",
                Document.metadata_status == "pending",
            )
        )
        changed = False
        for document in pending_documents:
            try:
                warnings = json.loads(document.quality_warnings_json or "[]")
            except json.JSONDecodeError:
                continue
            if not requires_metadata_review(warnings):
                document.metadata_status = "confirmed"
                changed = True
        if changed:
            session.commit()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
