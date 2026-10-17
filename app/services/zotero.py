import hashlib
import re
import unicodedata
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

BASE_URL = "http://127.0.0.1:23119/api"


class ZoteroError(RuntimeError):
    pass


def _message(response: httpx.Response, fallback: str) -> str:
    try:
        detail = response.json()
    except ValueError:
        detail = response.text.strip()
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("error") or detail
    return f"{fallback}（HTTP {response.status_code}：{detail}）"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def normalize_filename(value: str) -> str:
    return normalize_text(Path(value).stem)


def clean_tag_segment(value: str) -> str:
    return " ".join(value.strip().replace("/", "／").split())


def classification_tag(taxonomy_name: str, category_name: str | None) -> str:
    category = clean_tag_segment(category_name or "未分类") or "未分类"
    return f"文献分类/{clean_tag_segment(taxonomy_name)}/{category}"


def classification_collection_path(
    taxonomy_name: str, category_name: str | None
) -> list[str]:
    category = clean_tag_segment(category_name or "未分类") or "未分类"
    return ["文献分类", clean_tag_segment(taxonomy_name), category]


def replace_classification_tag(
    tags: list[Any], taxonomy_name: str, proposed_tag: str
) -> tuple[list[dict[str, Any]], bool]:
    prefix = f"文献分类/{clean_tag_segment(taxonomy_name)}/"
    normalized = [tag if isinstance(tag, dict) else {"tag": str(tag)} for tag in tags]
    kept = [tag for tag in normalized if not str(tag.get("tag", "")).startswith(prefix)]
    updated = [*kept, {"tag": proposed_tag}]
    before = [str(tag.get("tag", "")) for tag in normalized]
    after = [str(tag.get("tag", "")) for tag in updated]
    return updated, before != after


def _created_key(response: httpx.Response, fallback: str) -> str:
    payload = response.json()
    failed = payload.get("failed", {})
    if failed:
        raise ZoteroError(f"{fallback}：{next(iter(failed.values()))}")
    successful = payload.get("successful") or payload.get("success") or {}
    created = successful.get("0") or successful.get(0)
    if isinstance(created, str):
        return created
    if isinstance(created, dict):
        data = created.get("data") if isinstance(created.get("data"), dict) else created
        key = data.get("key")
        if key:
            return str(key)
    raise ZoteroError(f"{fallback}：Zotero 未返回新条目的标识。")


class ZoteroClient:
    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=httpx.Timeout(30, connect=3),
            trust_env=False,
        )
        self.api_key: str | None = None
        self.remembered = False

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ZoteroClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def status(self) -> dict[str, Any]:
        try:
            response = self.client.get(f"{BASE_URL}/")
        except httpx.RequestError:
            return {
                "connected": False,
                "writable": False,
                "message": "未检测到 Zotero，请先启动 Zotero 桌面端。",
            }
        if response.status_code == 403:
            return {
                "connected": False,
                "writable": False,
                "message": (
                    "Zotero 已运行，但尚未允许本机应用访问。"
                    "请在 Zotero 高级设置中开启本地 API。"
                ),
            }
        if response.is_error:
            return {
                "connected": False,
                "writable": False,
                "message": _message(response, "无法连接 Zotero"),
            }
        server_id = response.headers.get("Zotero-Server-ID")
        return {
            "connected": True,
            "writable": bool(server_id),
            "server_id": server_id,
            "api_version": response.headers.get("Zotero-API-Version"),
            "message": (
                "已连接 Zotero，可以导入文献和分类结果。"
                if server_id
                else "已连接 Zotero，但当前版本不支持本地写入，请升级到 Zotero 10 或更高版本。"
            ),
        }

    def library_items(self, server_id: str | None = None) -> tuple[list[dict], list[dict], str]:
        headers = {"Zotero-Server-ID": server_id} if server_id else {}
        params = {"format": "json", "include": "data"}
        try:
            top_response = self.client.get(
                f"{BASE_URL}/users/0/items/top", params=params, headers=headers
            )
            attachment_response = self.client.get(
                f"{BASE_URL}/users/0/items",
                params={**params, "itemType": "attachment"},
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise ZoteroError("读取 Zotero 文献库失败，请确认 Zotero 正在运行。") from exc
        for response in (top_response, attachment_response):
            if response.is_error:
                raise ZoteroError(_message(response, "读取 Zotero 文献库失败"))
        current_server_id = top_response.headers.get("Zotero-Server-ID")
        if not current_server_id:
            raise ZoteroError("当前 Zotero 版本不支持本地写入，请升级到 Zotero 10 或更高版本。")
        if server_id and current_server_id != server_id:
            raise ZoteroError("Zotero 文献库已切换，请重新生成写入预览。")
        top_items = [item for item in top_response.json() if isinstance(item, dict)]
        attachments = [item for item in attachment_response.json() if isinstance(item, dict)]
        return top_items, attachments, current_server_id

    def library_collections(self, server_id: str) -> list[dict[str, Any]]:
        try:
            response = self.client.get(
                f"{BASE_URL}/users/0/collections",
                params={"format": "json", "include": "data"},
                headers={"Zotero-Server-ID": server_id},
            )
        except httpx.RequestError as exc:
            raise ZoteroError("读取 Zotero 分类目录失败，请确认 Zotero 正在运行。") from exc
        if response.is_error:
            raise ZoteroError(_message(response, "读取 Zotero 分类目录失败"))
        return [item for item in response.json() if isinstance(item, dict)]

    def authorize(self, server_id: str) -> tuple[str, bool]:
        try:
            response = self.client.post(
                f"{BASE_URL}/local/authorize",
                headers={"Zotero-Server-ID": server_id},
                json={"appName": "文献分类工作台"},
                timeout=120,
            )
        except httpx.RequestError as exc:
            raise ZoteroError("请求 Zotero 写入授权失败。") from exc
        if response.status_code == 403:
            raise ZoteroError("你已在 Zotero 中拒绝写入授权。")
        if response.is_error:
            raise ZoteroError(_message(response, "请求 Zotero 写入授权失败"))
        payload = response.json()
        key = payload.get("key")
        if not key:
            raise ZoteroError("Zotero 未返回有效的写入授权。")
        return key, bool(payload.get("remember"))

    def _write(
        self,
        method: str,
        url: str,
        server_id: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(2):
            if not self.api_key:
                self.api_key, self.remembered = self.authorize(server_id)
            request_headers = {
                "Zotero-Server-ID": server_id,
                "Zotero-API-Key": self.api_key,
                **(headers or {}),
            }
            try:
                response = self.client.request(
                    method, url, headers=request_headers, **kwargs
                )
            except httpx.RequestError as exc:
                raise ZoteroError("写入 Zotero 失败，请确认 Zotero 正在运行。") from exc
            if response.status_code == 401 and attempt == 0:
                self.api_key = None
                self.remembered = False
                continue
            if not self.remembered:
                self.api_key = None
            return response
        raise ZoteroError("Zotero 写入授权已失效。")

    def get_item(self, key: str, server_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"{BASE_URL}/users/0/items/{key}",
            headers={"Zotero-Server-ID": server_id},
        )
        if response.is_error:
            raise ZoteroError(_message(response, "读取 Zotero 条目失败"))
        return response.json()

    def get_collection(self, key: str, server_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"{BASE_URL}/users/0/collections/{key}",
            headers={"Zotero-Server-ID": server_id},
        )
        if response.is_error:
            raise ZoteroError(_message(response, "读取 Zotero 分类目录失败"))
        return response.json()

    def create_collection(
        self, server_id: str, name: str, parent_key: str | None
    ) -> dict[str, Any]:
        response = self._write(
            "POST",
            f"{BASE_URL}/users/0/collections",
            server_id,
            headers={"Zotero-Write-Token": uuid.uuid4().hex},
            json=[{"name": name, "parentCollection": parent_key or False}],
        )
        if response.is_error:
            raise ZoteroError(_message(response, "创建 Zotero 分类目录失败"))
        key = _created_key(response, "创建 Zotero 分类目录失败")
        return self.get_collection(key, server_id)

    def ensure_collection_path(
        self,
        server_id: str,
        collections: list[dict[str, Any]],
        path: list[str],
    ) -> tuple[str, str]:
        parent_key: str | None = None
        taxonomy_key = ""
        for index, raw_name in enumerate(path):
            name = clean_tag_segment(raw_name)
            collection = next(
                (
                    item
                    for item in collections
                    if str(collection_data(item).get("name") or "") == name
                    and (collection_parent(item) or None) == parent_key
                ),
                None,
            )
            if not collection:
                collection = self.create_collection(server_id, name, parent_key)
                collections.append(collection)
            parent_key = collection_key(collection)
            if index == 1:
                taxonomy_key = parent_key
        return parent_key or "", taxonomy_key

    def create_document(
        self,
        server_id: str,
        *,
        title: str,
        abstract: str,
        keywords: list[str],
        tag: str | None,
        collection_key: str | None,
    ) -> dict[str, Any]:
        tags = [{"tag": keyword} for keyword in keywords if keyword.strip()]
        if tag:
            tags.append({"tag": tag})
        response = self._write(
            "POST",
            f"{BASE_URL}/users/0/items",
            server_id,
            headers={"Zotero-Write-Token": uuid.uuid4().hex},
            json=[
                {
                    "itemType": "document",
                    "title": title,
                    "abstractNote": abstract,
                    "tags": tags,
                    "collections": [collection_key] if collection_key else [],
                    "relations": {},
                }
            ],
        )
        if response.is_error:
            raise ZoteroError(_message(response, "创建 Zotero 文献条目失败"))
        key = _created_key(response, "创建 Zotero 文献条目失败")
        return self.get_item(key, server_id)

    def update_item(
        self,
        server_id: str,
        key: str,
        version: int,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._write(
            "PATCH",
            f"{BASE_URL}/users/0/items/{key}",
            server_id,
            headers={"If-Unmodified-Since-Version": str(version)},
            json=fields,
        )
        if response.is_error:
            raise ZoteroError(_message(response, "更新 Zotero 分类信息失败"))
        return self.get_item(key, server_id)

    def create_attachment(
        self, server_id: str, parent_key: str, file_path: Path, filename: str
    ) -> str:
        response = self._write(
            "POST",
            f"{BASE_URL}/users/0/items",
            server_id,
            headers={"Zotero-Write-Token": uuid.uuid4().hex},
            json=[
                {
                    "itemType": "attachment",
                    "parentItem": parent_key,
                    "linkMode": "imported_file",
                    "title": filename,
                    "contentType": "application/pdf",
                    "charset": "",
                    "filename": filename,
                    "md5": None,
                    "mtime": None,
                    "tags": [],
                    "relations": {},
                }
            ],
        )
        if response.is_error:
            raise ZoteroError(_message(response, "创建 Zotero PDF 附件失败"))
        key = _created_key(response, "创建 Zotero PDF 附件失败")
        self.upload_file(server_id, key, file_path, filename)
        return key

    def upload_file(
        self, server_id: str, attachment_key: str, file_path: Path, filename: str
    ) -> None:
        content = file_path.read_bytes()
        metadata = {
            "md5": hashlib.md5(content).hexdigest(),
            "filename": filename,
            "filesize": str(len(content)),
            "mtime": str(int(file_path.stat().st_mtime * 1000)),
        }
        url = f"{BASE_URL}/users/0/items/{attachment_key}/file"
        authorization = self._write(
            "POST",
            url,
            server_id,
            headers={"If-None-Match": "*"},
            data=metadata,
        )
        if authorization.is_error:
            raise ZoteroError(_message(authorization, "准备 Zotero PDF 上传失败"))
        payload = authorization.json()
        if payload.get("exists"):
            return
        raw_upload_url = str(payload.get("url") or "")
        upload_key = payload.get("uploadKey")
        if not raw_upload_url or not upload_key:
            raise ZoteroError("Zotero 未返回有效的 PDF 上传地址。")
        upload_url = urljoin(f"{BASE_URL}/", raw_upload_url)
        body = (
            str(payload.get("prefix") or "").encode()
            + content
            + str(payload.get("suffix") or "").encode()
        )
        upload = self.client.post(
            upload_url,
            content=body,
            headers={"Content-Type": str(payload.get("contentType") or "application/pdf")},
        )
        if upload.status_code != 201:
            raise ZoteroError(_message(upload, "上传 PDF 到 Zotero 失败"))
        registered = self._write(
            "POST",
            url,
            server_id,
            headers={"If-None-Match": "*"},
            data={"upload": upload_key},
        )
        if registered.status_code != 204:
            raise ZoteroError(_message(registered, "登记 Zotero PDF 附件失败"))


def item_data(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def item_key(item: dict[str, Any]) -> str:
    data = item_data(item)
    return str(data.get("key") or item.get("key") or "")


def collection_data(collection: dict[str, Any]) -> dict[str, Any]:
    data = collection.get("data")
    return data if isinstance(data, dict) else collection


def collection_key(collection: dict[str, Any]) -> str:
    data = collection_data(collection)
    return str(data.get("key") or collection.get("key") or "")


def collection_parent(collection: dict[str, Any]) -> str:
    return str(collection_data(collection).get("parentCollection") or "")


def find_attachment(
    parent_key: str, filename: str, attachments: list[dict[str, Any]]
) -> dict[str, Any] | None:
    expected = normalize_filename(filename)
    child_pdfs: list[dict[str, Any]] = []
    for attachment in attachments:
        data = item_data(attachment)
        if str(data.get("parentItem") or "") != parent_key:
            continue
        if data.get("contentType") == "application/pdf":
            child_pdfs.append(attachment)
        existing_name = str(data.get("filename") or data.get("title") or "")
        if expected and normalize_filename(existing_name) == expected:
            return attachment
    return next((item for item in child_pdfs if item_data(item).get("md5")), None)


def item_candidate(item: dict[str, Any], reason: str) -> dict[str, Any]:
    data = item_data(item)
    return {
        "item_key": str(data.get("key") or item.get("key") or ""),
        "title": str(data.get("title") or "未命名条目"),
        "item_type": str(data.get("itemType") or ""),
        "date": str(data.get("date") or ""),
        "version": int(data.get("version") or item.get("version") or 0),
        "match_reason": reason,
    }


def match_document(
    title: str,
    original_name: str,
    top_items: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> tuple[str, str | None, list[dict[str, Any]]]:
    usable_items = [
        item
        for item in top_items
        if item_data(item).get("itemType") not in {"note", "annotation"}
    ]
    by_key = {
        str(item_data(item).get("key") or item.get("key") or ""): item
        for item in usable_items
    }
    title_key = normalize_text(title)
    filename_key = normalize_filename(original_name)
    matched: dict[str, tuple[dict[str, Any], str]] = {}
    for item in usable_items:
        data = item_data(item)
        key = str(data.get("key") or item.get("key") or "")
        if title_key and normalize_text(str(data.get("title") or "")) == title_key:
            matched[key] = (item, "标题一致")
    for attachment in attachments:
        data = item_data(attachment)
        attachment_name = str(data.get("filename") or data.get("title") or "")
        if not filename_key or normalize_filename(attachment_name) != filename_key:
            continue
        parent_key = str(data.get("parentItem") or "")
        target = by_key.get(parent_key) or attachment
        target_data = item_data(target)
        target_key = str(target_data.get("key") or target.get("key") or "")
        matched[target_key] = (target, "附件文件名一致")
    exact = [item_candidate(item, reason) for item, reason in matched.values()]
    if len(exact) == 1:
        return "matched", exact[0]["item_key"], exact
    if exact:
        return "ambiguous", None, exact

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in usable_items:
        data = item_data(item)
        candidate_title = normalize_text(str(data.get("title") or ""))
        if not title_key or not candidate_title:
            continue
        score = SequenceMatcher(None, title_key, candidate_title).ratio()
        if score >= 0.6:
            scored.append((score, item))
    suggestions = [
        item_candidate(item, "标题相近，需人工确认")
        for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:5]
    ]
    return "unmatched", None, suggestions
