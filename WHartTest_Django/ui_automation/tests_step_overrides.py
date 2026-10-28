# -*- coding: utf-8 -*-
"""用例步骤「数据覆盖」与变量渲染的单测。

覆盖三条链路：
1. ``step_overrides`` 纯函数语义；
2. 执行器通道 execute-data 预合并（Django 侧唯一实现）；
3. 录制器通道 ``_serialize_page_step_for_recorder`` 合并 + 变量渲染。
"""

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Project, ProjectMember
from ui_automation.models import (
    UiCaseStepsDetailed,
    UiElement,
    UiModule,
    UiPage,
    UiPageSteps,
    UiPageStepsDetailed,
    UiPublicData,
    UiTestCase,
)
from ui_automation.step_overrides import apply_case_data_override, merge_case_data
from ui_automation.variables import render_variables


class MergeCaseDataTests(TestCase):
    """合并函数语义（两条通道共用，不能漂移）。"""

    def test_dict_override_merges_by_key_and_keeps_others(self):
        merged = merge_case_data({'text': 'old', 'timeout': 20}, {'text': 'new'}, 'fill')
        self.assertEqual(merged, {'text': 'new', 'timeout': 20})

    def test_dict_override_does_not_mutate_input(self):
        origin = {'text': 'old'}
        merge_case_data(origin, {'text': 'new'}, 'fill')
        self.assertEqual(origin, {'text': 'old'})

    def test_scalar_override_writes_primary_param_key(self):
        # press 的主参数是 key；旧实现「猜第一个存在的键」会写到 text 上
        merged = merge_case_data({'text': 'leftover'}, 'Enter', 'press')
        self.assertEqual(merged['key'], 'Enter')
        self.assertEqual(merged['text'], 'leftover')

    def test_scalar_override_falls_back_to_existing_key(self):
        merged = merge_case_data({'expected': 'old'}, 'new', 'assert_unknown_type')
        self.assertEqual(merged['expected'], 'new')

    def test_none_override_keeps_original(self):
        self.assertEqual(merge_case_data({'text': 'a'}, None, 'fill'), {'text': 'a'})

    def test_apply_accepts_int_keys(self):
        details = [{'id': 7, 'ope_key': 'fill', 'ope_value': {'text': 'old'}}]
        apply_case_data_override(details, {7: {'text': 'new'}})
        self.assertEqual(details[0]['ope_value']['text'], 'new')

    def test_apply_ignores_unknown_detail_id(self):
        details = [{'id': 7, 'ope_key': 'fill', 'ope_value': {'text': 'old'}}]
        apply_case_data_override(details, {'999': {'text': 'new'}})
        self.assertEqual(details[0]['ope_value']['text'], 'old')


class RenderVariablesTests(TestCase):
    """与执行器 DataProcessor 同语义的变量渲染。"""

    def test_whole_string_variable_returns_raw_type(self):
        self.assertEqual(render_variables('${{count}}', {'count': 3}), 3)

    def test_embedded_variable_is_string_concatenated(self):
        self.assertEqual(render_variables('user-${{name}}', {'name': 'alice'}), 'user-alice')

    def test_undefined_variable_kept_as_is(self):
        self.assertEqual(render_variables('${{missing}}', {'name': 'alice'}), '${{missing}}')

    def test_dict_and_list_are_rendered_recursively(self):
        rendered = render_variables({'a': ['${{x}}']}, {'x': 'v'})
        self.assertEqual(rendered, {'a': ['v']})

    def test_file_path_is_not_rendered(self):
        rendered = render_variables({'file_path': '/tmp/${{x}}.png'}, {'x': 'v'})
        self.assertEqual(rendered['file_path'], '/tmp/${{x}}.png')


class _UiFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='override-tester', password='secret')
        self.project = Project.objects.create(name='Override Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.module = UiModule.objects.create(project=self.project, name='M', creator=self.user)
        self.page = UiPage.objects.create(
            project=self.project, module=self.module, name='Page', url='/login', creator=self.user,
        )
        self.element = UiElement.objects.create(
            page=self.page, name='用户名输入框', creator=self.user,
            locator_type='css', locator_value='#username', wait_time=3,
        )
        self.page_step = UiPageSteps.objects.create(
            project=self.project, page=self.page, module=self.module, name='登录', creator=self.user,
        )
        self.detail = UiPageStepsDetailed.objects.create(
            page_step=self.page_step, step_type=0, element=self.element,
            step_sort=0, ope_key='fill', ope_value={'text': '默认值'},
        )
        self.wait_detail = UiPageStepsDetailed.objects.create(
            page_step=self.page_step, step_type=0,
            step_sort=1, ope_key='wait', ope_value={'timeout': 1},
        )
        self.case = UiTestCase.objects.create(
            project=self.project, module=self.module, name='用例', creator=self.user,
        )
        self.case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.case, page_step=self.page_step, case_sort=0,
            case_data={
                str(self.detail.id): {'text': '用例覆盖值'},
                str(self.wait_detail.id): {'timeout': 20},
            },
        )


class ExecuteDataOverrideTests(_UiFixture):
    """执行器通道：execute-data 直接返回已合并的参数。"""

    def _client(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client

    def test_case_execute_data_applies_override(self):
        response = self._client().get(f'/api/ui-automation/testcases/{self.case.id}/execute-data/')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        case_steps = response.data['case_step_details']
        self.assertEqual(len(case_steps), 1)
        self.assertTrue(case_steps[0]['case_data_applied'])
        details = case_steps[0]['page_step']['step_details']
        by_id = {d['id']: d for d in details}
        self.assertEqual(by_id[self.detail.id]['ope_value']['text'], '用例覆盖值')
        self.assertEqual(by_id[self.wait_detail.id]['ope_value']['timeout'], 20)

    def test_override_is_not_persisted(self):
        """预合并不落库：编辑页读到的仍是页面步骤原值。"""
        self._client().get(f'/api/ui-automation/testcases/{self.case.id}/execute-data/')
        self.detail.refresh_from_db()
        self.assertEqual(self.detail.ope_value, {'text': '默认值'})

    def test_page_step_execute_data_unaffected(self):
        response = self._client().get(
            f'/api/ui-automation/page-steps/{self.page_step.id}/execute-data/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_id = {d['id']: d for d in response.data['step_details']}
        self.assertEqual(by_id[self.detail.id]['ope_value']['text'], '默认值')


class RecorderSerializeOverrideTests(_UiFixture):
    """录制器通道：序列化时合并覆盖 + 渲染变量 + 透传元素级等待。"""

    def test_serialize_applies_case_data(self):
        from ui_automation.views import _serialize_page_step_for_recorder
        steps = _serialize_page_step_for_recorder(self.page_step, self.case_step.case_data)
        self.assertEqual(steps[0]['ope_value']['text'], '用例覆盖值')
        self.assertEqual(steps[1]['ope_value']['timeout'], 20)

    def test_serialize_without_case_data_keeps_raw(self):
        from ui_automation.views import _serialize_page_step_for_recorder
        steps = _serialize_page_step_for_recorder(self.page_step)
        self.assertEqual(steps[0]['ope_value']['text'], '默认值')

    def test_serialize_passes_element_wait_time(self):
        from ui_automation.views import _serialize_page_step_for_recorder
        steps = _serialize_page_step_for_recorder(self.page_step)
        self.assertEqual(steps[0]['wait_time'], 3)
        # 等待步骤不绑定元素 → 0（与执行器 element.wait_time 缺省一致）
        self.assertEqual(steps[1]['wait_time'], 0)

    def test_serialize_renders_project_variables(self):
        from ui_automation.views import _serialize_page_step_for_recorder
        from ui_automation.variables import load_project_variables
        UiPublicData.objects.create(
            project=self.project, key='user', value='alice', type=0, creator=self.user,
        )
        UiPageStepsDetailed.objects.filter(pk=self.detail.pk).update(
            ope_value={'text': '${{user}}'},
        )
        variables = load_project_variables(self.project.id)
        steps = _serialize_page_step_for_recorder(self.page_step, None, variables)
        self.assertEqual(steps[0]['ope_value']['text'], 'alice')


class BatchUpdateKeepCaseDataTests(_UiFixture):
    """拖拽排序不带 id 时，后端兜底按顺序原地配对，保住 case_data。"""

    def _client(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client

    def test_reorder_without_id_keeps_pk_and_case_data(self):
        other_page_step = UiPageSteps.objects.create(
            project=self.project, page=self.page, module=self.module, name='其它', creator=self.user,
        )
        other_case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.case, page_step=other_page_step, case_sort=1,
        )
        url = '/api/ui-automation/case-steps/batch_update/'
        response = self._client().post(url, {
            'test_case': self.case.id,
            'steps': [
                {'page_step': other_page_step.id},
                {'page_step': self.page_step.id},
            ],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # 主键保持不变 → case_data 保留
        self.case_step.refresh_from_db()
        other_case_step.refresh_from_db()
        self.assertEqual(self.case_step.case_sort, 1)
        self.assertEqual(other_case_step.case_sort, 0)
        self.assertEqual(self.case_step.case_data[str(self.detail.id)], {'text': '用例覆盖值'})

    def test_removed_step_still_deleted(self):
        other_page_step = UiPageSteps.objects.create(
            project=self.project, page=self.page, module=self.module, name='其它2', creator=self.user,
        )
        other_case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.case, page_step=other_page_step, case_sort=1,
        )
        url = '/api/ui-automation/case-steps/batch_update/'
        response = self._client().post(url, {
            'test_case': self.case.id,
            'steps': [{'page_step': self.page_step.id}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(UiCaseStepsDetailed.objects.filter(id=other_case_step.id).exists())
        self.assertTrue(UiCaseStepsDetailed.objects.filter(id=self.case_step.id).exists())
