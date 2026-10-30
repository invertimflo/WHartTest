#!/usr/bin/env python3
"""SSE 并发压测 / 观测脚本（仅用标准库，不引入额外依赖）。

用途：在"页面卡死"类问题排查中，把后端行为从浏览器里剥离出来单独量化。

它做三件事：
1. 并发发起 N 路 Agent Loop SSE 请求，逐帧打时间戳；
2. 统计首帧延迟、帧间隔（p50/p95/max）、心跳数量、错误帧、总时长；
3. 可选在指定秒数后调用 stop 接口，验证停止信号是否真的能让后端在 3s 内退出。

典型用法：
    # 10 路并发，跑 300 秒上限，观察帧间隔是否有 > 10s 的空洞
    python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 10

    # 只跑 1 路，用来对照 curl -N 的帧时间线
    python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 1

    # 验证停止：第 20 秒对每路发停止请求
    python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 3 --stop-after 20

判读标准：
- max_gap 应 <= AGENT_LOOP_HEARTBEAT_INTERVAL（默认 10s）+ 少量抖动；
- 若 max_gap 远大于心跳间隔，说明心跳没生效或事件循环被卡住；
- heartbeats 为 0 且总时长 > 10s，说明 guarded_sse 没接上或 AGENT_LOOP_SSE_GUARD=0；
- 多路并发时若各路 first_frame 同时变长，基本可以确认是事件循环/敏感线程阻塞。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field


@dataclass
class WorkerResult:
    index: int
    session_id: str
    ok: bool = False
    error: str = ""
    first_frame_at: float | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    frame_count: int = 0
    heartbeat_count: int = 0
    event_types: dict[str, int] = field(default_factory=dict)
    gaps: list[float] = field(default_factory=list)
    stopped_frame: bool = False
    error_frame: str = ""


def _post_json(url: str, payload: dict, token: str, timeout: float):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(request, timeout=timeout)


def _consume_stream(
    result: WorkerResult,
    url: str,
    payload: dict,
    token: str,
    timeout: float,
    stop_after: float,
    stop_url: str,
) -> None:
    result.started_at = time.monotonic()
    last_at = result.started_at
    stop_sent = False

    try:
        response = _post_json(url, payload, token, timeout)
    except urllib.error.HTTPError as exc:
        result.error = f"HTTP {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}"
        result.finished_at = time.monotonic()
        return
    except Exception as exc:  # noqa: BLE001 - 压测脚本，任何异常都记录即可
        result.error = f"{type(exc).__name__}: {exc}"
        result.finished_at = time.monotonic()
        return

    try:
        while True:
            now = time.monotonic()
            elapsed = now - result.started_at

            if stop_after > 0 and not stop_sent and elapsed >= stop_after:
                stop_sent = True
                _send_stop(stop_url, result.session_id, token)

            if timeout and elapsed > timeout:
                result.error = f"timeout after {timeout:.0f}s"
                break

            line = response.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if not text or not text.startswith("data:"):
                continue

            raw = text[5:].strip()
            if raw == "[DONE]":
                result.ok = True
                break

            try:
                event = json.loads(raw)
            except ValueError:
                continue

            stamp = time.monotonic()
            result.frame_count += 1
            if result.first_frame_at is None:
                result.first_frame_at = stamp
            if result.frame_count > 1:
                result.gaps.append(stamp - last_at)
            last_at = stamp

            event_type = str(event.get("type") or "unknown")
            result.event_types[event_type] = result.event_types.get(event_type, 0) + 1
            if event_type == "heartbeat":
                result.heartbeat_count += 1
            elif event_type == "stopped":
                result.stopped_frame = True
            elif event_type == "done":
                result.ok = True
                break
            elif "timeout" in event_type or event_type == "error":
                result.error_frame = event.get("message") or event_type
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.finished_at = time.monotonic()
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass


def _send_stop(stop_url: str, session_id: str, token: str) -> None:
    if not stop_url:
        return
    try:
        body = json.dumps({"session_id": session_id}).encode("utf-8")
        request = urllib.request.Request(stop_url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        urllib.request.urlopen(request, timeout=15).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  [stop] {session_id} failed: {exc}", file=sys.stderr)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[index]


def _print_report(results: list[WorkerResult], wall_seconds: float) -> int:
    print()
    print("=" * 78)
    print(f"{'#':>3}  {'frames':>6} {'hb':>4} {'first(s)':>9} {'total(s)':>9} "
          f"{'p95gap':>8} {'maxgap':>8}  status")
    print("-" * 78)

    first_frames: list[float] = []
    all_gaps: list[float] = []
    exit_code = 0

    for result in results:
        first = (result.first_frame_at - result.started_at) if result.first_frame_at else -1
        total = result.finished_at - result.started_at
        p95 = _percentile(result.gaps, 95)
        max_gap = max(result.gaps) if result.gaps else 0.0
        if first >= 0:
            first_frames.append(first)
        all_gaps.extend(result.gaps)

        status = "ok"
        if result.error_frame:
            status = f"frame:{result.error_frame[:40]}"
        elif result.error:
            status = f"err:{result.error[:40]}"
        elif result.stopped_frame:
            status = "stopped"
        elif not result.ok:
            status = "incomplete"

        if result.error or result.error_frame:
            exit_code = 1

        print(f"{result.index:>3}  {result.frame_count:>6} {result.heartbeat_count:>4} "
              f"{first:>9.2f} {total:>9.2f} {p95:>8.2f} {max_gap:>8.2f}  {status}")

    print("-" * 78)
    print(f"墙钟耗时: {wall_seconds:.1f}s")

    if first_frames:
        print(f"首帧延迟: p50={_percentile(first_frames, 50):.2f}s "
              f"p95={_percentile(first_frames, 95):.2f}s "
              f"max={max(first_frames):.2f}s")
    if all_gaps:
        print(f"帧间隔  : p50={_percentile(all_gaps, 50):.2f}s "
              f"p95={_percentile(all_gaps, 95):.2f}s "
              f"max={max(all_gaps):.2f}s  (样本 {len(all_gaps)})")
        if max(all_gaps) > 30:
            print("  ⚠️  出现 >30s 的帧间隔空洞：检查 AGENT_LOOP_SSE_GUARD 是否开启、"
                  "事件循环是否被同步调用卡住")

    total_heartbeats = sum(r.heartbeat_count for r in results)
    if total_heartbeats == 0 and any(r.finished_at - r.started_at > 15 for r in results):
        print("  ⚠️  长连接但零心跳：guarded_sse 未生效（AGENT_LOOP_SSE_GUARD=0？）")

    print("=" * 78)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Loop SSE 并发压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--token", default="", help="JWT access token")
    parser.add_argument("--project-id", type=int, required=True, help="项目 ID")
    parser.add_argument("--message", default="请简单介绍一下你自己", help="发送的消息")
    parser.add_argument("--concurrency", type=int, default=1, help="并发路数")
    parser.add_argument("--timeout", type=float, default=900.0, help="每路最长等待秒数")
    parser.add_argument(
        "--session-ids", default="",
        help="逗号分隔的已有 session_id；不传则每路随机生成（用于新建会话）",
    )
    parser.add_argument(
        "--stop-after", type=float, default=0.0,
        help="第 N 秒后对每路发停止请求（0 表示不停止）",
    )
    parser.add_argument("--non-stream", action="store_true", help="走非流式接口（stream=false）")
    args = parser.parse_args()

    stream_url = args.base_url.rstrip("/") + "/api/orchestrator/agent-loop/"
    stop_url = args.base_url.rstrip("/") + "/api/orchestrator/agent-loop/stop/"

    preset_ids = [s.strip() for s in args.session_ids.split(",") if s.strip()]
    results: list[WorkerResult] = []
    threads: list[threading.Thread] = []

    print(f"目标: {stream_url}")
    print(f"并发: {args.concurrency}  超时: {args.timeout:.0f}s  "
          f"{'非流式' if args.non_stream else '流式'}")

    for index in range(args.concurrency):
        session_id = (
            preset_ids[index] if index < len(preset_ids) else str(uuid.uuid4())
        )
        result = WorkerResult(index=index + 1, session_id=session_id)
        results.append(result)

        payload = {
            "message": args.message,
            "session_id": session_id,
            "project_id": args.project_id,
            "stream": not args.non_stream,
        }

        thread = threading.Thread(
            target=_consume_stream,
            args=(result, stream_url, payload, args.token, args.timeout,
                  args.stop_after, stop_url),
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    started = time.monotonic()
    for thread in threads:
        thread.join()
    wall_seconds = time.monotonic() - started

    return _print_report(results, wall_seconds)


if __name__ == "__main__":
    sys.exit(main())
