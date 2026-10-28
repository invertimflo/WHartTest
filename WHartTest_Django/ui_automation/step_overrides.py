# -*- coding: utf-8 -*-
"""用例步骤「数据覆盖」（UiCaseStepsDetailed.case_data）合并规则。

平台里同一个页面步骤可以被多个用例引用，每个用例需要给「填充内容 / 等待时间 /
断言期望值」等参数填不同的值 —— 这份按步骤详情行 id 覆盖的参数就是 case_data：

    {"<ui_page_steps_detailed.id>": {"text": "用例A的用户名"},
     "124": {"timeout": 20}}

覆盖合并必须有且只有一份实现，否则两条执行通道（录制器浏览器 / 执行器）迟早
出现「同一个用例在 A 通道生效、在 B 通道不生效」的漂移。因此本模块只放纯函数，
由以下两处共同调用：

- 执行器通道：``serializers.UiTestCaseExecuteSerializer`` 在 execute-data 阶段
  就把覆盖合并进 ``ope_value``，执行器拿到的是「已合并的最终参数」。
- 录制器通道：``views._serialize_page_step_for_recorder`` 在序列化时合并。

前端的主参数键表（``WHartTest_Vue/src/features/ui-automation/constants.ts``
的 ``OPE_PRIMARY_PARAM``）与本模块 ``OPE_PRIMARY_PARAM`` 必须保持同源，改动请
同步两处。
"""

from typing import Any, Dict, Iterable, Optional

# 每种操作方法的「主参数键」：标量形覆盖值写进哪个键。
#
# 正常情况下前端提交的是 dict 形覆盖（{"text": "值"}），走按键合并；标量形
# （{"123": "值"}）只可能来自历史数据、脚本或第三方调用，此时才需要推断主参数键。
# 早期实现是「猜 ope_value 里第一个存在的键」，同一份数据在两条通道上可能猜到
# 不同键（字典顺序 + 不同字段存在性），故改为按操作方法显式映射。
OPE_PRIMARY_PARAM: Dict[str, str] = {
    'fill': 'text',
    'type': 'text',
    'wait': 'timeout',
    'screenshot': 'name',
    'select_option': 'value',
    'select': 'value',
    'switch_tab': 'value',
    'press': 'key',
    'goto': 'url',
    'assert_text': 'expected',
    'assert_contain_text': 'expected',
    'assert_value': 'expected',
    'assert_count': 'expected',
    'assert_url': 'expected',
    'assert_title': 'expected',
}

# 标量覆盖且操作方法未登记时，按此顺序回落到 ope_value 里已存在的键
_FALLBACK_KEYS = ('text', 'value', 'timeout', 'url', 'key', 'expected', 'name')


def merge_case_data(
    ope_value: Any,
    override: Any,
    ope_key: str = '',
) -> Any:
    """把一条覆盖值合并进页面步骤详情的 ``ope_value``。

    Args:
        ope_value: 库里存的原始操作参数（通常 dict，历史数据可能是标量/None）。
        override: 该步骤详情行的覆盖值。dict 形按键合并；标量形写入主参数键。
        ope_key: 操作方法，标量形覆盖时用于定位主参数键。

    Returns:
        合并后的 ``ope_value``；``override`` 为 None 时原样返回（不改入参）。

    说明：dict 形合并是幂等的 —— ``{**merged, **override}`` 重复执行结果不变，
    因此即便上游漏传「已合并」标记导致二次合并也不会出错。
    """
    if override is None:
        return ope_value

    if isinstance(override, dict):
        base = ope_value if isinstance(ope_value, dict) else {}
        return {**base, **override}

    # 标量覆盖：定位主参数键
    key = OPE_PRIMARY_PARAM.get((ope_key or '').strip().lower())
    if key is None:
        base_keys = ope_value if isinstance(ope_value, dict) else {}
        for candidate in _FALLBACK_KEYS:
            if candidate in base_keys:
                key = candidate
                break

    base = dict(ope_value) if isinstance(ope_value, dict) else {}
    if key is None:
        # 无从推断：空参数按填充内容处理，非空则保持原参数（覆盖值丢弃会误导，
        # 但不猜测键可以避免写坏无关参数）
        if not base:
            return {'text': override}
        return base
    base[key] = override
    return base


def apply_case_data_override(
    step_details: Iterable[Dict[str, Any]],
    case_data: Optional[Dict[str, Any]],
) -> Iterable[Dict[str, Any]]:
    """把用例覆盖批量合并进已序列化的 ``step_details``（就地修改）。

    ``step_details`` 为 ``UiPageStepsDetailedExecuteSerializer`` 产出的 dict 列表，
    每项含 ``id`` / ``ope_key`` / ``ope_value``。``case_data`` 的键是步骤详情行 id，
    前端存的是字符串键，历史数据可能是整数键，统一按 ``str`` 比较。

    Returns:
        传入的 ``step_details``（便于链式调用）。
    """
    details = list(step_details or [])
    if not case_data or not isinstance(case_data, dict):
        return details

    # 键统一成字符串，避免 {"123": ...} 与 {123: ...} 混用导致漏匹配
    normalized = {str(k): v for k, v in case_data.items()}
    for detail in details:
        if not isinstance(detail, dict):
            continue
        detail_id = detail.get('id')
        if detail_id is None:
            continue
        override = normalized.get(str(detail_id))
        if override is None:
            continue
        detail['ope_value'] = merge_case_data(
            detail.get('ope_value'), override, detail.get('ope_key') or '',
        )
    return details
