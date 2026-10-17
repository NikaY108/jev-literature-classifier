import json

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models.entities import ClassificationResult, ClassificationRun, Document
from app.schemas.api import CategoryInput, GeneratedScheme
from app.services.pdf_parser import ParsedPdf


def taxonomy_payload() -> dict[str, object]:
    return {
        "name": "研究主题",
        "objective": "按主要研究问题分类",
        "mode": "manual",
        "categories": [
            {
                "code": "method",
                "name": "方法研究",
                "definition": "以方法设计和改进为主要贡献",
                "inclusion": "提出或比较方法",
                "exclusion": "仅使用现有方法",
            },
            {
                "code": "application",
                "name": "应用研究",
                "definition": "以特定场景中的应用发现为主要贡献",
                "inclusion": "解决具体应用问题",
                "exclusion": "仅讨论通用方法",
            },
        ],
    }


def test_health_and_home_are_available(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["jev_configured"] is False
    assert client.get("/").status_code == 200


def test_upload_duplicate_and_reject_non_pdf(client: TestClient, monkeypatch) -> None:
    def fake_parse_pdf(content: bytes, fallback_name: str) -> ParsedPdf:
        assert content == b"%PDF-test"
        return ParsedPdf(
            title="A compact fixture",
            abstract="A short abstract used to verify the upload workflow.",
            keywords=["classification"],
            text="Technical fixture text",
        )

    monkeypatch.setattr("app.api.routes.parse_pdf", fake_parse_pdf)
    files = [("files", ("paper.pdf", b"%PDF-test", "application/pdf"))]
    first = client.post("/api/documents/upload", files=files)
    second = client.post("/api/documents/upload", files=files)

    assert first.status_code == 200
    assert first.json()[0]["parse_status"] == "ready"
    assert first.json()[0]["duplicate"] is False
    assert second.json()[0]["duplicate"] is True
    assert len(client.get("/api/documents").json()) == 1

    invalid = client.post(
        "/api/documents/upload",
        files=[("files", ("notes.txt", b"text", "text/plain"))],
    )
    assert invalid.status_code == 415


def test_taxonomy_validation_and_creation(client: TestClient) -> None:
    response = client.post("/api/taxonomies", json=taxonomy_payload())
    assert response.status_code == 201
    assert response.json()["mode"] == "manual"
    assert [item["code"] for item in response.json()["categories"]] == [
        "method",
        "application",
    ]

    duplicate_codes = taxonomy_payload()
    duplicate_codes["categories"][1]["code"] = "method"
    assert client.post("/api/taxonomies", json=duplicate_codes).status_code == 422


def test_classification_requires_a_jev_key(client: TestClient) -> None:
    taxonomy = client.get("/api/taxonomies").json()[0]
    document = client.get("/api/documents").json()[0]
    response = client.post(
        "/api/classifications/run",
        json={"taxonomy_id": taxonomy["id"], "document_ids": [document["id"]]},
    )
    assert response.status_code == 503
    assert "TYPESAFE_API_KEY" in response.json()["detail"]


def test_scheme_generation_uses_only_selected_documents(
    client: TestClient, monkeypatch
) -> None:
    with SessionLocal() as session:
        documents = [
            Document(
                original_name=f"fixture-{index}.pdf",
                storage_path=f"fixture-{index}.pdf",
                content_hash=str(index) * 64,
                size_bytes=10,
                parse_status="ready",
                title=title,
                abstract="测试摘要",
            )
            for index, title in enumerate(
                ["selectedalpha", "selectedbeta", "excludedterm"], start=1
            )
        ]
        session.add_all(documents)
        session.commit()
        selected_ids = [documents[0].id, documents[1].id]

    captured: dict[str, object] = {}

    async def fake_generate(self, profile, objective, category_count, scheme_count):
        captured["profile"] = profile
        categories = [
            CategoryInput(
                code=f"category_{index}",
                name=f"类别 {index}",
                definition=f"类别 {index} 的测试定义",
            )
            for index in range(category_count)
        ]
        return [
            GeneratedScheme(
                name=f"方案 {index}",
                description="测试方案",
                categories=categories,
            )
            for index in range(scheme_count)
        ]

    monkeypatch.setattr("app.api.routes.TaxonomyGenerator.generate", fake_generate)
    response = client.post(
        "/api/schemes/generate",
        json={
            "document_ids": selected_ids,
            "objective": "测试所选范围",
            "category_count": 2,
            "scheme_count": 3,
        },
    )

    assert response.status_code == 200
    profile = captured["profile"]
    assert profile["document_count"] == 2
    assert "selectedalpha" in profile["top_terms"]
    assert "selectedbeta" in profile["top_terms"]
    assert "excludedterm" not in profile["top_terms"]


def test_probability_detail_review_and_exports(client: TestClient) -> None:
    taxonomy = client.get("/api/taxonomies").json()[0]
    document_payload = client.get("/api/documents").json()[0]
    with SessionLocal() as session:
        document = session.get(Document, document_payload["id"])
        run = ClassificationRun(
            taxonomy_id=taxonomy["id"],
            status="completed",
            model_name="jev-test",
            total_documents=1,
            completed_documents=1,
        )
        session.add(run)
        session.flush()
        result = ClassificationResult(
            run_id=run.id,
            document_id=document.id,
            taxonomy_id=taxonomy["id"],
            category_code="method",
            probabilities_json=json.dumps(
                {"method": 0.72, "application": 0.2, "none_of_above": 0.08}
            ),
            confidence=0.81,
            top_gap=0.52,
            model_version="jev-test",
        )
        session.add(result)
        session.commit()
        result_id = result.id

    response = client.get("/api/classifications/results")
    assert response.status_code == 200
    item = next(row for row in response.json() if row["id"] == result_id)
    assert item["probabilities"] == {
        "method": 0.72,
        "application": 0.2,
        "none_of_above": 0.08,
    }
    assert item["probability_labels"]["none_of_above"] == "不属于以上类别"

    reviewed = client.post(
        f"/api/classifications/results/{result_id}/review",
        json={"action": "correct", "category_code": "application", "note": "人工复核"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "corrected"
    assert reviewed.json()["reviewed_category_code"] == "application"

    assert client.get("/api/exports/results.json").status_code == 200
    csv_response = client.get("/api/exports/results.csv")
    assert csv_response.status_code == 200
    assert "document_title" in csv_response.text
