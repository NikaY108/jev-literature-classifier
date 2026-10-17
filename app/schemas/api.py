from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str
    jev_configured: bool
    jev_connection_status: Literal[
        "unconfigured",
        "unverified",
        "available",
        "authentication_failed",
        "model_unavailable",
        "connection_failed",
        "service_error",
    ]
    generation_configured: bool
    model: str


class ModelSettingsResponse(BaseModel):
    typesafe_api_key_configured: bool
    typesafe_model: str
    jev_connection_status: Literal[
        "unconfigured",
        "unverified",
        "available",
        "authentication_failed",
        "model_unavailable",
        "connection_failed",
        "service_error",
    ]
    generation_api_key_configured: bool
    generation_base_url: str
    generation_model: str


class ModelSettingsUpdate(BaseModel):
    typesafe_api_key: str = Field(default="", max_length=2000)
    typesafe_model: str = Field(min_length=1, max_length=300)
    generation_api_key: str = Field(default="", max_length=2000)
    generation_base_url: str = Field(min_length=8, max_length=1000)
    generation_model: str = Field(min_length=1, max_length=300)

    @field_validator(
        "typesafe_api_key",
        "typesafe_model",
        "generation_api_key",
        "generation_base_url",
        "generation_model",
    )
    @classmethod
    def clean_model_setting(cls, value: str) -> str:
        cleaned = value.strip()
        if "\n" in cleaned or "\r" in cleaned:
            raise ValueError("模型配置不能包含换行符")
        return cleaned

    @field_validator("generation_base_url")
    @classmethod
    def validate_generation_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("API 地址必须以 http:// 或 https:// 开头")
        return value.rstrip("/")


class DocumentResponse(BaseModel):
    id: str
    original_name: str
    content_hash: str
    size_bytes: int
    parse_status: str
    parse_error: str | None
    title: str
    abstract: str
    keywords: list[str]
    extracted_title: str
    extracted_abstract: str
    extracted_keywords: list[str]
    metadata_status: str
    quality_warnings: list[str]
    created_at: datetime
    duplicate: bool = False


class DocumentMetadataUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    abstract: str = Field(default="", max_length=20_000)
    keywords: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, keywords: list[str]) -> list[str]:
        cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
        if any(len(keyword) > 200 for keyword in cleaned):
            raise ValueError("单个关键词不能超过 200 个字符")
        return list(dict.fromkeys(cleaned))


class CategoryInput(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=240)
    definition: str = Field(min_length=5, max_length=3000)
    inclusion: str = Field(default="", max_length=3000)
    exclusion: str = Field(default="", max_length=3000)


class TaxonomyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    objective: str = Field(default="", max_length=3000)
    mode: str = Field(default="manual", pattern=r"^(manual|generated)$")
    categories: list[CategoryInput] = Field(min_length=2, max_length=254)

    @field_validator("categories")
    @classmethod
    def categories_are_unique(cls, categories: list[CategoryInput]) -> list[CategoryInput]:
        codes = [category.code for category in categories]
        if len(codes) != len(set(codes)):
            raise ValueError("类别代码不能重复")
        names = [category.name.strip().casefold() for category in categories]
        if len(names) != len(set(names)):
            raise ValueError("类别名称不能重复")
        if "none_of_above" in codes:
            raise ValueError("none_of_above 是系统保留代码")
        return categories


class CategoryResponse(CategoryInput):
    id: str
    sort_order: int


class TaxonomyResponse(BaseModel):
    id: str
    parent_id: str | None
    name: str
    objective: str
    mode: str
    version: int
    status: str
    categories: list[CategoryResponse]
    created_at: datetime


class ClassificationRunRequest(BaseModel):
    taxonomy_id: str
    document_ids: list[str] = Field(min_length=1)


class ClassificationRunResponse(BaseModel):
    id: str
    taxonomy_id: str
    taxonomy_name: str
    taxonomy_version: int
    status: str
    model_name: str
    total_documents: int
    completed_documents: int
    failed_documents: int
    input_tokens: int
    output_tokens: int
    error_message: str | None
    created_at: datetime


class ClassificationResultResponse(BaseModel):
    id: str
    run_id: str
    document_id: str
    document_title: str
    document_name: str
    taxonomy_id: str
    category_code: str | None
    category_name: str | None
    probabilities: dict[str, float]
    probability_labels: dict[str, str]
    confidence: float | None
    top_gap: float | None
    input_level: str
    model_version: str
    review_status: str
    reviewed_category_code: str | None
    review_note: str
    error_message: str | None
    created_at: datetime


class ReviewRequest(BaseModel):
    action: str = Field(pattern=r"^(confirm|correct|defer|unclassified|propose_new)$")
    category_code: str | None = None
    note: str = Field(default="", max_length=3000)


class ZoteroStatusResponse(BaseModel):
    connected: bool
    writable: bool
    server_id: str | None = None
    api_version: str | None = None
    message: str


class ZoteroPreviewRequest(BaseModel):
    run_id: str


class ZoteroMatchCandidate(BaseModel):
    item_key: str
    title: str
    item_type: str
    date: str
    version: int
    match_reason: str


class ZoteroPreviewItem(BaseModel):
    result_id: str
    document_title: str
    document_name: str
    proposed_tag: str
    proposed_collection_path: list[str]
    match_status: str
    default_action: str | None
    selected_item_key: str | None
    needs_change: bool | None
    candidates: list[ZoteroMatchCandidate]


class ZoteroPreviewResponse(BaseModel):
    run_id: str
    taxonomy_name: str
    server_id: str
    ready_count: int
    needs_choice_count: int
    items: list[ZoteroPreviewItem]


class ZoteroWriteSelection(BaseModel):
    result_id: str
    action: str = Field(pattern=r"^(create|reuse)$")
    item_key: str | None = None
    item_version: int | None = Field(default=None, ge=0)


class ZoteroWriteRequest(BaseModel):
    run_id: str
    server_id: str
    write_tags: bool = True
    write_collections: bool = True
    selections: list[ZoteroWriteSelection] = Field(min_length=1)


class ZoteroImportItemResult(BaseModel):
    result_id: str
    status: str
    message: str


class ZoteroWriteResponse(BaseModel):
    created_count: int
    updated_count: int
    unchanged_count: int
    attachment_count: int
    collection_count: int
    failed_count: int
    errors: list[str]
    items: list[ZoteroImportItemResult]


class SchemeGenerateRequest(BaseModel):
    document_ids: list[str] = Field(min_length=2)
    objective: str = Field(min_length=3, max_length=3000)
    category_count: int = Field(ge=2, le=20)
    scheme_count: int = Field(default=3, ge=3, le=5)


class GeneratedScheme(BaseModel):
    name: str
    description: str
    categories: list[CategoryInput]


class SchemeGenerateResponse(BaseModel):
    corpus_document_count: int
    profile_terms: list[str]
    objective_interpretation: str
    schemes: list[GeneratedScheme]
