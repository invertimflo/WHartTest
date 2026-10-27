# -*- coding: utf-8 -*-
"""UI 自动化 URL 拼接工具。

执行器（Actuator）、录制器浏览器执行、录制起点三处必须使用同一套语义，
否则同一条用例在不同执行通道上会落到不同地址：

- 页面 URL 为 ``http(s)`` 绝对地址 → 原样使用（环境 base_url 不生效）
- 页面 URL 为相对路径（``/admin`` 或 ``admin``）→ ``base_url + /admin``
- 页面 URL 为空 → 回落 ``base_url``
- ``base_url`` 为空 → 原样返回页面 URL
"""

_ABSOLUTE_PREFIXES = ('http://', 'https://')


def is_absolute_url(url: str) -> bool:
    """是否为 http(s) 完整地址。"""
    return str(url or '').strip().lower().startswith(_ABSOLUTE_PREFIXES)


def join_env_url(base_url: str | None, page_url: str | None) -> str:
    """把页面 URL 与环境基础 URL 拼成最终导航地址。"""
    base = str(base_url or '').strip().rstrip('/')
    path = str(page_url or '').strip()
    if not path:
        return base
    if is_absolute_url(path):
        return path
    if not base:
        return path
    return f"{base}/{path.lstrip('/')}"
