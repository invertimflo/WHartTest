"""客户端证书材料准备。

接口自动化（httprunner / requests）与 UI 自动化（Actuator / Playwright）对证书材料的
要求不同，本模块只解决**接口侧**的问题：

- ``requests`` 的 ``cert`` 参数只接受 **PEM 文件路径**（或 (证书, 私钥) 二元组，
  或"证书+未加密私钥"合并的单个 PEM），**不支持** .pfx/.p12，也不支持给私钥传口令。
- 因此凡是"带口令的 PEM"与"PKCS#12"，都必须在这里转换成**未加密的合并 PEM**再落盘，
  把路径交给 requests。转换产物按证书指纹缓存，避免每次执行都解密。

UI 侧不需要本模块：Playwright 的 ``client_certificates`` 原生支持
``pfxPath`` + ``passphrase`` 与 ``certPath``/``keyPath``（见执行器 client_cert.py）。

失败一律降级为「本次不启用该证书」并记录告警，不抛异常 —— 与执行器侧
"只告警不阻断"的风格保持一致，避免一个可选特性把整个用例执行搞挂。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional, Tuple, Union

from django.conf import settings

logger = logging.getLogger(__name__)

# requests 接受的 cert 形态：二元组 (证书, 私钥) 或单个合并 PEM 路径
RequestsCert = Union[str, Tuple[str, str]]

CACHE_DIR_NAME = '.client_cert_cache'


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
    """
    if env is None or not getattr(env, 'client_certificate_id', None):
        return None
    origins = [env.base_url] if getattr(env, 'base_url', None) else []
    try:
        return build_runtime_client_cert(env.client_certificate, origins=origins)
    except Exception as exc:  # noqa: BLE001 - 证书组装失败不应阻断任务下发
        logger.warning('构造环境 %s 的客户端证书载荷失败：%s', getattr(env, 'id', None), exc)
        return None


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
