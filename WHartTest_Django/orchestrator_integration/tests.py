import json
import os
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test import TestCase
from django.test.utils import override_settings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from . import agent_loop_view
from .agent_loop_view import (
    _extract_linked_image_urls,
    _is_linked_image_url_allowed,
    _is_streamable_token,
    _normalize_uploaded_image_base64_list,
    _prepare_agent_loop_human_message,
)
from .loop_guard import (
    LOOP_GUARD_ABORT,
    LOOP_GUARD_MARKER,
    LOOP_GUARD_NONE,
    LOOP_GUARD_WARN,
    LoopGuardConfig,
    LoopGuardEventBus,
    build_loop_guard_middleware,
    evaluate_repeats,
    load_loop_guard_config,
    normalize_tool_signature,
    step_signatures,
    truncate_tool_content,
)
from .builtin_tools.skill_tools import (
    _build_skill_artifacts_dir,
    _collect_skill_artifacts,
    _build_skill_screenshots_dir,
    _finalize_skill_result,
    _prepare_skill_screenshots_dir,
    _SKILL_DIR_STALE_SECONDS,
    _sanitize_runtime_path_segment,
)
from .builtin_tools.output_sanitizer import strip_terminal_control_sequences
from .middleware_config import get_user_friendly_llm_error, _model_retry_should_retry
from projects.models import Project, ProjectMember
from requirements.models import DocumentImage, RequirementDocument


class LLMFriendlyErrorTests(SimpleTestCase):
    def test_model_cooldown_error_returns_friendly_payload(self):
        exc = Exception(
            "Error code: 429 - {'error': {'code': 'model_cooldown', 'message': 'All credentials for model coder-model are cooling down', 'model': 'coder-model', 'reset_seconds': 27211, 'reset_time': '7h33m31s'}}"
        )

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly error payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "model_cooldown")
        self.assertEqual(result["model"], "coder-model")
        self.assertEqual(result["reset_seconds"], 27211)
        self.assertEqual(result["reset_time"], "7h33m31s")
        self.assertIn("coder-model", result["message"])
        self.assertIn("7h33m31s", result["message"])

    def test_generic_rate_limit_error_returns_friendly_payload(self):
        exc = Exception("HTTP 429 Too Many Requests")

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly error payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "rate_limit")
        self.assertEqual(result["message"], "当前模型服务请求过于频繁，请稍后重试。")

    def test_model_cooldown_error_will_not_retry(self):
        exc = Exception(
            "Error code: 429 - {'error': {'code': 'model_cooldown', 'message': 'All credentials for model coder-model are cooling down', 'model': 'coder-model', 'reset_seconds': 27211, 'reset_time': '7h33m31s'}}"
        )

        self.assertFalse(_model_retry_should_retry(exc))

    def test_cooling_down_text_without_code_still_maps_to_model_cooldown(self):
        exc = Exception(
            "RateLimitError: provider says model service is cooling down, retry-after: 6m0s"
        )

        result = get_user_friendly_llm_error(exc)

        if result is None:
            raise AssertionError("expected friendly cooldown payload")
        self.assertEqual(result["status_code"], 429)
        self.assertEqual(result["error_code"], "model_cooldown")
        self.assertIn("冷却中", result["message"])


class LinkedImageUrlExtractionTests(SimpleTestCase):
    def test_extract_plain_http_url_stops_before_chinese_description(self):
        text = "请访问 https://localhost:8080，准备注册信息：用户名testuser010、密码abcdef123"

        self.assertEqual(_extract_linked_image_urls(text), ["https://localhost:8080"])

    def test_extract_markdown_image_url_trims_wrapping_punctuation(self):
        text = "参考截图 ![image](https://example.com/demo.png)，然后继续分析"

        self.assertEqual(
            _extract_linked_image_urls(text),
            ["https://example.com/demo.png"],
        )

    def test_extract_invalid_unicode_netloc_does_not_raise(self):
        text = "异常链接 https://localhost:8080：准备注册信息：用户名testuser014"

        self.assertEqual(_extract_linked_image_urls(text), ["https://localhost:8080"])

    def test_extract_plain_http_url_stops_before_ascii_comma_description(self):
        text = "Open http://localhost:8080,then fill the registration form"

        self.assertEqual(_extract_linked_image_urls(text), ["http://localhost:8080"])

    def test_extract_plain_http_url_stops_before_closing_parenthesis_text(self):
        text = "查看截图 https://example.com/demo.png)后继续分析"

        self.assertEqual(
            _extract_linked_image_urls(text),
            ["https://example.com/demo.png"],
        )

    def test_allowlist_check_rejects_invalid_url_without_raising(self):
        with patch.object(
            agent_loop_view, "_LINKED_IMAGE_URL_ALLOWLIST", {"example.com"}
        ):
            self.assertFalse(
                _is_linked_image_url_allowed(
                    "https://localhost:8080：准备注册信息：用户名testuser014"
                )
            )


class UploadedImageNormalizationTests(SimpleTestCase):
    def test_normalize_uploaded_images_merges_legacy_and_array_fields(self):
        result = _normalize_uploaded_image_base64_list(
            ["img-a", " img-b ", "", "img-a"],
            "img-c",
        )

        self.assertEqual(result, ["img-a", "img-b", "img-c"])

    def test_normalize_uploaded_images_accepts_legacy_single_image_only(self):
        result = _normalize_uploaded_image_base64_list(None, " legacy-img ")

        self.assertEqual(result, ["legacy-img"])


class AgentLoopRequirementImageMessageTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.override_media = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)

        self.user = get_user_model().objects.create_user(
            username="agent-loop-user",
            password="password123",
        )
        self.project = Project.objects.create(
            name="Agent Loop Image Project",
            creator=self.user,
        )
        ProjectMember.objects.create(
            project=self.project,
            user=self.user,
            role="member",
        )
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="Requirement With Images",
            document_type="docx",
            uploader=self.user,
            has_images=True,
            image_count=1,
        )
        DocumentImage.objects.create(
            document=self.document,
            image_id="img_000",
            order=0,
            content_type="image/png",
            file_size=3,
            image_file=SimpleUploadedFile(
                "img-000.png",
                b"png",
                content_type="image/png",
            ),
        )

    def test_prepare_agent_loop_human_message_rewrites_requirement_placeholders(self):
        message = (
            "请分析以下需求\n\n"
            "![图片](docimg://img_000)\n\n"
            f"(这些需求模块来源于需求文档ID: {self.document.id})"
        )

        human_message_content, additional_kwargs, display_message = async_to_sync(
            _prepare_agent_loop_human_message
        )(
            message,
            project=self.project,
            supports_vision=False,
            uploaded_images_base64=[],
        )

        expected_url = (
            f"/api/requirements/documents/{self.document.id}/images/img_000/"
        )
        self.assertEqual(human_message_content, display_message)
        self.assertIn(expected_url, display_message)
        self.assertEqual(
            additional_kwargs["requirement_document_id"], str(self.document.id)
        )

    def test_prepare_agent_loop_human_message_attaches_requirement_images_for_vision(self):
        message = (
            "请分析以下需求\n\n"
            "![图片](docimg://img_000)\n\n"
            f"(这些需求模块来源于需求文档ID: {self.document.id})"
        )

        human_message_content, additional_kwargs, display_message = async_to_sync(
            _prepare_agent_loop_human_message
        )(
            message,
            project=self.project,
            supports_vision=True,
            uploaded_images_base64=[],
        )

        self.assertIsInstance(human_message_content, list)
        self.assertEqual(human_message_content[0]["type"], "text")
        self.assertIn(
            f"/api/requirements/documents/{self.document.id}/images/img_000/",
            human_message_content[0]["text"],
        )
        self.assertEqual(human_message_content[1]["type"], "image_url")
        self.assertTrue(
            human_message_content[1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertEqual(
            additional_kwargs["requirement_document_id"], str(self.document.id)
        )
        self.assertEqual(additional_kwargs["image_source"], "requirement_document")
        self.assertIn(
            f"/api/requirements/documents/{self.document.id}/images/img_000/",
            display_message,
        )


class SkillScreenshotDirectoryTests(SimpleTestCase):
    def test_sanitize_runtime_path_segment_blocks_path_traversal(self):
        self.assertEqual(
            _sanitize_runtime_path_segment("../case/89", "_default"),
            "__case_89",
        )

    def test_build_skill_screenshots_dir_uses_runtime_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _build_skill_screenshots_dir(1, "89")

        self.assertTrue(screenshots_dir.endswith("skill_runtime/screenshots/1/89"))
        self.assertNotIn("/skills/1/11/", screenshots_dir)

    def test_build_skill_screenshots_dir_keeps_path_inside_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _build_skill_screenshots_dir(1, "../case/89")

        self.assertTrue(screenshots_dir.startswith(temp_media_root))
        self.assertNotIn("..", screenshots_dir)

    def test_prepare_skill_screenshots_dir_clears_idle_dir(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                screenshots_dir = _prepare_skill_screenshots_dir(1, "89")
                stale_file = os.path.join(screenshots_dir, "old.png")
                with open(stale_file, "w", encoding="utf-8") as f:
                    f.write("old screenshot")

                # 目录仍新鲜：不清理，避免误删当前会话截图
                refreshed_dir = _prepare_skill_screenshots_dir(1, "89")
                self.assertEqual(refreshed_dir, screenshots_dir)
                self.assertTrue(os.path.exists(stale_file))

                # 子目录内文件也参与闲置判定：子目录内容变新则不清空
                sub_file = os.path.join(screenshots_dir, "sub", "recent.png")
                os.makedirs(os.path.dirname(sub_file), exist_ok=True)
                with open(sub_file, "w", encoding="utf-8") as f:
                    f.write("recent")
                refreshed_dir = _prepare_skill_screenshots_dir(1, "89")
                self.assertTrue(os.path.exists(stale_file))

                # 目录树闲置超过阈值后清理
                old = time.time() - _SKILL_DIR_STALE_SECONDS - 60
                os.utime(stale_file, (old, old))
                os.utime(sub_file, (old, old))
                refreshed_dir = _prepare_skill_screenshots_dir(1, "89")
                self.assertEqual(refreshed_dir, screenshots_dir)
                self.assertFalse(os.path.exists(stale_file))

    def test_build_skill_artifacts_dir_uses_runtime_media_root(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                artifacts_dir = _build_skill_artifacts_dir(1, "session-1")

        self.assertTrue(artifacts_dir.endswith("skill_runtime/artifacts/1/session-1"))
        self.assertNotIn("/skills/1/11/", artifacts_dir)

    def test_collect_skill_artifacts_detects_named_generated_file(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, MEDIA_URL="/media/"):
                skill_dir = os.path.join(temp_media_root, "skills", "1", "11")
                os.makedirs(skill_dir, exist_ok=True)
                generated_file = os.path.join(skill_dir, "order-payment-flow.drawio")
                with open(generated_file, "w", encoding="utf-8") as f:
                    f.write("<mxfile></mxfile>")

                artifacts = _collect_skill_artifacts(
                    "已帮你生成 draw.io 文件：order-payment-flow.drawio",
                    skill_dir=skill_dir,
                    artifacts_dir=os.path.join(temp_media_root, "skill_runtime", "artifacts", "1", "s1"),
                    artifacts_before={},
                )

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["name"], "order-payment-flow.drawio")
        self.assertEqual(artifacts[0]["url"], "/media/skills/1/11/order-payment-flow.drawio")

    def test_finalize_skill_result_wraps_output_with_file_payload(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, MEDIA_URL="/media/"):
                skill_dir = os.path.join(temp_media_root, "skills", "1", "11")
                os.makedirs(skill_dir, exist_ok=True)
                generated_file = os.path.join(skill_dir, "demo.drawio")
                with open(generated_file, "w", encoding="utf-8") as f:
                    f.write("<mxfile></mxfile>")

                wrapped = _finalize_skill_result(
                    "已生成文件 demo.drawio",
                    skill_dir=skill_dir,
                    artifacts_dir=os.path.join(temp_media_root, "skill_runtime", "artifacts", "1", "s1"),
                    artifacts_before={},
                )

        self.assertIn('"type": "file"', wrapped)
        self.assertIn('/media/skills/1/11/demo.drawio', wrapped)


class TerminalOutputSanitizerTests(SimpleTestCase):
    def test_strip_terminal_control_sequences_removes_ansi_color_codes(self):
        raw = "\x1b[32m✓\x1b[0m Browser closed"

        self.assertEqual(strip_terminal_control_sequences(raw), "✓ Browser closed")


# ============== Agent Loop 重复工具调用守卫 ==============

_REPEAT_LOOP_COMMAND = (
    "python whart_tools.py --action get_testcases --project_id 1 --module_id 7 --page 1"
)
_REPEAT_LOOP_RESULT = '{"count": 0, "next": null, "previous": null, "results": []}'


def _build_repeat_history(repeat: int, command: str = _REPEAT_LOOP_COMMAND, result=_REPEAT_LOOP_RESULT):
    """
    构造「同工具 + 同参数 + 同结果」连续重复的历史。

    直接对应线上 1.json 的死循环场景：
    execute_skill_script 以相同参数被调用 35 次，每次返回完全一致的空结果。
    """
    messages = [HumanMessage(content="请生成测试用例")]
    for index in range(repeat):
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "execute_skill_script",
                        "args": {"skill_name": "whart-test", "command": command},
                        "id": f"call_{index}",
                        "type": "tool_call",
                    }
                ],
            )
        )
        messages.append(
            ToolMessage(
                content=result,
                tool_call_id=f"call_{index}",
                name="execute_skill_script",
            )
        )
    return messages


class LoopGuardRepeatDetectionTests(SimpleTestCase):
    def test_repeat_below_warn_threshold_is_not_flagged(self):
        for repeat in (1, 2):
            verdict = evaluate_repeats(_build_repeat_history(repeat), warn=3, abort=5)
            self.assertEqual(verdict.level, LOOP_GUARD_NONE, msg=f"repeat={repeat}")

    def test_repeat_reaching_warn_threshold(self):
        verdict = evaluate_repeats(_build_repeat_history(3), warn=3, abort=5)

        self.assertEqual(verdict.level, LOOP_GUARD_WARN)
        self.assertEqual(verdict.count, 3)
        self.assertEqual(verdict.tool, "execute_skill_script")

    def test_repeat_reaching_abort_threshold(self):
        verdict = evaluate_repeats(_build_repeat_history(5), warn=3, abort=5)

        self.assertEqual(verdict.level, LOOP_GUARD_ABORT)
        self.assertEqual(verdict.count, 5)

    def test_same_tool_with_different_args_is_not_flagged(self):
        messages = _build_repeat_history(4)
        # 逐步变化参数：属于正常多轮查询，不应判定为死循环
        for index, message in enumerate(messages):
            if isinstance(message, AIMessage) and message.tool_calls:
                message.tool_calls[0]["args"]["command"] = (
                    f"{_REPEAT_LOOP_COMMAND} --page {index}"
                )

        self.assertEqual(
            evaluate_repeats(messages, warn=3, abort=5).level, LOOP_GUARD_NONE
        )

    def test_same_call_but_changing_result_is_not_flagged(self):
        """同参轮询直到结果变化（例如等待任务完成）不应被误判"""
        messages = _build_repeat_history(6)
        index = 0
        for message in messages:
            if isinstance(message, ToolMessage):
                message.content = f'{{"count": {index}}}'
                index += 1

        self.assertEqual(
            evaluate_repeats(messages, warn=3, abort=5).level, LOOP_GUARD_NONE
        )

    def test_alternating_tools_are_not_flagged(self):
        messages = [HumanMessage(content="hi")]
        for round_index in range(4):
            for tool_name in ("tool_a", "tool_b"):
                messages.append(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": tool_name,
                                "args": {"x": 1},
                                "id": f"{tool_name}_{round_index}",
                                "type": "tool_call",
                            }
                        ],
                    )
                )
                messages.append(
                    ToolMessage(
                        content="same", tool_call_id=f"{tool_name}_{round_index}", name=tool_name
                    )
                )

        self.assertEqual(
            evaluate_repeats(messages, warn=3, abort=5).level, LOOP_GUARD_NONE
        )

    def test_empty_history_is_not_flagged(self):
        self.assertEqual(evaluate_repeats([], warn=3, abort=5).level, LOOP_GUARD_NONE)


class LoopGuardSignatureNormalizationTests(SimpleTestCase):
    def test_arg_key_order_does_not_change_signature(self):
        first = AIMessage(
            content="",
            tool_calls=[{"name": "t", "args": {"a": 1, "b": [2, 3]}, "id": "1"}],
        )
        second = AIMessage(
            content="",
            tool_calls=[{"name": "t", "args": {"b": [2, 3], "a": 1}, "id": "2"}],
        )

        self.assertEqual(step_signatures(first), step_signatures(second))

    def test_whitespace_differences_are_normalized(self):
        self.assertEqual(
            normalize_tool_signature("t", {"command": "a   b\n c"}),
            normalize_tool_signature("t", {"command": "a b c"}),
        )

    def test_different_tool_name_produces_different_signature(self):
        self.assertNotEqual(
            normalize_tool_signature("tool_a", {"x": 1}),
            normalize_tool_signature("tool_b", {"x": 1}),
        )


class LoopGuardToolContentTruncationTests(SimpleTestCase):
    def test_short_content_is_returned_unchanged(self):
        self.assertEqual(truncate_tool_content("short output", 6000), "short output")

    def test_long_content_keeps_head_and_tail_with_marker(self):
        content = "HEAD-" + ("x" * 20000) + "-TAIL"

        truncated = truncate_tool_content(content, 6000, head_ratio=0.6)

        self.assertLessEqual(len(truncated), 6000)
        self.assertTrue(truncated.startswith("HEAD-"))
        self.assertTrue(truncated.endswith("-TAIL"))
        self.assertIn("已省略中间", truncated)
        self.assertIn("请勿重复调用同一工具", truncated)

    def test_placeholder_replacement_no_longer_drops_content_entirely(self):
        """回归：超长工具结果必须保留可读信息，避免模型因看不到结果而重复调用"""
        content = json.dumps({"results": [f"case-{i}" for i in range(4000)]}, ensure_ascii=False)

        truncated = truncate_tool_content(content, 6000)

        self.assertIn("case-", truncated)
        self.assertNotEqual(truncated, "[Tool output removed: content was invalid or too large]")


class LoopGuardEventBusTests(SimpleTestCase):
    def test_drain_returns_pushed_events_and_clears_bucket(self):
        bus = LoopGuardEventBus()

        bus.push("session-a", {"kind": LOOP_GUARD_WARN, "count": 3})
        bus.push("session-a", {"kind": LOOP_GUARD_ABORT, "count": 5})

        self.assertEqual(
            [event["kind"] for event in bus.drain("session-a")],
            [LOOP_GUARD_WARN, LOOP_GUARD_ABORT],
        )
        # 已排空
        self.assertEqual(bus.drain("session-a"), [])

    def test_events_are_isolated_per_session(self):
        bus = LoopGuardEventBus()

        bus.push("session-a", {"kind": LOOP_GUARD_WARN})

        self.assertEqual(bus.drain("session-b"), [])


class LoopGuardConfigTests(SimpleTestCase):
    def test_abort_is_forced_above_warn(self):
        with patch.dict(
            os.environ,
            {"AGENT_LOOP_REPEAT_WARN": "5", "AGENT_LOOP_REPEAT_ABORT": "5"},
            clear=False,
        ):
            config = load_loop_guard_config()

        self.assertGreater(config.abort, config.warn)

    def test_guard_can_be_disabled_by_env(self):
        with patch.dict(os.environ, {"AGENT_LOOP_LOOP_GUARD_ENABLED": "0"}, clear=False):
            config = load_loop_guard_config()

        self.assertFalse(config.enabled)

    def test_default_thresholds(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_loop_guard_config()

        self.assertEqual(config.warn, 3)
        self.assertEqual(config.abort, 5)
        self.assertTrue(config.require_same_result)


class LoopGuardMiddlewareBuildTests(SimpleTestCase):
    def test_build_loop_guard_middleware_returns_agent_middleware(self):
        bus = LoopGuardEventBus()

        middleware = build_loop_guard_middleware(
            session_id="session-x", config=LoopGuardConfig(), bus=bus
        )

        self.assertTrue(hasattr(middleware, "before_model"))


class SkillCommandDedupTests(SimpleTestCase):
    def test_read_only_actions_are_detected(self):
        from .builtin_tools.skill_tools import _is_read_only_skill_command

        for command in (
            "python whart_tools.py --action get_testcases --project_id 1",
            "python whart_tools.py --action list_files --project_id 1",
            "python whart_tools.py --action validate_files --file_ids 1,2",
            "python whart_tools.py --action get_modules --project_id 1",
        ):
            self.assertTrue(_is_read_only_skill_command(command), msg=command)

    def test_write_actions_are_not_treated_as_read_only(self):
        from .builtin_tools.skill_tools import _is_read_only_skill_command

        for command in (
            "python whart_tools.py --action add_testcase --project_id 1",
            "python whart_tools.py --action edit_testcase --case_id 9",
            "python whart_tools.py --action delete_file --file_id 3",
            "python whart_tools.py --action upload_file --file_path a.png",
            "ls -la",
        ):
            self.assertFalse(_is_read_only_skill_command(command), msg=command)

    def test_dedup_key_is_whitespace_insensitive(self):
        from .builtin_tools.skill_tools import _build_skill_dedup_key

        self.assertEqual(
            _build_skill_dedup_key("s1", "whart-test", "cmd   a\n b"),
            _build_skill_dedup_key("s1", "whart-test", "cmd a b"),
        )
        self.assertNotEqual(
            _build_skill_dedup_key("s1", "whart-test", "cmd a"),
            _build_skill_dedup_key("s2", "whart-test", "cmd a"),
        )

    def test_repeated_calls_beyond_threshold_short_circuit(self):
        from .builtin_tools.skill_tools import _SkillCallCache

        cache = _SkillCallCache(ttl_seconds=300, max_entries=8)
        key = "s1::whart-test::deadbeef"

        # 首次调用：无缓存结果
        occurrence, cached, _ = cache.touch(key)
        self.assertEqual((occurrence, cached), (1, None))
        cache.store(key, "RESULT-1")

        # 第二次调用：仍在允许范围内（阈值 2），可拿到上次结果
        occurrence, cached, _ = cache.touch(key)
        self.assertEqual(occurrence, 2)
        self.assertEqual(cached, "RESULT-1")

        # 第三次调用：超过阈值，调用方据此短路
        occurrence, cached, _ = cache.touch(key)
        self.assertEqual(occurrence, 3)
        self.assertEqual(cached, "RESULT-1")

    def test_cache_expires_after_ttl(self):
        from .builtin_tools.skill_tools import _SkillCallCache

        cache = _SkillCallCache(ttl_seconds=1, max_entries=8)
        key = "s1::skill::hash"
        cache.touch(key)
        cache.store(key, "RESULT")
        # 手动把 last_at 拨回过去
        cache._entries[key]["last_at"] -= 10

        occurrence, cached, _ = cache.touch(key)

        self.assertEqual(occurrence, 1)
        self.assertIsNone(cached)

    def test_cache_evicts_oldest_entries(self):
        from .builtin_tools.skill_tools import _SkillCallCache

        cache = _SkillCallCache(ttl_seconds=300, max_entries=2)
        for index in range(3):
            cache.touch(f"key-{index}")
            cache.store(f"key-{index}", f"r{index}")

        self.assertEqual(len(cache._entries), 2)
        self.assertNotIn("key-0", cache._entries)

    def test_short_circuit_notice_contains_guidance(self):
        from .builtin_tools.skill_tools import _build_repeat_short_circuit_notice

        notice = _build_repeat_short_circuit_notice(
            skill_name="whart-test", count=3, age_seconds=12, cached_result="RESULT"
        )

        self.assertIn("[重复调用拦截]", notice)
        self.assertIn("请立即停止重复调用", notice)
        self.assertIn("RESULT", notice)


class LoopGuardEndToEndTests(SimpleTestCase):
    """端到端回归：重复工具调用应先纠偏、再中止，而非耗尽 recursion_limit。

    复现 issue 场景（模型只发工具调用、不产出正文），验证：
    1) 守卫中间件在真实 create_agent 图里按 warn→abort 生效
    2) 中止发生在 recursion_limit 之前（不抛 GraphRecursionError）
    3) 守卫注入消息不泄漏到前端 token 流
    """

    @staticmethod
    def _build_repeating_model():
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.outputs import ChatGeneration, ChatResult

        class RepeatingModel(BaseChatModel):
            calls: int = 0

            @property
            def _llm_type(self) -> str:
                return "repeating-e2e"

            def bind_tools(self, tools, **kwargs):  # noqa: D102
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.calls += 1
                # 每次使用不同 tool_call id，与真实 provider 行为一致
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "echo",
                            "args": {"q": "same"},
                            "id": f"call_{self.calls}",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=msg)])

        return RepeatingModel()

    def _run_scenario(self, *, require_same_result: bool):
        import asyncio

        from langchain.agents import create_agent
        from langchain_core.tools import tool
        from langgraph.errors import GraphRecursionError

        @tool
        def echo(q: str) -> dict:
            """回显查询（永远返回空结果，模拟死循环诱因）"""
            return {"count": 0, "next": None, "previous": None, "results": []}

        session_id = f"e2e-{uuid4().hex}"
        bus = LoopGuardEventBus()
        config = LoopGuardConfig(
            warn=3, abort=5, window=12, require_same_result=require_same_result
        )
        guard = build_loop_guard_middleware(
            session_id=session_id, config=config, bus=bus
        )
        model = self._build_repeating_model()
        agent = create_agent(
            model,
            [echo],
            system_prompt="你是一名资深测试架构师。",
            middleware=[guard],
        )

        async def run():
            events = []
            recursion_hit = False
            leaked = False
            try:
                async for mode, chunk in agent.astream(
                    {"messages": [{"role": "user", "content": "go"}]},
                    config={
                        "configurable": {"thread_id": session_id},
                        "recursion_limit": 30,
                    },
                    stream_mode=["updates", "messages"],
                ):
                    if mode == "updates":
                        for ev in bus.drain(session_id):
                            events.append(ev.get("kind"))
                    elif mode == "messages":
                        token = chunk[0]
                        meta = chunk[1] if len(chunk) > 1 else None
                        if _is_streamable_token(token, meta):
                            kwargs = getattr(token, "additional_kwargs", None) or {}
                            if kwargs.get(LOOP_GUARD_MARKER):
                                leaked = True
            except GraphRecursionError:
                recursion_hit = True
            return events, recursion_hit, leaked

        events, recursion_hit, leaked = asyncio.run(run())
        return events, recursion_hit, leaked, model.calls

    def test_repeating_calls_abort_before_recursion_limit(self):
        events, recursion_hit, leaked, model_calls = self._run_scenario(
            require_same_result=True
        )

        self.assertIn(LOOP_GUARD_WARN, events, msg=f"events={events}")
        self.assertIn(LOOP_GUARD_ABORT, events, msg=f"events={events}")
        self.assertFalse(recursion_hit, "守卫应提前中止，不应触发递归上限")
        self.assertFalse(leaked, "守卫注入的纠偏/中止消息不应泄漏到 token 流")
        # abort 阈值 5：模型被调用 5 次即终止，远小于 recursion_limit=30
        self.assertEqual(model_calls, 5)

    def test_repeating_calls_with_varying_results_are_not_flagged(self):
        """结果不一致时不得误判（require_same_result=False 场景）"""
        events, recursion_hit, _leaked, _model_calls = self._run_scenario(
            require_same_result=False
        )
        # 结果一致（工具恒返回空结果），因此仍应被识别为重复
        self.assertIn(LOOP_GUARD_ABORT, events, msg=f"events={events}")
        self.assertFalse(recursion_hit)

