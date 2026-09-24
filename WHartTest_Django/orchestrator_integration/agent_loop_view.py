"""
Agent Loop API 视图 (LangChain v1 重构版)

使用 LangChain v1 的 create_agent + middleware 模式，
替代原有的手动 AgentOrchestrator 循环。

核心变更：
- 使用 create_agent() 统一创建 Agent
- 使用 SummarizationMiddleware 自动处理上下文压缩
- 使用 HumanInTheLoopMiddleware 处理 HITL 审批
- 使用 LoopGuardMiddleware 检测并中止重复工具调用死循环
- 在流处理层检测工具调用，生成 step_start/step_complete 事件
- 支持 stream 参数控制流式/非流式输出
- SSE 事件格式与旧版保持兼容，前端无需修改

关于节点名（langchain v1）：
`create_agent()` 生成的图节点为 `model` / `tools`（LangChain v1 迁移指南明确
将流式节点名从 `agent` 改为 `model`）。此处统一用 `MODEL_NODE_NAMES` 兼容两代命名，
并在 Agent 创建后打印实际节点名，避免上游版本变动导致 step 事件静默失效。
"""

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from django.http import StreamingHttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from asgiref.sync import sync_to_async

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError
from wharttest_django.checkpointer import get_async_checkpointer

from .middleware_config import (
    get_middleware_from_config,
    get_model_tier,
    get_user_tool_approvals,
    get_user_friendly_llm_error,
)
from .loop_guard import (
    LOOP_GUARD_ABORT,
    LOOP_GUARD_MARKER,
    LOOP_GUARD_WARN,
    MODEL_NODE_NAMES,
    TOOL_NODE_NAME,
    ToolStep,
    _get_env_float,
    _get_env_int,
    content_digest,
    count_trailing_repeats,
    get_loop_guard_bus,
    load_loop_guard_config,
    step_signatures,
    truncate_tool_content,
)
from .playwright_instructions import PLAYWRIGHT_SCRIPT_INSTRUCTION
from .stop_signal import should_stop, clear_stop_signal
from langgraph_integration.models import ChatSession, LLMConfig
from langgraph_integration.views import (
    _extract_requirement_doc_images_for_message,
    create_llm_instance,
    create_sse_data,
    get_effective_system_prompt_async,
    check_project_permission,
    schedule_auto_summarize_session_title,
)
from projects.models import Project
from prompts.models import UserPrompt
from mcp_tools.models import RemoteMCPConfig
from mcp_tools.persistent_client import mcp_session_manager
from file_management.services import validate_file_ids, build_llm_attachment_context, sync_file_references
from file_management.models import FileReference
from requirements.context_limits import (
    MODEL_CONTEXT_LIMITS,
    context_checker,
    get_context_limit_from_llm,
)

logger = logging.getLogger(__name__)


def _build_sse_error_event(exc: Exception) -> Dict[str, Any]:
    friendly_error = get_user_friendly_llm_error(exc)
    if friendly_error:
        event = {
            "type": "error",
            "message": friendly_error["message"],
            "code": friendly_error["status_code"],
            "error_code": friendly_error["error_code"],
            "errors": friendly_error["errors"],
        }
        if friendly_error.get("model"):
            event["model"] = friendly_error["model"]
        if friendly_error.get("reset_time"):
            event["retry_after"] = friendly_error["reset_time"]
        if friendly_error.get("reset_seconds") is not None:
            event["retry_after_seconds"] = friendly_error["reset_seconds"]
        return event

    return {"type": "error", "message": f"执行错误: {str(exc)}", "code": 500}


# ============== 循环守卫辅助函数 ==============


def _build_loop_abort_error_event(
    *, tool: Optional[str], count: int, message: str
) -> Dict[str, Any]:
    """构造「检测到工具调用死循环并自动中止」的 SSE error 事件。

    复用既有 `error` 事件类型，前端无需改动即可渲染为一条 AI 说明气泡。
    """
    return {
        "type": "error",
        "message": message,
        "code": 409,
        "error_code": "tool_call_loop",
        "tool": tool,
        "repeat_count": count,
        "errors": {"detail": [message], "error_code": "tool_call_loop"},
    }


def _build_recursion_limit_error_event(
    *, recursion_limit: int, step_count: int
) -> Dict[str, Any]:
    """构造 recursion_limit 触顶的友好 SSE error 事件"""
    message = (
        f"本次任务因反复调用工具达到执行步数上限（{recursion_limit}）已自动终止。"
        "建议缩小需求范围、拆分任务后重试，或检查是否存在工具参数不合理导致的重复调用。"
    )
    return {
        "type": "error",
        "message": message,
        "code": 409,
        "error_code": "recursion_limit",
        "recursion_limit": recursion_limit,
        "step": step_count,
        "errors": {"detail": [message], "error_code": "recursion_limit"},
    }


def _cli_tool_names(tool_calls: Any) -> List[str]:
    names: List[str] = []
    for tool_call in tool_calls or []:
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
        else:
            name = getattr(tool_call, "name", None)
        names.append(str(name or "unknown"))
    return names


def _is_streamable_token(token: Any, metadata: Any) -> bool:
    """
    判断 messages 流中的 token 是否应下发给前端。

    过滤三类 token：
    1) 空内容
    2) 非模型节点产出（tools 节点回显 / 中间件注入节点）
    3) 循环守卫注入的纠偏与中止消息（已通过 warning / error 事件单独呈现，避免重复展示）
    """
    if not getattr(token, "content", None):
        return False

    node_name = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
    if isinstance(node_name, str):
        if node_name not in MODEL_NODE_NAMES:
            return False
    elif "ToolMessage" in type(token).__name__:
        # 兼容 metadata 缺失的旧版本
        return False

    additional_kwargs = getattr(token, "additional_kwargs", None) or {}
    if isinstance(additional_kwargs, dict) and additional_kwargs.get(
        LOOP_GUARD_MARKER
    ):
        return False

    return True


def _limit_sse_tool_output(content: Any, summary: str) -> tuple[Any, str]:
    """限制 tool_result 事件下发给前端的正文长度，避免大 JSON 阻塞浏览器"""
    if isinstance(content, str) and len(content) > _MAX_SSE_TOOL_OUTPUT_CHARS:
        return (
            content[:_MAX_SSE_TOOL_OUTPUT_CHARS]
            + f"\n...[已截断，共 {len(content)} 字符]",
            summary,
        )
    return content, summary


def _drain_loop_guard_events(session_id: str) -> List[Dict[str, Any]]:
    """取出并在日志中记录本会话的循环守卫事件"""
    events = get_loop_guard_bus().drain(session_id)
    for event in events:
        logger.warning(
            "[LoopGuard] action=%s session_id=%s tool=%s repeat_count=%s",
            event.get("kind"),
            session_id,
            event.get("tool"),
            event.get("count"),
        )
    return events


# ============== 统一响应辅助函数 ==============


def api_success_response(
    message: str, data: Any = None, code: int = 200
) -> JsonResponse:
    """构建统一格式的成功响应"""
    return JsonResponse(
        {
            "status": "success",
            "code": code,
            "message": message,
            "data": data,
            "errors": None,
        },
        json_dumps_params={"ensure_ascii": False},
    )


def api_error_response(
    message: str, code: int = 400, errors: Any = None
) -> JsonResponse:
    """构建统一格式的错误响应"""
    if errors is None:
        errors = {"detail": [message]}
    return JsonResponse(
        {
            "status": "error",
            "code": code,
            "message": message,
            "data": None,
            "errors": errors,
        },
        status=code,
        json_dumps_params={"ensure_ascii": False},
    )


_MARKDOWN_IMAGE_URL_RE = re.compile(
    r"!\[[^\]]*?\]\((?P<url>https?://[^)\s]+)\)", re.IGNORECASE
)
_PLAIN_HTTP_URL_RE = re.compile(r'(?P<url>https?://[^\s<>"\']+)', re.IGNORECASE)
_URL_LEADING_WRAP_CHARS = "([<{\"'“‘（【《「『"
_URL_TRAILING_WRAP_CHARS = ")]}>\"'”’）】》」』.,;!?，。；！？、"
_URL_HARD_STOP_CHARS = "\r\n\t ,;)}]>\"'，。；！？、：”’）】》」』"

# `_get_env_int` / `_get_env_float` 已统一收敛到 loop_guard 模块，此处沿用同一实现。


def _normalize_uploaded_image_base64_list(
    raw_images: Any, raw_image: Any = None
) -> List[str]:
    """兼容旧 image 字段与新 images 数组，返回去重后的上传图片列表。"""

    normalized: List[str] = []

    def _append(candidate: Any) -> None:
        if not isinstance(candidate, str):
            return
        value = candidate.strip()
        if not value or value in normalized:
            return
        normalized.append(value)

    if isinstance(raw_images, list):
        for item in raw_images:
            _append(item)
    else:
        _append(raw_images)

    _append(raw_image)
    return normalized


_LINKED_IMAGE_URL_ALLOWLIST = {
    host.strip().lower()
    for host in os.getenv("AGENT_LOOP_IMAGE_URL_ALLOWLIST", "*").split(",")
    if host.strip()
}
_MAX_LINKED_IMAGES_PER_REQUEST = _get_env_int(
    "AGENT_LOOP_MAX_LINKED_IMAGES", 3, min_value=1
)
_MAX_LINKED_IMAGE_BYTES = _get_env_int(
    "AGENT_LOOP_MAX_LINKED_IMAGE_BYTES", 5 * 1024 * 1024, min_value=1024
)
_LINKED_IMAGE_FETCH_TIMEOUT = _get_env_float(
    "AGENT_LOOP_LINKED_IMAGE_FETCH_TIMEOUT", 8.0, min_value=1.0
)
_MAX_SAFE_TOOL_MESSAGE_CHARS = _get_env_int(
    "AGENT_LOOP_MAX_SAFE_TOOL_MESSAGE_CHARS", 20000, min_value=1000
)
# ToolMessage 截断策略：保留头尾而非整体替换为占位符，
# 避免模型因「看不到工具结果」而重复调用同一工具。
_TOOL_TRUNCATE_ENABLED = (
    os.getenv("AGENT_LOOP_TOOL_TRUNCATE_ENABLED", "1").strip().lower()
    in ("1", "true", "yes", "on")
)
_TOOL_TRUNCATE_HEAD_RATIO = min(
    0.9, _get_env_float("AGENT_LOOP_TOOL_TRUNCATE_HEAD_RATIO", 0.6, min_value=0.1)
)
# tool_result SSE 事件下发给前端的 tool_output 上限（避免大 JSON 打到浏览器）
_MAX_SSE_TOOL_OUTPUT_CHARS = load_loop_guard_config().max_sse_tool_output_chars

# ============== 弱模型 Agent Loop 调优（issue.md）==============
# 弱模型（短上下文、工具调用准确率低）需更短的循环步数上限与更激进的 ToolMessage 截断，
# 避免长循环撑爆上下文、provider 重试与前端逐 token 渲染卡死。
_WEAK_MODEL_RECURSION_LIMIT = _get_env_int(
    "AGENT_LOOP_WEAK_RECURSION_LIMIT", 160, min_value=20
)
_STRONG_MODEL_RECURSION_LIMIT = _get_env_int(
    "AGENT_LOOP_STRONG_RECURSION_LIMIT", 1000, min_value=20
)
_WEAK_MODEL_TOOL_MESSAGE_CHARS = _get_env_int(
    "AGENT_LOOP_WEAK_TOOL_MESSAGE_CHARS", 6000, min_value=1000
)


def _extract_linked_image_urls(text: str) -> List[str]:
    """从用户消息中提取图片 URL（支持 Markdown 图片语法和纯 URL）。"""
    if not text:
        return []

    urls: List[str] = []
    seen: set[str] = set()

    def _normalize_url(candidate: str) -> str:
        url = (candidate or "").strip()
        while url and url[0] in _URL_LEADING_WRAP_CHARS:
            url = url[1:]
        hard_stop_indexes = [
            url.find(char) for char in _URL_HARD_STOP_CHARS if char in url
        ]
        if hard_stop_indexes:
            url = url[: min(index for index in hard_stop_indexes if index >= 0)]
        while url and url[-1] in _URL_TRAILING_WRAP_CHARS:
            url = url[:-1]
        return url

    for pattern in (_MARKDOWN_IMAGE_URL_RE, _PLAIN_HTTP_URL_RE):
        for match in pattern.finditer(text):
            url = _normalize_url(match.group("url") or "")
            if not url or url in seen:
                continue

            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            if parsed.scheme.lower() not in ("http", "https"):
                continue
            if not parsed.netloc:
                continue

            seen.add(url)
            urls.append(url)

    return urls


def _is_linked_image_url_allowed(url: str) -> bool:
    """校验图片 URL 是否在允许的 host 白名单中（支持 * 全放开）。"""
    if "*" in _LINKED_IMAGE_URL_ALLOWLIST or "all" in _LINKED_IMAGE_URL_ALLOWLIST:
        return True

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().lower()
    return bool(host and host in _LINKED_IMAGE_URL_ALLOWLIST)


async def _download_linked_image_as_data_url(url: str) -> Optional[str]:
    """下载图片 URL 并转为 data URL，供视觉模型消费。"""
    if not _is_linked_image_url_allowed(url):
        logger.warning(
            "AgentLoopStreamAPI: Skip linked image URL not in allowlist. url=%s, allowlist=%s",
            url,
            sorted(_LINKED_IMAGE_URL_ALLOWLIST),
        )
        return None

    timeout = httpx.Timeout(
        _LINKED_IMAGE_FETCH_TIMEOUT, connect=_LINKED_IMAGE_FETCH_TIMEOUT
    )
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream(
                "GET", url, headers={"Accept": "image/*"}
            ) as response:
                response.raise_for_status()
                content_type = (
                    (response.headers.get("Content-Type") or "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                if not content_type.startswith("image/"):
                    logger.warning(
                        "AgentLoopStreamAPI: Skip linked URL with non-image content-type. url=%s, content_type=%s",
                        url,
                        content_type or "unknown",
                    )
                    return None

                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    if len(data) + len(chunk) > _MAX_LINKED_IMAGE_BYTES:
                        logger.warning(
                            "AgentLoopStreamAPI: Skip linked image over size limit. url=%s, max_bytes=%s",
                            url,
                            _MAX_LINKED_IMAGE_BYTES,
                        )
                        return None
                    data.extend(chunk)

                if not data:
                    logger.warning(
                        "AgentLoopStreamAPI: Skip empty linked image response. url=%s",
                        url,
                    )
                    return None

                encoded = base64.b64encode(bytes(data)).decode("utf-8")
                return f"data:{content_type};base64,{encoded}"
    except Exception as e:
        logger.warning(
            "AgentLoopStreamAPI: Failed to fetch linked image url=%s, error=%s", url, e
        )
        return None


async def _collect_linked_image_data_urls(
    user_message: str,
    linked_urls: Optional[List[str]] = None,
) -> List[str]:
    """从用户消息 URL 中收集可用图片，并转换为 data URL 列表。"""
    if linked_urls is None:
        linked_urls = _extract_linked_image_urls(user_message)
    if not linked_urls:
        return []

    limited_urls = linked_urls[:_MAX_LINKED_IMAGES_PER_REQUEST]
    if len(linked_urls) > len(limited_urls):
        logger.info(
            "AgentLoopStreamAPI: Truncated linked image URLs from %s to %s",
            len(linked_urls),
            len(limited_urls),
        )

    download_tasks = [_download_linked_image_as_data_url(url) for url in limited_urls]
    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    data_urls: List[str] = []
    for url, result in zip(limited_urls, results):
        if isinstance(result, Exception):
            logger.warning(
                "AgentLoopStreamAPI: Linked image download task failed. url=%s, error=%s",
                url,
                result,
            )
            continue
        if result:
            data_urls.append(result)

    return data_urls


async def _prepare_agent_loop_human_message(
    user_message: str,
    *,
    project: Project,
    supports_vision: bool,
    uploaded_images_base64: Optional[List[str]] = None,
) -> tuple[Any, Dict[str, Any], str]:
    """
    规范化 Agent Loop 的用户消息。

    - 将需求文档中的 `docimg://` 占位符替换为可访问的 `/api/.../images/...` URL
    - 当模型支持视觉时，把需求文档图片与普通 HTTP(S) 图片一并转成多模态输入
    - 返回：LangChain HumanMessage content、additional_kwargs、展示用文本
    """
    display_message = (user_message or "").strip()
    uploaded_images_base64 = uploaded_images_base64 or []

    (
        display_message,
        requirement_doc_image_data_urls,
        requirement_document_id,
    ) = await _extract_requirement_doc_images_for_message(display_message, project)

    if requirement_doc_image_data_urls and not supports_vision:
        logger.warning(
            "AgentLoopStreamAPI: Requirement document images detected but current model does not support vision"
        )

    linked_image_data_urls: List[str] = []
    linked_image_urls = _extract_linked_image_urls(display_message)
    if linked_image_urls:
        logger.info(
            "AgentLoopStreamAPI: Extracted %s candidate linked image URLs from message",
            len(linked_image_urls),
        )
        if supports_vision:
            linked_image_data_urls = await _collect_linked_image_data_urls(
                display_message,
                linked_urls=linked_image_urls,
            )
            if linked_image_data_urls:
                logger.info(
                    "AgentLoopStreamAPI: Loaded %s linked images for multimodal input",
                    len(linked_image_data_urls),
                )
        else:
            logger.warning(
                "AgentLoopStreamAPI: Found %s linked image URLs but current model does not support vision",
                len(linked_image_urls),
            )
    elif "http://" in display_message.lower() or "https://" in display_message.lower():
        logger.warning(
            "AgentLoopStreamAPI: Message contains URL text but extractor found 0 valid URLs"
        )

    multimodal_image_data_urls = requirement_doc_image_data_urls + linked_image_data_urls

    additional_kwargs: Dict[str, Any] = {}
    if requirement_document_id:
        additional_kwargs["requirement_document_id"] = requirement_document_id
        if requirement_doc_image_data_urls:
            additional_kwargs["image_source"] = "requirement_document"

    if supports_vision and (uploaded_images_base64 or multimodal_image_data_urls):
        human_message_content: Any = [{"type": "text", "text": display_message}]
        for data_url in multimodal_image_data_urls:
            human_message_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                }
            )
        for image_base64 in uploaded_images_base64:
            human_message_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                }
            )
    else:
        human_message_content = display_message

    return human_message_content, additional_kwargs, display_message


def process_mcp_tool_output(content: Any) -> tuple:
    """
    处理 MCP 工具返回的内容，提取实际数据并生成摘要

    Args:
        content: 工具返回的原始内容

    Returns:
        tuple: (processed_content, summary)
    """
    # 处理 MCP 工具返回的列表格式，提取 text 内容
    if isinstance(content, list) and len(content) == 1:
        first_item = content[0]
        if isinstance(first_item, dict) and first_item.get("type") == "text":
            text_content = first_item.get("text")
            if text_content is not None:
                content = text_content
            # text 为 None 或空时保留原始列表格式

    # 确保 content 可序列化
    if content is None:
        content = ""
    elif not isinstance(content, (str, dict, list, int, float, bool)):
        content = str(content)

    # 生成摘要
    if isinstance(content, str):
        summary = content[:200]
    else:
        try:
            summary = json.dumps(content, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            summary = str(content)[:200]

    return content, summary


_BINARY_IMAGE_CONTENT_RE = re.compile(r"data:image/(?P<mime>[\w.+-]+);base64,")


def _describe_binary_image_content(content: str) -> str:
    """把纯图片/base64 内容替换为结构化占位符（保留 mime 与体积信息）"""
    match = _BINARY_IMAGE_CONTENT_RE.search(content)
    mime = match.group("mime") if match else "unknown"
    approx_kb = max(1, len(content) // 1024)
    return (
        f"[工具返回图片数据，已省略: mime=image/{mime}, 约 {approx_kb} KB；"
        "如需图片请改用附件下载或截图上传接口]"
    )


def _sanitize_tool_message_content(msg: ToolMessage, safe_chars: int) -> Tuple[str, str]:
    """
    规范化单条 ToolMessage 的内容。

    返回 (new_content, action)，action ∈ {"ok", "truncated", "binary", "invalid"}。

    与旧实现的关键差异：超长文本不再整体替换为占位符，而是保留头尾关键信息。
    原实现会让模型完全看不到工具结果，从而反复重试同一调用（死循环的正反馈来源）。
    """
    content = getattr(msg, "content", None)
    if content is None or not isinstance(content, str):
        return "", "invalid"
    if not content:
        return content, "ok"
    # 纯图片/base64：文本形态对模型无用，整体替换但保留结构化信息
    if _BINARY_IMAGE_CONTENT_RE.search(content) and len(content) > safe_chars:
        return _describe_binary_image_content(content), "binary"
    if _TOOL_TRUNCATE_ENABLED and len(content) > safe_chars:
        return (
            truncate_tool_content(content, safe_chars, _TOOL_TRUNCATE_HEAD_RATIO),
            "truncated",
        )
    return content, "ok"


def _build_sanitized_messages(
    messages: List[Any], tool_message_chars: int = _MAX_SAFE_TOOL_MESSAGE_CHARS
) -> tuple[List[Any], int, Dict[str, int]]:
    """
    构建合法的消息列表：
    1) 为缺失 ToolMessage 响应的 tool_call 插入占位 ToolMessage
    2) 清理悬空的 ToolMessage（无匹配 tool_call）
    3) 修复有问题的 ToolMessage（content 非字符串 / 过长 / 含 base64）

    Args:
        messages: 原始消息列表
        tool_message_chars: ToolMessage 内容安全上限（弱模型下调以更早截断大输出）

    返回 (clean_messages, fix_count, stats)
        stats 形如 {"truncated": n, "binary": n, "invalid": n}，供日志观测。
    """
    result: List[Any] = []
    fix_count = 0
    stats: Dict[str, int] = {"truncated": 0, "binary": 0, "invalid": 0}

    safe_chars = max(1000, int(tool_message_chars or _MAX_SAFE_TOOL_MESSAGE_CHARS))

    # 当前 pending 的 tool_call IDs 及其工具名
    pending_call_ids: List[str] = []
    pending_call_names: Dict[str, str] = {}

    def _flush_pending() -> None:
        nonlocal fix_count
        for tc_id in pending_call_ids:
            result.append(
                ToolMessage(
                    content="[Tool execution was interrupted]",
                    tool_call_id=tc_id,
                    name=pending_call_names.get(tc_id, "unknown"),
                )
            )
            fix_count += 1
        pending_call_ids.clear()
        pending_call_names.clear()

    for msg in messages:
        # 带 tool_calls 的 AIMessage
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            _flush_pending()
            result.append(msg)

            for tc in msg.tool_calls:
                tc_id = (
                    tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                )
                tc_name = (
                    tc.get("name")
                    if isinstance(tc, dict)
                    else getattr(tc, "name", None)
                )
                if tc_id:
                    tc_id = str(tc_id)
                    pending_call_ids.append(tc_id)
                    pending_call_names[tc_id] = tc_name or "unknown"
            continue

        # ToolMessage 消息
        if isinstance(msg, ToolMessage):
            tc_id = str(getattr(msg, "tool_call_id", "") or "")
            if tc_id in pending_call_ids:
                pending_call_ids.remove(tc_id)
                new_content, action = _sanitize_tool_message_content(msg, safe_chars)
                if action == "ok":
                    result.append(msg)
                elif action == "invalid":
                    result.append(
                        ToolMessage(
                            content=new_content
                            or "[Tool output removed: content was not a string]",
                            tool_call_id=tc_id,
                            name=getattr(msg, "name", None)
                            or pending_call_names.get(tc_id, "unknown"),
                        )
                    )
                    stats["invalid"] += 1
                    fix_count += 1
                else:
                    # 超长文本 / 图片数据：保留可读信息后覆写
                    result.append(
                        ToolMessage(
                            content=new_content,
                            tool_call_id=tc_id,
                            name=getattr(msg, "name", None)
                            or pending_call_names.get(tc_id, "unknown"),
                        )
                    )
                    stats[action] = stats.get(action, 0) + 1
                    fix_count += 1
            else:
                # 悬空 ToolMessage，丢弃
                fix_count += 1
            continue

        # 其他消息类型
        _flush_pending()
        result.append(msg)

    _flush_pending()
    return result, fix_count, stats


async def _sanitize_history_before_model_call(
    agent: Any,
    invoke_config: Dict[str, Any],
    log_prefix: str,
    tool_message_chars: int = _MAX_SAFE_TOOL_MESSAGE_CHARS,
) -> Dict[str, Any]:
    """
    统一历史修复入口：读取状态，构建合法消息列表，若有修复则用 REMOVE_ALL + 完整列表覆写。

    Args:
        tool_message_chars: ToolMessage 内容安全上限（弱模型下调）
    """
    try:
        current_state = await agent.aget_state(invoke_config)
    except Exception as e:
        logger.warning("%s: Failed to load state for sanitize: %s", log_prefix, e)
        return {"removed_count": 0, "sanitized": False}

    values = (
        current_state.values
        if hasattr(current_state, "values") and current_state.values
        else {}
    )
    messages = values.get("messages", []) if isinstance(values, dict) else []
    if not messages:
        return {"removed_count": 0, "sanitized": False}

    clean_msgs, fix_count, stats = _build_sanitized_messages(
        messages, tool_message_chars
    )
    if fix_count == 0:
        return {"removed_count": 0, "sanitized": False}

    # 用 REMOVE_ALL + 完整干净列表替换状态
    update_payload = [RemoveMessage(id="__remove_all__"), *clean_msgs]

    available_nodes = list(getattr(agent, "nodes", {}).keys())
    preferred_nodes = [n for n in ("model", "agent", "tools") if n in available_nodes]
    if available_nodes and available_nodes[0] not in preferred_nodes:
        preferred_nodes.append(available_nodes[0])
    preferred_nodes.append(None)

    success = False
    last_error: Optional[Exception] = None
    for as_node in preferred_nodes:
        try:
            if as_node is None:
                await agent.aupdate_state(invoke_config, {"messages": update_payload})
            else:
                await agent.aupdate_state(
                    invoke_config, {"messages": update_payload}, as_node=as_node
                )
            success = True
            logger.info(
                "%s: Sanitized history via REMOVE_ALL, fixed %d issues "
                "(truncated=%d, binary=%d, invalid=%d), %d clean messages (as_node=%s)",
                log_prefix,
                fix_count,
                stats.get("truncated", 0),
                stats.get("binary", 0),
                stats.get("invalid", 0),
                len(clean_msgs),
                as_node or "auto",
            )
            break
        except Exception as e:
            last_error = e

    if not success:
        logger.error(
            "%s: Failed to sanitize history. fix_count=%d, available_nodes=%s, error=%s",
            log_prefix,
            fix_count,
            available_nodes,
            last_error,
        )
        return {"removed_count": 0, "sanitized": False}

    return {"removed_count": fix_count, "sanitized": True}


def calculate_context_tokens(
    messages: List[Any],
    model_name: str = "gpt-4o",
    tools: Optional[list] = None,
    system_prompt: Optional[str] = None,
) -> tuple[int, int, int]:
    """
    计算当前上下文 Token

    优先使用最后一条带 usage_metadata 的消息；
    如果 provider 未返回 usage_metadata，则回退到内容估算 + 真实开销。

    Args:
        messages: 消息列表
        model_name: 模型名称
        tools: 工具对象列表，用于精确计算开销
        system_prompt: 系统提示词，用于精确计算开销
    """
    # 1) 优先使用 usage_metadata（最准确）
    for msg in reversed(messages):
        if hasattr(msg, "usage_metadata") and msg.usage_metadata:
            usage = msg.usage_metadata
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            total_tokens = usage.get("total_tokens", 0) or (
                input_tokens + output_tokens
            )

            if total_tokens > 0:
                return input_tokens, output_tokens, total_tokens

    # 2) 回退到内容估算 + 真实开销（避免 context_update 始终为 0）
    from orchestrator_integration.middleware_config import _calculate_overhead_tokens

    overhead = _calculate_overhead_tokens(model_name, tools, system_prompt)

    content_tokens = 0
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            content_tokens += context_checker.count_tokens(content, model_name)

    estimated_total = content_tokens + overhead
    return 0, 0, estimated_total


def _is_unreliable_default_detected_limit(
    model_name: str, detected_limit: Optional[int]
) -> bool:
    """
    判断检测上限是否仅来自未知模型的默认回退值（如 128000）。
    该场景下应优先信任用户配置的 context_limit。
    """
    if not isinstance(detected_limit, int) or detected_limit <= 0:
        return False

    default_limit = int(MODEL_CONTEXT_LIMITS.get("default", 128000))
    if detected_limit != default_limit:
        return False

    normalized_name = (model_name or "").lower()
    for model_key in MODEL_CONTEXT_LIMITS.keys():
        if model_key == "default":
            continue
        if model_key in normalized_name:
            return False

    return True


def resolve_runtime_context_limit(
    config_context_limit: Optional[int], llm, model_name: str
) -> int:
    """
    运行时上下文限制（与 middleware_config 保持一致，用户优先）：
    - 用户配置存在时：直接使用 config
    - 无 config 时：profile > 可靠 detected > 默认值
    """
    config_limit = (
        config_context_limit
        if isinstance(config_context_limit, int) and config_context_limit > 0
        else None
    )
    detected_limit = (
        get_context_limit_from_llm(llm, fallback_model_name=model_name)
        if llm is not None
        else None
    )

    profile_limit = None
    if llm is not None:
        profile = getattr(llm, "profile", None)
        if isinstance(profile, dict):
            max_input_tokens = profile.get("max_input_tokens")
            if isinstance(max_input_tokens, int) and max_input_tokens > 0:
                profile_limit = max_input_tokens

    unreliable_detected_limit = _is_unreliable_default_detected_limit(
        model_name, detected_limit
    )

    if config_limit:
        return config_limit

    if profile_limit:
        return profile_limit

    if (
        isinstance(detected_limit, int)
        and detected_limit > 0
        and not unreliable_detected_limit
    ):
        return detected_limit

    return 128000


@method_decorator(csrf_exempt, name="dispatch")
class AgentLoopStreamAPIView(View):
    """
    Agent Loop 聊天 API (LangChain v1 重构版)

    核心特性：
    - 使用 create_agent() 统一创建 Agent
    - SummarizationMiddleware 自动上下文压缩
    - HumanInTheLoopMiddleware 处理 HITL 审批
    - 在流处理层检测工具调用生成步骤事件
    - 支持 stream 参数：
      - stream=true (默认)：返回 SSE 流式响应
      - stream=false：返回普通 JSON 响应
    """

    # 前端展示的步数上限由 `recursion_limit // 2` 动态推导（见 max_steps_display），
    # 不再使用固定常量，避免与模型分层配置、前端兜底值三者不一致。

    def _update_session_token_usage(
        self, session_id: str, input_tokens: int, output_tokens: int,
        cache_read_tokens: int = 0, user_id=None, project_id=None,
    ):
        """更新会话的 Token 使用统计，同时写入独立的 TokenUsageRecord"""
        try:
            from django.db.models import F
            from django.utils import timezone

            ChatSession.objects.filter(session_id=session_id).update(
                total_input_tokens=F("total_input_tokens") + input_tokens,
                total_output_tokens=F("total_output_tokens") + output_tokens,
                total_tokens=F("total_tokens") + input_tokens + output_tokens,
                total_cache_read_tokens=F("total_cache_read_tokens") + cache_read_tokens,
                request_count=F("request_count") + 1,
                updated_at=timezone.now(),
            )
        except Exception as e:
            logger.warning(f"Failed to update session token usage: {e}")

        # 写入独立记录（不随会话删除而丢失）
        try:
            from langgraph_integration.models import TokenUsageRecord

            TokenUsageRecord.objects.create(
                user_id=user_id,
                project_id=project_id,
                session_id=session_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_read_tokens=cache_read_tokens,
            )
        except Exception as e:
            logger.warning(f"Failed to create TokenUsageRecord: {e}")

    async def authenticate_request(self, request):
        """JWT 认证"""
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Authentication credentials were not provided.")

        token = auth_header.split(" ")[1]
        jwt_auth = JWTAuthentication()

        try:
            validated_token = await sync_to_async(jwt_auth.get_validated_token)(token)
            user = await sync_to_async(jwt_auth.get_user)(validated_token)
            return user
        except Exception as e:
            raise AuthenticationFailed(f"Invalid token: {str(e)}")

    async def _create_stream_generator(
        self,
        request,
        user_message: str,
        session_id: str,
        project_id: str,
        project: Project,
        knowledge_base_id: Optional[int] = None,
        use_knowledge_base: bool = True,
        prompt_id: Optional[int] = None,
        uploaded_images_base64: Optional[List[str]] = None,
        generate_playwright_script: bool = False,
        test_case_id: Optional[int] = None,
        use_pytest: bool = True,
        file_ids: Optional[List[int]] = None,
    ):
        """
        创建 SSE 流式生成器（LangChain v1 重构版）

        使用 create_agent + astream 模式，替代旧的 AgentOrchestrator 循环。
        通过检测 updates 流中的工具调用来生成 step_start/step_complete 事件。
        """
        thread_id = f"{request.user.id}_{project_id}_{session_id}"
        file_ids = file_ids or []
        try:
            attached_files = await sync_to_async(validate_file_ids)(file_ids, project, request.user)
            llm_attachment_context = await sync_to_async(build_llm_attachment_context)(attached_files)
            if file_ids:
                await sync_to_async(sync_file_references)(file_ids, project, FileReference.REF_LLM_CHAT, session_id, request.user)
        except Exception as exc:
            yield create_sse_data({"type": "error", "message": f"附件校验失败: {exc}"})
            return

        # 1. 获取 LLM 配置
        try:
            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            logger.info(f"AgentLoopStreamAPI: Using LLM config: {active_config.name}")
            context_limit = active_config.context_limit or 128000
            model_name = active_config.name or "gpt-4o"
        except LLMConfig.DoesNotExist:
            yield create_sse_data(
                {"type": "error", "message": "No active LLM configuration found"}
            )
            return

        # 模型能力分层：弱模型缩短循环步数上限并更激进地截断 ToolMessage
        model_tier = get_model_tier(active_config)
        is_weak_model = model_tier == "weak"
        recursion_limit = (
            _WEAK_MODEL_RECURSION_LIMIT
            if is_weak_model
            else _STRONG_MODEL_RECURSION_LIMIT
        )
        tool_message_chars = (
            _WEAK_MODEL_TOOL_MESSAGE_CHARS if is_weak_model else _MAX_SAFE_TOOL_MESSAGE_CHARS
        )
        # 每轮工具调用消耗 2 个 superstep（model + tools），用于前端展示步数上限。
        # 与 step_start 事件、start 事件共用同一取值，避免三处不一致。
        max_steps_display = max(1, recursion_limit // 2)
        loop_guard_config = load_loop_guard_config()
        logger.info(
            "AgentLoopStreamAPI: model_tier=%s, recursion_limit=%d, max_steps=%d, "
            "tool_message_chars=%d, loop_guard(enabled=%s, warn=%d, abort=%d, window=%d)",
            model_tier,
            recursion_limit,
            max_steps_display,
            tool_message_chars,
            loop_guard_config.enabled,
            loop_guard_config.warn,
            loop_guard_config.abort,
            loop_guard_config.window,
        )

        # 2. 验证多模态支持
        if uploaded_images_base64 and not active_config.supports_vision:
            yield create_sse_data(
                {
                    "type": "error",
                    "message": f"模型 {active_config.name} 不支持图片输入",
                }
            )
            return

        try:
            # 3. 初始化 LLM
            llm = await sync_to_async(create_llm_instance)(
                active_config, temperature=0.7
            )
            context_limit = resolve_runtime_context_limit(
                active_config.context_limit, llm, model_name
            )

            # 4. 加载 MCP 工具
            tools: List[Any] = []
            try:
                active_mcp_configs = await sync_to_async(list)(
                    RemoteMCPConfig.objects.filter(is_active=True)
                )
                if active_mcp_configs:
                    client_config = {}
                    for cfg in active_mcp_configs:
                        key = cfg.name or f"remote_{cfg.id}"
                        client_config[key] = {
                            "url": cfg.url,
                            "transport": (cfg.transport or "streamable_http").replace(
                                "-", "_"
                            ),
                        }
                        if cfg.headers:
                            client_config[key]["headers"] = cfg.headers

                    if client_config:
                        mcp_tools = await mcp_session_manager.get_tools_for_config(
                            client_config,
                            user_id=str(request.user.id),
                            project_id=str(project_id),
                            session_id=session_id,
                        )
                        tools.extend(mcp_tools)
                        logger.info(
                            f"AgentLoopStreamAPI: Loaded {len(mcp_tools)} MCP tools"
                        )
                        yield create_sse_data(
                            {
                                "type": "info",
                                "message": f"已加载 {len(mcp_tools)} 个工具",
                            }
                        )
            except Exception as e:
                logger.error(
                    f"AgentLoopStreamAPI: MCP tools loading failed: {e}", exc_info=True
                )
                yield create_sse_data(
                    {"type": "warning", "message": f"MCP 工具加载失败: {str(e)}"}
                )

            # 5. 添加知识库工具
            logger.info(
                f"AgentLoopStreamAPI: 检查知识库工具 - knowledge_base_id={knowledge_base_id}, use_knowledge_base={use_knowledge_base}"
            )
            if knowledge_base_id and use_knowledge_base:
                try:
                    from knowledge.langgraph_integration import create_knowledge_tool

                    logger.info(f"AgentLoopStreamAPI: 正在创建知识库工具...")
                    kb_tool = await sync_to_async(create_knowledge_tool)(
                        knowledge_base_id=knowledge_base_id, user=request.user
                    )
                    tools.append(kb_tool)
                    logger.info(
                        f"AgentLoopStreamAPI: ✅ 知识库工具已添加: {kb_tool.name}"
                    )
                except Exception as e:
                    logger.warning(
                        f"AgentLoopStreamAPI: ❌ Knowledge tool creation failed: {e}",
                        exc_info=True,
                    )
            else:
                logger.info(
                    f"AgentLoopStreamAPI: ⚠️ 跳过知识库工具 (knowledge_base_id={knowledge_base_id}, use_knowledge_base={use_knowledge_base})"
                )

            # 6. 添加内置工具（Playwright 脚本管理等）
            from orchestrator_integration.builtin_tools import get_builtin_tools

            builtin_tools = get_builtin_tools(
                user_id=request.user.id,
                project_id=int(project_id),
                test_case_id=test_case_id,
                chat_session_id=session_id,
            )
            tools.extend(builtin_tools)
            logger.info(f"AgentLoopStreamAPI: Added {len(builtin_tools)} builtin tools")

            # 7. 获取或创建 ChatSession（使用 get_or_create 避免竞态条件）
            prompt_obj = None
            if prompt_id:
                try:
                    prompt_obj = await sync_to_async(UserPrompt.objects.get)(
                        id=prompt_id, user=request.user, is_active=True
                    )
                except UserPrompt.DoesNotExist:
                    pass

            chat_session, created = await sync_to_async(
                ChatSession.objects.get_or_create
            )(
                session_id=session_id,
                defaults={
                    "user": request.user,
                    "project": project,
                    "prompt": prompt_obj,
                    "title": f"新对话 - {user_message[:30]}",
                },
            )
            if created:
                logger.info(
                    f"AgentLoopStreamAPI: Created new ChatSession: {session_id}"
                )

            # 8. 获取系统提示词
            effective_prompt, prompt_source = await get_effective_system_prompt_async(
                request.user, prompt_id, project
            )

            # 8.1 如果需要生成脚本，追加脚本生成指令
            if generate_playwright_script:
                effective_prompt = (
                    effective_prompt or ""
                ) + PLAYWRIGHT_SCRIPT_INSTRUCTION
                logger.info(f"AgentLoopStreamAPI: 已追加脚本生成指令")

            # 9. 构建用户消息（支持多模态：上传图片 + HTTP(S) 图片 + 需求文档图片）
            user_message_for_llm = user_message
            if llm_attachment_context:
                user_message_for_llm = user_message + "\n\n以下是用户附加文件内容，请作为本轮对话上下文使用:" + llm_attachment_context
            (
                human_message_content,
                human_message_kwargs,
                display_user_message,
            ) = await _prepare_agent_loop_human_message(
                user_message_for_llm,
                project=project,
                supports_vision=active_config.supports_vision,
                uploaded_images_base64=uploaded_images_base64,
            )
            user_msg = HumanMessage(
                content=human_message_content,
                additional_kwargs=human_message_kwargs,
            )

            # 10. 获取工具名列表用于 HITL
            tool_names = [t.name for t in tools] if tools else None

            # 11. 发送开始信号
            yield create_sse_data(
                {
                    "type": "start",
                    "session_id": session_id,
                    "thread_id": thread_id,
                    "project_id": project_id,
                    "display_message": display_user_message,
                    "mode": "agent_loop",
                    "max_steps": max_steps_display,
                    "created_at": chat_session.created_at.isoformat()
                    if chat_session and chat_session.created_at
                    else None,
                }
            )

            # 12. 创建 Agent（LangChain v1 统一路径）
            async with get_async_checkpointer() as checkpointer:
                # 获取中间件（需要同步到异步，因为内部有 ORM 查询）
                middleware = await sync_to_async(get_middleware_from_config)(
                    active_config,
                    llm,
                    user=request.user,
                    session_id=session_id,
                    all_tool_names=tool_names,
                    tools=tools,
                    system_prompt=effective_prompt,
                )

                agent = create_agent(
                    llm,
                    tools,
                    system_prompt=effective_prompt,
                    checkpointer=checkpointer,
                    middleware=middleware,
                )
                logger.info(
                    f"AgentLoopStreamAPI: Agent created with {len(tools)} tools"
                )
                # 常驻打印真实节点名，便于上游 langchain 版本变更时快速定位
                # 「step 事件静默失效」类问题（v1 节点名为 model/tools）
                logger.info(
                    "AgentLoopStreamAPI: agent nodes=%s, middleware=%s",
                    sorted(getattr(agent, "nodes", {}) or {}),
                    [type(m).__name__ for m in middleware],
                )

                # 13. 配置调用参数
                invoke_config = {
                    "configurable": {"thread_id": thread_id},
                    # 弱模型下调递归上限（约 recursion_limit/2 次工具调用），
                    # 避免工具调用准确率低导致长循环撑爆上下文
                    "recursion_limit": recursion_limit,
                }
                input_messages = {"messages": [user_msg]}

                # 13.1 发送前修复历史消息（配对错误 + 风险工具输出）
                await _sanitize_history_before_model_call(
                    agent=agent,
                    invoke_config=invoke_config,
                    log_prefix="AgentLoopStreamAPI",
                    tool_message_chars=tool_message_chars,
                )

                # 14. 步骤跟踪状态
                step_count = 0
                current_tool_calls = []
                interrupt_detected = False
                user_stopped = False

                # 14.1 死循环守卫状态
                # 主力守卫是 LoopGuardMiddleware（可注入纠偏消息并干净结束图）；
                # 这里维护一份独立的兜底计数器，即使中间件被关闭或失效也能止损。
                loop_aborted = False
                loop_abort_tool: Optional[str] = None
                loop_abort_count = 0
                loop_abort_message = ""
                fallback_steps: List[ToolStep] = []

                # 15. 流式执行
                stream_modes = ["updates", "messages"]

                # 15.1 清理上一轮可能残留的守卫事件，避免污染本轮
                _drain_loop_guard_events(session_id)

                try:
                    async for stream_mode, chunk in agent.astream(
                        input_messages, config=invoke_config, stream_mode=stream_modes
                    ):
                        # 检查用户停止信号
                        if should_stop(session_id):
                            user_stopped = True
                            clear_stop_signal(session_id)
                            logger.info(
                                f"AgentLoopStreamAPI: Stop signal received at step {step_count}"
                            )
                            yield create_sse_data(
                                {
                                    "type": "stopped",
                                    "message": "已停止生成",
                                    "step": step_count,
                                }
                            )
                            break

                        if stream_mode == "updates":
                            # 循环守卫事件（LoopGuardMiddleware 在模型调用前推送）
                            for guard_event in _drain_loop_guard_events(session_id):
                                if guard_event.get("kind") == LOOP_GUARD_ABORT:
                                    loop_aborted = True
                                    loop_abort_tool = guard_event.get("tool")
                                    loop_abort_count = int(
                                        guard_event.get("count") or 0
                                    )
                                    loop_abort_message = (
                                        guard_event.get("message") or ""
                                    )
                                elif guard_event.get("kind") == LOOP_GUARD_WARN:
                                    yield create_sse_data(
                                        {
                                            "type": "warning",
                                            "code": "loop_guard_warn",
                                            "message": guard_event.get("message")
                                            or "检测到重复工具调用，已注入纠偏提示",
                                            "tool": guard_event.get("tool"),
                                            "count": guard_event.get("count"),
                                        }
                                    )

                            # 检查中断事件 (HITL)
                            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                                interrupt_info = chunk["__interrupt__"]
                                logger.info(
                                    f"AgentLoopStreamAPI: HITL interrupt detected: {interrupt_info}"
                                )
                                logger.info(
                                    f"AgentLoopStreamAPI: interrupt_info type: {type(interrupt_info)}"
                                )

                                action_requests = []
                                interrupt_id = None
                                # 处理 tuple、list 或单个 Interrupt 对象
                                if isinstance(interrupt_info, (list, tuple)):
                                    interrupts_list = list(interrupt_info)
                                else:
                                    interrupts_list = [interrupt_info]

                                for intr in interrupts_list:
                                    logger.info(
                                        f"AgentLoopStreamAPI: Processing interrupt: type={type(intr)}, dir={dir(intr)}"
                                    )
                                    logger.info(
                                        f"AgentLoopStreamAPI: interrupt repr: {repr(intr)}"
                                    )

                                    if hasattr(intr, "id"):
                                        interrupt_id = intr.id
                                        logger.info(
                                            f"AgentLoopStreamAPI: interrupt_id from attr: {interrupt_id}"
                                        )
                                    elif isinstance(intr, dict) and "id" in intr:
                                        interrupt_id = intr["id"]
                                        logger.info(
                                            f"AgentLoopStreamAPI: interrupt_id from dict: {interrupt_id}"
                                        )

                                    intr_value = (
                                        getattr(intr, "value", intr)
                                        if hasattr(intr, "value")
                                        else intr
                                    )
                                    logger.info(
                                        f"AgentLoopStreamAPI: intr_value type={type(intr_value)}, value={intr_value}"
                                    )

                                    # 尝试多种方式获取 action_requests
                                    ars = []
                                    if isinstance(intr_value, dict):
                                        ars = intr_value.get("action_requests", [])
                                        logger.info(
                                            f"AgentLoopStreamAPI: action_requests from dict: {ars}"
                                        )
                                    elif hasattr(intr_value, "action_requests"):
                                        ars = intr_value.action_requests
                                        logger.info(
                                            f"AgentLoopStreamAPI: action_requests from attr: {ars}"
                                        )

                                    # 如果还是空的，尝试从 intr 本身获取
                                    if not ars and hasattr(intr, "action_requests"):
                                        ars = intr.action_requests
                                        logger.info(
                                            f"AgentLoopStreamAPI: action_requests from intr attr: {ars}"
                                        )

                                    logger.info(
                                        f"AgentLoopStreamAPI: Found {len(ars)} action_requests: {ars}"
                                    )

                                    for ar in ars:
                                        if isinstance(ar, dict):
                                            action_requests.append(
                                                {
                                                    "name": ar.get(
                                                        "name",
                                                        ar.get(
                                                            "action_name", "unknown"
                                                        ),
                                                    ),
                                                    "args": ar.get(
                                                        "arguments", ar.get("args", {})
                                                    ),
                                                    "description": ar.get(
                                                        "description", ""
                                                    ),
                                                }
                                            )
                                        else:
                                            action_requests.append(
                                                {
                                                    "name": getattr(
                                                        ar, "name", "unknown"
                                                    ),
                                                    "args": getattr(
                                                        ar,
                                                        "arguments",
                                                        getattr(ar, "args", {}),
                                                    ),
                                                    "description": getattr(
                                                        ar, "description", ""
                                                    ),
                                                }
                                            )

                                if action_requests:
                                    # 获取用户工具偏好，为 always_reject 的工具添加 auto_reject 标记
                                    user_approvals = await sync_to_async(
                                        get_user_tool_approvals
                                    )(request.user, session_id)
                                    for ar in action_requests:
                                        tool_name = ar.get("name", "")
                                        if (
                                            user_approvals.get(tool_name)
                                            == "always_reject"
                                        ):
                                            ar["auto_reject"] = True
                                            logger.info(
                                                f"AgentLoopStreamAPI: Tool {tool_name} marked as auto_reject"
                                            )

                                    interrupt_detected = True
                                    yield create_sse_data(
                                        {
                                            "type": "interrupt",
                                            "interrupt_id": interrupt_id
                                            or str(id(interrupt_info)),
                                            "action_requests": action_requests,
                                            "session_id": session_id,
                                            "thread_id": thread_id,
                                        }
                                    )
                                    logger.info(
                                        f"AgentLoopStreamAPI: Sent interrupt with {len(action_requests)} actions"
                                    )

                            # 检测工具调用开始（用于生成 step_start 事件）
                            elif isinstance(chunk, dict):
                                for node_name, node_output in chunk.items():
                                    if node_name in MODEL_NODE_NAMES and isinstance(
                                        node_output, dict
                                    ):
                                        messages = node_output.get("messages", [])
                                        for msg in messages:
                                            if (
                                                hasattr(msg, "tool_calls")
                                                and msg.tool_calls
                                            ):
                                                # 新的工具调用 -> 新步骤开始
                                                step_count += 1
                                                current_tool_calls = msg.tool_calls
                                                tool_names_in_step = _cli_tool_names(
                                                    current_tool_calls
                                                )
                                                yield create_sse_data(
                                                    {
                                                        "type": "step_start",
                                                        "step": step_count,
                                                        "max_steps": max_steps_display,
                                                        "tools": tool_names_in_step,
                                                    }
                                                )
                                                logger.info(
                                                    f"AgentLoopStreamAPI: Step {step_count} started with tools: {tool_names_in_step}"
                                                )

                                                # 兜底计数器：逐步累计工具调用步，
                                                # 与中间件共享同一套判定规则
                                                signatures = step_signatures(msg)
                                                if signatures:
                                                    fallback_steps.append(
                                                        ToolStep(signatures=signatures)
                                                    )
                                        if fallback_steps:
                                            repeats = count_trailing_repeats(
                                                fallback_steps,
                                                require_same_result=loop_guard_config.require_same_result,
                                            )
                                            if (
                                                repeats >= loop_guard_config.abort
                                                and not loop_aborted
                                            ):
                                                loop_aborted = True
                                                loop_abort_tool = ", ".join(
                                                    sorted(
                                                        {
                                                            s.split("::", 1)[0]
                                                            for s in fallback_steps[
                                                                -1
                                                            ].signatures
                                                        }
                                                    )
                                                )
                                                loop_abort_count = repeats
                                                loop_abort_message = (
                                                    f"检测到工具 {loop_abort_tool} 连续 "
                                                    f"{repeats} 次以完全相同参数调用且返回结果一致，"
                                                    "已中止本轮执行（工具调用死循环）。"
                                                    "建议调整查询参数或缩小需求范围后重试。"
                                                )
                                                logger.warning(
                                                    "[LoopGuard] action=abort(source=stream_fallback) "
                                                    "session_id=%s tool=%s repeat_count=%s",
                                                    session_id,
                                                    loop_abort_tool,
                                                    repeats,
                                                )
                                                break

                                    elif node_name == TOOL_NODE_NAME and isinstance(
                                        node_output, dict
                                    ):
                                        # 工具执行完成
                                        tool_messages = node_output.get("messages", [])
                                        for tool_msg in tool_messages:
                                            if hasattr(tool_msg, "content"):
                                                content = tool_msg.content
                                                tool_name = getattr(
                                                    tool_msg, "name", None
                                                ) or getattr(
                                                    tool_msg, "tool_name", "unknown"
                                                )

                                                # 兜底计数器：记录本步工具返回摘要
                                                digest = content_digest(tool_msg)
                                                if fallback_steps and digest:
                                                    last_step = fallback_steps[-1]
                                                    last_step.result_digests = (
                                                        last_step.result_digests
                                                        + (digest,)
                                                    )

                                                # 使用辅助函数处理 MCP 工具输出
                                                content, summary = (
                                                    process_mcp_tool_output(content)
                                                )
                                                content, summary = (
                                                    _limit_sse_tool_output(
                                                        content, summary
                                                    )
                                                )

                                                yield create_sse_data(
                                                    {
                                                        "type": "tool_result",
                                                        "tool_name": tool_name,
                                                        "tool_output": content,
                                                        "summary": summary,
                                                        "step": step_count,
                                                    }
                                                )
                                        # 步骤完成
                                        if step_count > 0:
                                            yield create_sse_data(
                                                {
                                                    "type": "step_complete",
                                                    "step": step_count,
                                                }
                                            )

                                if loop_aborted:
                                    break

                        elif stream_mode == "messages":
                            # LLM Token 流式输出
                            # messages 模式返回元组 (token, metadata)
                            if isinstance(chunk, tuple) and len(chunk) >= 1:
                                token = chunk[0]
                                metadata = chunk[1] if len(chunk) > 1 else None
                                # 只发送模型节点产出的正文：过滤 ToolMessage、
                                # 中间件节点以及守卫注入的纠偏/中止消息
                                if _is_streamable_token(token, metadata):
                                    yield create_sse_data(
                                        {"type": "stream", "data": token.content}
                                    )
                            elif _is_streamable_token(chunk, None):
                                # 兼容旧版本可能直接返回 message 的情况
                                yield create_sse_data(
                                    {"type": "stream", "data": chunk.content}
                                )

                except GraphRecursionError:
                    # 守卫未能提前止损时的最后一道防线：给出可读的中止说明，
                    # 而不是把 langgraph 的原始 Recursion limit 报错抛给用户
                    logger.warning(
                        "[LoopGuard] action=abort(source=recursion_limit) session_id=%s "
                        "thread_id=%s recursion_limit=%s step_count=%s",
                        session_id,
                        thread_id,
                        recursion_limit,
                        step_count,
                    )
                    yield create_sse_data(
                        _build_recursion_limit_error_event(
                            recursion_limit=recursion_limit, step_count=step_count
                        )
                    )
                except Exception as e:
                    friendly_error = get_user_friendly_llm_error(e)
                    if friendly_error:
                        logger.warning(
                            "AgentLoopStreamAPI: Friendly model error. session_id=%s, error_code=%s, message=%s",
                            session_id,
                            friendly_error.get("error_code"),
                            friendly_error.get("message"),
                        )
                        yield create_sse_data(_build_sse_error_event(e))
                    else:
                        logger.error(
                            "AgentLoopStreamAPI: Streaming error. session_id=%s, thread_id=%s, "
                            "model=%s, error_type=%s, error=%s",
                            session_id,
                            thread_id,
                            model_name,
                            type(e).__name__,
                            e,
                            exc_info=True,
                        )
                        yield create_sse_data(
                            {"type": "error", "message": f"Streaming error: {str(e)}"}
                        )

                # 16. 处理结束状态
                # 无论是否发生 interrupt，都需要计算和发送 context_update
                try:
                    current_state = await agent.aget_state(invoke_config)
                    all_messages = (
                        current_state.values.get("messages", [])
                        if current_state.values
                        else []
                    )

                    # 获取当前上下文 token 使用量（优先 usage_metadata，回退估算）
                    input_tokens, output_tokens, total_tokens = (
                        calculate_context_tokens(
                            all_messages, model_name,
                            tools=tools, system_prompt=effective_prompt,
                        )
                    )

                    yield create_sse_data(
                        {
                            "type": "context_update",
                            "context_token_count": total_tokens,
                            "context_limit": context_limit,
                        }
                    )

                    # 记录 Token 使用量到 ChatSession + TokenUsageRecord
                    if input_tokens > 0 or output_tokens > 0:
                        # 提取缓存命中信息
                        cache_read_tokens = 0
                        for msg in reversed(all_messages):
                            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                                cache_info = msg.usage_metadata.get("input_token_details", {})
                                cache_read_tokens = cache_info.get("cache_read", 0) or 0
                                logger.info(
                                    "AgentLoopStreamAPI: Token usage - input=%d, output=%d, cache_read=%d, cache_info=%s",
                                    input_tokens, output_tokens, cache_read_tokens, cache_info,
                                )
                                break
                        else:
                            logger.info(
                                f"AgentLoopStreamAPI: Token usage recorded - input={input_tokens}, output={output_tokens}"
                            )

                        await sync_to_async(self._update_session_token_usage)(
                            session_id, input_tokens, output_tokens,
                            cache_read_tokens=cache_read_tokens,
                            user_id=request.user.id,
                            project_id=int(project_id) if project_id else None,
                        )
                except Exception as e:
                    logger.warning(
                        f"AgentLoopStreamAPI: Failed to calculate token count: {e}"
                    )

                # AI 自动总结会话标题
                if chat_session.title.startswith("新对话") and "llm" in locals() and llm:
                    try:
                        scheduled = schedule_auto_summarize_session_title(
                            llm,
                            chat_session,
                            user_message,
                        )
                        if scheduled:
                            logger.info(f"AgentLoopStreamAPI: Scheduled title auto-summarization for session {session_id}")
                    except Exception as summarize_err:
                        logger.error(f"AgentLoopStreamAPI: Failed to auto-summarize title: {summarize_err}", exc_info=True)

                # 收尾兜底：捕获最后一个 superstep 中推送的守卫事件
                # （中间件的 abort 会自然结束图，无需在此 break）
                if not loop_aborted:
                    for guard_event in _drain_loop_guard_events(session_id):
                        if guard_event.get("kind") == LOOP_GUARD_ABORT:
                            loop_aborted = True
                            loop_abort_tool = guard_event.get("tool")
                            loop_abort_count = int(guard_event.get("count") or 0)
                            loop_abort_message = guard_event.get("message") or ""

                if user_stopped:
                    yield create_sse_data(
                        {"type": "complete", "status": "stopped", "steps": step_count}
                    )
                elif loop_aborted:
                    # 复用 error 事件承载中止说明：前端会把 message 渲染成
                    # 一条 AI 气泡并置为结束态，无需改动前端
                    yield create_sse_data(
                        _build_loop_abort_error_event(
                            tool=loop_abort_tool,
                            count=loop_abort_count,
                            message=loop_abort_message
                            or (
                                f"检测到工具 {loop_abort_tool or 'unknown'} 连续 "
                                f"{loop_abort_count} 次以完全相同参数调用且返回结果一致，"
                                "已中止本轮执行（工具调用死循环）。"
                            ),
                        )
                    )
                elif interrupt_detected:
                    logger.info(
                        "AgentLoopStreamAPI: Interrupt detected, returning early"
                    )
                else:
                    complete_data = {"type": "complete", "total_steps": step_count}
                    if generate_playwright_script:
                        complete_data["script_generation"] = {
                            "enabled": True,
                            "message": "脚本管理工具已启用",
                        }
                    yield create_sse_data(complete_data)

                yield "data: [DONE]\n\n"

        except Exception as e:
            friendly_error = get_user_friendly_llm_error(e)
            if friendly_error:
                logger.warning(
                    "AgentLoopStreamAPI: Friendly model error. session_id=%s, error_code=%s, message=%s",
                    session_id,
                    friendly_error.get("error_code"),
                    friendly_error.get("message"),
                )
                yield create_sse_data(_build_sse_error_event(e))
            else:
                logger.error(
                    "AgentLoopStreamAPI: Error. session_id=%s, thread_id=%s, model=%s, "
                    "error_type=%s, error=%s",
                    session_id,
                    thread_id,
                    model_name if "model_name" in locals() else "unknown",
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                yield create_sse_data(
                    {"type": "error", "message": f"执行错误: {str(e)}"}
                )

    async def post(self, request, *args, **kwargs):
        """
        处理聊天请求

        支持 stream 参数：
        - stream=true (默认)：返回 SSE 流式响应
        - stream=false：返回普通 JSON 响应
        """
        # 1. 认证
        try:
            user = await self.authenticate_request(request)
            request.user = user
        except AuthenticationFailed as e:
            return api_error_response(str(e), 401)

        # 2. 解析请求
        try:
            body_data = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError as e:
            return api_error_response(f"Invalid JSON: {e}", 400)

        user_message = body_data.get("message")
        session_id = body_data.get("session_id")
        project_id = body_data.get("project_id")
        knowledge_base_id = body_data.get("knowledge_base_id")
        use_knowledge_base = body_data.get("use_knowledge_base", True)
        prompt_id = body_data.get("prompt_id")
        file_ids = body_data.get("file_ids", [])

        # 调试日志：知识库参数
        logger.info(
            f"AgentLoopStreamAPI: knowledge_base_id={knowledge_base_id}, use_knowledge_base={use_knowledge_base}"
        )
        uploaded_images_base64 = _normalize_uploaded_image_base64_list(
            body_data.get("images"),
            body_data.get("image"),
        )

        # stream 参数：控制流式/非流式输出（默认 true）
        stream_mode = body_data.get("stream", True)
        if isinstance(stream_mode, str):
            stream_mode = stream_mode.lower() in ("true", "1", "yes")

        # Playwright 脚本生成参数
        generate_playwright_script = body_data.get("generate_playwright_script", False)
        test_case_id = body_data.get("test_case_id")  # 用于关联生成的脚本
        use_pytest = body_data.get("use_pytest", True)  # 生成 pytest 格式还是简单格式

        # 兜底：如果前端没传 test_case_id，尝试从消息中解析
        if not test_case_id and user_message:
            import re

            # 匹配 "执行ID为 11 的测试用例" 或 "测试用例 ID：11" 等模式
            match = re.search(
                r"(?:执行\s*ID\s*为|测试用例\s*(?:ID|id)[：:]\s*|case[_-]?id[：:=]\s*)(\d+)",
                user_message,
            )
            if match:
                test_case_id = int(match.group(1))
                logger.info(
                    f"AgentLoopStreamAPI: Parsed test_case_id from message: {test_case_id}"
                )

        # 3. 参数验证
        if not project_id:
            return api_error_response("project_id is required", 400)

        if not user_message:
            return api_error_response("message is required", 400)

        # 4. 项目权限检查
        project = await sync_to_async(check_project_permission)(
            request.user, project_id
        )
        if not project:
            return api_error_response("Project access denied", 403)

        # 5. 生成 session_id
        if not session_id:
            session_id = uuid.uuid4().hex
            logger.info(f"AgentLoopStreamAPI: Generated new session_id: {session_id}")

        # 5.1 清理陈旧停止信号，避免上一次"停止"残留影响本轮首次发送
        # 场景：前端先断开 SSE，再调用 stop API，可能导致信号留存到下一次请求
        if clear_stop_signal(session_id):
            logger.info(
                f"AgentLoopStreamAPI: Cleared stale stop signal for session {session_id}"
            )

        # 6. 根据 stream 参数决定响应方式
        if stream_mode:
            # 流式响应 (SSE)
            async def async_generator():
                async for chunk in self._create_stream_generator(
                    request,
                    user_message,
                    session_id,
                    project_id,
                    project,
                    knowledge_base_id,
                    use_knowledge_base,
                    prompt_id,
                    uploaded_images_base64,
                    generate_playwright_script,
                    test_case_id,
                    use_pytest,
                    file_ids,
                ):
                    yield chunk

            response = StreamingHttpResponse(
                async_generator(), content_type="text/event-stream; charset=utf-8"
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response
        else:
            # 非流式响应 (JSON)
            return await self._handle_non_stream_request(
                request,
                user_message,
                session_id,
                project_id,
                project,
                knowledge_base_id,
                use_knowledge_base,
                prompt_id,
                uploaded_images_base64,
                generate_playwright_script,
                test_case_id,
                use_pytest,
                file_ids,
            )

    async def _handle_non_stream_request(
        self,
        request,
        user_message: str,
        session_id: str,
        project_id: str,
        project: Project,
        knowledge_base_id: Optional[int] = None,
        use_knowledge_base: bool = True,
        prompt_id: Optional[int] = None,
        uploaded_images_base64: Optional[List[str]] = None,
        generate_playwright_script: bool = False,
        test_case_id: Optional[int] = None,
        use_pytest: bool = True,
        file_ids: Optional[List[int]] = None,
    ) -> JsonResponse:
        """
        处理非流式请求，收集所有流式事件后返回统一 JSON 响应
        """
        final_content = ""
        final_session_id = session_id
        tool_results = []
        total_steps = 0
        context_token_count = 0
        context_limit = 128000
        error_message = None
        error_status_code = 500
        error_details = None
        interrupt_info = None
        script_generation = None

        try:
            async for chunk in self._create_stream_generator(
                request,
                user_message,
                session_id,
                project_id,
                project,
                knowledge_base_id,
                use_knowledge_base,
                prompt_id,
                uploaded_images_base64,
                generate_playwright_script,
                test_case_id,
                use_pytest,
                file_ids,
            ):
                # 解析 SSE 数据
                if isinstance(chunk, str) and chunk.startswith("data: "):
                    data_str = chunk[6:].strip()
                    if data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("type")

                        if event_type == "start":
                            final_session_id = event.get("session_id", session_id)
                        elif event_type == "stream":
                            # 累积流式内容
                            final_content += event.get("data", "")
                        elif event_type == "tool_result":
                            tool_results.append(
                                {
                                    "summary": event.get("summary", ""),
                                    "tool_output": event.get("tool_output"),
                                    "tool_name": event.get("tool_name"),
                                    "step": event.get("step", 0),
                                }
                            )
                        elif event_type == "step_complete":
                            total_steps = max(total_steps, event.get("step", 0))
                        elif event_type == "context_update":
                            context_token_count = event.get("context_token_count", 0)
                            context_limit = event.get("context_limit", 128000)
                        elif event_type == "error":
                            error_message = event.get("message", "Unknown error")
                            error_status_code = event.get("code", 500)
                            error_details = event.get("errors") or {
                                "detail": [error_message],
                                "error_code": event.get("error_code"),
                            }
                        elif event_type == "interrupt":
                            interrupt_info = {
                                "interrupt_id": event.get("interrupt_id"),
                                "action_requests": event.get("action_requests", []),
                            }
                        elif event_type == "complete":
                            if event.get("script_generation"):
                                script_generation = event.get("script_generation")
                    except json.JSONDecodeError:
                        continue

            # 构建响应
            if error_message:
                return api_error_response(
                    error_message, error_status_code, error_details
                )

            response_data = {
                "session_id": final_session_id,
                "content": final_content,
                "total_steps": total_steps,
                "tool_results": tool_results,
                "context_token_count": context_token_count,
                "context_limit": context_limit,
            }

            if interrupt_info:
                response_data["interrupt"] = interrupt_info

            if script_generation:
                response_data["script_generation"] = script_generation

            return api_success_response("Chat completed", response_data)

        except Exception as e:
            logger.error(
                "AgentLoopStreamAPI: Non-stream request error. session_id=%s, project_id=%s, "
                "error_type=%s, error=%s",
                session_id,
                project_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            friendly_error = get_user_friendly_llm_error(e)
            if friendly_error:
                return api_error_response(
                    friendly_error["message"],
                    friendly_error["status_code"],
                    friendly_error["errors"],
                )
            return api_error_response(f"执行错误: {str(e)}", 500)


@method_decorator(csrf_exempt, name="dispatch")
class AgentLoopStopAPIView(View):
    """
    Agent Loop 停止 API

    用于中断正在执行的 Agent Loop 任务。
    """

    async def authenticate_request(self, request):
        """JWT 认证（复用 AgentLoopStreamAPIView 的逻辑）"""
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Authentication credentials were not provided.")

        token = auth_header.split(" ")[1]
        jwt_auth = JWTAuthentication()

        try:
            validated_token = await sync_to_async(jwt_auth.get_validated_token)(token)
            user = await sync_to_async(jwt_auth.get_user)(validated_token)
            return user
        except Exception as e:
            raise AuthenticationFailed(f"Invalid token: {str(e)}")

    async def post(self, request, *args, **kwargs):
        """处理停止请求"""
        from .stop_signal import set_stop_signal

        # 1. 认证
        try:
            user = await self.authenticate_request(request)
            request.user = user
        except AuthenticationFailed as e:
            return api_error_response(str(e), 401)

        # 2. 解析请求
        try:
            body_data = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError as e:
            return api_error_response(f"Invalid JSON: {e}", 400)

        session_id = body_data.get("session_id")
        if not session_id:
            return api_error_response("session_id is required", 400)

        # 3. 设置停止信号
        success = set_stop_signal(session_id)

        logger.info(
            f"AgentLoopStopAPI: Stop signal set for session {session_id} by user {user.id}"
        )

        return api_success_response(
            "已发送停止信号", {"session_id": session_id, "success": success}
        )


@method_decorator(csrf_exempt, name="dispatch")
class AgentLoopResumeAPIView(View):
    """
    Agent Loop Resume API (SSE 流式版)

    用于恢复被 HITL 中断的 Agent Loop 任务。
    接收用户对工具调用的审批决策，然后通过 SSE 流式返回后续执行结果。

    这样前端可以像处理主流一样处理 resume 后的工具执行和 LLM 响应。
    """

    # 前端展示的步数上限同样由 `resume_recursion_limit // 2` 动态推导

    async def authenticate_request(self, request):
        """JWT 认证（复用 AgentLoopStreamAPIView 的逻辑）"""
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Authentication credentials were not provided.")

        token = auth_header.split(" ")[1]
        jwt_auth = JWTAuthentication()

        try:
            validated_token = await sync_to_async(jwt_auth.get_validated_token)(token)
            user = await sync_to_async(jwt_auth.get_user)(validated_token)
            return user
        except Exception as e:
            raise AuthenticationFailed(f"Invalid token: {str(e)}")

    async def _create_resume_stream_generator(
        self,
        user,
        session_id: str,
        project_id: str,
        resume_data: dict,
        knowledge_base_id: Optional[str] = None,
        use_knowledge_base: bool = False,
    ):
        """
        创建 Resume SSE 流式生成器

        与主流的 _create_stream_generator 类似，但使用 Command(resume=...) 来恢复执行。
        """
        from langgraph.types import Command

        # 1. 解析 resume 数据
        interrupt_id = list(resume_data.keys())[0] if resume_data else None
        if not interrupt_id:
            yield create_sse_data(
                {"type": "error", "message": "Invalid resume data format"}
            )
            return

        decision_info = resume_data[interrupt_id].get("decisions", [{}])[0]
        decision_type = decision_info.get("type", "reject")

        # 获取工具调用数量（前端传递）
        action_count = resume_data[interrupt_id].get("action_count", 1)

        # 构建 resume 值 - HITL middleware 需要 decisions 格式
        # 为每个 pending 工具调用生成相同的决策
        resume_value = {
            "decisions": [{"type": decision_type} for _ in range(action_count)]
        }

        # 2. 发送 resume 开始信号
        yield create_sse_data(
            {
                "type": "resume_start",
                "session_id": session_id,
                "decision": decision_type,
            }
        )

        try:
            async with get_async_checkpointer() as checkpointer:
                # 3. 获取 LLM 配置
                active_config = await sync_to_async(
                    LLMConfig.objects.filter(is_active=True).first
                )()

                if not active_config:
                    yield create_sse_data(
                        {"type": "error", "message": "没有可用的 LLM 配置"}
                    )
                    return

                context_limit = active_config.context_limit or 128000
                model_name = active_config.name or "gpt-4o"
                llm = await sync_to_async(create_llm_instance)(active_config)
                context_limit = resolve_runtime_context_limit(
                    active_config.context_limit, llm, model_name
                )

                # 模型能力分层：弱模型缩短循环步数上限并更激进地截断 ToolMessage
                resume_model_tier = get_model_tier(active_config)
                resume_is_weak = resume_model_tier == "weak"
                resume_recursion_limit = (
                    _WEAK_MODEL_RECURSION_LIMIT
                    if resume_is_weak
                    else _STRONG_MODEL_RECURSION_LIMIT
                )
                resume_tool_message_chars = (
                    _WEAK_MODEL_TOOL_MESSAGE_CHARS
                    if resume_is_weak
                    else _MAX_SAFE_TOOL_MESSAGE_CHARS
                )
                # 与主视图保持一致：前端展示步数上限由 recursion_limit // 2 推导，
                # step_start / start 事件共用同一取值，避免多处不一致
                resume_max_steps_display = max(1, resume_recursion_limit // 2)
                resume_loop_guard_config = load_loop_guard_config()
                logger.info(
                    "AgentLoopResumeAPI: model_tier=%s, recursion_limit=%d, "
                    "max_steps=%d, tool_message_chars=%d, "
                    "loop_guard(enabled=%s, warn=%d, abort=%d, window=%d)",
                    resume_model_tier,
                    resume_recursion_limit,
                    resume_max_steps_display,
                    resume_tool_message_chars,
                    resume_loop_guard_config.enabled,
                    resume_loop_guard_config.warn,
                    resume_loop_guard_config.abort,
                    resume_loop_guard_config.window,
                )

                # 4. 加载工具
                tools = []

                # 加载 MCP 工具
                try:
                    active_mcp_configs = await sync_to_async(list)(
                        RemoteMCPConfig.objects.filter(is_active=True)
                    )
                    if active_mcp_configs:
                        client_config = {}
                        for cfg in active_mcp_configs:
                            key = cfg.name or f"remote_{cfg.id}"
                            client_config[key] = {
                                "url": cfg.url,
                                "transport": (
                                    cfg.transport or "streamable_http"
                                ).replace("-", "_"),
                            }
                            if cfg.headers:
                                client_config[key]["headers"] = cfg.headers

                        if client_config:
                            mcp_tools = await mcp_session_manager.get_tools_for_config(
                                client_config,
                                user_id=str(user.id),
                                project_id=str(project_id) if project_id else "0",
                                session_id=session_id,
                            )
                            tools.extend(mcp_tools)
                            logger.info(
                                f"AgentLoopResumeAPI: Loaded {len(mcp_tools)} MCP tools"
                            )
                except Exception as e:
                    logger.warning(f"AgentLoopResumeAPI: MCP tools loading failed: {e}")

                # 加载知识库工具
                if knowledge_base_id and use_knowledge_base:
                    try:
                        from knowledge.langgraph_integration import (
                            create_knowledge_tool,
                        )

                        kb_tool = await sync_to_async(create_knowledge_tool)(
                            knowledge_base_id=knowledge_base_id, user=user
                        )
                        tools.append(kb_tool)
                        logger.info(
                            f"AgentLoopResumeAPI: ✅ 知识库工具已添加: {kb_tool.name}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"AgentLoopResumeAPI: ❌ Knowledge tool creation failed: {e}"
                        )

                # 加载内置工具
                try:
                    from orchestrator_integration.builtin_tools import get_builtin_tools

                    builtin_tools = get_builtin_tools(
                        user_id=user.id,
                        project_id=int(project_id) if project_id else 0,
                        test_case_id=None,
                        chat_session_id=session_id,
                    )
                    tools.extend(builtin_tools)
                    logger.info(
                        f"AgentLoopResumeAPI: Added {len(builtin_tools)} builtin tools"
                    )
                except Exception as e:
                    logger.warning(
                        f"AgentLoopResumeAPI: Builtin tools loading failed: {e}"
                    )

                # 5. 获取工具名列表和中间件配置
                # 尝试从 ChatSession 关联的 prompt 获取系统提示词，用于精确计算 overhead
                resume_system_prompt = None
                try:
                    chat_session = await sync_to_async(
                        ChatSession.objects.filter(session_id=session_id).select_related("prompt").first
                    )()
                    if chat_session and chat_session.prompt and chat_session.prompt.content:
                        resume_system_prompt = chat_session.prompt.content
                except Exception:
                    pass

                tool_names = [t.name for t in tools] if tools else []
                middleware = await sync_to_async(get_middleware_from_config)(
                    active_config,
                    llm,
                    user=user,
                    session_id=session_id,
                    all_tool_names=tool_names,
                    tools=tools,
                    system_prompt=resume_system_prompt,
                )

                # 6. 创建 agent
                # 修复 D8：resume 分支此前遗漏 system_prompt，导致恢复执行时
                # 缺少系统提示词与工具约束，行为与主视图不一致
                agent = create_agent(
                    llm,
                    tools,
                    system_prompt=resume_system_prompt,
                    checkpointer=checkpointer,
                    middleware=middleware,
                )
                logger.info(
                    f"AgentLoopResumeAPI: Agent created with {len(tools)} tools"
                )
                # 常驻打印真实节点名，便于上游 langchain 版本变更时快速定位
                # 「step 事件静默失效」类问题（v1 节点名为 model/tools）
                logger.info(
                    "AgentLoopResumeAPI: agent nodes=%s, middleware=%s",
                    sorted(getattr(agent, "nodes", {}) or {}),
                    [type(m).__name__ for m in middleware],
                )

                thread_id = (
                    f"{user.id}_{project_id}_{session_id}" if project_id else session_id
                )
                config = {
                    "configurable": {"thread_id": thread_id},
                    # 弱模型下调递归上限
                    "recursion_limit": resume_recursion_limit,
                }

                # 6.1 恢复执行前，先修复历史消息（配对错误 + 风险工具输出）
                await _sanitize_history_before_model_call(
                    agent=agent,
                    invoke_config=config,
                    log_prefix="AgentLoopResumeAPI",
                    tool_message_chars=resume_tool_message_chars,
                )

                # 7. 构建 Command 来 resume
                command = Command(resume=resume_value)

                # 8. 步骤跟踪状态
                step_count = 0
                interrupt_detected = False

                # 8.1 死循环守卫状态（与主视图保持一致）
                # 主力守卫是 LoopGuardMiddleware；这里维护一份独立兜底计数器，
                # 即使中间件被关闭或失效也能止损。
                loop_aborted = False
                loop_abort_tool: Optional[str] = None
                loop_abort_count = 0
                loop_abort_message = ""
                fallback_steps: List[ToolStep] = []

                # 9. 流式执行
                # 清理上一轮可能残留的守卫事件，避免污染本轮
                _drain_loop_guard_events(session_id)
                try:
                    async for stream_mode, chunk in agent.astream(
                        command, config=config, stream_mode=["updates", "messages"]
                    ):
                        if stream_mode == "updates":
                            # 循环守卫事件（LoopGuardMiddleware 在模型调用前推送）
                            for guard_event in _drain_loop_guard_events(session_id):
                                if guard_event.get("kind") == LOOP_GUARD_ABORT:
                                    loop_aborted = True
                                    loop_abort_tool = guard_event.get("tool")
                                    loop_abort_count = int(
                                        guard_event.get("count") or 0
                                    )
                                    loop_abort_message = (
                                        guard_event.get("message") or ""
                                    )
                                elif guard_event.get("kind") == LOOP_GUARD_WARN:
                                    yield create_sse_data(
                                        {
                                            "type": "warning",
                                            "code": "loop_guard_warn",
                                            "message": guard_event.get("message")
                                            or "检测到重复工具调用，已注入纠偏提示",
                                            "tool": guard_event.get("tool"),
                                            "count": guard_event.get("count"),
                                        }
                                    )

                            # 检查中断事件 (HITL) - resume 后可能又触发新的中断
                            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                                interrupt_info = chunk["__interrupt__"]
                                logger.info(
                                    f"AgentLoopResumeAPI: HITL interrupt detected after resume: {interrupt_info}"
                                )

                                action_requests = []
                                new_interrupt_id = None

                                if isinstance(interrupt_info, (list, tuple)):
                                    interrupts_list = list(interrupt_info)
                                else:
                                    interrupts_list = [interrupt_info]

                                for intr in interrupts_list:
                                    if hasattr(intr, "id"):
                                        new_interrupt_id = intr.id
                                    elif isinstance(intr, dict) and "id" in intr:
                                        new_interrupt_id = intr["id"]

                                    intr_value = (
                                        getattr(intr, "value", intr)
                                        if hasattr(intr, "value")
                                        else intr
                                    )
                                    if isinstance(intr_value, dict):
                                        ars = intr_value.get("action_requests", [])
                                    elif hasattr(intr_value, "action_requests"):
                                        ars = intr_value.action_requests
                                    else:
                                        ars = []

                                    for ar in ars:
                                        if isinstance(ar, dict):
                                            action_requests.append(
                                                {
                                                    "name": ar.get(
                                                        "name",
                                                        ar.get(
                                                            "action_name", "unknown"
                                                        ),
                                                    ),
                                                    "args": ar.get(
                                                        "arguments", ar.get("args", {})
                                                    ),
                                                    "description": ar.get(
                                                        "description", ""
                                                    ),
                                                }
                                            )
                                        else:
                                            action_requests.append(
                                                {
                                                    "name": getattr(
                                                        ar, "name", "unknown"
                                                    ),
                                                    "args": getattr(
                                                        ar,
                                                        "arguments",
                                                        getattr(ar, "args", {}),
                                                    ),
                                                    "description": getattr(
                                                        ar, "description", ""
                                                    ),
                                                }
                                            )

                                if action_requests:
                                    # 获取用户工具偏好，为 always_reject 的工具添加 auto_reject 标记
                                    user_approvals = await sync_to_async(
                                        get_user_tool_approvals
                                    )(user, session_id)
                                    for ar in action_requests:
                                        tool_name = ar.get("name", "")
                                        if (
                                            user_approvals.get(tool_name)
                                            == "always_reject"
                                        ):
                                            ar["auto_reject"] = True
                                            logger.info(
                                                f"AgentLoopResumeAPI: Tool {tool_name} marked as auto_reject"
                                            )

                                    interrupt_detected = True
                                    yield create_sse_data(
                                        {
                                            "type": "interrupt",
                                            "interrupt_id": new_interrupt_id
                                            or str(id(interrupt_info)),
                                            "action_requests": action_requests,
                                            "session_id": session_id,
                                            "thread_id": thread_id,
                                        }
                                    )

                            # 检测工具调用开始
                            elif isinstance(chunk, dict):
                                for node_name, node_output in chunk.items():
                                    if node_name in MODEL_NODE_NAMES and isinstance(
                                        node_output, dict
                                    ):
                                        messages = node_output.get("messages", [])
                                        for msg in messages:
                                            if (
                                                hasattr(msg, "tool_calls")
                                                and msg.tool_calls
                                            ):
                                                step_count += 1
                                                tool_names_in_step = _cli_tool_names(
                                                    msg.tool_calls
                                                )
                                                yield create_sse_data(
                                                    {
                                                        "type": "step_start",
                                                        "step": step_count,
                                                        "max_steps": resume_max_steps_display,
                                                        "tools": tool_names_in_step,
                                                    }
                                                )

                                                # 兜底计数器：逐步累计工具调用步，
                                                # 与中间件共享同一套判定规则
                                                signatures = step_signatures(msg)
                                                if signatures:
                                                    fallback_steps.append(
                                                        ToolStep(signatures=signatures)
                                                    )
                                        if fallback_steps:
                                            repeats = count_trailing_repeats(
                                                fallback_steps,
                                                require_same_result=resume_loop_guard_config.require_same_result,
                                            )
                                            if (
                                                repeats >= resume_loop_guard_config.abort
                                                and not loop_aborted
                                            ):
                                                loop_aborted = True
                                                loop_abort_tool = ", ".join(
                                                    sorted(
                                                        {
                                                            s.split("::", 1)[0]
                                                            for s in fallback_steps[
                                                                -1
                                                            ].signatures
                                                        }
                                                    )
                                                )
                                                loop_abort_count = repeats
                                                loop_abort_message = (
                                                    f"检测到工具 {loop_abort_tool} 连续 "
                                                    f"{repeats} 次以完全相同参数调用且返回结果一致，"
                                                    "已中止本轮执行（工具调用死循环）。"
                                                    "建议调整查询参数或缩小需求范围后重试。"
                                                )
                                                logger.warning(
                                                    "[LoopGuard] action=abort(source=stream_fallback) "
                                                    "session_id=%s tool=%s repeat_count=%s",
                                                    session_id,
                                                    loop_abort_tool,
                                                    repeats,
                                                )
                                                break

                                    elif node_name == TOOL_NODE_NAME and isinstance(
                                        node_output, dict
                                    ):
                                        tool_messages = node_output.get("messages", [])
                                        for tool_msg in tool_messages:
                                            if hasattr(tool_msg, "content"):
                                                content = tool_msg.content
                                                tool_name = getattr(
                                                    tool_msg, "name", None
                                                ) or getattr(
                                                    tool_msg, "tool_name", "unknown"
                                                )

                                                # 兜底计数器：记录本步工具返回摘要
                                                digest = content_digest(tool_msg)
                                                if fallback_steps and digest:
                                                    last_step = fallback_steps[-1]
                                                    last_step.result_digests = (
                                                        last_step.result_digests
                                                        + (digest,)
                                                    )

                                                # 使用辅助函数处理 MCP 工具输出
                                                content, summary = (
                                                    process_mcp_tool_output(content)
                                                )
                                                content, summary = (
                                                    _limit_sse_tool_output(
                                                        content, summary
                                                    )
                                                )

                                                yield create_sse_data(
                                                    {
                                                        "type": "tool_result",
                                                        "tool_name": tool_name,
                                                        "tool_output": content,
                                                        "summary": summary,
                                                        "step": step_count,
                                                    }
                                                )
                                        if step_count > 0:
                                            yield create_sse_data(
                                                {
                                                    "type": "step_complete",
                                                    "step": step_count,
                                                }
                                            )

                                if loop_aborted:
                                    break

                        elif stream_mode == "messages":
                            # LLM Token 流式输出
                            # messages 模式返回元组 (token, metadata)
                            if isinstance(chunk, tuple) and len(chunk) >= 1:
                                token = chunk[0]
                                metadata = chunk[1] if len(chunk) > 1 else None
                                # 只发送模型节点产出的正文：过滤 ToolMessage、
                                # 中间件节点以及守卫注入的纠偏/中止消息
                                if _is_streamable_token(token, metadata):
                                    yield create_sse_data(
                                        {"type": "stream", "data": token.content}
                                    )
                            elif _is_streamable_token(chunk, None):
                                # 兼容旧版本可能直接返回 message 的情况
                                yield create_sse_data(
                                    {"type": "stream", "data": chunk.content}
                                )

                except GraphRecursionError:
                    # 守卫未能提前止损时的最后一道防线：给出可读的中止说明，
                    # 而不是把 langgraph 的原始 Recursion limit 报错抛给用户
                    logger.warning(
                        "[LoopGuard] action=abort(source=recursion_limit) session_id=%s "
                        "thread_id=%s recursion_limit=%s step_count=%s",
                        session_id,
                        thread_id,
                        resume_recursion_limit,
                        step_count,
                    )
                    yield create_sse_data(
                        _build_recursion_limit_error_event(
                            recursion_limit=resume_recursion_limit,
                            step_count=step_count,
                        )
                    )
                except Exception as e:
                    friendly_error = get_user_friendly_llm_error(e)
                    if friendly_error:
                        logger.warning(
                            "AgentLoopResumeAPI: Friendly model error. session_id=%s, error_code=%s, message=%s",
                            session_id,
                            friendly_error.get("error_code"),
                            friendly_error.get("message"),
                        )
                        yield create_sse_data(_build_sse_error_event(e))
                    else:
                        logger.error(
                            "AgentLoopResumeAPI: Streaming error: %s", e, exc_info=True
                        )
                        yield create_sse_data(
                            {"type": "error", "message": f"Streaming error: {str(e)}"}
                        )

                # 10. 处理结束状态
                # 无论是否发生 interrupt，都需要计算和发送 context_update
                try:
                    current_state = await agent.aget_state(config)
                    all_messages = (
                        current_state.values.get("messages", [])
                        if current_state.values
                        else []
                    )

                    # 获取当前上下文 token 使用量（优先 usage_metadata，回退估算）
                    input_tokens, output_tokens, total_tokens = (
                        calculate_context_tokens(
                            all_messages, model_name,
                            tools=tools, system_prompt=resume_system_prompt,
                        )
                    )

                    yield create_sse_data(
                        {
                            "type": "context_update",
                            "context_token_count": total_tokens,
                            "context_limit": context_limit,
                        }
                    )

                    # 记录 Token 使用量到 ChatSession + TokenUsageRecord
                    if input_tokens > 0 or output_tokens > 0:
                        # 提取缓存命中信息
                        cache_read_tokens = 0
                        for msg in reversed(all_messages):
                            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                                cache_info = msg.usage_metadata.get("input_token_details", {})
                                cache_read_tokens = cache_info.get("cache_read", 0) or 0
                                break

                        await sync_to_async(
                            AgentLoopStreamAPIView()._update_session_token_usage
                        )(
                            session_id, input_tokens, output_tokens,
                            cache_read_tokens=cache_read_tokens,
                            user_id=user.id,
                            project_id=int(project_id) if project_id else None,
                        )
                        logger.info(
                            "AgentLoopResumeAPI: Token usage - input=%d, output=%d, cache_read=%d",
                            input_tokens, output_tokens, cache_read_tokens,
                        )
                except Exception as e:
                    logger.warning(
                        f"AgentLoopResumeAPI: Failed to calculate token count: {e}"
                    )

                # 收尾兜底：捕获最后一个 superstep 中推送的守卫事件
                # （中间件的 abort 会自然结束图，无需在此 break）
                if not loop_aborted:
                    for guard_event in _drain_loop_guard_events(session_id):
                        if guard_event.get("kind") == LOOP_GUARD_ABORT:
                            loop_aborted = True
                            loop_abort_tool = guard_event.get("tool")
                            loop_abort_count = int(guard_event.get("count") or 0)
                            loop_abort_message = guard_event.get("message") or ""

                if loop_aborted:
                    # 复用 error 事件承载中止说明：前端会把 message 渲染成
                    # 一条 AI 气泡并置为结束态，无需改动前端
                    yield create_sse_data(
                        _build_loop_abort_error_event(
                            tool=loop_abort_tool,
                            count=loop_abort_count,
                            message=loop_abort_message
                            or (
                                f"检测到工具 {loop_abort_tool or 'unknown'} 连续 "
                                f"{loop_abort_count} 次以完全相同参数调用且返回结果一致，"
                                "已中止本轮执行（工具调用死循环）。"
                            ),
                        )
                    )
                elif interrupt_detected:
                    logger.info(
                        "AgentLoopResumeAPI: New interrupt detected after resume"
                    )
                else:
                    yield create_sse_data(
                        {
                            "type": "complete",
                            "total_steps": step_count,
                            "decision": decision_type,
                        }
                    )

                yield "data: [DONE]\n\n"

        except Exception as e:
            friendly_error = get_user_friendly_llm_error(e)
            if friendly_error:
                logger.warning(
                    "AgentLoopResumeAPI: Friendly model error. session_id=%s, error_code=%s, message=%s",
                    session_id,
                    friendly_error.get("error_code"),
                    friendly_error.get("message"),
                )
                yield create_sse_data(_build_sse_error_event(e))
            else:
                logger.exception(
                    "AgentLoopResumeAPI: Error in resume stream for session %s",
                    session_id,
                )
                yield create_sse_data({"type": "error", "message": str(e)})

    async def post(self, request, *args, **kwargs):
        """处理 HITL resume 请求 - 返回 SSE 流式响应"""
        # 1. 认证
        try:
            user = await self.authenticate_request(request)
            request.user = user
        except AuthenticationFailed as e:
            return StreamingHttpResponse(
                iter(
                    [create_sse_data({"type": "error", "message": str(e), "code": 401})]
                ),
                content_type="text/event-stream; charset=utf-8",
                status=401,
            )

        # 2. 解析请求
        try:
            body_data = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError as e:
            return StreamingHttpResponse(
                iter(
                    [
                        create_sse_data(
                            {
                                "type": "error",
                                "message": f"Invalid JSON: {e}",
                                "code": 400,
                            }
                        )
                    ]
                ),
                content_type="text/event-stream; charset=utf-8",
                status=400,
            )

        session_id = body_data.get("session_id")
        project_id = body_data.get("project_id")
        resume_data = body_data.get("resume", {})
        # 知识库参数（用于 resume 时重新加载知识库工具）
        knowledge_base_id = body_data.get("knowledge_base_id")
        use_knowledge_base = body_data.get("use_knowledge_base", False)

        if not session_id:
            return StreamingHttpResponse(
                iter(
                    [
                        create_sse_data(
                            {
                                "type": "error",
                                "message": "session_id is required",
                                "code": 400,
                            }
                        )
                    ]
                ),
                content_type="text/event-stream; charset=utf-8",
                status=400,
            )

        if not resume_data:
            return StreamingHttpResponse(
                iter(
                    [
                        create_sse_data(
                            {
                                "type": "error",
                                "message": "resume data is required",
                                "code": 400,
                            }
                        )
                    ]
                ),
                content_type="text/event-stream; charset=utf-8",
                status=400,
            )

        logger.info(
            f"AgentLoopResumeAPI: Resume request for session {session_id}, knowledge_base_id={knowledge_base_id}"
        )

        # 3. 返回 SSE 流式响应
        async def async_generator():
            async for chunk in self._create_resume_stream_generator(
                user,
                session_id,
                project_id,
                resume_data,
                knowledge_base_id,
                use_knowledge_base,
            ):
                yield chunk

        response = StreamingHttpResponse(
            async_generator(), content_type="text/event-stream; charset=utf-8"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
