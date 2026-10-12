#!/usr/bin/env python
"""HTTPS 客户端证书支持的单元测试。

覆盖范围（仅单元测试，不做真实证书握手 —— 见文件末尾「已知缺口」）：
1. client_cert 纯函数：origin 归一化、路径解析、校验、camelCase dict 构造
2. PlaywrightExecutor._build_browser_context_options 的 ignore_https_errors 三态矩阵
3. 任务 origin 推导、证书配置幂等性、口令不泄漏
4. 证书材料预校验与「建上下文失败降级」判定
5. base_url 导航参数（对齐录制器，回归 cn.bing.com 超时 BUG）
6. 节点级证书配置已彻底移除（config.toml / 环境变量 / 平台白名单 / 执行器上报）

独立运行：python test_client_cert.py
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import client_cert
import executor as executor_module
from client_cert import (
    build_client_certificates,
    normalize_origin,
    parse_origins,
    resolve_cert_path,
    validate_cert_files,
)
from executor import PageStepConfig, PlaywrightExecutor, TestCaseConfig
from main import Config
from runtime_config import extract_env_policy, normalize_run_options, resolve_from_env_and_actuator


# 一个明显的哨兵口令：任何日志里出现它都算泄漏
SECRET_PASSPHRASE = 'S3cr3t-Passphrase-Must-OnlyDanceInMemory'

# 节点级证书配置的字段名（用于「已移除」的静态回归断言）
NODE_LEVEL_CERT_KEYS = (
    'client_cert_enabled',
    'client_cert_pfx_path',
    'client_cert_cert_path',
    'client_cert_key_path',
    'client_cert_origins',
)


def _write_file(path: Path, content: str = 'dummy') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


def _has_cryptography() -> bool:
    """``cryptography`` 是可选依赖；未安装时跳过真实的证书可加载性预校验。"""
    try:
        import cryptography  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


HAS_CRYPTOGRAPHY = _has_cryptography()


class ActuatorTestCase(unittest.TestCase):
    """统一提供临时目录与执行器实例，避免污染工作区。

    默认把 ``_precheck_cert_material`` 打桩成「跳过」——本组用例是围绕
    origin/参数构造/日志脱敏的行为测试，用假的 pfx 字节流即可；真实的可加载性
    预校验由 ``CertPrecheckTest`` 单独覆盖（那里用真实的 cryptography）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._precheck_patch = patch.object(
            executor_module.PlaywrightExecutor,
            '_precheck_cert_material',
            return_value=None,
        )
        self._precheck_patch.start()

    def tearDown(self):
        self._precheck_patch.stop()
        self._tmp.cleanup()

    def make_executor(self, **overrides) -> PlaywrightExecutor:
        kwargs = {
            'user_data_dir': str(self.tmp / 'browser'),
            'screenshot_dir': str(self.tmp / 'shots'),
        }
        kwargs.update(overrides)
        return PlaywrightExecutor(**kwargs)

    def make_cert_files(self) -> dict:
        return {
            'pfx': _write_file(self.tmp / 'certs' / 'client.pfx', 'P12-BYTES'),
            'pfx2': _write_file(self.tmp / 'certs' / 'other.p12', 'P12-BYTES-2'),
            'cert': _write_file(self.tmp / 'certs' / 'client.crt', 'CERT-PEM'),
            'key': _write_file(self.tmp / 'certs' / 'client.key', 'KEY-PEM'),
        }


# ---------------------------------------------------------------------------
# 1. client_cert 纯函数
# ---------------------------------------------------------------------------

class NormalizeOriginTest(unittest.TestCase):
    def test_strips_path_query_and_fragment(self):
        self.assertEqual(
            normalize_origin('https://example.com/path?q=1#frag'),
            'https://example.com',
        )

    def test_keeps_non_default_port(self):
        self.assertEqual(
            normalize_origin('https://example.com:8443/x'),
            'https://example.com:8443',
        )

    def test_drops_explicit_default_port(self):
        # https://host:443 与 https://host 等价，统一成后者
        self.assertEqual(normalize_origin('https://example.com:443/x'), 'https://example.com')

    def test_rejects_non_https_and_schemeless(self):
        self.assertIsNone(normalize_origin('http://example.com'))
        self.assertIsNone(normalize_origin('example.com'))
        self.assertIsNone(normalize_origin('ftp://example.com'))

    def test_rejects_empty_and_none(self):
        self.assertIsNone(normalize_origin(''))
        self.assertIsNone(normalize_origin('   '))
        self.assertIsNone(normalize_origin(None))

    def test_drops_userinfo(self):
        self.assertEqual(
            normalize_origin('https://user:pw@example.com/x'),
            'https://example.com',
        )

    def test_keeps_ipv6_brackets(self):
        self.assertEqual(normalize_origin('https://[::1]:8443/x'), 'https://[::1]:8443')

    def test_is_idempotent(self):
        once = normalize_origin('https://example.com:8443/a?b=1')
        self.assertEqual(normalize_origin(once), once)


class ParseOriginsTest(unittest.TestCase):
    def test_splits_strips_and_dedupes_preserving_order(self):
        result = parse_origins('https://b.com, https://a.com ,https://b.com')
        self.assertEqual(result, ['https://b.com', 'https://a.com'])

    def test_merges_multiple_sources(self):
        result = parse_origins('https://a.com', 'https://b.com')
        self.assertEqual(result, ['https://a.com', 'https://b.com'])

    def test_drops_invalid_entries(self):
        result = parse_origins('http://plain.com, ,https://ok.com, notaurl')
        self.assertEqual(result, ['https://ok.com'])

    def test_empty_input_yields_empty_list(self):
        self.assertEqual(parse_origins(''), [])
        self.assertEqual(parse_origins(None), [])
        self.assertEqual(parse_origins(), [])


class ResolveCertPathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_absolute_path_returned_as_is(self):
        absolute = self.tmp / 'certs' / 'client.pfx'
        self.assertEqual(resolve_cert_path(str(absolute), self.tmp), absolute)

    def test_relative_path_is_anchored_to_base_dir(self):
        self.assertEqual(
            resolve_cert_path('./certs/client.pfx', self.tmp),
            self.tmp / 'certs' / 'client.pfx',
        )
        # 不带 ./ 前缀同样成立
        self.assertEqual(
            resolve_cert_path('certs/client.pfx', self.tmp),
            self.tmp / 'certs' / 'client.pfx',
        )

    def test_dot_prefixed_path_is_not_treated_as_absolute(self):
        resolved = resolve_cert_path('./a.pfx', self.tmp)
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved.parent, self.tmp)

    def test_empty_returns_none(self):
        self.assertIsNone(resolve_cert_path(None, self.tmp))
        self.assertIsNone(resolve_cert_path('', self.tmp))
        self.assertIsNone(resolve_cert_path('   ', self.tmp))

    def test_without_base_dir_defaults_to_cwd(self):
        """执行器侧只传一个参数：任务下发的证书路径恒为绝对路径，故不会再走相对分支。"""
        resolved = resolve_cert_path('certs/client.pfx')
        self.assertEqual(resolved, (Path.cwd() / 'certs' / 'client.pfx').resolve())


class ValidateCertFilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_files_produce_no_warning(self):
        pfx = _write_file(self.tmp / 'client.pfx')
        self.assertEqual(validate_cert_files(pfx_path=pfx), [])

    def test_unexpected_extension_warns_but_does_not_raise(self):
        weird = _write_file(self.tmp / 'client.txt')
        warnings = validate_cert_files(pfx_path=weird)
        self.assertEqual(len(warnings), 1)
        self.assertIn('.txt', warnings[0])

    def test_missing_file_warns(self):
        warnings = validate_cert_files(pfx_path=self.tmp / 'nope.pfx')
        self.assertEqual(len(warnings), 1)
        self.assertIn('不存在', warnings[0])

    def test_pem_extensions_accepted(self):
        cert = _write_file(self.tmp / 'client.crt')
        key = _write_file(self.tmp / 'client.key')
        self.assertEqual(validate_cert_files(cert_path=cert, key_path=key), [])


class BuildClientCertificatesTest(unittest.TestCase):
    """本组断言的核心是 camelCase 键名 —— 写错会被 Playwright 静默忽略。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.pfx = _write_file(self.tmp / 'client.pfx')
        self.cert = _write_file(self.tmp / 'client.crt')
        self.key = _write_file(self.tmp / 'client.key')

    def tearDown(self):
        self._tmp.cleanup()

    def test_pfx_entry_uses_camel_case_keys(self):
        entries = build_client_certificates(
            ['https://a.example.com'],
            pfx_path=self.pfx,
            passphrase='pw',
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['origin'], 'https://a.example.com')
        self.assertEqual(entry['pfxPath'], str(self.pfx))
        self.assertEqual(entry['passphrase'], 'pw')
        self.assertLessEqual(set(entry), {'origin', 'pfxPath', 'passphrase'})
        self.assertIn('pfxPath', entry)

    def test_snake_case_keys_are_absent(self):
        """防退化：Playwright 不做 snake_case -> camelCase 转换，写错会静默不生效。"""
        entry = build_client_certificates(['https://a.com'], pfx_path=self.pfx)[0]
        for wrong in ('pfx_path', 'cert_path', 'key_path', 'origin_url'):
            self.assertNotIn(wrong, entry)

    def test_pem_entry_uses_camel_case_keys(self):
        entry = build_client_certificates(
            ['https://a.com'],
            cert_path=self.cert,
            key_path=self.key,
        )[0]
        self.assertEqual(entry['certPath'], str(self.cert))
        self.assertEqual(entry['keyPath'], str(self.key))
        self.assertNotIn('cert', entry)
        self.assertNotIn('key', entry)

    def test_one_entry_per_origin(self):
        entries = build_client_certificates(
            ['https://a.com', 'https://b.com:8443', 'https://a.com'],
            pfx_path=self.pfx,
        )
        self.assertEqual(
            [e['origin'] for e in entries],
            ['https://a.com', 'https://b.com:8443'],
        )

    def test_origin_is_normalized(self):
        entry = build_client_certificates(
            ['https://a.com:443/login?x=1'],
            pfx_path=self.pfx,
        )[0]
        self.assertEqual(entry['origin'], 'https://a.com')

    def test_empty_passphrase_omits_key(self):
        """空口令必须不带 passphrase 键：Playwright 视空串为无效口令。"""
        for blank in (None, '', '   '):
            entry = build_client_certificates(
                ['https://a.com'], pfx_path=self.pfx, passphrase=blank
            )[0]
            self.assertNotIn('passphrase', entry, msg=f'passphrase={blank!r}')

    def test_passphrase_with_real_content_is_not_stripped(self):
        """含非空白字符的口令原样传递，避免破坏带前后空格的真实口令。"""
        entry = build_client_certificates(
            ['https://a.com'], pfx_path=self.pfx, passphrase='  p w  '
        )[0]
        self.assertEqual(entry['passphrase'], '  p w  ')

    def test_no_origins_returns_empty(self):
        self.assertEqual(build_client_certificates([], pfx_path=self.pfx), [])
        self.assertEqual(build_client_certificates([None, 'http://x.com'], pfx_path=self.pfx), [])

    def test_no_cert_material_returns_empty(self):
        self.assertEqual(build_client_certificates(['https://a.com']), [])
        # PEM 只给一半也不成立
        self.assertEqual(
            build_client_certificates(['https://a.com'], cert_path=self.cert),
            [],
        )

    def test_pfx_wins_over_pem(self):
        with self.assertLogs('actuator', level='WARNING'):
            entry = build_client_certificates(
                ['https://a.com'],
                pfx_path=self.pfx,
                cert_path=self.cert,
                key_path=self.key,
            )[0]
        self.assertEqual(entry['pfxPath'], str(self.pfx))
        self.assertNotIn('certPath', entry)


# ---------------------------------------------------------------------------
# 2. ignore_https_errors 三态矩阵（节点级配置已移除，仅剩 runtime 下发通道）
# ---------------------------------------------------------------------------

class ContextOptionsMatrixTest(ActuatorTestCase):
    def test_stealth_on_without_cert_matches_legacy_behaviour(self):
        executor = self.make_executor(stealth_enabled=True)
        options = executor._build_browser_context_options()
        self.assertIs(options['ignore_https_errors'], True)
        self.assertNotIn('client_certificates', options)

    def test_stealth_off_without_cert_omits_key(self):
        """回归保护：与改动前完全一致，stealth 关闭且无证书时不设置该键。"""
        executor = self.make_executor(stealth_enabled=False)
        options = executor._build_browser_context_options()
        self.assertNotIn('ignore_https_errors', options)

    def test_stealth_off_with_cert_enables_both(self):
        files = self.make_cert_files()
        executor = self.make_executor(stealth_enabled=False)
        executor.configure_client_cert(
            enabled=True,
            pfx_path=str(files['pfx']),
            origins='https://a.example.com',
        )
        executor.set_task_origins(['https://a.example.com'])

        options = executor._build_browser_context_options()
        self.assertIs(options['ignore_https_errors'], True)
        self.assertEqual(
            options['client_certificates'],
            [{'origin': 'https://a.example.com', 'pfxPath': str(files['pfx'])}],
        )

    def test_runtime_false_overrides_stealth_default(self):
        """任务级 runtime 显式 false 时，即便 stealth 打开也不再容忍证书错误。"""
        executor = self.make_executor(stealth_enabled=True)
        executor.apply_runtime_options({'browser': 'chromium', 'ignore_https_errors': False})
        options = executor._build_browser_context_options()
        self.assertNotIn('ignore_https_errors', options)

    def test_runtime_true_overrides_stealth_off(self):
        executor = self.make_executor(stealth_enabled=False)
        executor.apply_runtime_options({'browser': 'chromium', 'ignore_https_errors': True})
        options = executor._build_browser_context_options()
        self.assertIs(options['ignore_https_errors'], True)

    def test_runtime_none_keeps_auto(self):
        executor = self.make_executor(stealth_enabled=False)
        executor.apply_runtime_options({'browser': 'chromium', 'ignore_https_errors': None})
        self.assertIsNone(executor.ignore_https_errors)
        options = executor._build_browser_context_options()
        self.assertNotIn('ignore_https_errors', options)

    def test_restore_resets_tri_state(self):
        executor = self.make_executor(stealth_enabled=False)
        previous = executor.apply_runtime_options(
            {'browser': 'chromium', 'ignore_https_errors': True}
        )
        self.assertIs(executor.ignore_https_errors, True)
        executor.restore_runtime_options(previous)
        self.assertIsNone(executor.ignore_https_errors)

    def test_viewport_still_applied_when_stealth_off(self):
        """重构时把证书逻辑提到了早退分支之前，确认原视口行为未被破坏。"""
        executor = self.make_executor(stealth_enabled=False, viewport_width=1024, viewport_height=768)
        options = executor._build_browser_context_options()
        self.assertEqual(options['viewport'], {'width': 1024, 'height': 768})

    def test_stealth_on_chromium_uses_stealth_defaults(self):
        executor = self.make_executor(stealth_enabled=True, browser_type='chromium')
        options = executor._build_browser_context_options()
        # stealth 开启时使用伪装 UA；视口回退到节点默认视口（任务级未指定）
        self.assertIn('user_agent', options)
        self.assertEqual(options['viewport'], {'width': 1280, 'height': 720})

    def test_stealth_off_non_chromium_omits_user_agent(self):
        """非 chromium 且未配置 stealth_user_agent 时不注入 UA（与改动前一致）。"""
        executor = self.make_executor(stealth_enabled=True, browser_type='firefox')
        options = executor._build_browser_context_options()
        self.assertNotIn('user_agent', options)


class CertWarningDedupTest(ActuatorTestCase):
    def test_missing_origin_warning_logged_only_once(self):
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(
            enabled=True,
            pfx_path=str(files['pfx']),
            origins=None,  # 不提供额外 origin
        )
        executor.set_task_origins([])

        with self.assertLogs('actuator', level='WARNING') as captured:
            first = executor._build_browser_context_options()
            second = executor._build_browser_context_options()

        self.assertNotIn('client_certificates', first)
        self.assertNotIn('client_certificates', second)

        matched = [r for r in captured.records if '未能推导出 https origin' in r.getMessage()]
        self.assertEqual(len(matched), 1, msg='告警应只出现一次，避免每个上下文都刷日志')

    def test_incomplete_material_warns(self):
        executor = self.make_executor()
        executor.configure_client_cert(enabled=True, origins='https://a.example.com')
        executor.set_task_origins(['https://a.example.com'])

        with self.assertLogs('actuator', level='WARNING') as captured:
            options = executor._build_browser_context_options()

        self.assertNotIn('client_certificates', options)
        self.assertTrue(
            any('未拿到完整的证书材料' in r.getMessage() for r in captured.records)
        )

    def test_disabled_cert_never_warns_or_applies(self):
        executor = self.make_executor()
        executor.configure_client_cert(pfx_path='/nonexistent/client.pfx', origins='https://a.com')
        executor.set_task_origins(['https://a.com'])

        options = executor._build_browser_context_options()
        self.assertNotIn('client_certificates', options)


# ---------------------------------------------------------------------------
# 3. origin 推导 / 配置幂等 / 口令不泄漏
# ---------------------------------------------------------------------------

class TaskOriginsTest(ActuatorTestCase):
    def test_derives_from_env_config_and_page_urls(self):
        executor = self.make_executor()
        page_step = PageStepConfig(
            page_step_id=1,
            page_url='https://b.example.com:8443/login',
            page_name='登录页',
            env_config={'base_url': 'http://ignored.example.com'},
        )
        case = TestCaseConfig(
            case_id=1,
            case_name='登录用例',
            page_steps=[page_step],
            env_config={'base_url': 'https://a.example.com/x'},
        )

        self.assertEqual(
            executor._task_origins(case),
            ['https://a.example.com', 'https://b.example.com:8443'],
        )

    def test_http_base_url_is_dropped(self):
        executor = self.make_executor()
        case = TestCaseConfig(
            case_id=2, case_name='c', env_config={'base_url': 'http://insecure.example.com'}
        )
        self.assertEqual(executor._task_origins(case), [])

    def test_page_step_config_is_supported_directly(self):
        executor = self.make_executor()
        page_step = PageStepConfig(
            page_step_id=3, page_url='https://direct.example.com/path', page_name='p'
        )
        self.assertEqual(executor._task_origins(page_step), ['https://direct.example.com'])

    def test_extra_origins_are_merged(self):
        executor = self.make_executor()
        executor.configure_client_cert(origins='https://extra.example.com, https://a.example.com')
        case = TestCaseConfig(
            case_id=4, case_name='c', env_config={'base_url': 'https://a.example.com'}
        )
        self.assertEqual(
            executor._task_origins(case),
            ['https://a.example.com', 'https://extra.example.com'],
        )

    def test_accepts_plain_strings_and_multiple_configs(self):
        executor = self.make_executor()
        case_a = TestCaseConfig(case_id=5, case_name='a', env_config={'base_url': 'https://a.com'})
        case_b = TestCaseConfig(case_id=6, case_name='b', env_config={'base_url': 'https://b.com'})
        self.assertEqual(
            executor._task_origins(case_a, case_b),
            ['https://a.com', 'https://b.com'],
        )
        self.assertEqual(executor._task_origins('https://c.com/x'), ['https://c.com'])

    def test_no_configs_yields_empty(self):
        executor = self.make_executor()
        self.assertEqual(executor._task_origins(), [])


class SetTaskOriginsTest(ActuatorTestCase):
    def test_overwrites_instead_of_accumulating(self):
        executor = self.make_executor()
        executor.set_task_origins(['https://a.com'])
        executor.set_task_origins(['https://b.com'])
        self.assertEqual(executor._task_cert_origins, ['https://b.com'])

    def test_empty_clears(self):
        executor = self.make_executor()
        executor.set_task_origins(['https://a.com'])
        executor.set_task_origins([])
        self.assertEqual(executor._task_cert_origins, [])
        executor.set_task_origins(None)
        self.assertEqual(executor._task_cert_origins, [])

    def test_string_input_is_accepted(self):
        executor = self.make_executor()
        executor.set_task_origins('https://a.com, https://b.com')
        self.assertEqual(executor._task_cert_origins, ['https://a.com', 'https://b.com'])


class PrepareTaskOriginsTest(ActuatorTestCase):
    """任务级 origin 固定的入口语义（prepare / refresh / clear）。

    关键点：平台随证书下发的 origin 未必出现在 config 里，执行入口内部按 config
    refresh 时不能把它冲掉 —— 这是「环境 base_url 与用例 URL 不同源」场景下
    证书仍然生效的前提。
    """

    def test_prepare_merges_platform_origins_with_config_origins(self):
        executor = self.make_executor()
        case = TestCaseConfig(
            case_id=1, case_name='c', env_config={'base_url': 'https://a.example.com/x'}
        )
        origins = executor.prepare_task_origins(
            case, extra_origins=['https://mtls.example.com:8443']
        )
        self.assertEqual(
            origins,
            ['https://a.example.com', 'https://mtls.example.com:8443'],
        )
        self.assertEqual(executor._task_cert_origins, origins)

    def test_refresh_keeps_platform_origins_absent_from_config(self):
        executor = self.make_executor()
        case = TestCaseConfig(
            case_id=2, case_name='c', env_config={'base_url': 'https://a.example.com'}
        )
        executor.prepare_task_origins(case, extra_origins=['https://platform.example.com'])

        # 执行入口内部会按 config 重新推导，此时平台下发的 origin 必须保留
        refreshed = executor.refresh_task_origins(case)
        self.assertEqual(
            refreshed,
            ['https://a.example.com', 'https://platform.example.com'],
        )

    def test_extra_origins_are_deduplicated(self):
        executor = self.make_executor()
        case = TestCaseConfig(
            case_id=3, case_name='c', env_config={'base_url': 'https://a.example.com'}
        )
        executor.prepare_task_origins(case, extra_origins=['https://a.example.com'])
        self.assertEqual(executor._task_cert_origins, ['https://a.example.com'])

    def test_prepare_without_extra_origins_resets_previous_task(self):
        executor = self.make_executor()
        executor.prepare_task_origins(
            TestCaseConfig(case_id=4, case_name='c', env_config={'base_url': 'https://a.com'}),
            extra_origins=['https://stale.example.com'],
        )
        # 下一个任务没有证书（extra_origins 缺省）→ 上一个任务的 origin 不得残留
        fresh = executor.prepare_task_origins(
            TestCaseConfig(case_id=5, case_name='d', env_config={'base_url': 'https://b.com'})
        )
        self.assertEqual(fresh, ['https://b.com'])

    def test_prepare_drops_invalid_platform_origins(self):
        executor = self.make_executor()
        origins = executor.prepare_task_origins(
            None, extra_origins=['http://insecure.example.com', 'not-a-url']
        )
        self.assertEqual(origins, [])

    def test_clear_task_origins_clears_both_sets(self):
        executor = self.make_executor()
        executor.prepare_task_origins(None, extra_origins=['https://a.example.com'])
        executor.clear_task_origins()
        self.assertEqual(executor._task_cert_origins, [])
        self.assertEqual(executor._task_extra_origins, [])
        # 清空后 refresh 不应把平台 origin 又"复活"
        self.assertEqual(executor.refresh_task_origins(None), [])

    def test_restore_runtime_options_clears_task_origins(self):
        executor = self.make_executor()
        previous = executor.apply_runtime_options({'browser': 'chromium', 'headless': True})
        executor.prepare_task_origins(None, extra_origins=['https://a.example.com'])
        self.assertEqual(executor._task_cert_origins, ['https://a.example.com'])

        executor.restore_runtime_options(previous)
        self.assertEqual(executor._task_cert_origins, [])
        self.assertEqual(executor._task_extra_origins, [])


class ConfigureClientCertTest(ActuatorTestCase):
    def test_only_passed_fields_are_updated(self):
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(
            enabled=True,
            pfx_path=str(files['pfx']),
            passphrase=SECRET_PASSPHRASE,
            origins='https://a.com',
        )

        # 只更新 origins，其余保持不变
        executor.configure_client_cert(origins='https://b.com')

        self.assertTrue(executor._client_cert_enabled)
        self.assertEqual(executor._client_cert_pfx_path, str(files['pfx']))
        self.assertEqual(executor._client_cert_passphrase, SECRET_PASSPHRASE)
        self.assertEqual(executor._client_cert_origins, 'https://b.com')

    def test_absolute_path_used_directly(self):
        """任务下发的证书恒为绝对路径（执行器已下载到本地缓存），无需相对路径基准。"""
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(enabled=True, pfx_path=str(files['pfx']))
        executor.set_task_origins(['https://a.com'])

        options = executor._build_browser_context_options()
        self.assertEqual(
            options['client_certificates'][0]['pfxPath'],
            str(files['pfx']),
        )

    def test_reset_material_clears_everything(self):
        """任务级证书走 reset_material=True，避免上一任务的材料串到本任务。"""
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(
            enabled=True,
            pfx_path=str(files['pfx']),
            passphrase=SECRET_PASSPHRASE,
            cert_path=str(files['cert']),
            key_path=str(files['key']),
            origins='https://a.com',
        )
        # enable 保持 True（reset 只清材料），但所有材料字段归零
        executor.configure_client_cert(enabled=True, reset_material=True)
        self.assertIsNone(executor._client_cert_pfx_path)
        self.assertIsNone(executor._client_cert_passphrase)
        self.assertIsNone(executor._client_cert_cert_path)
        self.assertIsNone(executor._client_cert_key_path)
        self.assertIsNone(executor._client_cert_origins)

    def test_empty_string_clears_path(self):
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(enabled=True, pfx_path=str(files['pfx']))
        executor.configure_client_cert(pfx_path='')
        self.assertIsNone(executor._client_cert_pfx_path)

    def test_reconfigure_invalidates_cached_resolution(self):
        files = self.make_cert_files()
        executor = self.make_executor()
        executor.configure_client_cert(enabled=True, pfx_path=str(files['pfx']))
        executor.set_task_origins(['https://a.com'])
        executor._build_browser_context_options()  # 触发缓存

        executor.configure_client_cert(pfx_path=None)
        executor.configure_client_cert(pfx_path=str(files['pfx2']))
        options = executor._build_browser_context_options()
        self.assertEqual(
            options['client_certificates'][0]['pfxPath'], str(files['pfx2'])
        )


class PassphraseLeakTest(ActuatorTestCase):
    """口令不能出现在任何日志里（含 record.args）。"""

    def test_passphrase_not_logged_anywhere(self):
        files = self.make_cert_files()
        executor = self.make_executor()

        with self.assertLogs('actuator', level='DEBUG') as captured:
            executor.configure_client_cert(
                enabled=True,
                pfx_path=str(files['pfx']),
                passphrase=SECRET_PASSPHRASE,
                origins='https://a.com, notaurl',
            )
            executor.set_task_origins(['https://a.com'])
            options = executor._build_browser_context_options()
            # 再走一遍，覆盖「已打印过指纹」的分支
            executor._build_browser_context_options()

        # 功能正常：口令确实被传给了 Playwright
        self.assertEqual(options['client_certificates'][0]['passphrase'], SECRET_PASSPHRASE)

        for record in captured.records:
            self.assertNotIn(SECRET_PASSPHRASE, record.getMessage())
            self.assertNotIn(SECRET_PASSPHRASE, str(record.args))
            self.assertNotIn(SECRET_PASSPHRASE, str(record.__dict__.get('exc_info')))

    def test_attach_log_contains_origin_and_path(self):
        files = self.make_cert_files()
        executor = self.make_executor()

        with self.assertLogs('actuator', level='INFO') as captured:
            executor.configure_client_cert(enabled=True, pfx_path=str(files['pfx']))
            executor.set_task_origins(['https://a.com'])
            executor._build_browser_context_options()

        attach = [r for r in captured.records if '客户端证书已启用' in r.getMessage()]
        self.assertEqual(len(attach), 1)
        self.assertIn('https://a.com', attach[0].getMessage())


# ---------------------------------------------------------------------------
# 4. 证书材料预校验 + 建上下文失败降级
# ---------------------------------------------------------------------------

class CertPrecheckTest(unittest.TestCase):
    """``_precheck_cert_material``：把「口令错误 / 格式不支持」提前变成明确原因。

    这里用真实 ``cryptography``（若未安装则跳过），因为预校验的整个意义就是
    「真读一遍文件」。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_material_is_skipped(self):
        # 无任何材料 / PEM 只给一半 → 不判断（交给存在性告警）
        self.assertIsNone(PlaywrightExecutor._precheck_cert_material(None, None, None, None, None))
        cert = _write_file(self.tmp / 'client.crt')
        self.assertIsNone(PlaywrightExecutor._precheck_cert_material(None, None, cert, None, None))

    def test_missing_pfx_is_skipped(self):
        missing = self.tmp / 'nope.pfx'
        self.assertIsNone(
            PlaywrightExecutor._precheck_cert_material(None, missing, None, None, None)
        )

    @unittest.skipUnless(HAS_CRYPTOGRAPHY, 'cryptography 未安装（可选依赖），跳过真实预校验')
    def test_corrupted_pfx_reports_reason(self):
        bad = _write_file(self.tmp / 'client.pfx', 'NOT-A-REAL-PKCS12')
        reason = PlaywrightExecutor._precheck_cert_material(None, bad, None, None, None)
        self.assertIsInstance(reason, str)
        self.assertIn('材料无法加载', reason)

    @unittest.skipUnless(HAS_CRYPTOGRAPHY, 'cryptography 未安装（可选依赖），跳过真实预校验')
    def test_corrupted_pem_key_reports_reason(self):
        cert = _write_file(self.tmp / 'client.crt', 'CERT')
        key = _write_file(self.tmp / 'client.key', 'NOT-A-REAL-KEY')
        reason = PlaywrightExecutor._precheck_cert_material(None, None, cert, key, None)
        self.assertIsInstance(reason, str)
        self.assertIn('材料无法加载', reason)

    def test_precheck_failure_disables_cert_and_records_reason(self):
        """预校验失败 → 不注入证书，并记下原因供结果消息提示。"""
        file = _write_file(self.tmp / 'client.pfx', 'P12')
        executor = PlaywrightExecutor(
            user_data_dir=str(self.tmp / 'browser'),
            screenshot_dir=str(self.tmp / 'shots'),
        )
        with patch.object(
            PlaywrightExecutor, '_precheck_cert_material', return_value='boom'
        ):
            executor.configure_client_cert(enabled=True, pfx_path=str(file))
            executor.set_task_origins(['https://a.com'])
            options = executor._build_browser_context_options()

        self.assertNotIn('client_certificates', options)
        self.assertIsNotNone(executor._last_cert_failure)
        self.assertIn('客户端证书不可用', executor._last_cert_failure)


class IsCertErrorTest(unittest.TestCase):
    def test_certificate_related_messages_match(self):
        for text in (
            'client_certificate invalid',
            'Client certificate error',
            'PKCS12 decoding failed',
            'bad pfx',
            'wrong passphrase',
            'certificate verify failed',
            'SSL handshake failure',
            'TLS alert',
        ):
            self.assertTrue(
                PlaywrightExecutor._is_cert_error(Exception(text)), msg=text
            )

    def test_unrelated_messages_do_not_match(self):
        for text in ('target closed', 'timeout 30000ms exceeded', 'browser has been closed'):
            self.assertFalse(
                PlaywrightExecutor._is_cert_error(Exception(text)), msg=text
            )


class InitBrowserContextFallbackTest(unittest.IsolatedAsyncioTestCase):
    """建上下文因证书失败时，必须降级为「不带 client_certificates」重试一次。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _executor(self) -> PlaywrightExecutor:
        executor = PlaywrightExecutor(
            user_data_dir=str(self.tmp / 'browser'),
            screenshot_dir=str(self.tmp / 'shots'),
            persistent=False,
        )
        executor.browser_type = 'chromium'
        executor._playwright = SimpleNamespace(chromium=object())
        executor._page = MagicMock()
        return executor

    async def test_cert_error_falls_back_and_records_reason(self):
        executor = self._executor()
        calls = []

        async def fake_create(browser_launcher, launch_options, context_options):
            calls.append(dict(context_options))
            if 'client_certificates' in context_options:
                raise Exception('pkcs12: unable to load client certificate')

        executor._create_context_page = fake_create
        with patch.object(
            executor, '_build_client_certificates',
            return_value=[{'origin': 'https://a.com', 'pfxPath': '/x.pfx'}],
        ):
            await executor._init_browser_context()

        self.assertEqual(len(calls), 2)
        self.assertIn('client_certificates', calls[0])
        self.assertNotIn('client_certificates', calls[1])
        self.assertIsNotNone(executor._last_cert_failure)
        self.assertIn('降级', executor._last_cert_failure)

    async def test_unrelated_error_is_reraised(self):
        executor = self._executor()

        async def fake_create(browser_launcher, launch_options, context_options):
            raise Exception('target closed')

        executor._create_context_page = fake_create
        with patch.object(
            executor, '_build_client_certificates',
            return_value=[{'origin': 'https://a.com', 'pfxPath': '/x.pfx'}],
        ):
            with self.assertRaises(Exception) as ctx:
                await executor._init_browser_context()

        self.assertIn('target closed', str(ctx.exception))

    async def test_no_cert_in_options_means_no_fallback(self):
        executor = self._executor()

        async def fake_create(browser_launcher, launch_options, context_options):
            raise Exception('ssl error')

        executor._create_context_page = fake_create
        with patch.object(executor, '_build_client_certificates', return_value=[]):
            with self.assertRaises(Exception):
                await executor._init_browser_context()

    def test_result_messages_carry_cert_failure_hint(self):
        """结果消息必须带降级提示，否则用户只看到失败却不知道证书问题。"""
        src = Path(__file__).parent.joinpath('executor.py').read_text(encoding='utf-8')
        self.assertEqual(
            src.count("getattr(self, '_last_cert_failure', None)"),
            2,
            msg='串行与并发两个执行入口都要附上证书降级提示',
        )
        self.assertEqual(src.count('message += f" （提示：{self._last_cert_failure}）"'), 2)


# ---------------------------------------------------------------------------
# 5. base_url 导航参数（回归 cn.bing.com 超时 BUG）
# ---------------------------------------------------------------------------

class EnvBaseUrlNavigationTest(unittest.TestCase):
    """环境 base_url 导航必须对齐录制器：domcontentloaded + 30s 显式超时。

    历史 BUG：``wait_until="networkidle"`` 且未显式传 timeout，会落到页面默认
    超时（= action_timeout，默认 5000ms），导致 cn.bing.com 这类存在持续网络活动
    的站点必然超时。
    """

    def test_navigation_constant_matches_recorder(self):
        self.assertEqual(
            executor_module._ENV_BASE_URL_NAV,
            {'wait_until': 'domcontentloaded', 'timeout': 30000},
        )

    def test_both_entrypoints_use_the_constant(self):
        src = Path(__file__).parent.joinpath('executor.py').read_text(encoding='utf-8')
        self.assertEqual(
            src.count('**_ENV_BASE_URL_NAV'), 2,
            msg='串行与并发入口的 base_url 导航都要用统一参数',
        )

    def test_no_networkidle_in_base_url_navigation(self):
        src = Path(__file__).parent.joinpath('executor.py').read_text(encoding='utf-8')
        self.assertNotIn(
            'wait_until="networkidle"', src,
            msg='base_url 导航不得再用 networkidle（会导致 bing 等站点必然超时）',
        )


# ---------------------------------------------------------------------------
# 6. 节点级证书配置已彻底移除
# ---------------------------------------------------------------------------

class NodeLevelCertRemovedTest(unittest.TestCase):
    """防回归：节点级（config.toml / 环境变量 / 平台白名单）证书配置不得复活。

    证书一律由平台「客户端证书」按 UI 自动化环境配置随任务下发，节点只接收
    任务级参数。任何一处残留都会造成「配置看起来生效、实际被平台覆盖」的歧义。
    """

    def _repo_file(self, relative: str) -> str:
        repo_root = Path(__file__).parent.parent
        path = repo_root / relative
        self.assertTrue(path.exists(), msg=f'找不到文件: {path}')
        return path.read_text(encoding='utf-8')

    def test_executor_constructor_rejects_cert_kwargs(self):
        with self.assertRaises(TypeError):
            PlaywrightExecutor(client_cert_enabled=True)
        with self.assertRaises(TypeError):
            PlaywrightExecutor(ignore_https_errors=True)

    def test_configure_client_cert_has_no_config_dir_param(self):
        import inspect

        params = inspect.signature(PlaywrightExecutor.configure_client_cert).parameters
        self.assertNotIn('config_dir', params)

    def test_actuator_config_field_map_excludes_cert_keys(self):
        from consumer import TaskConsumer

        for key in NODE_LEVEL_CERT_KEYS + ('ignore_https_errors',):
            self.assertNotIn(key, TaskConsumer._CONFIG_FIELD_MAP, msg=f'残留 {key}')

    def test_django_views_whitelist_excludes_cert_keys(self):
        views = self._repo_file('WHartTest_Django/ui_automation/views.py')
        start = views.index('_ACTUATOR_CONFIG_FIELDS = frozenset({')
        end = views.index('})', start)
        block = views[start:end]
        for key in NODE_LEVEL_CERT_KEYS + ('client_cert_passphrase', 'ignore_https_errors'):
            self.assertNotIn(key, block, msg=f'Django views 白名单残留 {key}')

    def test_django_consumers_config_keys_excludes_cert_keys(self):
        consumers = self._repo_file('WHartTest_Django/ui_automation/consumers.py')
        start = consumers.index('config_keys = (')
        end = consumers.index(')', start)
        block = consumers[start:end]
        for key in NODE_LEVEL_CERT_KEYS + ('client_cert_passphrase',):
            self.assertNotIn(key, block, msg=f'Django consumers.config_keys 残留 {key}')

    def test_vue_actuator_api_and_view_exclude_cert_keys(self):
        api_ts = self._repo_file('WHartTest_Vue/src/features/ui-automation/api/index.ts')
        vue = self._repo_file(
            'WHartTest_Vue/src/features/ui-automation/views/ActuatorList.vue'
        )
        for key in NODE_LEVEL_CERT_KEYS:
            self.assertNotIn(key, api_ts, msg=f'Vue api 类型残留 {key}')
            self.assertNotIn(key, vue, msg=f'ActuatorList.vue 残留 {key}')

    def test_websocket_actuator_info_excludes_cert_keys(self):
        import inspect

        from websocket_client import WebSocketClient

        source = inspect.getsource(WebSocketClient._send_actuator_info)
        for key in NODE_LEVEL_CERT_KEYS + ('client_cert_passphrase', 'ignore_https_errors'):
            self.assertNotIn(f"'{key}':", source, msg=f'执行器上报残留 {key}')


class LegacyConfigDeprecationTest(unittest.TestCase):
    """config.toml / 环境变量中的旧证书键只提示迁移，绝不生效。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_config_has_no_cert_attributes(self):
        config = Config()
        for attr in NODE_LEVEL_CERT_KEYS + ('ignore_https_errors', 'config_dir'):
            self.assertFalse(hasattr(config, attr), msg=f'Config 仍持有 {attr}')

    def test_toml_legacy_keys_only_warn(self):
        path = self.tmp / 'config.toml'
        path.write_text(
            '[browser]\n'
            'browser_type = "chromium"\n'
            'client_cert_enabled = true\n'
            'client_cert_pfx_path = "./certs/client.pfx"\n'
            'client_cert_passphrase = "pw"\n'
            'ignore_https_errors = true\n',
            encoding='utf-8',
        )
        config = Config()
        with self.assertLogs(level='WARNING') as captured:
            config.load_from_toml(str(path))

        self.assertTrue(
            any('已不再生效' in r.getMessage() for r in captured.records),
            msg='应提示迁移到 Web 端',
        )
        # 正常键仍生效（证明只是忽略了证书键，不影响其余解析）
        self.assertEqual(config.browser_type, 'chromium')
        for attr in NODE_LEVEL_CERT_KEYS + ('ignore_https_errors',):
            self.assertFalse(hasattr(config, attr), msg=f'{attr} 不应被写入')

    def test_env_legacy_vars_ignored_and_passphrase_popped(self):
        env = {
            'WHARTTEST_ACTUATOR_CLIENT_CERT_ENABLED': 'true',
            'WHARTTEST_ACTUATOR_CLIENT_CERT_PFX_PATH': '/app/certs/client.pfx',
            'WHARTTEST_ACTUATOR_CLIENT_CERT_PASSPHRASE': SECRET_PASSPHRASE,
            'WHARTTEST_ACTUATOR_IGNORE_HTTPS_ERRORS': 'true',
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config()
            with self.assertLogs(level='WARNING') as captured:
                config.load_from_env()

            self.assertTrue(
                any('已不再生效' in r.getMessage() for r in captured.records)
            )
            # 口令即使已废弃也要从环境中移除，避免泄漏给子进程
            self.assertNotIn('WHARTTEST_ACTUATOR_CLIENT_CERT_PASSPHRASE', os.environ)

        for attr in NODE_LEVEL_CERT_KEYS + ('ignore_https_errors',):
            self.assertFalse(hasattr(config, attr), msg=f'{attr} 不应被写入')


class ConsumerRedactionTest(unittest.TestCase):
    def setUp(self):
        from consumer import TaskConsumer

        self.TaskConsumer = TaskConsumer

    def test_config_field_map_excludes_passphrase(self):
        mapping = self.TaskConsumer._CONFIG_FIELD_MAP
        for key, value in mapping.items():
            self.assertNotIn('passphrase', key)
            self.assertNotIn('passphrase', value)

    def test_redact_masks_sensitive_keys(self):
        redacted = self.TaskConsumer._redact(
            {
                'client_cert_passphrase': SECRET_PASSPHRASE,
                'api_password': 'p',
                'model_api_key': 'k',
                'client_cert_pfx_path': '/app/certs/client.pfx',
                'nested': {'passphrase': 'x'},
                'items': [{'secret': 'y'}],
            }
        )
        self.assertEqual(redacted['client_cert_passphrase'], '***')
        self.assertEqual(redacted['api_password'], '***')
        self.assertEqual(redacted['model_api_key'], '***')
        self.assertEqual(redacted['nested']['passphrase'], '***')
        self.assertEqual(redacted['items'][0]['secret'], '***')
        # 非敏感字段原样保留
        self.assertEqual(redacted['client_cert_pfx_path'], '/app/certs/client.pfx')

    def test_redact_keeps_empty_values(self):
        self.assertEqual(self.TaskConsumer._redact({'api_password': ''})['api_password'], '')

    def test_redact_passthrough_for_scalars(self):
        self.assertEqual(self.TaskConsumer._redact('plain'), 'plain')
        self.assertIsNone(self.TaskConsumer._redact(None))


class PersistConfigNoCertKeysTest(unittest.TestCase):
    """平台下发配置写回 config.toml 时，绝不能再写入节点级证书键。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.path = self.tmp / 'config.toml'

    def tearDown(self):
        self._tmp.cleanup()

    def _make_consumer(self):
        from consumer import TaskConsumer

        consumer = TaskConsumer.__new__(TaskConsumer)  # 跳过 __init__（会拉起网络/队列）
        consumer.config_path = str(self.path)
        return consumer

    def test_cert_keys_are_not_persisted(self):
        import tomllib

        self.path.write_text(
            f'[browser]\nclient_cert_passphrase = "{SECRET_PASSPHRASE}"\n',
            encoding='utf-8',
        )
        consumer = self._make_consumer()
        consumer._persist_config(
            {
                'client_cert_enabled': True,
                'client_cert_pfx_path': './certs/client.pfx',
                'client_cert_origins': 'https://a.example.com',
            }
        )

        with open(self.path, 'rb') as fh:
            data = tomllib.load(fh)

        browser = data['browser']
        for key in NODE_LEVEL_CERT_KEYS:
            self.assertNotIn(key, browser, msg=f'{key} 不应被持久化')
        # 本机已有的旧键也不会被铲除（不主动破坏用户文件），但绝不会被平台值覆盖
        self.assertEqual(browser['client_cert_passphrase'], SECRET_PASSPHRASE)

    def test_normal_fields_round_trip(self):
        import tomllib

        self.path.write_text(
            '[server]\nws_url = "ws://backend:8000/ws/ui/actuator/"\n',
            encoding='utf-8',
        )
        consumer = self._make_consumer()
        consumer._persist_config({'browser_type': 'firefox', 'retry_count': 5})

        with open(self.path, 'rb') as fh:
            data = tomllib.load(fh)

        self.assertEqual(data['server']['ws_url'], 'ws://backend:8000/ws/ui/actuator/')
        self.assertEqual(data['browser']['browser_type'], 'firefox')
        self.assertEqual(data['execution']['retry_count'], 5)

    def test_none_values_are_skipped(self):
        import tomllib

        consumer = self._make_consumer()
        consumer._persist_config({'browser_type': None, 'retry_count': 2})

        with open(self.path, 'rb') as fh:
            data = tomllib.load(fh)

        self.assertNotIn('browser_type', data['browser'])
        self.assertEqual(data['execution']['retry_count'], 2)


# ---------------------------------------------------------------------------
# 7. 执行器 local_merge 兜底路径的 ignore_https_errors 三态
# ---------------------------------------------------------------------------

class IgnoreHttpsErrorsRuntimeTest(unittest.TestCase):
    """执行器 local_merge 兜底路径的 ignore_https_errors 三态。

    后端正常会直接下发 effective_runtime（已含该键）；这里覆盖的是后端未下发、
    执行器按 env_config + 节点默认值本地合并的场景，行为必须与 Django 侧
    ui_automation/runtime_config.py 一致：None = auto。
    """

    def _resolve(self, env=None, run_options=None):
        return resolve_from_env_and_actuator(env=env, run_options=run_options)

    def test_absent_everywhere_yields_none(self):
        self.assertIsNone(self._resolve(env={'name': 'e'})['ignore_https_errors'])

    def test_env_true_is_applied(self):
        self.assertTrue(self._resolve(env={'ignore_https_errors': True})['ignore_https_errors'])

    def test_env_false_is_applied(self):
        self.assertFalse(self._resolve(env={'ignore_https_errors': False})['ignore_https_errors'])

    def test_env_none_means_auto(self):
        self.assertIsNone(self._resolve(env={'ignore_https_errors': None})['ignore_https_errors'])

    def test_run_options_override_env(self):
        resolved = self._resolve(
            env={'ignore_https_errors': True},
            run_options={'ignore_https_errors': False},
        )
        self.assertFalse(resolved['ignore_https_errors'])

    def test_string_value_is_normalized(self):
        self.assertTrue(self._resolve(env={'ignore_https_errors': 'true'})['ignore_https_errors'])

    def test_env_policy_omits_auto(self):
        """None 不进 policy：否则会被误判为"环境显式配置"。"""
        self.assertNotIn('ignore_https_errors', extract_env_policy({'ignore_https_errors': None}))
        self.assertIn('ignore_https_errors', extract_env_policy({'ignore_https_errors': False}))

    def test_normalize_run_options_keeps_explicit_values(self):
        self.assertEqual(
            normalize_run_options({'ignore_https_errors': False})['ignore_https_errors'], False
        )
        self.assertNotIn('ignore_https_errors', normalize_run_options({'ignore_https_errors': None}))


# ---------------------------------------------------------------------------
# 8. consumer 任务级证书通道（平台下发 → 下载 → 注入）
# ---------------------------------------------------------------------------

class ConsumerTaskOriginWiringTest(unittest.TestCase):
    """三个执行入口必须显式固定任务 origin 并让三态开关贯通（防回归）。"""

    def _consumer(self) -> str:
        path = Path(__file__).parent / 'consumer.py'
        return path.read_text(encoding='utf-8')

    def test_every_entrypoint_prepares_task_origins(self):
        src = self._consumer()
        self.assertEqual(
            src.count('self.executor.prepare_task_origins('), 3,
            msg='页面步骤/用例/批量三个执行入口都要调用 prepare_task_origins',
        )

    def test_entrypoints_pass_platform_origins(self):
        src = self._consumer()
        self.assertEqual(src.count('extra_origins=self._client_cert_task_origins(args)'), 3)

    def test_runtime_opts_forward_ignore_https_errors(self):
        src = self._consumer()
        self.assertIn(
            '"ignore_https_errors": effective.get("ignore_https_errors")',
            src,
            msg='_runtime_for_executor 必须把三态开关透传给执行器',
        )

    def test_task_cert_resolved_and_downloaded(self):
        src = self._consumer()
        self.assertIn('await self._resolve_task_client_cert(args)', src)
        self.assertIn('opts["client_cert"] = task_cert', src)

    def test_task_origins_extracted_from_payload(self):
        from consumer import TaskConsumer

        args = {
            'client_cert': {
                'origins': ['https://a.example.com', 'http://insecure.example.com'],
            }
        }
        self.assertEqual(
            TaskConsumer._client_cert_task_origins(args),
            ['https://a.example.com', 'http://insecure.example.com'],
        )
        self.assertEqual(TaskConsumer._client_cert_task_origins(None), [])
        self.assertEqual(TaskConsumer._client_cert_task_origins({}), [])


if __name__ == '__main__':
    # 避免测试过程的日志被生产 handler 吞掉（assertLogs 需要真实生效）
    logging.getLogger('actuator').setLevel(logging.DEBUG)
    unittest.main(verbosity=2)
