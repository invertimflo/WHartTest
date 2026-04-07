from __future__ import annotations

from pathlib import Path

import requests
from django.conf import settings


class DocxEditorClientError(RuntimeError):
    pass


def create_docx_editor_session(document, pushback_url: str) -> dict:
    base_url = str(getattr(settings, "DOCX_EDITOR_BASE_URL", "") or "").strip().rstrip("/")
    service_key = str(getattr(settings, "DOCX_EDITOR_SERVICE_KEY", "") or "").strip()
    if not base_url:
        raise DocxEditorClientError("DOCX_EDITOR_BASE_URL 未配置")
    if not service_key:
        raise DocxEditorClientError("DOCX_EDITOR_SERVICE_KEY 未配置")
    if not document.file:
        raise DocxEditorClientError("该文档没有原始文件")

    endpoint = f"{base_url}/api/integration/external-documents/upsert-and-launch"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "User-Agent": "wharttest-docx-editor-client",
    }
    data = {
        "source_system": "wharttest",
        "source_document_id": str(document.id),
        "title": document.title,
        "filename": Path(document.file.name).name,
        "pushback_url": pushback_url,
    }
    if document.updated_at:
        data["source_updated_at"] = document.updated_at.isoformat()

    content_type = (
        "application/msword"
        if document.document_type == "doc"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    with open(document.file.path, "rb") as handle:
        files = {
            "file": (
                Path(document.file.name).name,
                handle,
                content_type,
            )
        }
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise DocxEditorClientError(f"DOCX Editor 调用失败: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error") or payload.get("detail") or "").strip()
        if not detail:
            detail = (response.text or "").strip()[:1000]
        raise DocxEditorClientError(detail or f"DOCX Editor 返回异常状态码 {response.status_code}")

    if not isinstance(payload, dict):
        raise DocxEditorClientError("DOCX Editor 返回了无法识别的响应")
    if not str(payload.get("launch_url", "")).strip():
        raise DocxEditorClientError("DOCX Editor 未返回 launch_url")
    return payload
