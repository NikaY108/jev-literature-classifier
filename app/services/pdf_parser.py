import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


REVIEW_REQUIRED_WARNINGS = frozenset(
    {
        "标题来自文件名，请检查",
        "可提取文本较少",
        "文本中存在较多异常字符",
    }
)


@dataclass(slots=True)
class ParsedPdf:
    title: str
    abstract: str
    keywords: list[str]
    text: str
    warnings: list[str]


def requires_metadata_review(warnings: list[str]) -> bool:
    return any(warning in REVIEW_REQUIRED_WARNINGS for warning in warnings)


def _clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\x00", " ").replace("\u00ad", "").replace("\ufeff", "")
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
    value = re.sub(r"(?<=[\u3400-\u9fff])[ \t]+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(
        r"(?<![A-Za-z])(?:[A-Za-z][ \t]+){3,}[A-Za-z](?![A-Za-z])",
        lambda match: re.sub(r"[ \t]+", "", match.group(0)),
        value,
    )
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _find_title(metadata_title: str, text: str, fallback: str) -> str:
    fallback = Path(fallback).stem.strip()[:1000]
    metadata_title = _clean_text(metadata_title).replace("\n", " ")[:1000]
    ignored_titles = {"untitled", "unknown", "无标题", "microsoft word"}
    if (
        metadata_title
        and metadata_title.casefold() not in ignored_titles
        and metadata_title.casefold() != fallback.casefold()
        and not metadata_title.casefold().endswith((".pdf", ".doc", ".docx"))
    ):
        return metadata_title

    ignored_prefixes = (
        "doi:", "http://", "https://", "www.", "abstract", "摘要",
        "keywords", "关键词", "收稿日期", "中图分类号",
    )
    candidates: list[str] = []
    for line in text.splitlines()[:35]:
        candidate = line.strip(" -—:：")
        lowered = candidate.casefold()
        if not 8 <= len(candidate) <= 240:
            continue
        if candidate.isdigit() or "@" in candidate or lowered.startswith(ignored_prefixes):
            continue
        if re.fullmatch(r"[\d\W_]+", candidate):
            continue
        candidates.append(candidate)
        if len(candidates) == 5:
            break
    return max(candidates, key=len, default=fallback)[:1000]


def _find_abstract(text: str) -> str:
    head = text[:80_000]
    start = re.search(r"(?im)^\s*(?:abstract|summary|摘要)\s*[:：.。—-]*\s*", head)
    if not start:
        return ""
    remainder = head[start.end() :]
    end = re.search(
        r"(?im)^\s*(?:key\s*words?|keywords?|index\s+terms|关键词|关键字|"
        r"(?:\d+(?:\.\d+)*)?[、.\s]*(?:introduction|引言|绪论|研究背景|材料与方法))\s*[:：]?",
        remainder,
    )
    limit = end.start() if end else 4000
    abstract = _clean_text(remainder[:limit])
    return abstract[:5000] if len(abstract) >= 40 else ""


def _find_keywords(text: str) -> list[str]:
    patterns = [
        r"(?im)^\s*(?:key\s*words?|index\s+terms)\s*[:：—-]\s*(.{3,500})$",
        r"(?m)^\s*(?:关键词|关键字)\s*[:：—-]\s*(.{2,500})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            values = [item.strip(" .") for item in re.split(r"[,;，；]", match.group(1))]
            return [item for item in values if item][:30]
    return []


def _quality_warnings(title: str, abstract: str, keywords: list[str], text: str, fallback: str) -> list[str]:
    warnings: list[str] = []
    if title.casefold() == Path(fallback).stem.strip().casefold():
        warnings.append("标题来自文件名，请检查")
    if not abstract:
        warnings.append("未识别到摘要")
    if not keywords:
        warnings.append("未识别到关键词")
    if len(text) < 1200:
        warnings.append("可提取文本较少")
    if text.count("�") >= 3:
        warnings.append("文本中存在较多异常字符")
    return warnings


def parse_pdf(content: bytes, fallback_name: str) -> ParsedPdf:
    reader = PdfReader(BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = _clean_text("\n\n".join(pages))[:1_500_000]
    if not text:
        raise ValueError("PDF 中没有可提取的文本")
    metadata_title = str(reader.metadata.title) if reader.metadata and reader.metadata.title else ""
    title = _find_title(metadata_title, text, fallback_name)
    abstract = _find_abstract(text)
    keywords = _find_keywords(text)
    return ParsedPdf(
        title=title,
        abstract=abstract,
        keywords=keywords,
        text=text,
        warnings=_quality_warnings(title, abstract, keywords, text, fallback_name),
    )
