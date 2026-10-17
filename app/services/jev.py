import json
from dataclasses import dataclass

from app.core.config import Settings
from app.models.entities import Category, Document


@dataclass(slots=True)
class JevDecision:
    category_code: str
    probabilities: dict[str, float]
    confidence: float
    model_version: str
    input_tokens: int
    output_tokens: int
    input_level: str


class JevNotConfiguredError(RuntimeError):
    pass


async def check_jev_connection(settings: Settings) -> str:
    if not settings.typesafe_api_key:
        return "unconfigured"

    from typesafe_sdk import (
        AsyncTypeSafeClient,
        RetryPolicy,
        TypeSafeAPIConnectionError,
        TypeSafeAPIError,
        TypeSafeAuthenticationError,
        TypeSafeError,
        TypeSafePermissionDeniedError,
    )

    try:
        async with AsyncTypeSafeClient(
            api_key=settings.typesafe_api_key,
            model=settings.typesafe_model,
            retry=RetryPolicy(max_retries=0),
            timeout=12,
        ) as client:
            response = await client.models.list()
    except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError):
        return "authentication_failed"
    except TypeSafeAPIConnectionError:
        return "connection_failed"
    except TypeSafeAPIError:
        return "service_error"
    except TypeSafeError:
        return "authentication_failed"
    except Exception:
        return "service_error"

    available_models = {model.name for model in response.models}
    return "available" if settings.typesafe_model in available_models else "model_unavailable"


class JevClassifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _state(document: Document) -> tuple[dict[str, object], str]:
        state: dict[str, object] = {
            "title": document.title or document.original_name,
            "abstract": document.abstract,
            "keywords": json.loads(document.keywords_json or "[]"),
        }
        if document.abstract:
            return state, "L1"
        state["text_excerpt"] = document.extracted_text[:6000]
        return state, "L2"

    async def classify(self, document: Document, categories: list[Category]) -> JevDecision:
        if not self.settings.typesafe_api_key:
            raise JevNotConfiguredError(
                "尚未配置 TYPESAFE_API_KEY，请填写 .env 后重启服务。"
            )

        from typesafe_sdk import AsyncTypeSafeClient, Choice

        criteria: dict[str, object] = {
            category.code: {
                "definition": f"类别名称：{category.name}。{category.definition}",
                "include": category.inclusion or None,
                "exclude": category.exclusion or None,
            }
            for category in categories
        }
        criteria["none_of_above"] = {
            "definition": "文献不符合任何现有类别，或信息不足以可靠分类。",
            "include": "当文献与所有现有类别的匹配度都较低时使用。",
        }
        state, input_level = self._state(document)
        async with AsyncTypeSafeClient(
            api_key=self.settings.typesafe_api_key,
            model=self.settings.typesafe_model,
        ) as client:
            response = await client.system_one(
                state=state,
                questions={
                    "category": Choice(
                        instructions=(
                            "选择与文献主要研究内容最匹配的唯一类别。"
                            "如果文献无法可靠归入任何现有类别，选择 none_of_above。"
                        ),
                        criteria=criteria,
                    )
                },
            )

        answers = getattr(response, "choices", None) or getattr(response, "answers", None)
        if answers is None:
            raise RuntimeError("TypeSafe 响应中没有分类答案")
        answer = answers["category"]
        probabilities = {str(key): float(value) for key, value in answer.probabilities.items()}
        usage = getattr(response, "usage", None)
        return JevDecision(
            category_code=str(answer.choice),
            probabilities=probabilities,
            confidence=float(answer.confidence),
            model_version=str(getattr(response, "model", self.settings.typesafe_model)),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            input_level=input_level,
        )
