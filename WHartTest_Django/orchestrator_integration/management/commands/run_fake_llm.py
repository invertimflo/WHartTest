"""假慢速思考模型服务（OpenAI 兼容），用于复现 LLM 流式输出各类异常。

为什么需要它：真实思考模型的首 token 延迟、逐字速度、偶发断连都不可控，
排查"页面卡死"时无法稳定复现。这个命令起一个本地 OpenAI 兼容服务，
把各种病态行为变成可配置参数，从而可以对着真实链路（openai SDK → httpx →
agent_loop → SSE）做确定性验证。

用法：
    # 默认：首 token 等 3s，之后每 80ms 一个 chunk，共 200 个
    python manage.py run_fake_llm

    # 模拟思考模型：首 token 等 180s
    python manage.py run_fake_llm --first-token-delay 180

    # 模拟中途静默 300s（验证 SSE 心跳与空闲看门狗）
    python manage.py run_fake_llm --silent-after 50 --silent-for 300

    # 模拟第 200 个 chunk 后直接断连（验证 ModelRetryMiddleware + stream_reset）
    python manage.py run_fake_llm --fail-after 200

    # 模拟上游 500（验证 get_user_friendly_llm_error）
    python manage.py run_fake_llm --status 500

配合后端配置：
    LLM 配置里的 base_url 填 http://127.0.0.1:8100/v1，api_key 随便填，
    模型名填 fake-thinking-model，并把 context_limit 设成 50000。

注意：本命令只用于本地联调与压测，不要在生产环境部署。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.core.management.base import BaseCommand

_DEFAULT_TEXT = (
    "这是一段用于压测的模拟模型输出。为了尽量贴近真实的思考模型，"
    "服务端会按固定节奏逐块吐字，并支持在中途插入长时间静默或直接断连，"
    "以便验证服务端心跳、空闲看门狗、重试去重以及前端渲染节流的表现。"
)


class _FakeModelHandler(BaseHTTPRequestHandler):
    # 由 build_handler() 注入
    opts: dict = {}
    stop_event: threading.Event | None = None

    # 关掉默认的请求日志噪音（每次请求都打一行会淹没 SSE 观察）
    def log_message(self, fmt, *args):  # noqa: A003
        if self.opts.get("verbose"):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ utils
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _open_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        # 不发送 Content-Length，走 chunked 语义，保证客户端能持续读
        self.end_headers()

    def _write_chunk(self, payload: dict) -> None:
        frame = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        self.wfile.write(frame.encode("utf-8"))
        self.wfile.flush()

    def _sleep(self, seconds: float) -> bool:
        """可被 Ctrl+C 打断的 sleep，返回 True 表示应中止输出。"""
        if seconds <= 0:
            return False
        stop = self.stop_event
        return bool(stop and stop.wait(seconds))

    # -------------------------------------------------------------- endpoints
    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send_json(200, {
                "object": "list",
                "data": [{"id": self.opts["model"], "object": "model"}],
            })
            return
        self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        if not path.endswith("/chat/completions"):
            self._send_json(404, {"error": {"message": f"unknown path {path}"}})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": {"message": "invalid json body"}})
            return

        # 上游直接报错：验证错误文案映射与前端 error 帧
        preset_status = int(self.opts.get("status") or 0)
        if preset_status:
            self._send_json(preset_status, {
                "error": {
                    "message": self.opts.get("status_message")
                    or f"fake upstream error {preset_status}",
                    "type": "fake_error",
                    "code": preset_status,
                }
            })
            return

        if self.opts.get("echo"):
            text = _extract_prompt(request) or _DEFAULT_TEXT
        else:
            text = _DEFAULT_TEXT

        stream = bool(request.get("stream"))
        if stream:
            self._stream_completion(text)
        else:
            self._full_completion(text)

    # ----------------------------------------------------------------- bodies
    def _full_completion(self, text: str) -> None:
        self._sleep(float(self.opts.get("first_token_delay") or 0))
        self._send_json(200, {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.opts["model"],
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": len(text),
                "total_tokens": 100 + len(text),
            },
        })

    def _stream_completion(self, text: str) -> None:
        chunk_size = max(1, int(self.opts.get("chunk_size") or 4))
        interval = float(self.opts.get("chunk_interval") or 0.08)
        total_chunks = int(self.opts.get("total_chunks") or 0)
        silent_after = int(self.opts.get("silent_after") or 0)
        silent_for = float(self.opts.get("silent_for") or 0)
        fail_after = int(self.opts.get("fail_after") or 0)

        pieces = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        if total_chunks > 0:
            # 不够就循环补足，保证能产出足够多的帧用于压测
            repeated: list[str] = []
            while len(repeated) < total_chunks:
                repeated.extend(pieces)
            pieces = repeated[:total_chunks]

        try:
            self._open_sse()
        except (BrokenPipeError, ConnectionResetError):
            return

        # 首 token 延迟：模拟思考阶段
        if self._sleep(float(self.opts.get("first_token_delay") or 0)):
            return

        base = {
            "id": "chatcmpl-fake",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.opts["model"],
        }

        for index, piece in enumerate(pieces):
            # 中途长时间静默：验证服务端心跳能否顶住 nginx / 前端空闲判定
            if silent_after and index == silent_after and silent_for > 0:
                if self.opts.get("verbose"):
                    self.log_message("[fake] entering silence for %.1fs", silent_for)
                if self._sleep(silent_for):
                    return

            # 中途断连：不做 [DONE]，直接关 socket，模拟真实网络故障
            if fail_after and index >= fail_after:
                if self.opts.get("verbose"):
                    self.log_message("[fake] aborting connection after %d chunks", index)
                try:
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.close()
                except OSError:
                    pass
                return

            body = dict(base)
            body["choices"] = [{
                "index": 0,
                "delta": {"content": piece},
                "finish_reason": None,
            }]
            try:
                self._write_chunk(body)
            except (BrokenPipeError, ConnectionResetError):
                # 客户端已断连（用户点了停止 / 关页面），正常退出
                return

            if self._sleep(interval):
                return

        # 结束帧
        final = dict(base)
        final["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        try:
            self._write_chunk(final)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def _extract_prompt(request: dict) -> str:
    """把用户的最后一条消息回显出来，便于确认链路拿到的上下文。"""
    messages = request.get("messages") or []
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            joined = "".join(parts)
            if joined:
                return joined
    return ""


class Command(BaseCommand):
    help = "启动一个 OpenAI 兼容的假慢速思考模型服务，用于复现 LLM 流式异常"

    # 这是纯外部服务，跟 Django 业务无关。
    # 跳过系统检查，避免 URLconf 里任何与 LLM 无关的导入问题（例如第三方包版本
    # 冲突）把压测工具一起挡住 —— 排查性能问题时恰恰需要它随时可用。
    requires_system_checks: list = []

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1", help="监听地址")
        parser.add_argument("--port", type=int, default=8100, help="监听端口")
        parser.add_argument("--model", default="fake-thinking-model", help="对外声明的模型名")
        parser.add_argument(
            "--first-token-delay", type=float, default=3.0,
            help="首 token 延迟秒数，模拟思考阶段（默认 3）",
        )
        parser.add_argument(
            "--chunk-interval", type=float, default=0.08,
            help="相邻 chunk 间隔秒数（默认 0.08）",
        )
        parser.add_argument("--chunk-size", type=int, default=4, help="每个 chunk 的字符数（默认 4）")
        parser.add_argument(
            "--total-chunks", type=int, default=0,
            help="总 chunk 数，0 表示只输出一遍默认文本；用于生成超长输出",
        )
        parser.add_argument(
            "--silent-after", type=int, default=0,
            help="在第 N 个 chunk 后进入静默（验证心跳与空闲看门狗）",
        )
        parser.add_argument(
            "--silent-for", type=float, default=0.0,
            help="静默持续秒数",
        )
        parser.add_argument(
            "--fail-after", type=int, default=0,
            help="在第 N 个 chunk 后直接断连（验证重试与 stream_reset）",
        )
        parser.add_argument(
            "--status", type=int, default=0,
            help="直接返回该 HTTP 状态码（如 500 / 429），不进入流式",
        )
        parser.add_argument("--status-message", default="", help="配合 --status 的错误文案")
        parser.add_argument("--echo", action="store_true", help="回显用户最后一条消息作为输出")
        parser.add_argument("--verbose", action="store_true", help="打印请求日志")

    def handle(self, *args, **options):
        opts = dict(options)
        stop_event = threading.Event()

        handler_cls = type(
            "FakeModelHandler",
            (_FakeModelHandler,),
            {"opts": opts, "stop_event": stop_event},
        )

        server = ThreadingHTTPServer((opts["host"], opts["port"]), handler_cls)
        server.daemon_threads = True

        self.stdout.write(self.style.SUCCESS(
            f"fake LLM listening on http://{opts['host']}:{opts['port']}/v1"
        ))
        self.stdout.write(
            f"  model={opts['model']} first_token_delay={opts['first_token_delay']}s "
            f"chunk_interval={opts['chunk_interval']}s total_chunks={opts['total_chunks']}"
        )
        if opts["silent_after"]:
            self.stdout.write(
                self.style.WARNING(
                    f"  silence after chunk {opts['silent_after']} for {opts['silent_for']}s"
                )
            )
        if opts["fail_after"]:
            self.stdout.write(
                self.style.WARNING(f"  abort connection after chunk {opts['fail_after']}")
            )
        if opts["status"]:
            self.stdout.write(
                self.style.WARNING(f"  always respond {opts['status']} {opts['status_message']}")
            )
        self.stdout.write("  Ctrl+C to stop")

        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            self.stdout.write("\nstopping fake LLM ...")
        finally:
            stop_event.set()
            server.shutdown()
            server.server_close()
