import json
import logging
from typing import Any, Dict, Optional

from .models import ApiEnvironment, ApiEnvironmentVariable


logger = logging.getLogger(__name__)

PROJECT_VARIABLE_TYPE = 'project'


def infer_environment_variable_type(value: Any) -> str:
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int) and not isinstance(value, bool):
        return 'integer'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'dict'
    if value is None:
        return 'json'
    return 'string'


def serialize_environment_variable_value(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, dict)) or value is None:
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def persist_project_extract_variables(
    *,
    project_id: int,
    environment_id: Optional[int],
    extracted_variables: Optional[Dict[str, Any]],
    extract_meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    result = {
        'matched_count': 0,
        'created_count': 0,
        'updated_count': 0,
        'skipped_no_environment': False,
    }

    if not isinstance(extracted_variables, dict) or not isinstance(extract_meta, dict):
        return result

    matched_items = [
        (name, value)
        for name, value in extracted_variables.items()
        if isinstance(extract_meta.get(name), dict)
        and extract_meta[name].get('variable_type') == PROJECT_VARIABLE_TYPE
    ]

    if not matched_items:
        return result

    result['matched_count'] = len(matched_items)

    if not environment_id:
        result['skipped_no_environment'] = True
        return result

    environment = ApiEnvironment.objects.filter(
        id=environment_id,
        project_id=project_id,
    ).first()
    if environment is None:
        return result

    for variable_name, value in matched_items:
        serialized_value = serialize_environment_variable_value(value)
        variable, created = ApiEnvironmentVariable.objects.get_or_create(
            environment=environment,
            name=variable_name,
            defaults={
                'value': serialized_value,
                'type': infer_environment_variable_type(value),
            },
        )

        if created:
            result['created_count'] += 1
            continue

        if variable.value != serialized_value:
            variable.value = serialized_value
            variable.save(update_fields=['value', 'updated_at'])
            result['updated_count'] += 1

    return result


def public_environment_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """面向 API 响应的环境配置副本。

    `client_cert` 是执行引擎内部使用的证书文件路径，对前端无意义，
    不应随接口执行结果回显（避免泄露后端容器内的文件布局）。
    """
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key != 'client_cert'}


def build_environment_payload(env) -> Optional[Dict[str, Any]]:
    """把 ApiEnvironment 实例转成执行引擎消费的环境配置 dict。

    历史上「环境 → 执行配置」的 dict 在 4 处各自内联（api_testcases/views.py 与
    api_testtasks/services.py），新增字段极易漏改。这里收敛为单一入口，
    后续环境相关字段（证书、数据库、全局变量…）只需改这一处。

    包含：
      - id / name / base_url / verify_ssl / variables（含父环境继承的变量）
      - client_cert：requests 可用的证书参数（PEM 路径，或 (证书, 私钥) 二元组）。
        证书未配置、文件缺失或口令错误时为 None —— 由 materialize_for_requests
        统一降级并告警，**不阻断**执行。

    数据库配置（db_config）由调用方按需追加，因为不同执行入口的注入时机不同。
    """
    if env is None:
        return None

    payload: Dict[str, Any] = {
        'id': env.id,
        'name': env.name,
        'base_url': env.base_url,
        'verify_ssl': env.verify_ssl,
        'variables': env.get_all_variables(),
        'client_cert': None,
    }

    try:
        certificate = env.get_client_certificate()
    except Exception as exc:  # noqa: BLE001 - 证书解析失败不应阻断用例执行
        logger.warning('解析环境 %s 的客户端证书失败：%s', env.id, exc)
        certificate = None

    if certificate is not None:
        try:
            from client_certificates.services import materialize_for_requests

            payload['client_cert'] = materialize_for_requests(certificate)
        except Exception as exc:  # noqa: BLE001
            logger.warning('准备环境 %s 的客户端证书材料失败：%s', env.id, exc)
            payload['client_cert'] = None

    return payload
