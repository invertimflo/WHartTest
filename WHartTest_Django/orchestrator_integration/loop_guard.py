"""
Agent Loop 重复工具调用守卫（Loop Guard）

背景
----
弱模型（如 qwen3-coder）在「工具集与提示词不匹配」或「工具返回空结果」时，
会进入机械重试：以完全相同的参数反复调用同一个工具，且不产出任何文本。
框架侧原先没有任何重复调用检测，唯一终止条件是 recursion_limit，
表现为用户长时间等待后只拿到一条不可读的报错。

本模块提供三层守卫中可复用的两部分：
1. 纯函数：签名归一化 + 重复步判定（可单测，不依赖 LLM）
2. `build_loop_guard_middleware()`：在模型调用前检测重复，
   首次命中注入纠偏消息（给模型一次自救机会），再次命中直接结束循环。

设计要点
--------
- 判定要求「工具 + 参数 + 返回结果」三者完全一致，规避「同参轮询但结果在变」的误判。
- 注入的纠偏消息带 `additional_kwargs["loop_guard"]`，可识别、可去重、可清理。
- 所有阈值均可通过环境变量调整。
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware import before_model

logger = logging.getLogger(__name__)

# create_agent 在 langchain v1 中的节点名是 "model"；"agent" 仅为兼容旧版本保留
MODEL_NODE_NAMES = frozenset({"model", "agent"})
TOOL_NODE_NAME = "tools"

LOOP_GUARD_WARN = "warn"
LOOP_GUARD_ABORT = "abort"
LOOP_GUARD_NONE = "none"

# `additional_kwargs` 中用于标记纠偏消息的键
LOOP_GUARD_MARKER = "loop_guard"


# ============== 环境变量读取 ==============


def _get_env_int(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(min_value, int(raw))
    except ValueError:
        logger.warning(
            "LoopGuard: Invalid int env %s=%s, fallback=%s", name, raw, default
        )
        return default


def _get_env_float(name: str, default: float, min_value: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(min_value, float(raw))
    except ValueError:
        logger.warning(
            "LoopGuard: Invalid float env %s=%s, fallback=%s", name, raw, default
        )
        return default


def _get_env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ============== 配置 ==============

_REPEAT_WARN_DEFAULT = 3
_REPEAT_ABORT_DEFAULT = 5
_REPEAT_WINDOW_DEFAULT = 12


@dataclass(frozen=True)
class LoopGuardConfig:
    """重复调用守卫配置（环境变量可覆盖）"""

    enabled: bool = True
    warn: int = _REPEAT_WARN_DEFAULT
    abort: int = _REPEAT_ABORT_DEFAULT
    window: int = _REPEAT_WINDOW_DEFAULT
    require_same_result: bool = True
    truncate_head_ratio: float = 0.6
    max_sse_tool_output_chars: int = 4000


def load_loop_guard_config() -> LoopGuardConfig:
    """从环境变量装配守卫配置，并保证 warn < abort"""
    warn = _get_env_int("AGENT_LOOP_REPEAT_WARN", _REPEAT_WARN_DEFAULT, min_value=2)
    abort = _get_env_int(
        "AGENT_LOOP_REPEAT_ABORT", _REPEAT_ABORT_DEFAULT, min_value=2
    )
    # abort 必须严格大于 warn，否则纠偏机会会被跳过
    if abort <= warn:
        abort = warn + 1

    return LoopGuardConfig(
        enabled=_get_env_bool("AGENT_LOOP_LOOP_GUARD_ENABLED", True),
        warn=warn,
        abort=abort,
        window=_get_env_int(
            "AGENT_LOOP_REPEAT_WINDOW", _REPEAT_WINDOW_DEFAULT, min_value=2
        ),
        require_same_result=_get_env_bool(
            "AGENT_LOOP_REPEAT_REQUIRE_SAME_RESULT", True
        ),
        truncate_head_ratio=min(
            0.9,
            _get_env_float("AGENT_LOOP_TOOL_TRUNCATE_HEAD_RATIO", 0.6, min_value=0.1),
        ),
        max_sse_tool_output_chars=_get_env_int(
            "AGENT_LOOP_MAX_SSE_TOOL_OUTPUT_CHARS", 4000, min_value=200
        ),
    )


# ============== 签名归一化 ==============

_WHITESPACE_RE = re.compile(r"\s+")


def _canonical(value: Any) -> Any:
    """
    递归规范化参数，消除无语义的格式差异：
    - dict 按 key 排序（参数顺序不影响签名）
    - list/tuple 保持原序（顺序通常有语义）
    - 字符串折叠连续空白并去首尾空白（抗多行/多空格书写差异）
    """
    if isinstance(value, dict):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, str):
        return _WHITESPACE_RE.sub(" ", value).strip()
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _digest(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


def normalize_tool_signature(tool_name: str, args: Any) -> str:
    """把一次工具调用归一化为稳定签名：`{tool_name}::{args_digest}`"""
    try:
        payload = json.dumps(
            _canonical(args), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        payload = str(args)
    return f"{(tool_name or 'unknown').strip()}::{_digest(payload)}"


def _tool_call_field(tool_call: Any, key: str) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(key)
    return getattr(tool_call, key, None)


def step_signatures(message: Any) -> Tuple[str, ...]:
    """
    计算一条 AIMessage 中所有 tool_call 的签名多元组。
    返回空元组表示该消息不含工具调用。
    同一轮批量调用内顺序无语义，故排序后比较。
    """
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return ()
    signatures = []
    for tool_call in tool_calls:
        name = _tool_call_field(tool_call, "name")
        args = _tool_call_field(tool_call, "args")
        if args is None:
            args = _tool_call_field(tool_call, "arguments")
        signatures.append(normalize_tool_signature(str(name or "unknown"), args))
    return tuple(sorted(signatures))


def content_digest(message: Any) -> str:
    """计算消息内容的摘要；内容为空返回空串（调用方视为「未知」）"""
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            content = str(content)
    return _digest(content)


# ============== 重复步判定 ==============


@dataclass
class ToolStep:
    """一步工具调用：模型发出的签名 + 该步工具返回结果摘要"""

    signatures: Tuple[str, ...] = ()
    result_digests: Tuple[str, ...] = ()


def steps_from_messages(messages: List[Any]) -> List[ToolStep]:
    """
    从消息列表中还原「工具调用步」序列。
    一步 = 一条带 tool_calls 的 AIMessage + 紧随其后的若干 ToolMessage。
    """
    steps: List[ToolStep] = []
    current: Optional[ToolStep] = None

    for message in messages:
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            signatures = step_signatures(message)
            if not signatures:
                continue
            current = ToolStep(signatures=signatures)
            steps.append(current)
            continue

        if isinstance(message, ToolMessage) and current is not None:
            digest = content_digest(message)
            if digest:
                current.result_digests = current.result_digests + (digest,)
            continue

        # 遇到其它消息（HumanMessage / 无 tool_calls 的 AIMessage）视为一轮结束
        current = None

    return steps


def count_trailing_repeats(
    steps: List[ToolStep], require_same_result: bool = True
) -> int:
    """
    统计尾部连续重复的步数。

    - 相邻两步签名必须完全一致
    - require_same_result=True 时，还要求两步的工具返回结果摘要一致
      （结果摘要未知的一方不参与比较，避免中断统计）
    """
    if not steps:
        return 0

    count = 1
    for index in range(len(steps) - 1, 0, -1):
        current = steps[index]
        previous = steps[index - 1]
        if current.signatures != previous.signatures:
            break
        if require_same_result:
            if (
                current.result_digests
                and previous.result_digests
                and current.result_digests != previous.result_digests
            ):
                break
        count += 1
    return count


@dataclass
class RepeatVerdict:
    """重复调用判定结果"""

    level: str = LOOP_GUARD_NONE
    tool: Optional[str] = None
    signature: Optional[str] = None
    count: int = 0
    window: int = 0
    signatures: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "tool": self.tool,
            "signature": self.signature,
            "count": self.count,
            "window": self.window,
        }


def _representative_signature(signatures: Tuple[str, ...]) -> Optional[str]:
    if not signatures:
        return None
    return "|".join(signatures)


def _tool_names_from_signatures(signatures: Tuple[str, ...]) -> str:
    names = []
    for signature in signatures:
        name = signature.split("::", 1)[0]
        if name and name not in names:
            names.append(name)
    return ", ".join(names) if names else "unknown"


def evaluate_repeats(
    messages: List[Any],
    warn: int = _REPEAT_WARN_DEFAULT,
    abort: int = _REPEAT_ABORT_DEFAULT,
    window: int = _REPEAT_WINDOW_DEFAULT,
    require_same_result: bool = True,
) -> RepeatVerdict:
    """
    判定最近是否陷入工具调用死循环。

    只看最近 `window` 步，尾部连续重复次数达到 warn / abort 阈值时给出对应等级。
    """
    steps = steps_from_messages(messages or [])
    if not steps:
        return RepeatVerdict(level=LOOP_GUARD_NONE, window=window)

    recent = steps[-max(2, window) :]
    count = count_trailing_repeats(recent, require_same_result=require_same_result)
    if count < max(2, warn):
        return RepeatVerdict(level=LOOP_GUARD_NONE, window=window, count=count)

    last = recent[-1]
    verdict = RepeatVerdict(
        tool=_tool_names_from_signatures(last.signatures),
        signature=_representative_signature(last.signatures),
        count=count,
        window=window,
        signatures=last.signatures,
    )
    verdict.level = LOOP_GUARD_ABORT if count >= abort else LOOP_GUARD_WARN
    return verdict


# ============== 纠偏 / 中止文案 ==============

WARN_MESSAGE_TEMPLATE = (
    "[系统纠偏] 检测到你已连续第 {count} 次以完全相同的参数调用工具 `{tool}`，"
    "且该工具每次返回的结果完全一致（结果未发生变化）。重复调用不会带来任何新信息。\n"
    "请立即停止重复调用，并改为以下三种做法之一：\n"
    "1) 直接基于已有工具结果继续后续步骤；\n"
    "2) 调整参数后重试（更换 action、分页、缩小或扩大查询范围）；\n"
    "3) 直接输出分析结论，或如实说明当前阻塞原因（例如「该模块下暂无测试用例」）。\n"
    "注意：若再次以相同参数调用该工具，本次执行将被自动终止。"
)

ABORT_MESSAGE_TEMPLATE = (
    "本次执行已自动终止：工具 `{tool}` 连续 {count} 次以完全相同的参数调用，"
    "且每次返回结果完全一致，模型始终未取得有效进展（疑似工具调用死循环）。\n"
    "可能原因与建议：\n"
    "1) 工具返回结果不符合预期（例如查询结果为空，表示该范围内暂无数据），"
    "请调整查询范围或参数后重试；\n"
    "2) 所需能力当前不可用（例如提示词中提及的工具未在工具列表中下发），"
    "请改用已下发的工具或说明该能力不可用；\n"
    "3) 若问题持续，建议拆分需求范围、更换模型或调整提示词后重试。"
)


def build_warn_message(verdict: RepeatVerdict) -> str:
    return WARN_MESSAGE_TEMPLATE.format(tool=verdict.tool or "unknown", count=verdict.count)


def build_abort_message(verdict: RepeatVerdict) -> str:
    return ABORT_MESSAGE_TEMPLATE.format(tool=verdict.tool or "unknown", count=verdict.count)


# ============== 事件总线 ==============


class LoopGuardEventBus:
    """向 SSE 流处理层单向传递守卫事件（同一请求内，进程内即可）"""

    def __init__(self, ttl_seconds: int = 600, max_events_per_session: int = 20):
        self._events: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max_events = max_events_per_session

    def push(self, session_id: str, event: Dict[str, Any]) -> None:
        if not session_id:
            return
        with self._lock:
            bucket = self._events.setdefault(session_id, [])
            bucket.append((time.time(), event))
            if len(bucket) > self._max_events:
                del bucket[: len(bucket) - self._max_events]

    def drain(self, session_id: str) -> List[Dict[str, Any]]:
        """取出并清空指定会话的事件（同时清理过期会话）"""
        if not session_id:
            return []
        now = time.time()
        with self._lock:
            expired = [
                key
                for key, bucket in self._events.items()
                if key != session_id
                and (not bucket or now - bucket[-1][0] > self._ttl)
            ]
            for key in expired:
                del self._events[key]

            bucket = self._events.pop(session_id, [])
        return [event for timestamp, event in bucket if now - timestamp <= self._ttl]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._events.pop(session_id, None)


_loop_guard_bus: Optional[LoopGuardEventBus] = None
_bus_lock = threading.Lock()


def get_loop_guard_bus() -> LoopGuardEventBus:
    """获取全局守卫事件总线单例"""
    global _loop_guard_bus
    if _loop_guard_bus is None:
        with _bus_lock:
            if _loop_guard_bus is None:
                _loop_guard_bus = LoopGuardEventBus()
    return _loop_guard_bus


# ============== 中间件 ==============


def _state_messages(state: Any) -> List[Any]:
    if isinstance(state, dict):
        return list(state.get("messages") or [])
    messages = getattr(state, "messages", None)
    return list(messages or [])


def _already_warned(messages: List[Any], signature: Optional[str]) -> bool:
    """同一签名的纠偏消息只注入一次（状态内判定，不依赖进程内计数）"""
    for message in messages:
        kwargs = getattr(message, "additional_kwargs", None) or {}
        if not isinstance(kwargs, dict):
            continue
        if kwargs.get(LOOP_GUARD_MARKER) != LOOP_GUARD_WARN:
            continue
        if signature is None or kwargs.get("signature") == signature:
            return True
    return False


def build_loop_guard_middleware(
    *,
    session_id: str,
    config: Optional[LoopGuardConfig] = None,
    bus: Optional[LoopGuardEventBus] = None,
):
    """
    构建重复工具调用守卫中间件。

    - 首次命中 warn 阈值：注入一条纠偏 HumanMessage，给模型一次自救机会
    - 命中 abort 阈值：写入中止说明并 jump_to="end"，干净地结束本轮循环

    返回 langchain 的 AgentMiddleware 实例，可直接放进 create_agent(middleware=[...])。
    """
    cfg = config or load_loop_guard_config()
    event_bus = bus or get_loop_guard_bus()

    @before_model(can_jump_to=["end"])
    def _loop_guard_before_model(state: Any, runtime: Any):  # noqa: ANN001
        try:
            messages = _state_messages(state)
            if not messages:
                return None

            verdict = evaluate_repeats(
                messages,
                warn=cfg.warn,
                abort=cfg.abort,
                window=cfg.window,
                require_same_result=cfg.require_same_result,
            )
            if verdict.level == LOOP_GUARD_NONE:
                return None

            if verdict.level == LOOP_GUARD_WARN:
                if _already_warned(messages, verdict.signature):
                    return None
                text = build_warn_message(verdict)
                event_bus.push(
                    session_id,
                    {"kind": LOOP_GUARD_WARN, "message": text, **verdict.as_dict()},
                )
                logger.warning(
                    "[LoopGuard] action=warn session_id=%s tool=%s signature=%s repeat_count=%s window=%s",
                    session_id,
                    verdict.tool,
                    verdict.signature,
                    verdict.count,
                    verdict.window,
                )
                return {
                    "messages": [
                        HumanMessage(
                            content=text,
                            additional_kwargs={
                                LOOP_GUARD_MARKER: LOOP_GUARD_WARN,
                                "signature": verdict.signature,
                            },
                        )
                    ]
                }

            text = build_abort_message(verdict)
            event_bus.push(
                session_id,
                {"kind": LOOP_GUARD_ABORT, "message": text, **verdict.as_dict()},
            )
            logger.warning(
                "[LoopGuard] action=abort session_id=%s tool=%s signature=%s repeat_count=%s window=%s",
                session_id,
                verdict.tool,
                verdict.signature,
                verdict.count,
                verdict.window,
            )
            return {
                "messages": [
                    AIMessage(
                        content=text,
                        additional_kwargs={
                            LOOP_GUARD_MARKER: LOOP_GUARD_ABORT,
                            "signature": verdict.signature,
                        },
                    )
                ],
                "jump_to": "end",
            }
        except Exception as exc:  # 守卫自身绝不阻断主流程
            logger.error("[LoopGuard] before_model failed: %s", exc, exc_info=True)
            return None

    return _loop_guard_before_model


# ============== 工具输出截断 ==============

_TRUNCATE_MARKER_BUDGET = 80


def truncate_tool_content(content: str, limit: int, head_ratio: float = 0.6) -> str:
    """
    头尾保留式截断：保留头部上下文与尾部结论，中间以明确标注省略。

    相比「整体替换为占位符」，模型仍能看到关键信息，避免因「看不到结果」而重复调用。
    """
    if not isinstance(content, str) or limit <= 0 or len(content) <= limit:
        return content

    head_len = max(1, int(limit * head_ratio))
    tail_len = max(0, limit - head_len - _TRUNCATE_MARKER_BUDGET)
    omitted = len(content) - head_len - tail_len
    if omitted <= 0:
        return content[:limit]

    marker = (
        f"\n...[内容过长，已省略中间 {omitted} 个字符；"
        f"请勿重复调用同一工具，如需更多内容请缩小查询范围]...\n"
    )
    head = content[:head_len]
    tail = content[-tail_len:] if tail_len else ""
    return f"{head}{marker}{tail}"
