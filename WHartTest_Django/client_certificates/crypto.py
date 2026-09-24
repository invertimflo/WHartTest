"""客户端证书口令的对称加解密（Fernet）。

设计要点：

1. 本模块刻意**不导入本 app 的其他模块**（models/services），以避免循环导入；
   只依赖 Django settings 与 cryptography。
2. cryptography 采用**惰性导入**：即使环境未安装该依赖，app 仍可正常加载，
   只有真正加密/解密时才报错 —— 避免把整个后端拖挂。
3. 密钥来源优先取环境变量 ``CLIENT_CERT_FERNET_KEY``（可轮换、与 SECRET_KEY 解耦）；
   未配置时由 ``SECRET_KEY`` 派生。**用 SECRET_KEY 派生时，DJANGO_SECRET_KEY 一旦变更，
   历史口令将无法解密**，生产环境建议显式固定 CLIENT_CERT_FERNET_KEY。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# 派生密钥用的域分隔前缀，避免与其他基于 SECRET_KEY 的派生撞车
DERIVE_PREFIX = b"wharttest-client-cert:"
ENV_KEY_NAME = "CLIENT_CERT_FERNET_KEY"

_fernet = None


def _derive_key() -> bytes:
    """返回 Fernet 所需的 urlsafe base64 密钥。"""
    configured = (os.environ.get(ENV_KEY_NAME) or "").strip()
    if configured:
        try:
            raw = configured.encode("ascii")
            # Fernet 要求 32 字节 urlsafe base64；这里只做形状校验，具体由 Fernet 决定
            if len(base64.urlsafe_b64decode(raw)) == 32:
                return raw
            logger.warning(
                "%s 解码后不是 32 字节，将改用 SECRET_KEY 派生密钥", ENV_KEY_NAME
            )
        except Exception:
            logger.warning(
                "%s 不是合法的 Fernet 密钥，将改用 SECRET_KEY 派生密钥", ENV_KEY_NAME
            )

    digest = hashlib.sha256(DERIVE_PREFIX + str(settings.SECRET_KEY).encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet():
    """惰性构造并缓存 Fernet 实例（密钥变更需重启进程生效）。"""
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_derive_key())
    return _fernet


def encrypt_passphrase(raw: Optional[str]) -> str:
    """加密口令；空值返回空串（表示"未设置口令"）。"""
    if not raw:
        return ""
    return get_fernet().encrypt(str(raw).encode("utf-8")).decode("ascii")


def decrypt_passphrase(token: Optional[str]) -> str:
    """解密口令；失败（密钥变更/数据损坏）时返回空串并记录告警，绝不抛异常。"""
    if not token:
        return ""
    try:
        return get_fernet().decrypt(str(token).encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - 解密失败一律降级为空口令
        logger.warning("客户端证书口令解密失败（密钥可能已变更）：%s", exc)
        return ""
