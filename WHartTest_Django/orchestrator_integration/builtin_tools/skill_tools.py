"""
Skill 工具

提供渐进式加载的 Skill 系统：
- read_skill_content: 读取 Skill 的 SKILL.md 内容（按需加载）
- execute_skill_script: 执行 Skill 的 shell 命令（支持持久化浏览器会话）
"""

import logging
import subprocess
import os
import shutil
import threading
import json
import time
import mimetypes
import re
import hashlib
from collections import OrderedDict
from typing import Optional, Tuple

from langchain_core.tools import tool as langchain_tool
from django.conf import settings

from .output_sanitizer import strip_terminal_control_sequences
from .persistent_playwright import PlaywrightSessionManager, extract_runjs_args
from ..loop_guard import _get_env_bool, _get_env_int

logger = logging.getLogger("orchestrator_integration")

_playwright_session_manager: Optional[PlaywrightSessionManager] = None
_playwright_session_manager_lock = threading.Lock()
_ARTIFACT_EXTENSIONS = {
    ".drawio",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".html",
    ".htm",
    ".txt",
    ".json",
    ".csv",
    ".xml",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}
_MAX_ARTIFACT_SIZE_BYTES = 50 * 1024 * 1024
_ARTIFACT_TOKEN_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?[^\s<>\"'`|]+?\.(?:drawio|png|jpe?g|gif|svg|pdf|html?|txt|json|csv|xml|zip|docx?|xlsx?|pptx?))",
    re.IGNORECASE,
)
_QUOTED_ARTIFACT_TOKEN_RE = re.compile(
    r"[`'\"](?P<path>[^`'\"]+?\.(?:drawio|png|jpe?g|gif|svg|pdf|html?|txt|json|csv|xml|zip|docx?|xlsx?|pptx?))[`'\"]",
    re.IGNORECASE,
)


# ============== Skill 命令重复调用拦截 ==============
#
# 弱模型（如 qwen3-coder）在工具返回空结果时会以完全相同的参数反复调用同一命令，
# 表现为「工具调用死循环」。这里按「会话 + Skill + 命令」维度做短期缓存：
# 允许前 N 次真实执行，之后直接返回上次结果并明确提示「请勿重复调用」，
# 既避免每次都起新子进程，也让模型明确看到「该调用已被拦截」这一信号。

_SKILL_DEDUP_ENABLED = _get_env_bool("SKILL_TOOL_DEDUP_ENABLED", True)
# 允许真实执行的重复次数上限（第 N+1 次起短路）
_SKILL_DEDUP_MIN_REPEAT = _get_env_int("SKILL_TOOL_DEDUP_MIN_REPEAT", 2, min_value=1)
_SKILL_DEDUP_TTL_SECONDS = _get_env_int(
    "SKILL_TOOL_DEDUP_TTL_SECONDS", 120, min_value=1
)
_SKILL_DEDUP_MAX_ENTRIES = _get_env_int(
    "SKILL_TOOL_DEDUP_MAX_ENTRIES", 256, min_value=8
)

_WHITESPACE_RE = re.compile(r"\s+")
_SKILL_ACTION_RE = re.compile(r"--action[=\s]+(?P<action>[A-Za-z0-9_]+)")
# 只读 action 前缀：这些命令不改状态，重复执行结果一致，可安全短路
_READ_ONLY_ACTION_PREFIXES = (
    "get_",
    "list_",
    "read_",
    "query_",
    "search_",
    "check_",
    "obtain_",
    "validate_",
    "preview_",
    "download_",
)


class _SkillCallCache:
    """线程安全的会话级命令缓存（LRU + TTL）"""

    def __init__(self, ttl_seconds: int, max_entries: int):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()

    def _prune_expired(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry["last_at"] > self._ttl
        ]
        for key in expired:
            self._entries.pop(key, None)

    def touch(self, key: str) -> Tuple[int, Optional[str], float]:
        """
        记录一次调用。

        返回 (本次是第几次调用, 上次结果, 距上次调用的秒数)；
        缓存已过期或首次调用时，上次结果与间隔为 None / 0。
        """
        now = time.time()
        with self._lock:
            self._prune_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = {
                    "count": 1,
                    "result": None,
                    "first_at": now,
                    "last_at": now,
                }
                self._trim()
                return 1, None, 0.0

            age = now - entry["last_at"]
            entry["count"] += 1
            entry["last_at"] = now
            self._entries.move_to_end(key)
            return entry["count"], entry.get("result"), age

    def store(self, key: str, result: str) -> None:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = {
                    "count": 1,
                    "result": result,
                    "first_at": now,
                    "last_at": now,
                }
            else:
                entry["result"] = result
                entry["last_at"] = now
                self._entries.move_to_end(key)
            self._trim()

    def _trim(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self, key_prefix: str = "") -> None:
        with self._lock:
            if not key_prefix:
                self._entries.clear()
                return
            for key in [k for k in self._entries if k.startswith(key_prefix)]:
                self._entries.pop(key, None)


_skill_call_cache = _SkillCallCache(
    ttl_seconds=_SKILL_DEDUP_TTL_SECONDS,
    max_entries=_SKILL_DEDUP_MAX_ENTRIES,
)


def _is_read_only_skill_command(command: str) -> bool:
    """依据 `--action` 判定是否为只读命令（写命令一律不短路）"""
    match = _SKILL_ACTION_RE.search(command or "")
    if not match:
        return False
    action = (match.group("action") or "").strip().lower()
    return action.startswith(_READ_ONLY_ACTION_PREFIXES)


def _build_skill_dedup_key(
    session_scope: str, skill_name: str, command: str
) -> str:
    normalized = _WHITESPACE_RE.sub(" ", (command or "").strip())
    digest = hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{session_scope}::{skill_name}::{digest}"


def _build_repeat_short_circuit_notice(
    *, skill_name: str, count: int, age_seconds: float, cached_result: str
) -> str:
    return (
        f"[重复调用拦截] 该命令（Skill: {skill_name}）已在最近 "
        f"{int(age_seconds)} 秒内以完全相同的参数调用 {count - 1} 次，结果未发生变化。"
        "框架已阻止重复执行，直接返回上次结果。\n"
        "请立即停止重复调用本命令，改为：调整参数（更换 action / 分页 / 查询范围）、"
        "基于已有结果继续下一步，或直接输出结论/说明阻塞原因。\n"
        f"原始结果:\n{cached_result}"
    )


def _build_repeat_reminder_prefix(count: int) -> str:
    return (
        f"[重复提醒] 该命令与之前第 {count - 1} 次调用参数完全相同，已再次执行；"
        "若属无意重复，请停止重复调用。\n"
    )


def _sanitize_runtime_path_segment(value: Optional[str], default: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return default

    sanitized = raw.replace("..", "_")
    for separator in filter(None, {os.sep, os.altsep}):
        sanitized = sanitized.replace(separator, "_")

    sanitized = sanitized.strip(" .")
    return sanitized or default


def _build_skill_screenshots_dir(
    project_id: Optional[int] = None,
    case_dir_key: Optional[str] = None,
) -> str:
    project_segment = str(project_id if project_id is not None else 0)
    case_segment = _sanitize_runtime_path_segment(case_dir_key, "_default")
    return os.path.abspath(
        os.path.join(
            settings.MEDIA_ROOT,
            "skill_runtime",
            "screenshots",
            project_segment,
            case_segment,
        )
    )


# 截图/产物目录空闲超过该时长（秒）才允许清理，避免 chat_session_id 变化时误删正在使用的截图
_SKILL_DIR_STALE_SECONDS = 5 * 60 * 60


def _dir_latest_mtime(path: str) -> float:
    """目录树内最新文件 mtime；无文件返回 0（目录结构变更不算活跃写入）。"""
    latest = 0.0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, name))
            except OSError:
                continue
            if mtime > latest:
                latest = mtime
    return latest


def _prepare_skill_screenshots_dir(
    project_id: Optional[int] = None,
    case_dir_key: Optional[str] = None,
) -> str:
    screenshots_dir = _build_skill_screenshots_dir(project_id, case_dir_key)
    if not case_dir_key:
        os.makedirs(screenshots_dir, exist_ok=True)
        return screenshots_dir

    should_clear = False
    if os.path.exists(screenshots_dir):
        latest = _dir_latest_mtime(screenshots_dir)
        if latest and time.time() - latest > _SKILL_DIR_STALE_SECONDS:
            should_clear = True

    if should_clear:
        shutil.rmtree(screenshots_dir, ignore_errors=True)
        logger.info(f"[execute_skill_script] 清空旧截图目录: {screenshots_dir}")

    os.makedirs(screenshots_dir, exist_ok=True)
    return screenshots_dir


def _build_skill_artifacts_dir(
    project_id: Optional[int] = None,
    case_dir_key: Optional[str] = None,
) -> str:
    project_segment = str(project_id if project_id is not None else 0)
    case_segment = _sanitize_runtime_path_segment(case_dir_key, "_default")
    return os.path.abspath(
        os.path.join(
            settings.MEDIA_ROOT,
            "skill_runtime",
            "artifacts",
            project_segment,
            case_segment,
        )
    )


def _prepare_skill_artifacts_dir(
    project_id: Optional[int] = None,
    case_dir_key: Optional[str] = None,
) -> str:
    artifacts_dir = _build_skill_artifacts_dir(project_id, case_dir_key)
    if not case_dir_key:
        os.makedirs(artifacts_dir, exist_ok=True)
        return artifacts_dir

    should_clear = False
    if os.path.exists(artifacts_dir):
        latest = _dir_latest_mtime(artifacts_dir)
        if latest and time.time() - latest > _SKILL_DIR_STALE_SECONDS:
            should_clear = True

    if should_clear:
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        logger.info(f"[execute_skill_script] 清空旧产物目录: {artifacts_dir}")

    os.makedirs(artifacts_dir, exist_ok=True)
    return artifacts_dir


def _is_allowed_artifact_file(file_path: str) -> bool:
    if not file_path or not os.path.isfile(file_path) or os.path.islink(file_path):
        return False
    suffix = os.path.splitext(file_path)[1].lower()
    if suffix not in _ARTIFACT_EXTENSIONS:
        return False
    if os.path.basename(file_path).startswith("."):
        return False
    try:
        return os.path.getsize(file_path) <= _MAX_ARTIFACT_SIZE_BYTES
    except OSError:
        return False


def _snapshot_artifact_files(root_dir: str) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root_dir or not os.path.isdir(root_dir):
        return snapshot

    for current_root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        for name in files:
            full_path = os.path.join(current_root, name)
            if not _is_allowed_artifact_file(full_path):
                continue
            rel_path = os.path.relpath(full_path, root_dir).replace(os.sep, "/")
            snapshot[rel_path] = full_path
    return snapshot


def _path_to_media_url(file_path: str) -> Optional[str]:
    try:
        media_root = os.path.abspath(settings.MEDIA_ROOT)
        candidate = os.path.abspath(file_path)
        if os.path.commonpath([media_root, candidate]) != media_root:
            return None
        relative_path = os.path.relpath(candidate, media_root).replace(os.sep, "/")
        return f"{settings.MEDIA_URL.rstrip('/')}/{relative_path}"
    except Exception:
        return None


def _build_artifact_payload(file_path: str) -> Optional[dict[str, object]]:
    media_url = _path_to_media_url(file_path)
    if not media_url:
        return None

    mime_type, _ = mimetypes.guess_type(file_path)
    if file_path.lower().endswith(".drawio"):
        mime_type = mime_type or "application/vnd.jgraph.mxfile"

    payload: dict[str, object] = {
        "type": "file",
        "name": os.path.basename(file_path),
        "url": media_url,
        "path": os.path.relpath(file_path, settings.MEDIA_ROOT).replace(os.sep, "/"),
        "mime_type": mime_type or "application/octet-stream",
    }
    try:
        payload["size"] = os.path.getsize(file_path)
    except OSError:
        pass
    return payload


def _extract_artifact_candidates(text: str) -> list[str]:
    if not text:
        return []

    seen: set[str] = set()
    candidates: list[str] = []
    strip_chars = " \t\r\n()[]{}<>,;:：。，“”‘’"

    for pattern in (_QUOTED_ARTIFACT_TOKEN_RE, _ARTIFACT_TOKEN_RE):
        for match in pattern.finditer(text):
            candidate = (match.group("path") or "").strip(strip_chars)
            if "：" in candidate:
                candidate = candidate.split("：")[-1].strip(strip_chars)
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)

    return candidates


def _find_named_file(root_dir: str, candidate: str) -> Optional[str]:
    if not root_dir or not os.path.isdir(root_dir):
        return None

    normalized_candidate = candidate.replace("\\", os.sep)
    joined_path = os.path.join(root_dir, normalized_candidate.lstrip("./"))
    if _is_allowed_artifact_file(joined_path):
        return joined_path

    basename = os.path.basename(normalized_candidate)
    if not basename:
        return None

    for current_root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        if basename in files:
            full_path = os.path.join(current_root, basename)
            if _is_allowed_artifact_file(full_path):
                return full_path
    return None


def _collect_skill_artifacts(
    output_text: str,
    *,
    skill_dir: str,
    artifacts_dir: str,
    artifacts_before: dict[str, str],
) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    def add_file(file_path: Optional[str]) -> None:
        if not file_path or not _is_allowed_artifact_file(file_path):
            return
        payload = _build_artifact_payload(file_path)
        if not payload:
            return
        media_url = str(payload.get("url") or "")
        if not media_url or media_url in seen_urls:
            return
        seen_urls.add(media_url)
        collected.append(payload)

    artifacts_after = _snapshot_artifact_files(artifacts_dir)
    for rel_path, full_path in artifacts_after.items():
        if rel_path not in artifacts_before:
            add_file(full_path)

    for candidate in _extract_artifact_candidates(output_text):
        if candidate.startswith("/media/"):
            continue
        if os.path.isabs(candidate):
            add_file(candidate)
            continue
        add_file(_find_named_file(artifacts_dir, candidate))
        add_file(_find_named_file(skill_dir, candidate))

    return collected


def _finalize_skill_result(
    result_output: str,
    *,
    skill_dir: str,
    artifacts_dir: str,
    artifacts_before: dict[str, str],
) -> str:
    artifacts = _collect_skill_artifacts(
        result_output,
        skill_dir=skill_dir,
        artifacts_dir=artifacts_dir,
        artifacts_before=artifacts_before,
    )
    if not artifacts:
        return result_output

    text_content = result_output.strip() if result_output and result_output.strip() else ""
    if not text_content:
        text_content = f"已生成 {len(artifacts)} 个文件，可直接下载。"

    payload = [{"type": "text", "text": text_content}, *artifacts]
    return json.dumps(payload, ensure_ascii=False)


def _get_playwright_session_manager() -> PlaywrightSessionManager:
    """延迟初始化，避免在 import 时启动后台清理线程（线程安全）"""
    global _playwright_session_manager
    if _playwright_session_manager is None:
        with _playwright_session_manager_lock:
            if _playwright_session_manager is None:
                idle_timeout = getattr(
                    settings, "PLAYWRIGHT_BROWSER_SESSION_IDLE_TIMEOUT_SECONDS", 15 * 60
                )
                max_sessions = getattr(settings, "PLAYWRIGHT_BROWSER_MAX_SESSIONS", 20)
                _playwright_session_manager = PlaywrightSessionManager(
                    idle_timeout_seconds=int(idle_timeout),
                    max_sessions=int(max_sessions),
                )
    return _playwright_session_manager


def _resolve_skill_runtime_api_key(user_id: int) -> tuple[str, str]:
    """解析 Skill 运行时使用的 API Key。

    优先级：
    1. 非空的 settings/环境变量 WHARTTEST_API_KEY（运维覆盖）
    2. 当前对话用户名下最新一条有效 API Key
    3. 空字符串（不注入，保留 skill 脚本内默认值）

    Returns:
        (api_key, source_label) source_label 仅用于日志，不含密钥内容。
    """
    configured = (
        getattr(settings, "WHARTTEST_API_KEY", None)
        or os.environ.get("WHARTTEST_API_KEY")
        or ""
    ).strip()
    if configured:
        return configured, "env_or_settings"

    if not user_id:
        return "", "none"

    try:
        from api_keys.models import APIKey
    except ImportError:
        logger.debug(
            "[execute_skill_script] api_keys 应用不可用，跳过用户 Key 解析 user_id=%s",
            user_id,
        )
        return "", "none"

    try:
        for key_obj in APIKey.objects.filter(user_id=user_id, is_active=True).order_by(
            "-created_at"
        ):
            if key_obj.is_valid() and (key_obj.key or "").strip():
                return key_obj.key.strip(), f"user_key_id={key_obj.id}"
    except Exception as e:
        logger.error(
            "[execute_skill_script] 读取用户 API Key 失败 user_id=%s: %s",
            user_id,
            e,
            exc_info=True,
        )
        return "", "error"
    return "", "none"


def _resolve_skill_runtime_backend_url() -> str:
    """Skill 在 backend 进程内执行时，默认回环访问本服务。"""
    configured = (
        getattr(settings, "WHARTTEST_BACKEND_URL", None)
        or os.environ.get("WHARTTEST_BACKEND_URL")
        or ""
    ).strip()
    if configured:
        return configured.rstrip("/")
    # 容器/本机同进程：默认本机 8000，避免 skill 脚本默认 127.0.0.1 与部署端口不一致时无覆盖
    return "http://127.0.0.1:8000"


# 客户端证书配置：backend 侧变量名 -> 注入给 skill 子进程的变量名
_CLIENT_CERT_ENV_MAP = (
    ("PLAYWRIGHT_CLIENT_CERT_PFX", "PW_CLIENT_CERT_PFX"),
    ("PLAYWRIGHT_CLIENT_CERT_PASSPHRASE", "PW_CLIENT_CERT_PASSPHRASE"),
    ("PLAYWRIGHT_CLIENT_CERT_CERT", "PW_CLIENT_CERT_CERT"),
    ("PLAYWRIGHT_CLIENT_CERT_KEY", "PW_CLIENT_CERT_KEY"),
    ("PLAYWRIGHT_CLIENT_CERT_ORIGINS", "PW_CLIENT_CERT_ORIGINS"),
    ("PLAYWRIGHT_IGNORE_HTTPS_ERRORS", "PW_IGNORE_HTTPS_ERRORS"),
)

# 这些变量在日志中必须脱敏
_CLIENT_CERT_SECRET_ENV = frozenset({"PW_CLIENT_CERT_PASSPHRASE"})


def _resolve_skill_client_cert_env() -> dict:
    """解析要注入给 skill 子进程的 HTTPS 客户端证书环境变量。

    取值优先级：Django settings -> 进程环境变量。空值不注入（避免用空串覆盖 skill 侧默认）。

    注意：证书路径必须是 **backend 容器内可见的绝对路径** —— Node 子进程的 cwd 是 skill 目录
    （MEDIA_ROOT 下），相对路径不可预期。
    """
    resolved: dict = {}
    for setting_name, env_name in _CLIENT_CERT_ENV_MAP:
        value = getattr(settings, setting_name, None)
        if value is None:
            value = os.environ.get(setting_name)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        resolved[env_name] = text
    return resolved


def _redact_client_cert_env(cert_env: dict) -> dict:
    """日志用：口令脱敏，只保留路径与 origin，便于排查配置问题。"""
    return {
        key: ("***" if key in _CLIENT_CERT_SECRET_ENV else value)
        for key, value in cert_env.items()
    }


def get_skill_tools(
    user_id: int,
    project_id: Optional[int] = None,
    test_case_id: Optional[int] = None,
    chat_session_id: Optional[str] = None,
) -> list[object]:
    """获取 Skill 工具列表（Skills 全局共享，不限制项目）"""
    current_user_id = user_id
    current_project_id = project_id if project_id is not None else 0
    current_test_case_id = test_case_id
    current_chat_session_id = chat_session_id

    @langchain_tool
    def read_skill_content(skill_name: str) -> str:
        """
        读取指定 Skill 的完整 SKILL.md 内容。

        当你需要使用某个 Skill 时，先调用此工具获取详细的使用说明。
        系统提示词中只包含 Skill 的名称和简短描述，完整的指令和示例需要通过此工具获取。

        Args:
            skill_name: Skill 名称

        Returns:
            SKILL.md 的完整内容，包含详细的使用说明和示例
        """
        from skills.models import Skill

        logger.info(f"[read_skill_content] skill_name={skill_name}")

        try:
            skill = Skill.objects.filter(name=skill_name, is_active=True).first()

            if not skill:
                available = Skill.objects.filter(is_active=True).values_list(
                    "name", flat=True
                )
                available_list = list(available)
                return f"错误: 未找到名为 '{skill_name}' 的 Skill。可用的 Skills: {available_list}"

            if not skill.skill_content:
                return f"错误: Skill '{skill_name}' 没有 SKILL.md 内容"

            return skill.skill_content

        except Exception as e:
            logger.error(f"[read_skill_content] 读取失败: {e}", exc_info=True)
            return f"错误: {str(e)}"

    def _execute_single_skill_script(
        skill_name: str,
        command: str,
        session_id: Optional[str] = None,
    ) -> str:
        """内部函数：执行单条 Skill 命令"""
        from skills.models import Skill

        # 重复调用拦截：按「会话 + Skill + 命令」统计，只影响只读命令
        dedup_key = ""
        occurrence = 1
        if _SKILL_DEDUP_ENABLED:
            session_scope = current_chat_session_id or f"project:{current_project_id}"
            dedup_key = _build_skill_dedup_key(session_scope, skill_name, command)
            occurrence, cached_result, cached_age = _skill_call_cache.touch(dedup_key)
            if (
                _is_read_only_skill_command(command)
                and cached_result is not None
                and occurrence > _SKILL_DEDUP_MIN_REPEAT
            ):
                logger.warning(
                    "[execute_skill_script] 重复调用拦截 skill=%s occurrence=%d age=%.0fs",
                    skill_name,
                    occurrence,
                    cached_age,
                )
                return _build_repeat_short_circuit_notice(
                    skill_name=skill_name,
                    count=occurrence,
                    age_seconds=cached_age,
                    cached_result=cached_result,
                )

        logger.info(
            f"[execute_skill_script] skill_name={skill_name}, command={command}"
        )

        try:
            skill = Skill.objects.filter(name=skill_name, is_active=True).first()

            if not skill:
                available = Skill.objects.filter(is_active=True).values_list(
                    "name", flat=True
                )
                available_list = list(available)
                return f"错误: 未找到名为 '{skill_name}' 的 Skill。可用的 Skills: {available_list}"

            skill_dir = skill.get_full_path()
            if not skill_dir or not os.path.isdir(skill_dir):
                return f"错误: Skill '{skill_name}' 目录不存在"

            logger.info(f"[execute_skill_script] 在目录 {skill_dir} 执行: {command}")

            env = os.environ.copy()
            # 1) 运维配置 / 2) 当前用户有效 API Key / 3) 不注入（保留脚本默认）
            backend_url = _resolve_skill_runtime_backend_url()
            api_key, key_source = _resolve_skill_runtime_api_key(current_user_id)
            if backend_url:
                env["WHARTTEST_BACKEND_URL"] = backend_url
            if api_key:
                env["WHARTTEST_API_KEY"] = api_key
                logger.info(
                    "[execute_skill_script] 已注入运行时 API Key (user_id=%s, source=%s)",
                    current_user_id,
                    key_source,
                )
            else:
                logger.warning(
                    "[execute_skill_script] 未找到可用 API Key (user_id=%s, source=%s)，"
                    "将依赖 skill 脚本内默认值（可能 401）",
                    current_user_id,
                    key_source,
                )

            case_dir_key = None
            if current_test_case_id:
                case_dir_key = str(current_test_case_id)
            elif session_id:
                case_dir_key = session_id

            screenshots_dir = _prepare_skill_screenshots_dir(
                project_id=current_project_id,
                case_dir_key=case_dir_key,
            )
            env["SCREENSHOT_DIR"] = screenshots_dir
            artifacts_dir = _prepare_skill_artifacts_dir(
                project_id=current_project_id,
                case_dir_key=case_dir_key,
            )
            env["SKILL_OUTPUT_DIR"] = artifacts_dir
            env["ARTIFACT_DIR"] = artifacts_dir

            # HTTPS 客户端证书（可选）：口令只注入，绝不写日志
            cert_env = _resolve_skill_client_cert_env()
            if cert_env:
                env.update(cert_env)
                logger.info(
                    "[execute_skill_script] 已注入 HTTPS 客户端证书配置: %s",
                    _redact_client_cert_env(cert_env),
                )

            artifacts_before = _snapshot_artifact_files(artifacts_dir)

            # Windows 兼容：将单引号包裹的参数转换为双引号（用于 cmd.exe）
            # 同时处理多行字符串，将换行符转换为单行
            import platform
            import re

            exec_command = command
            if platform.system() == "Windows":
                # 处理多行字符串：将双引号内的换行符替换为空格或分号
                def collapse_multiline(m):
                    content = m.group(1)
                    # 将换行替换为空格，保持代码可执行
                    collapsed = " ".join(
                        line.strip() for line in content.split("\n") if line.strip()
                    )
                    return f'"{collapsed}"'

                # 匹配 "..." 形式的多行字符串
                exec_command = re.sub(r'"([^"]*\n[^"]*)"', collapse_multiline, command)

                # 单引号转双引号
                def convert_quotes(m):
                    param = m.group(1)
                    value = m.group(2)
                    escaped = value.replace('"', '\\"')
                    return f'{param}"{escaped}"'

                exec_command = re.sub(
                    r"(--\w+\s+)'([^']*)'", convert_quotes, exec_command
                )

                if exec_command != command:
                    logger.info(f"[execute_skill_script] Windows 命令转换完成")

            # 持久化 Playwright 会话路径
            # 仅当 session_id 存在 + skill_name == 'playwright-skill' + 命令是 run.js 调用时启用
            if session_id and skill_name == "playwright-skill":
                run_js_args = extract_runjs_args(exec_command)
                if run_js_args is not None:
                    # 调试日志
                    logger.debug(f"[execute_skill_script] run_js_args: {run_js_args}")
                    # session_key 包含 chat_session_id 以隔离不同对话的浏览器会话
                    chat_id_part = current_chat_session_id or "default"
                    session_key = f"{current_user_id}_{current_project_id}_{chat_id_part}_{session_id}"
                    try:
                        manager = _get_playwright_session_manager()
                        output = manager.execute_run_js(
                            session_key=session_key,
                            skill_dir=skill_dir,
                            run_js_args=run_js_args,
                            env=env,
                            timeout_seconds=120,
                        )
                        logger.info(
                            f"[execute_skill_script] 持久化会话执行完成, session_key={session_key}"
                        )
                        cleaned_output = strip_terminal_control_sequences(output)
                        result_output = (
                            cleaned_output.strip()
                            if cleaned_output.strip()
                            else "(无输出)"
                        )
                        result_output = (
                            f'[PERSISTENT_SESSION] session_id={session_id}\n'
                            f'[SCREENSHOT_DIR] {screenshots_dir}\n'
                            f'{result_output}\n'
                            f'[提示] 后续步骤请继续使用 session_id="{session_id}"；截图已保存在 {screenshots_dir}'
                        )
                        return _finalize_skill_result(
                            result_output,
                            skill_dir=skill_dir,
                            artifacts_dir=artifacts_dir,
                            artifacts_before=artifacts_before,
                        )
                    except TimeoutError:
                        logger.error(
                            "[execute_skill_script] 持久化 Playwright 执行超时"
                        )
                        return "错误: 命令执行超时（120秒）"
                    except Exception as e:
                        logger.error(
                            f"[execute_skill_script] 持久化 Playwright 执行失败: {e}",
                            exc_info=True,
                        )
                        return f"错误: {str(e)}"

            # Windows 编码处理：cmd.exe 默认使用 GBK (cp936)，需要使用系统默认编码
            import locale

            # playwright-cli 在只读的 skill 目录下以相对文件名保存截图会 EACCES，
            # 改在可写的截图目录执行，使截图默认落入 SCREENSHOT_DIR
            exec_cwd = screenshots_dir if skill_name == "playwright-cli" else skill_dir

            if platform.system() == "Windows":
                # Windows cmd 默认使用 GBK 编码，使用 None 让 subprocess 自动检测
                result = subprocess.run(
                    exec_command,
                    shell=True,
                    cwd=exec_cwd,
                    capture_output=True,
                    timeout=120,
                    env=env,
                )

                # 智能解码：先尝试 UTF-8（现代工具通常输出 UTF-8），失败再用 GBK（Windows cmd 默认）
                def smart_decode(data: bytes) -> str:
                    if not data:
                        return ""
                    try:
                        return data.decode("utf-8")
                    except UnicodeDecodeError:
                        return data.decode("gbk", errors="replace")

                stdout = strip_terminal_control_sequences(smart_decode(result.stdout))
                stderr = strip_terminal_control_sequences(smart_decode(result.stderr))
            else:
                result = subprocess.run(
                    exec_command,
                    shell=True,
                    cwd=exec_cwd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )
                stdout = strip_terminal_control_sequences(result.stdout or "")
                stderr = strip_terminal_control_sequences(result.stderr or "")

            output = ""
            if stdout:
                output += stdout
            if stderr:
                if output:
                    output += "\n--- stderr ---\n"
                output += stderr

            if result.returncode != 0:
                output = f"命令执行失败 (退出码: {result.returncode})\n{output}"

            logger.info(
                f"[execute_skill_script] 执行完成, returncode={result.returncode}, output_len={len(output)}"
            )
            if output:
                logger.debug(f"[execute_skill_script] output: {output[:500]}")
            result_output = output.strip() if output.strip() else "(无输出)"

            # 如果是 playwright-skill 的 run.js 调用但没有使用 session_id，提醒 LLM
            if (
                skill_name == "playwright-skill"
                and "run.js" in command
                and not session_id
            ):
                result_output = f"[SCREENSHOT_DIR] {screenshots_dir}\n{result_output}\n\n[注意] 此次执行未使用 session_id，浏览器已关闭。如果这是多步骤测试的一部分，请在后续调用中使用 session_id 参数保持浏览器会话。"
            elif skill_name == "playwright-skill":
                result_output = f"[SCREENSHOT_DIR] {screenshots_dir}\n{result_output}"
            elif occurrence > 1:
                # 写命令不短路，但要让模型明确看到「这是重复调用」
                result_output = (
                    _build_repeat_reminder_prefix(occurrence) + result_output
                )

            if dedup_key:
                _skill_call_cache.store(dedup_key, result_output)

            return _finalize_skill_result(
                result_output,
                skill_dir=skill_dir,
                artifacts_dir=artifacts_dir,
                artifacts_before=artifacts_before,
            )

        except subprocess.TimeoutExpired:
            logger.error("[execute_skill_script] 执行超时")
            return "错误: 命令执行超时（120秒）"
        except Exception as e:
            logger.error(f"[execute_skill_script] 执行失败: {e}", exc_info=True)
            return f"错误: {str(e)}"

    @langchain_tool
    def execute_skill_script(
        skill_name: Optional[str] = None,
        command: Optional[str] = None,
        session_id: Optional[str] = None,
        commands: Optional[list[dict[str, str]]] = None,
        parallel: bool = True,
        max_workers: int = 5,
    ) -> str:
        """
        执行 Skill 命令，支持单个执行或批量并发执行。

        **单个执行模式**：传入 skill_name 和 command
        **批量执行模式**：传入 commands 列表（自动并发，大幅提升效率）

        Args:
            skill_name: Skill 名称（单个执行时必填）
            command: shell 命令，如 "python whart_tools.py --action get_projects"（单个执行时必填）
            session_id: 可选会话ID，用于 playwright-skill 保持浏览器会话
            commands: 批量命令列表，每个元素包含 skill_name、command、session_id（可选）
                示例: [
                    {"skill_name": "whart-test", "command": "python whart_tools.py --action add_testcase ..."},
                    {"skill_name": "whart-test", "command": "python whart_tools.py --action add_testcase ..."}
                ]
            parallel: 批量模式下是否并发执行（默认 True）
            max_workers: 批量模式下最大并发数（默认 5）

        Returns:
            单个模式返回命令输出；如执行中生成了文件，会追加可下载附件信息。
            Skills 可将导出文件写入 `SKILL_OUTPUT_DIR`（或 `ARTIFACT_DIR`）以便 Web 端直接下载。
            批量模式返回 JSON 格式结果汇总
        """
        import json
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from django.db import close_old_connections

        # 批量执行模式
        if commands:
            logger.info(
                f"[execute_skill_script] 批量模式: {len(commands)} 条命令, parallel={parallel}, max_workers={max_workers}"
            )

            if not commands:
                return json.dumps({"error": "命令列表为空"}, ensure_ascii=False)

            def execute_single(idx: int, cmd: dict[str, str]) -> dict[str, object]:
                cmd_skill_name = cmd.get("skill_name")
                cmd_command = cmd.get("command")
                cmd_session_id = cmd.get("session_id")

                if not cmd_skill_name or not cmd_command:
                    return {
                        "index": idx,
                        "skill_name": cmd_skill_name,
                        "command": cmd_command,
                        "error": "缺少 skill_name 或 command",
                    }

                try:
                    result = _execute_single_skill_script(
                        cmd_skill_name, cmd_command, cmd_session_id
                    )
                    return {
                        "index": idx,
                        "skill_name": cmd_skill_name,
                        "command": cmd_command,
                        "result": result,
                    }
                except Exception as e:
                    return {
                        "index": idx,
                        "skill_name": cmd_skill_name,
                        "command": cmd_command,
                        "error": str(e),
                    }
                finally:
                    close_old_connections()

            results: list[Optional[dict[str, object]]] = [None] * len(commands)

            if parallel and len(commands) > 1:
                with ThreadPoolExecutor(
                    max_workers=min(max_workers, len(commands))
                ) as executor:
                    future_to_idx = {
                        executor.submit(execute_single, idx, cmd): idx
                        for idx, cmd in enumerate(commands)
                    }
                    for future in as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        results[idx] = future.result()
            else:
                for idx, cmd in enumerate(commands):
                    results[idx] = execute_single(idx, cmd)

            success_count = sum(
                1
                for r in results
                if r is not None and "result" in r and "error" not in r
            )
            error_count = len(results) - success_count

            logger.info(
                f"[execute_skill_script] 批量完成: {success_count} 成功, {error_count} 失败"
            )

            return json.dumps(
                {
                    "summary": {
                        "total": len(commands),
                        "success": success_count,
                        "error": error_count,
                        "parallel": parallel,
                    },
                    "results": [r for r in results if r is not None],
                },
                ensure_ascii=False,
                indent=2,
            )

        # 单个执行模式
        if not skill_name or not command:
            return "错误: 单个执行模式需要提供 skill_name 和 command 参数"

        return _execute_single_skill_script(skill_name, command, session_id)

    return [read_skill_content, execute_skill_script]
