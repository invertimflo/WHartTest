"""
Agent Loop SSE 心跳与看门狗包装器

背景
----
接入思考型本地模型（如 qwen3.8-flash-next）后，模型在真正产出第一个 token 之前
可能静默 1~5 分钟。原实现的 SSE 通道在这种情况下**一个字节都不发**，导致：

1. 反向代理（nginx `proxy_read_timeout`）、浏览器、负载均衡器可能直接掐断连接；
2. 前端拿不到任何"仍然活着"的信号，只能无限转圈，用户感知为"卡死"；
3. httpx 的 read timeout（默认 120s）会先于任何业务逻辑触发，重试又从头生成。

本模块在**不修改流生成器内部逻辑**的前提下，于消费层叠加：

- 周期性心跳帧（默认 10s），保证链路始终有数据流动，并驱动前端"模型思考中 120s"；
- 分阶段空闲看门狗：模型阶段静默超 240s、工具阶段静默超 900s 判定为卡死；
- 单轮总时长上限（默认 1800s）；
- 客户端断开时主动 cancel 内层生成器并 `aclose()`，确保 `agent.astream`
  与底层 LLM 请求被真正取消（否则后端会在无人消费的情况下继续烧算力）。

设计要点
--------
- 心跳帧沿用 `data: {...}\\n\\n` 格式，前端解析器只处理 `data: ` 前缀，
  未知 `type` 会被静默忽略，因此对现有前端零破坏。
- 内层生成器由独立 task 驱动，通过有界队列做背压，避免快模型把内存打满。
- 只有真正"产出了帧"才刷新活跃时间；心跳本身不算活跃，
  否则看门狗永远不会触发。

环境变量
--------
- `AGENT_LOOP_SSE_GUARD`            总开关，0/false 时不包装（回到直连行为）
- `AGENT_LOOP_HEARTBEAT_INTERVAL`   心跳间隔秒，默认 10
- `AGENT_LOOP_MODEL_IDLE_TIMEOUT`   模型阶段静默上限秒，默认 240
- `AGENT_LOOP_TOOL_IDLE_TIMEOUT`    工具阶段静默上限秒，默认 900
- `AGENT_LOOP_TOTAL_DEADLINE`       单轮总时长上限秒，默认 1800
- `AGENT_LOOP_LAG_WARN_MS`          事件循环卡顿告警阈值毫秒，默认 300
"""

import asyncio
import contextlib
import json
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)

# 事件类型提取：只读帧头部，避免对每个 token 帧做完整 JSON 解析
_EVENT_TYPE_RE = re.compile(r'"type"\s*:\s*"([a-z_]+)"')

# 这些事件代表"后端确实产出过内容"，用于刷新活跃时间
_ACTIVITY_EVENTS = frozenset(
    {
        "start",
        "info",
        "warning",
        "phase",
        "step_start",
        "step_complete",
        "tool_result",
        "update",
        "stream",
        "stream_end",
        "message",
        "interrupt",
        "context_update",
        "complete",
        "stopped",
        "error",
    }
)


def _env_float(name: str, default: float, min_value: float = 0.5) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(min_value, float(raw))
    except (TypeError, ValueError):
        logger.warning("SSEGuard: invalid float env %s=%s, fallback=%s", name, raw, default)
        return default


def is_enabled() -> bool:
    """总开关：关闭后 `guarded_sse` 退化为直通。"""
    return os.getenv("AGENT_LOOP_SSE_GUARD", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _sse(payload: Dict[str, Any]) -> str:
    """构造 SSE 帧（与 create_sse_data 输出保持一致）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_event_type(chunk: Any) -> Optional[str]:
    if not isinstance(chunk, str):
        return None
    match = _EVENT_TYPE_RE.search(chunk[:120])
    return match.group(1) if match else None


def _build_idle_timeout_event(*, budget: float, phase: str, elapsed: float) -> Dict[str, Any]:
    if phase == "tool":
        message = (
            f"工具执行已连续 {int(elapsed)} 秒没有返回结果（上限 {int(budget)} 秒），"
            "本轮已自动终止。请检查工具依赖的服务是否可用，或缩小任务范围后重试。"
        )
    elif phase == "summarizing":
        message = (
            f"上下文压缩已连续 {int(elapsed)} 秒没有进展（上限 {int(budget)} 秒），"
            "本轮已自动终止。建议新建会话或缩小需求范围后重试。"
        )
    else:
        message = (
            f"模型已连续 {int(elapsed)} 秒没有返回任何内容（上限 {int(budget)} 秒），"
            "本轮已自动终止。可重试，或改用响应更快的模型。"
        )
    return {
        "type": "error",
        "code": 504,
        "error_code": "stream_idle_timeout",
        "phase": phase,
        "idle_seconds": int(elapsed),
        "message": message,
        "errors": {"detail": [message], "error_code": "stream_idle_timeout"},
    }


def _build_total_timeout_event(*, deadline: float) -> Dict[str, Any]:
    message = (
        f"本轮执行已超过总时长上限（{int(deadline)} 秒），已自动终止。"
        "建议缩小需求范围、拆分为多轮对话后重试。"
    )
    return {
        "type": "error",
        "code": 504,
        "error_code": "stream_total_timeout",
        "message": message,
        "errors": {"detail": [message], "error_code": "stream_total_timeout"},
    }


def _build_internal_error_event(exc: BaseException) -> Dict[str, Any]:
    message = f"流式响应中断：{type(exc).__name__}: {exc}"
    return {
        "type": "error",
        "code": 500,
        "error_code": "stream_internal_error",
        "message": message,
        "errors": {"detail": [message], "error_code": "stream_internal_error"},
    }


async def guarded_sse(
    inner: AsyncIterator[str],
    *,
    session_id: str,
    heartbeat_interval: Optional[float] = None,
    model_idle: Optional[float] = None,
    tool_idle: Optional[float] = None,
    deadline: Optional[float] = None,
) -> AsyncIterator[str]:
    """在内层 SSE 生成器之上叠加心跳、空闲看门狗与总时长上限。

    Args:
        inner: 原始 SSE 字符串异步生成器（产出 `data: {...}\\n\\n`）。
        session_id: 会话 ID，仅用于日志。
        heartbeat_interval: 心跳间隔秒，None 时读环境变量（默认 10）。
        model_idle: 模型阶段静默上限秒，None 时读环境变量（默认 240）。
        tool_idle: 工具阶段静默上限秒，None 时读环境变量（默认 900）。
        deadline: 单轮总时长上限秒，None 时读环境变量（默认 1800）。

    Yields:
        原始帧 + 周期性 heartbeat 帧 + 超时时的 error 帧。
    """
    if not is_enabled():
        async for chunk in inner:
            yield chunk
        return

    heartbeat_interval = heartbeat_interval or _env_float(
        "AGENT_LOOP_HEARTBEAT_INTERVAL", 10.0
    )
    model_idle = model_idle or _env_float("AGENT_LOOP_MODEL_IDLE_TIMEOUT", 240.0)
    tool_idle = tool_idle or _env_float("AGENT_LOOP_TOOL_IDLE_TIMEOUT", 900.0)
    deadline = deadline or _env_float("AGENT_LOOP_TOTAL_DEADLINE", 1800.0)
    lag_warn_seconds = _env_float("AGENT_LOOP_LAG_WARN_MS", 300.0, 50.0) / 1000.0

    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    sentinel = object()
    pump_error: list = []

    async def _pump() -> None:
        try:
            async for chunk in inner:
                await queue.put(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 需要把异常转成 SSE 错误帧
            pump_error.append(exc)
            logger.error(
                "SSEGuard: inner generator raised. session_id=%s error=%s: %s",
                session_id,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
        finally:
            with contextlib.suppress(Exception):
                await queue.put(sentinel)

    task = asyncio.create_task(_pump())
    loop = asyncio.get_running_loop()
    started = loop.time()
    last_activity = started
    phase = "model"
    seq = 0

    try:
        while True:
            remaining = deadline - (loop.time() - started)
            if remaining <= 0:
                logger.warning(
                    "SSEGuard: total deadline hit. session_id=%s elapsed=%d",
                    session_id,
                    int(loop.time() - started),
                )
                yield _sse(_build_total_timeout_event(deadline=deadline))
                return

            timeout = min(heartbeat_interval, remaining)
            wait_started = loop.time()
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                # 事件循环被其它同步任务阻塞时，wait_for 会明显超出预期时间，
                # 这条日志是定位"整体变慢"的关键依据。
                drift = (loop.time() - wait_started) - timeout
                if drift > lag_warn_seconds:
                    logger.warning(
                        "[LoopLag] SSEGuard timer drift %.0fms (expected %.0fs). session_id=%s",
                        drift * 1000,
                        timeout,
                        session_id,
                    )

                idle_for = loop.time() - last_activity
                budget = model_idle if phase == "model" else tool_idle
                if idle_for > budget:
                    logger.warning(
                        "SSEGuard: idle timeout. session_id=%s phase=%s idle=%ds budget=%ds",
                        session_id,
                        phase,
                        int(idle_for),
                        int(budget),
                    )
                    yield _sse(
                        _build_idle_timeout_event(
                            budget=budget, phase=phase, elapsed=idle_for
                        )
                    )
                    return

                seq += 1
                yield _sse(
                    {
                        "type": "heartbeat",
                        "seq": seq,
                        "elapsed_s": int(loop.time() - started),
                        "idle_s": int(idle_for),
                        "phase": phase,
                    }
                )
                continue

            if item is sentinel:
                break

            event_type = _extract_event_type(item)
            if event_type in _ACTIVITY_EVENTS:
                last_activity = loop.time()
                if event_type == "step_start":
                    phase = "tool"
                elif event_type == "step_complete":
                    phase = "model"
                elif event_type == "phase":
                    # 上下文压缩、自定义阶段等：统一按工具档预算，避免误杀
                    phase = "summarizing" if "summarizing" in str(item) else "tool"

            yield item

        if pump_error:
            yield _sse(_build_internal_error_event(pump_error[0]))
    finally:
        # 客户端断开 / 超时退出：取消内层任务并关闭生成器，
        # 让 agent.astream 与底层 httpx 请求真正停下来。
        task.cancel()
        with contextlib.suppress(Exception, RuntimeError):
            await inner.aclose()
        with contextlib.suppress(BaseException):
            await task
        logger.debug("SSEGuard: closed. session_id=%s elapsed=%ds", session_id, int(loop.time() - started))
