import logging
# -*- coding: utf-8 -*-
"""UI 自动化序列化器"""

from rest_framework import serializers

logger = logging.getLogger(__name__)
from file_management.services import validate_file_ids, sync_file_references, serialize_file_for_runtime
from file_management.models import FileReference
from client_certificates.models import ClientCertificate
from wharttest_django.serializer_fields import NullablePrimaryKeyRelatedField
from .models import (
    UiModule, UiPage, UiElement, UiPageSteps, UiPageStepsDetailed,
    UiTestCase, UiCaseStepsDetailed, UiExecutionRecord, UiPublicData, UiEnvironmentConfig,
    UiBatchExecutionRecord, UiAuthState,
)


def _validate_ui_file_ids(file_ids, project, user=None):
    if file_ids in (None, ''):
        return []
    validate_file_ids(file_ids, project, user)
    return file_ids


def _ui_request_user(serializer):
    request = serializer.context.get('request') if hasattr(serializer, 'context') else None
    return request.user if request else None


# ==================== 页面 URL / 登录态快照校验辅助 ====================

# 站内相对路径与 http(s) 绝对地址之外一律拒绝（javascript:/data: 会让 page.goto 直接失败或越权执行脚本）
_PAGE_URL_BLOCKED_SCHEMES = ('javascript:', 'data:', 'file:', 'ftp:', 'vbscript:')

_SAME_SITE_VALUES = ('Strict', 'Lax', 'None')


def _as_text(value) -> str:
    """把任意标量安全转成字符串（Cookie / localStorage 的值可能是数字或布尔）。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_expires(value) -> float:
    """Cookie 过期时间统一为 Unix 秒；-1 表示会话型 Cookie。"""
    if value in (None, ''):
        return -1
    try:
        expires = float(value)
    except (TypeError, ValueError):
        raise serializers.ValidationError(
            'Cookie 的 expires 必须是数字（Unix 秒，-1 表示会话型）'
        )
    return -1 if expires <= 0 else expires


def _resolve_upload_ope_value(obj, serializer):
    value = dict(obj.ope_value or {})
    if obj.ope_key != 'upload':
        return value
    file_id = value.get('file_id')
    if not file_id:
        return value
    try:
        project = obj.page_step.project if obj.page_step else None
        files = validate_file_ids([file_id], project, _ui_request_user(serializer))
        if files:
            runtime_file = serialize_file_for_runtime(files[0])
            # Prefer shared-storage absolute path; actuators may fall back to download_url.
            resolved_path = runtime_file.get('path') or ''
            value['value'] = resolved_path or value.get('value')
            value['file_path'] = resolved_path
            value['file_name'] = runtime_file.get('name') or value.get('file_name')
            value['mime_type'] = runtime_file.get('mime_type')
            value['file_id'] = runtime_file.get('file_id') or file_id
            value['project_id'] = runtime_file.get('project_id') or (project.id if project else None)
            value['download_url'] = runtime_file.get('download_url') or ''
            value['url'] = runtime_file.get('url') or ''
            value['sha256'] = runtime_file.get('sha256') or ''
            value['size'] = runtime_file.get('size')
    except Exception as exc:
        logger.warning('resolve upload ope_value failed: %s', exc, exc_info=True)
    return value


def _resolve_captcha_ope_value(obj):
    value = dict(obj.ope_value or {})
    if obj.ope_key != 'captcha_recognize':
        return value
    target_id = value.get('target_element_id') or value.get('target_element')
    if not target_id:
        return value
    try:
        target_el = UiElement.objects.filter(pk=target_id).first()
        if target_el:
            value['target_locator'] = {
                'element_id': target_el.id,
                'element_name': target_el.name,
                'locator_type': target_el.locator_type,
                'locator_value': target_el.locator_value,
                'locator_index': target_el.locator_index,
                'locator_type_2': target_el.locator_type_2,
                'locator_value_2': target_el.locator_value_2,
                'locator_index_2': target_el.locator_index_2,
                'locator_type_3': target_el.locator_type_3,
                'locator_value_3': target_el.locator_value_3,
                'locator_index_3': target_el.locator_index_3,
                'wait_time': target_el.wait_time,
                'is_iframe': target_el.is_iframe,
                'iframe_locator': target_el.iframe_locator,
            }
    except Exception as exc:
        logger.warning('resolve captcha ope_value failed: %s', exc, exc_info=True)
    return value


class UiModuleSerializer(serializers.ModelSerializer):
    """模块序列化器"""
    children = serializers.SerializerMethodField()
    creator_name = serializers.CharField(source='creator.username', read_only=True)

    class Meta:
        model = UiModule
        fields = ['id', 'project', 'name', 'parent', 'level', 'order', 'children', 'creator', 'creator_name', 'created_at', 'updated_at']
        read_only_fields = ['level', 'creator', 'created_at', 'updated_at', 'order']

    def get_children(self, obj):
        children = obj.children.all()
        return UiModuleSerializer(children, many=True).data if children else []


class UiElementSerializer(serializers.ModelSerializer):
    """元素序列化器"""
    creator_name = serializers.CharField(source='creator.username', read_only=True)

    class Meta:
        model = UiElement
        fields = '__all__'
        read_only_fields = ['creator', 'created_at', 'updated_at']


class UiPageSerializer(serializers.ModelSerializer):
    """页面序列化器"""
    module_name = serializers.CharField(source='module.name', read_only=True)
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    element_count = serializers.SerializerMethodField()

    class Meta:
        model = UiPage
        fields = '__all__'
        read_only_fields = ['creator', 'created_at', 'updated_at']

    def get_element_count(self, obj):
        return obj.elements.count()

    def validate_url(self, value):
        """页面 URL：允许为空；支持 http(s) 绝对地址与站内相对路径。

        这里只做协议白名单校验，**不改写用户输入**：
        - 相对路径（``/admin`` 或 ``admin``）原样入库，执行时按所选环境的
          base_url 拼接（见 ``ui_automation/url_utils.py``），更换环境无需改页面；
        - http(s) 绝对地址原样使用，执行时不再拼接环境 base_url；
        - javascript:/data: 等协议会让执行器 page.goto 失败或越权执行脚本，直接拒绝。
        """
        if value is None:
            return value
        url = str(value).strip()
        if not url:
            return ''
        lowered = url.lower()
        if lowered.startswith(_PAGE_URL_BLOCKED_SCHEMES):
            raise serializers.ValidationError(
                '页面 URL 仅支持 http/https 绝对地址或站内相对路径'
            )
        if '://' in url and not lowered.startswith(('http://', 'https://')):
            raise serializers.ValidationError(
                '页面 URL 仅支持 http/https 绝对地址或站内相对路径'
            )
        return url


class UiPageDetailSerializer(UiPageSerializer):
    """页面详情序列化器（含元素列表）"""
    elements = UiElementSerializer(many=True, read_only=True)

    class Meta(UiPageSerializer.Meta):
        fields = '__all__'


class UiPageStepsDetailedSerializer(serializers.ModelSerializer):
    """步骤详情序列化器"""
    element_name = serializers.CharField(source='element.name', read_only=True)
    page_name = serializers.SerializerMethodField()
    module_name = serializers.SerializerMethodField()

    class Meta:
        model = UiPageStepsDetailed
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']

    def get_page_name(self, obj):
        if obj.element and obj.element.page:
            return obj.element.page.name
        return None

    def get_module_name(self, obj):
        if obj.element and obj.element.page and obj.element.page.module:
            return obj.element.page.module.name
        return None

    def validate(self, attrs):
        page_step = attrs.get('page_step') or getattr(self.instance, 'page_step', None)
        ope_key = attrs.get('ope_key') if 'ope_key' in attrs else getattr(self.instance, 'ope_key', None)
        ope_value = attrs.get('ope_value') if 'ope_value' in attrs else getattr(self.instance, 'ope_value', {})
        if ope_key == 'upload':
            file_id = (ope_value or {}).get('file_id')
            if not file_id:
                raise serializers.ValidationError({'ope_value': '上传文件操作必须选择文件。'})
            if page_step and page_step.project:
                validate_file_ids([file_id], page_step.project, _ui_request_user(self))
        elif ope_key == 'captcha_recognize':
            target_id = (ope_value or {}).get('target_element_id') or (ope_value or {}).get('target_element')
            if not target_id:
                raise serializers.ValidationError({'ope_value': '智能识别验证码操作必须选择目标输入框元素。'})
        return attrs


class UiPageStepsDetailedExecuteSerializer(serializers.ModelSerializer):
    """步骤详情序列化器（含元素定位信息，用于执行器）"""
    ope_value = serializers.SerializerMethodField()
    element_name = serializers.CharField(source='element.name', read_only=True)
    locator_type = serializers.CharField(source='element.locator_type', read_only=True)
    locator_value = serializers.CharField(source='element.locator_value', read_only=True)
    locator_index = serializers.IntegerField(source='element.locator_index', read_only=True)
    
    # 备用定位1
    locator_type_2 = serializers.CharField(source='element.locator_type_2', read_only=True)
    locator_value_2 = serializers.CharField(source='element.locator_value_2', read_only=True)
    locator_index_2 = serializers.IntegerField(source='element.locator_index_2', read_only=True)
    
    # 备用定位2
    locator_type_3 = serializers.CharField(source='element.locator_type_3', read_only=True)
    locator_value_3 = serializers.CharField(source='element.locator_value_3', read_only=True)
    locator_index_3 = serializers.IntegerField(source='element.locator_index_3', read_only=True)
    
    wait_time = serializers.IntegerField(source='element.wait_time', read_only=True)
    is_iframe = serializers.BooleanField(source='element.is_iframe', read_only=True)
    iframe_locator = serializers.CharField(source='element.iframe_locator', read_only=True)

    def get_ope_value(self, obj):
        val = _resolve_upload_ope_value(obj, self)
        if obj.ope_key == 'captcha_recognize':
            val = _resolve_captcha_ope_value(obj)
        return val

    class Meta:
        model = UiPageStepsDetailed
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']


class UiPageStepsListSerializer(serializers.ModelSerializer):
    """页面步骤列表序列化器（精简字段，提升性能）"""
    page_name = serializers.CharField(source='page.name', read_only=True)
    module_name = serializers.CharField(source='module.name', read_only=True)
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    step_count = serializers.SerializerMethodField()
    # 绑定登录态：前端步骤详情/执行按列表行数据直接回显（详情抽屉不重新拉详情）
    auth_state_id = serializers.PrimaryKeyRelatedField(
        source='auth_state', read_only=True, allow_null=True,
    )

    class Meta:
        model = UiPageSteps
        fields = [
            'id', 'project', 'page', 'page_name', 'module', 'module_name',
            'name', 'status', 'file_ids', 'step_count', 'creator', 'creator_name',
            'auth_state_id', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'creator', 'created_at', 'updated_at']

    def get_step_count(self, obj):
        return obj.step_details.count()


class UiPageStepsSerializer(serializers.ModelSerializer):
    """页面步骤序列化器"""
    page_name = serializers.CharField(source='page.name', read_only=True)
    module_name = serializers.CharField(source='module.name', read_only=True)
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    step_count = serializers.SerializerMethodField()
    # 输入键兼容：前端以 auth_state_id 绑定/清空登录态（DRF 对 FK 默认只认 auth_state 键，'xxx_id' 会被静默忽略）
    auth_state_id = serializers.PrimaryKeyRelatedField(
        source='auth_state', queryset=UiAuthState.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model = UiPageSteps
        fields = '__all__'
        read_only_fields = ['status', 'result_data', 'creator', 'created_at', 'updated_at']

    def get_step_count(self, obj):
        return obj.step_details.count()


class UiPageStepsDetailSerializer(UiPageStepsSerializer):
    """页面步骤详情序列化器（含步骤详情列表）"""
    step_details = UiPageStepsDetailedSerializer(many=True, read_only=True)

    class Meta(UiPageStepsSerializer.Meta):
        fields = '__all__'


class UiPageStepsExecuteSerializer(UiPageStepsSerializer):
    """页面步骤执行序列化器（含步骤详情列表和元素定位信息）

    auth_state_id：步骤绑定的登录态，执行器按组优先注入/切换。
    """
    auth_state_id = serializers.PrimaryKeyRelatedField(
        source='auth_state', read_only=True, required=False, allow_null=True,
    )
    step_details = UiPageStepsDetailedExecuteSerializer(many=True, read_only=True)
    page_url = serializers.CharField(source='page.url', read_only=True)
    managed_files = serializers.SerializerMethodField()

    def get_managed_files(self, obj):
        try:
            files = validate_file_ids(obj.file_ids or [], obj.project, _ui_request_user(self))
            return [serialize_file_for_runtime(asset) for asset in files]
        except Exception:
            return []

    class Meta(UiPageStepsSerializer.Meta):
        fields = '__all__'


class UiCaseStepsDetailedSerializer(serializers.ModelSerializer):
    """用例步骤序列化器"""
    page_step_name = serializers.CharField(source='page_step.name', read_only=True)
    page_name = serializers.SerializerMethodField()
    module_name = serializers.SerializerMethodField()

    class Meta:
        model = UiCaseStepsDetailed
        fields = '__all__'
        read_only_fields = ['status', 'error_message', 'result_data', 'created_at', 'updated_at']

    def get_page_name(self, obj):
        if obj.page_step and obj.page_step.page:
            return obj.page_step.page.name
        return None

    def get_module_name(self, obj):
        if obj.page_step and obj.page_step.module:
            return obj.page_step.module.name
        return None


class UiCaseStepsWithDetailSerializer(serializers.ModelSerializer):
    """用例步骤序列化器（含完整page_step详情）- 用于执行时获取步骤详情"""
    page_step = UiPageStepsExecuteSerializer(read_only=True)

    class Meta:
        model = UiCaseStepsDetailed
        fields = '__all__'
        read_only_fields = ['status', 'error_message', 'result_data', 'created_at', 'updated_at']


class UiTestCaseListSerializer(serializers.ModelSerializer):
    """测试用例列表序列化器（精简字段，提升性能）"""
    module_name = serializers.CharField(source='module.name', read_only=True)
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = UiTestCase
        fields = [
            'id', 'project', 'module', 'module_name', 'name', 'level', 'status',
            'file_ids', 'step_count', 'creator', 'creator_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'creator', 'created_at', 'updated_at']

    def get_step_count(self, obj):
        return obj.case_steps.count()


class UiTestCaseSerializer(serializers.ModelSerializer):
    """测试用例序列化器"""
    module_name = serializers.CharField(source='module.name', read_only=True)
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = UiTestCase
        fields = '__all__'
        read_only_fields = ['status', 'result_data', 'error_message', 'creator', 'created_at', 'updated_at']

    def get_step_count(self, obj):
        return obj.case_steps.count()


class UiTestCaseDetailSerializer(UiTestCaseSerializer):
    """测试用例详情序列化器（含步骤列表）"""
    case_steps = UiCaseStepsDetailedSerializer(many=True, read_only=True)

    class Meta(UiTestCaseSerializer.Meta):
        fields = '__all__'


class UiTestCaseExecuteSerializer(UiTestCaseSerializer):
    """测试用例执行序列化器（含完整步骤详情，用于执行器获取数据）"""
    case_step_details = UiCaseStepsWithDetailSerializer(source='case_steps', many=True, read_only=True)
    managed_files = serializers.SerializerMethodField()

    def get_managed_files(self, obj):
        try:
            files = validate_file_ids(obj.file_ids or [], obj.project, _ui_request_user(self))
            return [serialize_file_for_runtime(asset) for asset in files]
        except Exception:
            return []

    class Meta(UiTestCaseSerializer.Meta):
        fields = '__all__'


class UiExecutionRecordListSerializer(serializers.ModelSerializer):
    """执行记录列表序列化器（精简字段，提升性能）"""
    test_case_name = serializers.CharField(source='test_case.name', read_only=True)
    executor_name = serializers.CharField(source='executor.username', read_only=True)

    class Meta:
        model = UiExecutionRecord
        fields = [
            'id', 'batch', 'test_case', 'test_case_name', 'executor', 'executor_name',
            'status', 'trigger_type', 'start_time', 'end_time', 'duration', 'created_at'
        ]
        read_only_fields = ['created_at']


class UiExecutionRecordBatchDetailSerializer(serializers.ModelSerializer):
    """批量执行详情中的执行记录序列化器（包含步骤结果和错误信息，不含过大字段）"""
    test_case_name = serializers.CharField(source='test_case.name', read_only=True)
    executor_name = serializers.CharField(source='executor.username', read_only=True)

    class Meta:
        model = UiExecutionRecord
        fields = [
            'id', 'batch', 'test_case', 'test_case_name', 'executor', 'executor_name',
            'status', 'trigger_type', 'start_time', 'end_time', 'duration',
            'step_results', 'screenshots', 'error_message', 'trace_path', 'created_at'
        ]
        read_only_fields = ['created_at']


class UiExecutionRecordSerializer(serializers.ModelSerializer):
    """执行记录序列化器"""
    test_case_name = serializers.CharField(source='test_case.name', read_only=True)
    executor_name = serializers.CharField(source='executor.username', read_only=True)

    class Meta:
        model = UiExecutionRecord
        fields = '__all__'
        read_only_fields = ['created_at']


class UiPublicDataSerializer(serializers.ModelSerializer):
    """公共数据序列化器"""
    creator_name = serializers.CharField(source='creator.username', read_only=True)

    class Meta:
        model = UiPublicData
        fields = '__all__'
        read_only_fields = ['creator', 'created_at', 'updated_at']


class UiEnvironmentConfigSerializer(serializers.ModelSerializer):
    """环境配置序列化器"""
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    auth_state_active = serializers.SerializerMethodField()
    client_cert_info = serializers.SerializerMethodField()
    client_cert_warnings = serializers.SerializerMethodField()

    # fields='__all__' 下只覆写此字段：本模型唯一的可空外键。
    # 允许前端用 '' / 'null' / 'undefined' 等哨兵字符串表达「不关联」；
    # required=False 保证 PATCH 下「字段缺失 = 不修改」的语义不被破坏。
    client_certificate = NullablePrimaryKeyRelatedField(
        queryset=ClientCertificate.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = UiEnvironmentConfig
        fields = '__all__'
        read_only_fields = ['creator', 'created_at', 'updated_at']

    def get_auth_state_active(self, obj) -> bool:
        """该环境当前是否有启用的登录态（前端列表徽标展示）。"""
        return UiAuthState.objects.filter(env_config_id=obj.id, is_active=True).exists()

    def get_client_cert_info(self, obj) -> dict:
        """客户端证书摘要（**绝不含口令明文**，只暴露 has_passphrase）。"""
        certificate = obj.client_certificate if obj.client_certificate_id else None
        if certificate is None:
            return None
        return {
            'id': certificate.id,
            'name': certificate.name,
            'cert_type': certificate.cert_type,
            'has_passphrase': certificate.has_passphrase,
            'is_active': certificate.is_active,
        }

    def get_client_cert_warnings(self, obj) -> list:
        """客户端证书预检告警（只读，**绝不含口令明文**）。

        回答「这张证书在这个环境里有没有可能生效」——base_url 非 https、origin
        推导不出、证书被禁用/文件缺失等。让用户在前端保存环境配置时就能看到问题，
        而不是等到录制/执行时只看到白屏。
        """
        from client_certificates.services import env_config_certificate_warnings

        try:
            return env_config_certificate_warnings(obj)
        except Exception:  # noqa: BLE001 - 预检失败不应影响配置读写
            return []

    def validate(self, attrs):
        """证书必须与环境中同项目。

        归一化后语义：attrs 中存在键且值为 None = 显式置空，不做同项目校验也不回退
        旧值；键缺失 = 未修改该字段，才回退到实例旧值。
        """
        instance = self.instance
        if 'client_certificate' in attrs:
            certificate = attrs['client_certificate']  # None 表示显式置空
        else:
            certificate = getattr(instance, 'client_certificate', None)  # 缺失 = 不变

        project_id = getattr(instance, 'project_id', None) or getattr(
            attrs.get('project'), 'id', None
        )
        if certificate is not None and project_id and certificate.project_id != project_id:
            raise serializers.ValidationError({
                'client_certificate': ['Client certificate must belong to the same project.'],
            })
        return attrs


class UiAuthStateSerializer(serializers.ModelSerializer):
    """环境登录态序列化器（state_json 为执行器使用的 storageState 快照）"""
    creator_name = serializers.CharField(source='creator.username', read_only=True)
    env_name = serializers.CharField(source='env_config.name', read_only=True)
    project_id = serializers.IntegerField(source='env_config.project_id', read_only=True)

    class Meta:
        model = UiAuthState
        fields = '__all__'
        read_only_fields = ['creator', 'created_at', 'updated_at']

    def validate_name(self, value):
        name = (value or '').strip()
        if not name:
            raise serializers.ValidationError('登录态名称不能为空')
        return name

    def validate_state_json(self, value):
        """校验并规范化 Playwright storageState 快照（支持手动编辑后回写）。

        结构：``{"cookies": [...], "origins": [{"origin": "...", "localStorage": [...]}]}``
        执行器直接把这个 JSON 注入浏览器上下文，结构写坏会导致执行期静默失效，
        因此在这里做严格校验 + 归一化（补 path、expires 转数字、剔除未知键）。
        """
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError(
                '登录态快照不能为空，至少需要一项 Cookie 或 localStorage'
            )

        unknown = sorted(set(value.keys()) - {'cookies', 'origins'})
        if unknown:
            raise serializers.ValidationError(
                f'登录态快照包含不支持的字段：{"、".join(unknown)}（仅支持 cookies / origins）'
            )

        raw_cookies = value.get('cookies')
        if raw_cookies is not None and not isinstance(raw_cookies, list):
            raise serializers.ValidationError('cookies 必须是数组')

        cookies = []
        for index, cookie in enumerate(raw_cookies or [], start=1):
            if not isinstance(cookie, dict):
                raise serializers.ValidationError(f'第 {index} 个 Cookie 必须是对象')
            name = _as_text(cookie.get('name')).strip()
            if not name:
                raise serializers.ValidationError(f'第 {index} 个 Cookie 缺少 name')
            if 'value' not in cookie:
                raise serializers.ValidationError(f'Cookie「{name}」缺少 value')

            normalized = {
                'name': name,
                'value': _as_text(cookie.get('value')),
                'domain': _as_text(cookie.get('domain')).strip(),
                'path': _as_text(cookie.get('path')).strip() or '/',
                'expires': _normalize_expires(cookie.get('expires')),
                'httpOnly': bool(cookie.get('httpOnly', False)),
                'secure': bool(cookie.get('secure', False)),
            }
            same_site = cookie.get('sameSite')
            if same_site:
                same_site = str(same_site)
                if same_site not in _SAME_SITE_VALUES:
                    raise serializers.ValidationError(
                        f'Cookie「{name}」的 sameSite 仅支持 Strict / Lax / None'
                    )
                normalized['sameSite'] = same_site
            cookies.append(normalized)

        raw_origins = value.get('origins')
        if raw_origins is not None and not isinstance(raw_origins, list):
            raise serializers.ValidationError('origins 必须是数组')

        origins = []
        for index, origin in enumerate(raw_origins or [], start=1):
            if not isinstance(origin, dict):
                raise serializers.ValidationError(f'第 {index} 个 origin 必须是对象')
            origin_url = _as_text(origin.get('origin')).strip().rstrip('/')
            if not origin_url.startswith(('http://', 'https://')):
                raise serializers.ValidationError(
                    f'第 {index} 个 origin 必须以 http:// 或 https:// 开头'
                )
            raw_items = origin.get('localStorage')
            if raw_items is not None and not isinstance(raw_items, list):
                raise serializers.ValidationError(f'origin「{origin_url}」的 localStorage 必须是数组')

            items = []
            for item in raw_items or []:
                if not isinstance(item, dict):
                    raise serializers.ValidationError(
                        f'origin「{origin_url}」的 localStorage 项必须是对象'
                    )
                key = _as_text(item.get('name')).strip()
                if not key:
                    raise serializers.ValidationError(
                        f'origin「{origin_url}」存在缺少 name 的 localStorage 项'
                    )
                items.append({'name': key, 'value': _as_text(item.get('value'))})

            normalized_origin = {'origin': origin_url, 'localStorage': items}
            # indexedDB 快照不在编辑 UI 暴露，但原样保留，避免手动编辑时丢失
            if 'indexedDB' in origin:
                normalized_origin['indexedDB'] = origin.get('indexedDB')
            origins.append(normalized_origin)

        if not cookies and not any(o['localStorage'] for o in origins):
            raise serializers.ValidationError(
                '登录态快照不能为空，至少需要一项 Cookie 或 localStorage'
            )

        normalized_state = {}
        if cookies:
            normalized_state['cookies'] = cookies
        if origins:
            normalized_state['origins'] = origins
        return normalized_state


class UiBatchExecutionRecordSerializer(serializers.ModelSerializer):
    """批量执行记录序列化器"""
    executor_name = serializers.CharField(source='executor.username', read_only=True)
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = UiBatchExecutionRecord
        fields = '__all__'
        read_only_fields = ['created_at']

    def get_success_rate(self, obj):
        if obj.total_cases == 0:
            return 0
        return round(obj.passed_cases / obj.total_cases * 100, 1)


class UiBatchExecutionRecordDetailSerializer(UiBatchExecutionRecordSerializer):
    """批量执行记录详情序列化器（含关联执行记录详情：包含步骤结果和错误信息）"""
    execution_records = UiExecutionRecordBatchDetailSerializer(many=True, read_only=True)

    class Meta(UiBatchExecutionRecordSerializer.Meta):
        fields = '__all__'


# 附件 file_ids 校验与引用关系维护

def _ui_page_steps_validate(self, attrs):
    project = attrs.get('project') or (self.instance.project if self.instance else None)
    if 'file_ids' in attrs and project:
        attrs['file_ids'] = _validate_ui_file_ids(attrs.get('file_ids'), project, _ui_request_user(self))
    return attrs


def _ui_page_steps_create(self, validated_data):
    instance = super(UiPageStepsSerializer, self).create(validated_data)
    sync_file_references(instance.file_ids or [], instance.project, FileReference.REF_UI_PAGE_STEPS, instance.id, _ui_request_user(self))
    return instance


def _ui_page_steps_update(self, instance, validated_data):
    instance = super(UiPageStepsSerializer, self).update(instance, validated_data)
    if 'file_ids' in validated_data:
        sync_file_references(instance.file_ids or [], instance.project, FileReference.REF_UI_PAGE_STEPS, instance.id, _ui_request_user(self))
    return instance


def _ui_testcase_validate(self, attrs):
    project = attrs.get('project') or (self.instance.project if self.instance else None)
    if 'file_ids' in attrs and project:
        attrs['file_ids'] = _validate_ui_file_ids(attrs.get('file_ids'), project, _ui_request_user(self))
    return attrs


def _ui_testcase_create(self, validated_data):
    instance = super(UiTestCaseSerializer, self).create(validated_data)
    sync_file_references(instance.file_ids or [], instance.project, FileReference.REF_UI_TESTCASE, instance.id, _ui_request_user(self))
    return instance


def _ui_testcase_update(self, instance, validated_data):
    instance = super(UiTestCaseSerializer, self).update(instance, validated_data)
    if 'file_ids' in validated_data:
        sync_file_references(instance.file_ids or [], instance.project, FileReference.REF_UI_TESTCASE, instance.id, _ui_request_user(self))
    return instance

UiPageStepsSerializer.validate = _ui_page_steps_validate
UiPageStepsSerializer.create = _ui_page_steps_create
UiPageStepsSerializer.update = _ui_page_steps_update
UiTestCaseSerializer.validate = _ui_testcase_validate
UiTestCaseSerializer.create = _ui_testcase_create
UiTestCaseSerializer.update = _ui_testcase_update
