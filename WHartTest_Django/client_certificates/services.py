"""客户端证书材料准备。

接口自动化（httprunner / requests）与 UI 自动化（Actuator / Playwright）对证书材料的
要求不同，本模块只解决**接口侧**的问题：

- ``requests`` 的 ``cert`` 参数只接受 **PEM 文件路径**（或 (证书, 私钥) 二元组，
  或"证书+未加密私钥"合并的单个 PEM），**不支持** .pfx/.p12，也不支持给私钥传口令。
- 因此凡是"带口令的 PEM"与"PKCS#12"，都必须在这里转换成**未加密的合并 PEM**再落盘，
  把路径交给 requests。转换产物按证书指纹缓存，避免每次执行都解密。

UI 侧（执行器）不需要本模块的 requests 转换：Playwright 的 ``client_certificates``
原生支持 ``pfxPath`` + ``passphrase`` 与 ``certPath``/``keyPath``（见执行器
client_cert.py）。但**本地录制器**（ui_automation/recorder/recorder_server.js）
与 Django 同机运行，需要「本地文件路径 + 已解析的 ignore 布尔」这一形态，
故本模块另提供 ``build_recorder_https_payload`` 一族函数。

失败一律降级为「本次不启用该证书」并记录告警，不抛异常 —— 与执行器侧
"只告警不阻断"的风格保持一致，避免一个可选特性把整个用例执行搞挂。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Iterable, Optional, Tuple, Union
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import SynchronousOnlyOperation

logger = logging.getLogger(__name__)

# requests 接受的 cert 形态：二元组 (证书, 私钥) 或单个合并 PEM 路径
RequestsCert = Union[str, Tuple[str, str]]

CACHE_DIR_NAME = '.client_cert_cache'

# Playwright 的 origin 必须精确匹配 https://host[:port]，443 显式端口与省略等价
DEFAULT_HTTPS_PORT = 443


# ----------------------------------------------------------------------
# 路径与缓存
# ----------------------------------------------------------------------

def get_cache_dir() -> Path:
    """证书转换产物的缓存目录（默认 MEDIA_ROOT/.client_cert_cache）。"""
    configured = getattr(settings, 'CLIENT_CERT_CACHE_DIR', None)
    base = Path(configured) if configured else Path(settings.MEDIA_ROOT) / CACHE_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def asset_filesystem_path(asset) -> str:
    """取托管文件的本地绝对路径；不可用时返回空串。"""
    if asset is None or not getattr(asset, 'file', None):
        return ''
    try:
        return asset.file.path or ''
    except (NotImplementedError, ValueError, AttributeError, OSError) as exc:
        logger.warning('客户端证书文件无法解析本地路径 (file_id=%s): %s', getattr(asset, 'id', None), exc)
        return ''


def _fingerprint(certificate) -> str:
    """按 (证书id, 更新时间, 文件 sha256) 生成缓存键，材料变化即失效。"""
    parts = [
        str(getattr(certificate, 'id', '') or ''),
        str(getattr(certificate, 'updated_at', '') or ''),
        str(certificate.cert_file_id or ''),
        str(certificate.key_file_id or ''),
    ]
    for asset in (certificate.cert_file, certificate.key_file):
        if asset is not None:
            parts.append(asset.sha256 or str(asset.id))
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]


def _write_private_file(data: bytes, target: Path) -> str:
    """原子写入并尽力收紧权限（0600）。"""
    tmp = target.with_name(f'{target.name}.{os.getpid()}.part')
    with open(tmp, 'wb') as fh:
        fh.write(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Windows 等平台可能不支持，属可接受降级
        pass
    tmp.replace(target)
    return str(target)


def _write_combined_pem(cert_pem: bytes, key_pem: bytes, cache_key: str) -> str:
    """把证书与未加密私钥合并写成单个 PEM（requests 可直接使用）。"""
    target = get_cache_dir() / f'{cache_key}.pem'
    if target.exists() and target.stat().st_size > 0:
        return str(target)
    merged = cert_pem.rstrip() + b'\n' + key_pem.rstrip() + b'\n'
    return _write_private_file(merged, target)


# ----------------------------------------------------------------------
# 材料准备
# ----------------------------------------------------------------------

def _load_pkcs12(pfx_path: str, passphrase: str) -> Tuple[bytes, bytes]:
    """解析 .pfx/.p12，返回 (证书PEM, 未加密私钥PEM)。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    with open(pfx_path, 'rb') as fh:
        pfx_bytes = fh.read()

    password = passphrase.encode('utf-8') if passphrase else None
    key_obj, cert_obj, additional = pkcs12.load_key_and_certificates(pfx_bytes, password)
    if key_obj is None or cert_obj is None:
        raise ValueError('PKCS#12 文件中缺少私钥或证书，或口令不正确')

    cert_pem = cert_obj.public_bytes(serialization.Encoding.PEM)
    for extra in additional or []:
        cert_pem += extra.public_bytes(serialization.Encoding.PEM)
    key_pem = key_obj.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _load_encrypted_pem_key(key_path: str, passphrase: str) -> bytes:
    """读取带口令的 PEM 私钥并解密为未加密 PEM。"""
    from cryptography.hazmat.primitives import serialization

    with open(key_path, 'rb') as fh:
        key_bytes = fh.read()
    key_obj = serialization.load_pem_private_key(
        key_bytes, password=passphrase.encode('utf-8') if passphrase else None
    )
    return key_obj.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def materialize_for_requests(certificate) -> Optional[RequestsCert]:
    """把 ClientCertificate 转成 requests 可用的 ``cert`` 参数。

    返回值：
      - ``(cert_path, key_path)``：PEM 且私钥无口令 —— requests 原生支持，不落缓存
      - ``str``（合并 PEM 路径）：带口令 PEM / PKCS#12 已解密转换后的产物
      - ``None``：证书未配置完整、文件缺失、口令错误 —— 本次不启用并告警
    """
    if certificate is None:
        return None

    cert_path = asset_filesystem_path(certificate.cert_file)
    key_path = asset_filesystem_path(certificate.key_file)
    passphrase = certificate.get_passphrase()

    if certificate.cert_type == certificate.CERT_TYPE_PEM:
        if not cert_path or not os.path.exists(cert_path):
            logger.warning('客户端证书「%s」的证书文件缺失，本次不启用该证书', certificate.name)
            return None
        if passphrase:
            if not key_path or not os.path.exists(key_path):
                logger.warning('客户端证书「%s」的私钥文件缺失，本次不启用该证书', certificate.name)
                return None
            try:
                key_pem = _load_encrypted_pem_key(key_path, passphrase)
                with open(cert_path, 'rb') as fh:
                    cert_pem = fh.read()
                return _write_combined_pem(cert_pem, key_pem, _fingerprint(certificate))
            except Exception as exc:  # noqa: BLE001 - 口令错误/格式损坏均降级
                logger.warning(
                    '客户端证书「%s」私钥解密失败（口令是否正确？），本次不启用该证书：%s',
                    certificate.name, exc,
                )
                return None
        # 无口令 PEM：requests 直接吃两个路径，无需转换
        if not key_path or not os.path.exists(key_path):
            logger.warning('客户端证书「%s」的私钥文件缺失，本次不启用该证书', certificate.name)
            return None
        return (cert_path, key_path)

    if certificate.cert_type == certificate.CERT_TYPE_PKCS12:
        if not cert_path or not os.path.exists(cert_path):
            logger.warning('客户端证书「%s」的 PKCS#12 文件缺失，本次不启用该证书', certificate.name)
            return None
        try:
            cert_pem, key_pem = _load_pkcs12(cert_path, passphrase)
            return _write_combined_pem(cert_pem, key_pem, _fingerprint(certificate))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                '客户端证书「%s」PKCS#12 解析失败（口令是否正确？），本次不启用该证书：%s',
                certificate.name, exc,
            )
            return None

    logger.warning('客户端证书「%s」类型未知，本次不启用该证书', certificate.name)
    return None


def build_runtime_client_cert(certificate, *, origins=None) -> Optional[dict]:
    """构造执行器侧（Playwright）使用的证书任务载荷。

    与 materialize_for_requests 的区别：Playwright **原生支持**
    ``pfxPath`` + ``passphrase`` 与 ``certPath``/``keyPath``，因此这里不做任何
    格式转换，只需要把「托管文件的可下载描述」与口令原样交给执行器，
    由执行器下载落盘后再组装（见 WHartTest_Actuator/client_cert.py）。

    ⚠️ 返回值**包含口令明文**，只允许经 WebSocket 下发给执行器；
    任何回传前端的路径都必须先剥离 passphrase（见 ui_automation.consumers
    的 _sanitize_result_args）。
    """
    if certificate is None:
        return None

    from file_management.services import serialize_file_for_runtime

    payload: dict = {
        'certificate_id': certificate.id,
        'name': certificate.name,
        'cert_type': certificate.cert_type,
        'has_passphrase': certificate.has_passphrase,
        'cert_file': (
            serialize_file_for_runtime(certificate.cert_file)
            if certificate.cert_file_id else None
        ),
        'key_file': (
            serialize_file_for_runtime(certificate.key_file)
            if certificate.key_file_id else None
        ),
    }

    passphrase = certificate.get_passphrase()
    if passphrase:
        payload['passphrase'] = passphrase

    if origins:
        payload['origins'] = list(origins)

    return payload


def build_env_client_cert_payload(env) -> Optional[dict]:
    """按 UI 环境配置构造待下发执行器的证书载荷（环境未绑定证书时返回 None）。

    收敛到一处，保证 WebSocket 单用例/批量与 HTTP 批量触发三条下发路径行为一致。

    ⚠️ **同步函数**：内部会通过外键懒加载 ``client_certificate`` 及其
    ``cert_file`` / ``key_file``。**绝不可在异步上下文（Channels consumer 的事件
    循环）里直接调用** —— 同步 ORM 会抛 ``SynchronousOnlyOperation``。异步调用方
    请改用 :func:`build_env_client_cert_payload_async`。
    """
    if env is None or not getattr(env, 'client_certificate_id', None):
        return None
    origins = [env.base_url] if getattr(env, 'base_url', None) else []
    try:
        return build_runtime_client_cert(env.client_certificate, origins=origins)
    except SynchronousOnlyOperation:
        # 编程错误（不是证书本身的问题），必须明显区别于「证书不可用」的降级：
        # 早期版本把它一起吞成「本次不启用证书」，导致 mTLS 站点只看到 400/白屏、
        # 日志里只有一条不起眼的告警，排查代价极高。这里按 ERROR 记录并给出改法。
        logger.error(
            '构造环境 %s 的客户端证书载荷失败：检测到在异步上下文内同步访问 ORM，'
            '请改用 build_env_client_cert_payload_async()。本次未下发客户端证书。',
            getattr(env, 'id', None),
        )
        return None
    except Exception as exc:  # noqa: BLE001 - 证书组装失败不应阻断任务下发
        logger.warning('构造环境 %s 的客户端证书载荷失败：%s', getattr(env, 'id', None), exc)
        return None


async def build_env_client_cert_payload_async(env) -> Optional[dict]:
    """:func:`build_env_client_cert_payload` 的**异步上下文安全版**。

    专供 Channels 异步 consumer（``ui_automation.consumers``）使用：载荷组装会触发
    ``client_certificate`` → ``cert_file`` / ``key_file`` 等外键懒加载，直接在事件循环
    内执行会被 Django 拒绝（``SynchronousOnlyOperation``）。这里统一丢进线程池，调用方
    无需再关心 DB 线程边界。

    失败语义与同步版一致：任何异常都降级为 ``None``（本次不启用客户端证书），不阻断任务。
    """
    from asgiref.sync import sync_to_async

    return await sync_to_async(build_env_client_cert_payload)(env)


# ----------------------------------------------------------------------
# HTTPS origin 归一化
#
# Playwright 的 clientCertificates 要求 origin **精确匹配** https://host[:port]，
# 不支持通配、不接受 path/query。语义必须与执行器侧
# WHartTest_Actuator/client_cert.py 的 normalize_origin 完全一致 —— 两侧对同一
# 个 base_url 必须推导出同一个 origin，否则会出现「执行器能用、录制器不能用」
# 这类难查的偏差。本模块是平台侧（env_config 权威数据所在）的权威实现，
# 录制器 Node 侧只消费结果、不做二次推导。
# ----------------------------------------------------------------------

def normalize_origin(url: Optional[str]) -> Optional[str]:
    """把任意 URL 归一化成 Playwright 需要的 https origin（``https://host[:port]``）。

    仅接受 https；丢弃 path / query / fragment / userinfo；非 443 端口保留，
    显式 443 去掉（``https://a.com:443`` 与 ``https://a.com`` 等价）；IPv6 主机
    重新加方括号。无法解析或非 https 时返回 ``None``。
    """
    if not url or not isinstance(url, str):
        return None

    raw = url.strip()
    if not raw:
        return None

    try:
        parts = urlsplit(raw)
    except ValueError:
        return None

    if parts.scheme.lower() != 'https':
        return None

    hostname = parts.hostname
    if not hostname:
        return None

    # urlsplit.hostname 会剥掉 IPv6 的方括号，这里补回来
    host = f'[{hostname}]' if ':' in hostname else hostname

    try:
        port = parts.port
    except ValueError:
        return None

    if port is None or port == DEFAULT_HTTPS_PORT:
        return f'https://{host}'

    return f'https://{host}:{port}'


def parse_origins(*values: Optional[str]) -> list:
    """把若干「origin 或逗号分隔的 origin 串」合并为去重、保序的 origin 列表。

    非 https 项与无法解析项被静默丢弃（调用方通过返回值是否为空判断）。
    """
    result: list = []
    seen: set = set()

    for value in values:
        if not value or not isinstance(value, str):
            continue
        for chunk in value.split(','):
            origin = normalize_origin(chunk)
            if origin and origin not in seen:
                seen.add(origin)
                result.append(origin)

    return result


# ----------------------------------------------------------------------
# 本地录制器（Node recorder_server.js）侧材料准备
#
# 与执行器路径的本质差异：录制器由 Django 用 subprocess 拉起，**与 Django 同机同
# 容器**，因此不需要「托管文件描述 + 远程下载」，直接给本地绝对路径即可。
# ----------------------------------------------------------------------

def _asset_cache_suffix(asset) -> str:
    """缓存文件名后缀：沿用原文件扩展名便于排查，拿不到就退化为 .bin。"""
    file_field = getattr(asset, 'file', None)
    raw = getattr(file_field, 'name', '') if file_field is not None else ''
    if not raw:
        raw = getattr(asset, 'filename', '') or ''
    suffix = Path(str(raw)).suffix.lower()
    return suffix if 0 < len(suffix) <= 10 else '.bin'


def _materialize_asset_to_cache(asset, cache_key: str, suffix: str) -> str:
    """取证书文件的**本地可读路径**；文件不在本地磁盘时落到缓存目录兜底。

    ``asset_filesystem_path`` 依赖 ``FieldFile.path``，对 S3 等非本地存储后端会
    抛 NotImplementedError —— 而录制器 Node 进程只能读本地文件。此时改为读出字节
    写入 ``MEDIA_ROOT/.client_cert_cache``（0600），保证一定能拿到可读路径。
    失败返回空串（调用方降级为「本次不启用证书」）。
    """
    path = asset_filesystem_path(asset)
    if path and os.path.exists(path):
        return path

    file_field = getattr(asset, 'file', None)
    if file_field is None:
        return ''

    try:
        target = get_cache_dir() / f'{cache_key}{suffix}'
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        with file_field.storage.open(file_field.name, 'rb') as fh:
            data = fh.read()
        if not data:
            return ''
        return _write_private_file(data, target)
    except Exception as exc:  # noqa: BLE001 - 存储后端异常统一降级
        logger.warning('客户端证书文件无法落到本地缓存：%s', exc)
        return ''


def build_recorder_client_certificates(certificate, *, origins=None) -> Tuple[list, list]:
    """构造**本地录制器**用的 Playwright ``clientCertificates`` 条目 + 中文告警。

    返回 ``(entries, warnings)``：

    - ``entries``：camelCase 键的 dict 列表（Playwright **JS** 侧只认
      ``origin`` / ``pfxPath`` / ``certPath`` / ``keyPath`` / ``passphrase``，
      写成 snake_case 会被**静默忽略** —— 证书不生效且不报错）。
    - ``warnings``：中文原因列表，供接口响应/前端提示。

    材料形态（Playwright 只接受这两种）：
      - PKCS#12：``pfxPath`` + ``passphrase``（口令为空时不带该键）
      - PEM：``certPath`` + ``keyPath``

    PEM 带口令时，Playwright 对「加密私钥 + passphrase」的支持随实现而异，这里
    统一先用 ``cryptography`` 解出**未加密私钥**落缓存再交给 Playwright，规避
    不确定性。PKCS#12 也先本地预校验一次，把「口令错/格式不支持」在启动阶段就
    变成明确告警，而不是等 Chromium 握手失败后只看到白屏。

    **绝不抛异常**：证书只是可选特性，任何失败都降级为「本次不启用 + 告警」。
    日志只记录 origin 与文件路径，**绝不记录口令**。
    """
    if certificate is None:
        return [], []

    name = getattr(certificate, 'name', '') or ''
    origin_list = parse_origins(*(origins or []))
    if not origin_list:
        return [], [
            f'客户端证书「{name}」未生效：未能从环境基础 URL 推导出 https origin'
            '（Playwright 要求 origin 精确匹配且不支持通配，非 https 站点无法启用客户端证书）。'
        ]

    fingerprint = _fingerprint(certificate)
    cert_path = _materialize_asset_to_cache(
        certificate.cert_file, f'{fingerprint}-cert', _asset_cache_suffix(certificate.cert_file),
    )
    key_path = _materialize_asset_to_cache(
        certificate.key_file, f'{fingerprint}-key', _asset_cache_suffix(certificate.key_file),
    )

    passphrase = ''
    try:
        passphrase = certificate.get_passphrase() or ''
    except Exception as exc:  # noqa: BLE001
        logger.warning('客户端证书「%s」口令解密失败：%s', name, exc)

    if not cert_path:
        return [], [f'客户端证书「{name}」的证书文件缺失或不可读，本次不启用该证书。']

    common: dict = {}
    if certificate.cert_type == certificate.CERT_TYPE_PKCS12:
        try:
            # 预校验：口令错误 / 不是合法的 PKCS#12 都在这里暴露
            _load_pkcs12(cert_path, passphrase)
        except Exception as exc:  # noqa: BLE001
            logger.warning('客户端证书「%s」PKCS#12 预校验失败：%s', name, exc)
            return [], [
                f'客户端证书「{name}」不可用：PKCS#12 解析失败（口令是否正确？或格式不受支持）：{exc}'
            ]
        common['pfxPath'] = cert_path
        # 纯空白视为「未设置」：带上会让 Chromium 解密失败；含非空白字符的口令原样传递
        if passphrase and passphrase.strip():
            common['passphrase'] = passphrase
    else:
        if not key_path:
            return [], [f'客户端证书「{name}」的私钥文件缺失或不可读，本次不启用该证书。']
        if passphrase:
            try:
                key_pem = _load_encrypted_pem_key(key_path, passphrase)
            except Exception as exc:  # noqa: BLE001
                logger.warning('客户端证书「%s」私钥解密失败：%s', name, exc)
                return [], [
                    f'客户端证书「{name}」不可用：私钥解密失败（口令是否正确？或私钥格式不受支持）：{exc}'
                ]
            try:
                key_path = _write_private_file(
                    key_pem, get_cache_dir() / f'{fingerprint}.key.pem',
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning('客户端证书「%s」解密私钥落盘失败：%s', name, exc)
                return [], [f'客户端证书「{name}」不可用：解密后的私钥无法落盘（{exc}）。']
        common['certPath'] = cert_path
        common['keyPath'] = key_path

    logger.info(
        '录制器已启用客户端证书「%s」（类型=%s），生效 origin：%s，证书文件：%s',
        name, certificate.cert_type, ', '.join(origin_list), cert_path,
    )
    return [{'origin': origin, **common} for origin in origin_list], []


def resolve_recorder_ignore_https_errors(env, cert_entries) -> bool:
    """录制器的「忽略 HTTPS 证书校验」三态解析 —— 语义严格对齐执行器。

    环境配置留空（``None``）= auto：**仅当客户端证书确实生效时**才忽略服务端证书
    错误。理由是自签名服务端证书恰恰是客户端证书最常见的搭配场景，此时不忽略必然
    握手失败；而裸 HTTP/公网可信证书场景维持原有的严格校验行为不变。
    ``True`` / ``False`` = 用户显式选择，强制覆盖。
    """
    configured = getattr(env, 'ignore_https_errors', None)
    if configured is None:
        return bool(cert_entries)
    return bool(configured)


def build_recorder_https_payload(env, *, extra_urls: Iterable[str] = ()) -> dict:
    """收敛入口：为本地录制器构造 https 相关启动参数。

    返回::

        {
          'client_certificates': [ {...camelCase...} ],   # 材料不可用时为空列表
          'ignore_https_errors': bool,                    # 已按三态解析完成
          'warnings': [ '中文原因', ... ],
        }

    ``extra_urls`` 用于补充 origin 候选（录制=base_url；无执行器执行=各分组导航
    地址），覆盖「环境未配 base_url、按页面 URL 导航」的场景。
    """
    payload = {'client_certificates': [], 'ignore_https_errors': False, 'warnings': []}
    if env is None:
        return payload

    cert_bound = bool(getattr(env, 'client_certificate_id', None))
    certificate = getattr(env, 'client_certificate', None) if cert_bound else None

    if certificate is None:
        # 未绑定证书时仍要解析三态：用户可能显式要求「忽略 HTTPS 校验」
        payload['ignore_https_errors'] = resolve_recorder_ignore_https_errors(env, [])
        if cert_bound:
            payload['warnings'] = ['环境绑定的客户端证书已被删除，本次不启用客户端证书。']
        return payload

    origins = parse_origins(getattr(env, 'base_url', None), *(extra_urls or ()))
    try:
        entries, warnings = build_recorder_client_certificates(certificate, origins=origins)
    except Exception as exc:  # noqa: BLE001
        # 双保险：证书只是可选特性，任何意外都不允许阻断录制/执行的启动
        logger.warning('构造录制器客户端证书失败：%s', exc)
        name = getattr(certificate, 'name', '') or ''
        entries, warnings = [], [f'客户端证书「{name}」组装失败，本次不启用：{exc}']
    payload['client_certificates'] = entries
    payload['ignore_https_errors'] = resolve_recorder_ignore_https_errors(env, entries)
    payload['warnings'] = list(warnings)
    return payload


def env_config_certificate_warnings(env) -> list:
    """环境配置层面的证书预检告警（供 API 只读字段展示，不写副作用、不抛异常）。

    只回答一个问题：**这张证书在这个环境里有没有可能生效**。为此刻意只做廉价
    检查（origin 可推导性、证书是否启用、文件是否存在），不做 cryptography 加载
    —— 后者已由证书自身的 ``validate`` 动作覆盖，而本函数会在环境列表接口里对
    每一行执行。
    """
    if env is None or not getattr(env, 'client_certificate_id', None):
        return []

    certificate = getattr(env, 'client_certificate', None)
    if certificate is None:
        return ['环境绑定的客户端证书已被删除，执行与录制时都不会启用。']

    warnings: list = []
    base_url = (getattr(env, 'base_url', '') or '').strip()
    if not base_url:
        warnings.append(
            '未填写基础 URL，无法确定客户端证书的生效 origin（录制/执行将回退到页面 URL）。'
        )
    elif not normalize_origin(base_url):
        warnings.append(
            f'基础 URL「{base_url}」不是可用的 https 地址，客户端证书不会生效'
            '（Playwright 仅对 https origin 启用客户端证书）。'
        )

    if not getattr(certificate, 'is_active', True):
        warnings.append(f'客户端证书「{certificate.name}」已禁用，执行与录制时都不会启用。')

    cert_path = asset_filesystem_path(certificate.cert_file)
    if certificate.cert_file_id and not cert_path:
        warnings.append(f'客户端证书「{certificate.name}」的证书文件在存储后端不可读。')
    elif cert_path and not os.path.exists(cert_path):
        warnings.append(f'客户端证书「{certificate.name}」的证书文件不存在：{cert_path}')

    return warnings


def validate_certificate(certificate) -> list:
    """试办加载证书，返回告警字符串列表（空列表表示可用）。

    供前端"校验"按钮使用：**不抛异常、不写缓存以外的副作用**。
    """
    warnings = []
    if certificate is None:
        return ['证书不存在。']

    from .models import validate_certificate_fields

    field_errors = validate_certificate_fields(
        certificate.cert_type,
        certificate.cert_file if certificate.cert_file_id else None,
        certificate.key_file if certificate.key_file_id else None,
        certificate.project_id,
    )
    warnings.extend(str(msg) for msg in field_errors.values())

    cert_path = asset_filesystem_path(certificate.cert_file)
    if certificate.cert_file_id and not cert_path:
        warnings.append('证书文件在存储后端不可读。')
    elif cert_path and not os.path.exists(cert_path):
        warnings.append(f'证书文件不存在：{cert_path}')

    key_path = asset_filesystem_path(certificate.key_file)
    if certificate.key_file_id and key_path and not os.path.exists(key_path):
        warnings.append(f'私钥文件不存在：{key_path}')

    if warnings:
        return warnings

    passphrase = certificate.get_passphrase()
    if certificate.has_passphrase and not passphrase:
        warnings.append('口令已存储但无法解密（加密密钥可能已变更），请重新设置口令。')
        return warnings

    try:
        if certificate.cert_type == certificate.CERT_TYPE_PKCS12:
            from cryptography.hazmat.primitives.serialization import pkcs12

            with open(cert_path, 'rb') as fh:
                pfx_bytes = fh.read()
            key_obj, cert_obj, _ = pkcs12.load_key_and_certificates(
                pfx_bytes, passphrase.encode('utf-8') if passphrase else None
            )
            if key_obj is None or cert_obj is None:
                warnings.append('PKCS#12 文件中缺少私钥或证书。')
        else:
            if passphrase:
                _load_encrypted_pem_key(key_path, passphrase)
            else:
                from cryptography.hazmat.primitives import serialization

                with open(key_path, 'rb') as fh:
                    serialization.load_pem_private_key(fh.read(), password=None)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f'证书加载失败（口令或文件格式问题）：{exc}')

    return warnings
