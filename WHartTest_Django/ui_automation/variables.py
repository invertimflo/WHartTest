# -*- coding: utf-8 -*-
"""``${{变量名}}`` 变量替换（录制器浏览器通道使用）。

平台有两套变量体系：

- 公共数据（``UiPublicData``）：项目级共享键值，本轮冲突最少、最常用；
- 用例级前置变量/参数化：只服务于执行器通道，录制器通道暂不涉及。

执行器通道（``WHartTest_Actuator/data_processor.py``）早已实现同一套
``${{变量名}}`` 语义。录制器通道此前**完全不做替换** —— 同一个步骤在两端
执行，``${{user}}`` 在录执器里会被原样填进输入框。本模块把执行器的语义
对齐到 Django 侧，让录制器通道在序列化阶段就把变量渲染好。

语义**刻意与 ``DataProcessor`` 保持一致**（正则、类型转换、整串变量返回原始
类型、未定义变量保持原样并告警），改动请同步
``WHartTest_Actuator/data_processor.py``，避免两端漂移。
"""

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 与 DataProcessor.VARIABLE_PATTERN 完全一致
VARIABLE_PATTERN = re.compile(r'\$\{\{([^}]+)\}\}')

# 这些键的值是平台解析后的**绝对路径**（如上传附件的 file_path），
# 路径里出现 ``$`` 时不能当变量替换，否则会把真实路径改坏。
_SKIP_VARIABLE_KEYS = frozenset({'file_path'})


def load_project_variables(project_id: Optional[int]) -> dict:
    """读取项目公共数据为变量字典（仅启用项）。

    类型转换与执行器 ``DataProcessor.load_public_data`` 一致：
    0=字符串 / 1=整数 / 2=列表 / 3=字典，转换失败保留原始字符串。
    """
    if not project_id:
        return {}

    from .models import UiPublicData

    rows = (
        UiPublicData.objects
        .filter(project_id=project_id, is_enabled=True)
        .values_list('key', 'value', 'type')
    )

    variables: dict[str, Any] = {}
    for key, raw_value, data_type in rows:
        if not key:
            continue
        value = raw_value
        try:
            if data_type == 1:
                value = int(raw_value)
            elif data_type in (2, 3):
                value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning('公共数据 %s 类型转换失败，使用原始字符串值', key)
        variables[key] = value
    return variables


def _render_string(text: str, variables: dict, max_depth: int) -> Any:
    """替换字符串中的变量（语义对齐 DataProcessor._replace_string）。"""
    matches = list(VARIABLE_PATTERN.finditer(text))
    if not matches:
        return text

    # 整个字符串就是一个变量：返回原始类型（列表/字典可直接用于 select_option 等）
    if len(matches) == 1 and matches[0].group(0) == text.strip():
        var_name = matches[0].group(1).strip()
        if var_name in variables:
            value = variables[var_name]
            if isinstance(value, str) and VARIABLE_PATTERN.search(value):
                return _render_string(value, variables, max_depth - 1)
            return value
        logger.warning('变量 %s 未定义，保持原样', var_name)
        return text

    # 多个变量或变量嵌在字符串中：全部转字符串拼接
    result = text
    for match in reversed(matches):
        var_name = match.group(1).strip()
        if var_name in variables:
            var_value = variables[var_name]
            if isinstance(var_value, (dict, list)):
                replacement = json.dumps(var_value, ensure_ascii=False)
            else:
                replacement = str(var_value)
            result = result[:match.start()] + replacement + result[match.end():]
        else:
            logger.warning('变量 %s 未定义，保持原样', var_name)

    if max_depth > 1 and VARIABLE_PATTERN.search(result):
        return _render_string(result, variables, max_depth - 1)
    return result


def render_variables(value: Any, variables: Optional[dict], max_depth: int = 10) -> Any:
    """递归替换字符串/字典/列表中的 ``${{变量名}}``。

    ``variables`` 为空时原样返回（避免无公共数据的项目产生额外开销）。
    """
    if not variables or max_depth <= 0 or value is None:
        return value

    if isinstance(value, str):
        return _render_string(value, variables, max_depth)
    if isinstance(value, dict):
        return {
            key: (
                item if key in _SKIP_VARIABLE_KEYS
                else render_variables(item, variables, max_depth - 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [render_variables(item, variables, max_depth - 1) for item in value]
    return value


def render_selector_variables(selector: Optional[dict], variables: Optional[dict]) -> Optional[dict]:
    """只替换定位相关字段（定位表达式与 iframe 链可能含变量）。"""
    if not selector or not variables:
        return selector
    rendered = dict(selector)
    for key in ('locator_value', 'locator_value_2', 'locator_value_3', 'iframe_locator'):
        if isinstance(rendered.get(key), str):
            rendered[key] = render_variables(rendered[key], variables)
    return rendered
