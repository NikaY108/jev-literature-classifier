import json
import re
from collections import Counter

import httpx

from app.core.config import Settings
from app.models.entities import Document
from app.schemas.api import GeneratedScheme


class GenerationNotConfiguredError(RuntimeError):
    pass


STOP_WORDS = {
    "about",
    "after",
    "also",
    "among",
    "based",
    "from",
    "into",
    "paper",
    "research",
    "study",
    "that",
    "their",
    "these",
    "this",
    "using",
    "were",
    "with",
}


def build_selected_corpus_profile(documents: list[Document]) -> dict[str, object]:
    counter: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    with_abstract = 0
    for document in documents:
        content = f"{document.title} {document.abstract}"
        if document.abstract:
            with_abstract += 1
        languages["zh" if re.search(r"[\u4e00-\u9fff]", content) else "other"] += 1
        terms = re.findall(r"[A-Za-z][A-Za-z-]{2,}|[\u4e00-\u9fff]{2,6}", content.lower())
        counter.update(term for term in terms if term not in STOP_WORDS)
    return {
        "document_count": len(documents),
        "documents_with_abstract": with_abstract,
        "language_distribution": dict(languages),
        "top_terms": [term for term, _ in counter.most_common(80)],
    }


class TaxonomyGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate(
        self,
        profile: dict[str, object],
        objective: str,
        category_count: int,
        scheme_count: int,
    ) -> tuple[str, list[GeneratedScheme]]:
        if not self.settings.generation_api_key or not self.settings.generation_model:
            raise GenerationNotConfiguredError(
                "生成分类方案需要配置 GENERATION_API_KEY 和 GENERATION_MODEL。"
            )
        prompt = {
            "任务": "围绕用户指定的唯一分类维度，生成多套边界设计不同的文献分类方案。",
            "分类目的": objective,
            "首要约束": [
                "分类目的决定唯一的分类维度，优先级高于语料概况中的高频词。",
                "所有候选方案都必须严格使用同一个分类维度。",
                "候选方案只能在类别边界、命名和覆盖粒度上有所不同，不得改用其他分类维度。",
                "例如用户要求按研究对象分类时，类别必须都是研究对象，不能改按研究方法、数据类型、空间尺度或时间尺度分类。",
            ],
            "语料概况用途": (
                "仅用于让类别名称和边界贴合所选文献，不能据此改变用户指定的分类维度。"
            ),
            "输出要求": [
                f"返回且仅返回 {scheme_count} 套方案。",
                f"每套方案必须且仅包含 {category_count} 个类别。",
                "方案名称、方案说明、类别名称和类别说明使用简体中文。",
                "类别代码使用小写 ASCII snake_case。",
                "同一方案内的类别应围绕同一分类维度，边界清晰并尽量互斥。",
                "objective_interpretation 用一句简体中文准确说明你理解的唯一分类维度，并明确排除容易混淆的其他维度。",
                "每套方案说明必须说明它如何落实该分类目的。",
                "每个类别必须提供定义、纳入条件和排除条件。",
                "不得提及代表文献，不得虚构论文标题。",
                "返回前自行检查每个类别是否都回答了分类目的；发现偏离时先修正再输出。",
            ],
            "所选文献语料概况": profile,
            "响应结构": {
                "objective_interpretation": "string",
                "schemes": [
                    {
                        "name": "string",
                        "description": "string",
                        "categories": [
                            {
                                "code": "snake_case",
                                "name": "string",
                                "definition": "string",
                                "inclusion": "string",
                                "exclusion": "string",
                            }
                        ],
                    }
                ]
            },
        }
        url = f"{self.settings.generation_base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.generation_api_key}"},
                json={
                    "model": self.settings.generation_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "只返回符合指定结构的有效 JSON，不要使用 Markdown。"
                                "所有面向用户的文字使用简体中文，类别代码除外。"
                                "用户提供的分类目的是不可偏离的最高优先级约束。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        objective_interpretation = str(data.get("objective_interpretation", "")).strip()
        if len(objective_interpretation) < 3:
            raise ValueError("模型未返回对分类目的的有效解释")
        schemes = [GeneratedScheme.model_validate(item) for item in data.get("schemes", [])]
        if len(schemes) != scheme_count:
            raise ValueError(f"模型返回了 {len(schemes)} 套方案，应为 {scheme_count} 套")
        for scheme in schemes:
            if len(scheme.categories) != category_count:
                raise ValueError(
                    f"方案“{scheme.name}”返回了 {len(scheme.categories)} 个类别，"
                    f"应为 {category_count} 个"
                )
        return objective_interpretation, schemes
