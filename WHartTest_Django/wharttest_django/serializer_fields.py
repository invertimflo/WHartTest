"""可空关联字段的输入归一化工具。

前端把「不关联」表达为若干哨兵值（''、'null'、'undefined'），而 DRF 的
PrimaryKeyRelatedField 只接受整数或 JSON null，收到字符串会直接抛 invalid 错误
（前端表现为「类型错误。期望为主键，获得的类型为 str」或「请求参数有误或处理失败」）。
本模块对哨兵字符串做宽容处理，同时完整保留 DRF 既有校验语义。
"""

from rest_framework import serializers
from rest_framework.fields import empty

# 前端约定的「不关联」哨兵（大小写不敏感，忽略前后空白）
NULL_SENTINELS = frozenset({'', 'null', 'none', 'undefined'})


def is_null_sentinel(value) -> bool:
    """仅对字符串判定；真正的 None 交给带 allow_null 的字段自身处理。"""
    if not isinstance(value, str):
        return False
    return value.strip().lower() in NULL_SENTINELS


class NullablePrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """允许用 '' / 'null' / 'undefined' 等哨兵字符串表示「置空」的外键字段。

    在 `get_value` 阶段把哨兵归一为 None，交给 DRF 默认的
    `validate_empty_values`（allow_null=True 时返回 None）处理。

    为什么是 `get_value` 而不是 `to_internal_value`：
    - `get_value` 只在字段**出现在输入中**时被调用。字段缺失时它不会被调用，
      因此 PATCH 下「字段缺失 = 不修改」的语义天然不受影响。
    - 若改在 `to_internal_value` 里返回 None，会让 DRF 把「显式置空」误判为
      「字段缺失」，从而静默跳过更新，关联对象不会被清空。

    同时保留父类的 queryset / 存在性（does_not_exist）/ 类型（incorrect_type）
    等全部校验，未越权放宽任何约束。
    """

    def get_value(self, dictionary):
        value = super().get_value(dictionary)
        if value is not empty and is_null_sentinel(value):
            # 归一为 None：allow_null=True → validate_empty_values 返回 (True, None)
            # → validated_data 中出现该键且值为 None → save() 写入 NULL。
            # allow_null=False 时仍会按原逻辑报 null 错误。
            return None
        return value
