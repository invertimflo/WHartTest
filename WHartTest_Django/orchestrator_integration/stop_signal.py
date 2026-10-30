"""
Agent Loop 停止信号管理

提供可插拔后端的停止信号存储，用于中断正在执行的 Agent Loop。

使用场景：
- 用户点击"停止"按钮时，调用 `set_stop_signal(session_id)`（或异步 `aset_stop_signal`）
- Agent Loop 在每步检查 `should_stop(session_id)`（异步上下文用 `ashould_stop`）
- 任务结束后调用 `clear_stop_signal(session_id)` 清理

后端选择（`AGENT_STOP_BACKEND`）
--------------------------------
- `memory`（默认）：进程内字典，语义等价于改造前实现，单 worker 部署足够；
- `redis`：跨进程共享。**开启 uvicorn 多 worker 时必须切到 redis**，
  否则"停止"请求落到另一个 worker 时信号会被写进那个进程的内存，当前进程永远收不到，
  用户侧表现为"点了停止没反应"。

信号 TTL 默认 300s，防止异常退出后残留信号影响下一轮对话。
"""

import logging
import os
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_SIGNAL_TTL = 300
REDIS_KEY_PREFIX = "agent:stop:"


def _backend_name() -> str:
    return (os.getenv("AGENT_STOP_BACKEND") or "memory").strip().lower()


def _redis_url() -> str:
    return (
        os.getenv("REDIS_URL")
        or os.getenv("CELERY_BROKER_URL")
        or "redis://127.0.0.1:6379/0"
    )


def _signal_ttl() -> int:
    raw = os.getenv("AGENT_STOP_TTL")
    if not raw:
        return DEFAULT_SIGNAL_TTL
    try:
        return max(10, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_SIGNAL_TTL


# ============== 内存后端 ==============


class MemoryStopSignalManager:
    """停止信号管理器（线程安全的内存存储）"""

    def __init__(self, signal_ttl: int = DEFAULT_SIGNAL_TTL):
        """
        Args:
            signal_ttl: 信号过期时间（秒），防止信号永不清理
        """
        self._signals: Dict[str, float] = {}  # session_id -> timestamp
        self._lock = threading.Lock()
        self._signal_ttl = signal_ttl

    def set_stop_signal(self, session_id: str) -> bool:
        with self._lock:
            self._signals[session_id] = time.time()
            logger.info("[StopSignal] Set stop signal for session: %s", session_id)
            return True

    def should_stop(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._signals:
                return False

            signal_time = self._signals[session_id]
            if time.time() - signal_time > self._signal_ttl:
                del self._signals[session_id]
                logger.debug("[StopSignal] Signal expired for session: %s", session_id)
                return False

            return True

    def clear_stop_signal(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._signals:
                del self._signals[session_id]
                logger.info("[StopSignal] Cleared stop signal for session: %s", session_id)
                return True
            return False

    def cleanup_expired(self) -> int:
        with self._lock:
            current_time = time.time()
            expired = [
                sid for sid, t in self._signals.items()
                if current_time - t > self._signal_ttl
            ]
            for sid in expired:
                del self._signals[sid]

            if expired:
                logger.info("[StopSignal] Cleaned up %d expired signals", len(expired))
            return len(expired)

    def get_active_signals(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._signals)

    # 异步接口与同步接口同构（内存后端本身不涉及 IO）
    async def aset_stop_signal(self, session_id: str) -> bool:
        return self.set_stop_signal(session_id)

    async def ashould_stop(self, session_id: str) -> bool:
        return self.should_stop(session_id)

    async def aclear_stop_signal(self, session_id: str) -> bool:
        return self.clear_stop_signal(session_id)


# ============== Redis 后端 ==============


class RedisStopSignalManager:
    """基于 Redis 的停止信号（多 worker / 多副本共享）"""

    def __init__(self, url: str, signal_ttl: int = DEFAULT_SIGNAL_TTL):
        self._url = url
        self._signal_ttl = signal_ttl
        self._async_client = None
        self._sync_client = None
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{REDIS_KEY_PREFIX}{session_id}"

    def _get_async_client(self):
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    import redis.asyncio as aioredis

                    self._async_client = aioredis.from_url(
                        self._url,
                        encoding="utf-8",
                        decode_responses=True,
                        max_connections=16,
                    )
        return self._async_client

    def _get_sync_client(self):
        if self._sync_client is None:
            with self._lock:
                if self._sync_client is None:
                    import redis

                    self._sync_client = redis.Redis.from_url(
                        self._url, encoding="utf-8", decode_responses=True
                    )
        return self._sync_client

    # ---- 异步接口（事件循环内唯一应该使用的入口）----

    async def aset_stop_signal(self, session_id: str) -> bool:
        client = self._get_async_client()
        await client.set(self._key(session_id), "1", ex=self._signal_ttl)
        logger.info("[StopSignal] Set stop signal (redis) for session: %s", session_id)
        return True

    async def ashould_stop(self, session_id: str) -> bool:
        client = self._get_async_client()
        return bool(await client.exists(self._key(session_id)))

    async def aclear_stop_signal(self, session_id: str) -> bool:
        client = self._get_async_client()
        removed = await client.delete(self._key(session_id))
        if removed:
            logger.info("[StopSignal] Cleared stop signal (redis) for session: %s", session_id)
        return bool(removed)

    # ---- 同步接口（供非事件循环上下文使用，例如管理脚本）----

    def set_stop_signal(self, session_id: str) -> bool:
        client = self._get_sync_client()
        client.set(self._key(session_id), "1", ex=self._signal_ttl)
        logger.info("[StopSignal] Set stop signal (redis/sync) for session: %s", session_id)
        return True

    def should_stop(self, session_id: str) -> bool:
        client = self._get_sync_client()
        return bool(client.exists(self._key(session_id)))

    def clear_stop_signal(self, session_id: str) -> bool:
        client = self._get_sync_client()
        return bool(client.delete(self._key(session_id)))


# ============== 后端选择单例 ==============

_manager = None
_manager_lock = threading.Lock()


def get_stop_signal_manager():
    """获取全局停止信号管理器单例（按 AGENT_STOP_BACKEND 选择实现）"""
    global _manager
    if _manager is not None:
        return _manager

    with _manager_lock:
        if _manager is not None:
            return _manager

        ttl = _signal_ttl()
        if _backend_name() == "redis":
            try:
                _manager = RedisStopSignalManager(_redis_url(), signal_ttl=ttl)
                logger.info("[StopSignal] Using redis backend, ttl=%ss", ttl)
            except Exception as exc:  # noqa: BLE001 - 初始化失败降级到内存
                logger.error(
                    "[StopSignal] Redis backend unavailable, fallback to memory: %s", exc
                )
                _manager = MemoryStopSignalManager(signal_ttl=ttl)
        else:
            _manager = MemoryStopSignalManager(signal_ttl=ttl)
            logger.info("[StopSignal] Using memory backend, ttl=%ss", ttl)

    return _manager


# ============== 便捷函数（同步）==============


def set_stop_signal(session_id: str) -> bool:
    return get_stop_signal_manager().set_stop_signal(session_id)


def should_stop(session_id: str) -> bool:
    return get_stop_signal_manager().should_stop(session_id)


def clear_stop_signal(session_id: str) -> bool:
    return get_stop_signal_manager().clear_stop_signal(session_id)


# ============== 便捷函数（异步，事件循环内应使用这些）==============


async def aset_stop_signal(session_id: str) -> bool:
    return await get_stop_signal_manager().aset_stop_signal(session_id)


async def ashould_stop(session_id: str) -> bool:
    return await get_stop_signal_manager().ashould_stop(session_id)


async def aclear_stop_signal(session_id: str) -> bool:
    return await get_stop_signal_manager().aclear_stop_signal(session_id)
