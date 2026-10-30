"""
流式输出进度标记（用于"重试去重"）

背景
----
思考型模型在网络抖动 / 读超时的情况下，`ModelRetryMiddleware` 会在**节点级**重试
整次模型调用。如果重试发生时已经向前端下发过一部分 token，重试会从头再生成一遍，
用户侧看到的就是「重复的两段文本」。

本模块记录"当前会话本轮是否已经向前端下发过 token"，供重试前判定：

- 未下发过 → 静默重试，用户无感；
- 已下发过 → 向 SSE 层推送 `stream_reset` 事件，由前端丢弃已展示的残缺内容，
  再接收重试后的完整内容。

实现说明
--------
- 进程内字典 + 线程锁。同一会话的 Agent Loop 与其模型中间件在同一进程内执行，
  多 worker 部署下每个请求仍落在同一进程，因此无需 Redis。
- key 只用 session_id：同一会话同一时刻只有一个 Agent Loop 在跑。
- 必须调用 `clear_stream_emitted()` 清理，避免跨轮污染。
"""

import threading
from typing import Set

_lock = threading.Lock()
_emitted_sessions: Set[str] = set()


def mark_stream_emitted(session_id: str) -> None:
    """标记该会话本轮已向前端下发过 token。"""
    if not session_id:
        return
    with _lock:
        _emitted_sessions.add(session_id)


def has_stream_emitted(session_id: str) -> bool:
    """该会话本轮是否已下发过 token。"""
    if not session_id:
        return False
    with _lock:
        return session_id in _emitted_sessions


def consume_stream_emitted(session_id: str) -> bool:
    """读取并清除标记，返回清除前的状态。

    用于"准备重试"的时刻：读取是否已下发过 token，同时把标记复位，
    使重试后的新一轮 token 重新从零计数。
    """
    if not session_id:
        return False
    with _lock:
        existed = session_id in _emitted_sessions
        _emitted_sessions.discard(session_id)
        return existed


def clear_stream_emitted(session_id: str) -> None:
    """清理该会话的标记（每轮开始时调用）。"""
    if not session_id:
        return
    with _lock:
        _emitted_sessions.discard(session_id)
