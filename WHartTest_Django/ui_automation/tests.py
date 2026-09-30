import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from client_certificates.models import ClientCertificate
from client_certificates.services import (
    build_env_client_cert_payload,
    build_recorder_client_certificates,
    build_recorder_https_payload,
    env_config_certificate_warnings,
    normalize_origin,
    parse_origins,
    resolve_recorder_ignore_https_errors,
)
from projects.models import Project, ProjectMember
from ui_automation.models import (
    UiCaseStepsDetailed,
    UiElement,
    UiModule,
    UiPage,
    UiPageSteps,
    UiPageStepsDetailed,
    UiTestCase,
)
from ui_automation.serializers import UiPageStepsExecuteSerializer
from file_management.models import FileAsset, FileManagementSetting, FileReference


class UiPageStepsExecuteDataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='tester', password='secret')
        self.project = Project.objects.create(name='Demo Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.module = UiModule.objects.create(
            project=self.project,
            name='Module A',
            creator=self.user,
        )
        self.page = UiPage.objects.create(
            project=self.project,
            module=self.module,
            name='Login Page',
            url='/login',
            creator=self.user,
        )
        self.element = UiElement.objects.create(
            page=self.page,
            name='Submit Button',
            locator_type='css',
            locator_value='button[type="submit"]',
            locator_index=2,
            locator_type_2='xpath',
            locator_value_2='//button[@type="submit"]',
            locator_index_2=1,
            locator_type_3='text',
            locator_value_3='Submit',
            is_iframe=True,
            iframe_locator='iframe.login-frame',
            creator=self.user,
        )
        self.page_step = UiPageSteps.objects.create(
            project=self.project,
            page=self.page,
            module=self.module,
            name='Submit Login',
            creator=self.user,
        )
        UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            element=self.element,
            ope_key='click',
            step_sort=0,
        )

    def test_execute_data_includes_iframe_fields(self):
        response = UiPageStepsExecuteSerializer(self.page_step).data
        self.assertEqual(len(response['step_details']), 1)
        detail = response['step_details'][0]
        self.assertEqual(detail['locator_index'], 2)
        self.assertEqual(detail['locator_type_2'], 'xpath')
        self.assertEqual(detail['locator_value_2'], '//button[@type="submit"]')
        self.assertEqual(detail['locator_index_2'], 1)
        self.assertEqual(detail['locator_type_3'], 'text')
        self.assertEqual(detail['locator_value_3'], 'Submit')
        self.assertTrue(detail['is_iframe'])
        self.assertEqual(detail['iframe_locator'], 'iframe.login-frame')

    def test_delete_referenced_element_is_rejected(self):
        client = APIClient()
        client.force_authenticate(user=self.user)

        response = client.delete(f'/api/ui-automation/elements/{self.element.id}/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('元素已被 1 个页面步骤引用', response.data['error'])
        self.assertTrue(UiElement.objects.filter(id=self.element.id).exists())
        self.assertEqual(
            UiPageStepsDetailed.objects.get(page_step=self.page_step, step_sort=0).element_id,
            self.element.id,
        )

    def test_execute_data_resolves_upload_file_id_to_file_path(self):
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='avatar.png',
            mime_type='image/png',
            size=5,
            sha256='abc',
        )
        asset.file.save('avatar.png', ContentFile(b'hello'), save=True)
        UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            element=self.element,
            ope_key='upload',
            ope_value={'file_id': asset.id, 'file_name': 'avatar.png', 'value': f'file_id:{asset.id}'},
            step_sort=1,
        )
        response = UiPageStepsExecuteSerializer(self.page_step).data
        upload_detail = next(item for item in response['step_details'] if item.get('ope_key') == 'upload')
        self.assertEqual(upload_detail['ope_value']['file_id'], asset.id)
        self.assertEqual(upload_detail['ope_value']['file_name'], 'avatar.png')
        self.assertIn('file_management/projects/', upload_detail['ope_value']['file_path'])
        self.assertEqual(upload_detail['ope_value']['value'], upload_detail['ope_value']['file_path'])
        self.assertEqual(
            upload_detail['ope_value']['download_url'],
            f'/api/projects/{self.project.id}/files/{asset.id}/download/',
        )
        self.assertEqual(upload_detail['ope_value']['project_id'], self.project.id)

    def test_delete_upload_step_keeps_file_when_auto_delete_disabled(self):
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='delete-me.txt',
            mime_type='text/plain',
            size=5,
            sha256='def',
        )
        asset.file.save('delete-me.txt', ContentFile(b'hello'), save=True)
        storage = asset.file.storage
        storage_name = asset.file.name
        upload_step = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            element=self.element,
            ope_key='upload',
            ope_value={'file_id': asset.id, 'file_name': 'delete-me.txt', 'value': f'file_id:{asset.id}'},
            step_sort=2,
        )

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.delete(f'/api/ui-automation/page-steps-detailed/{upload_step.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertTrue(FileAsset.objects.filter(id=asset.id).exists())
        self.assertTrue(storage.exists(storage_name))

    def test_delete_upload_step_keeps_file_when_no_reference_exists_even_if_enabled(self):
        from file_management.models import FileManagementSetting
        FileManagementSetting.objects.update_or_create(
            project=self.project,
            defaults={'auto_delete_on_unbind': True},
        )
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='delete-me-enabled.txt',
            mime_type='text/plain',
            size=5,
            sha256='ghi',
        )
        asset.file.save('delete-me-enabled.txt', ContentFile(b'hello'), save=True)
        storage = asset.file.storage
        storage_name = asset.file.name
        upload_step = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            element=self.element,
            ope_key='upload',
            ope_value={'file_id': asset.id, 'file_name': 'delete-me-enabled.txt', 'value': f'file_id:{asset.id}'},
            step_sort=3,
        )

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.delete(f'/api/ui-automation/page-steps-detailed/{upload_step.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertTrue(FileAsset.objects.filter(id=asset.id).exists())
        self.assertTrue(storage.exists(storage_name))

    def test_create_upload_step_creates_file_reference_count(self):
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='referenced.txt',
            mime_type='text/plain',
            size=5,
            sha256='ref',
        )
        asset.file.save('referenced.txt', ContentFile(b'hello'), save=True)
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post('/api/ui-automation/page-steps-detailed/', {
            'page_step': self.page_step.id,
            'step_type': 0,
            'element': self.element.id,
            'step_sort': 4,
            'ope_key': 'upload',
            'ope_value': {'file_id': asset.id, 'file_name': 'referenced.txt', 'value': f'file_id:{asset.id}'},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(FileReference.objects.filter(
            file=asset,
            project=self.project,
            ref_type=FileReference.REF_UI_PAGE_STEPS,
            ref_id=f"detail:{response.data['id']}",
        ).exists())
        asset.refresh_from_db()
        self.assertEqual(asset.references.count(), 1)

    def test_api_created_upload_step_deletes_file_when_auto_delete_enabled(self):
        from file_management.models import FileManagementSetting
        FileManagementSetting.objects.update_or_create(
            project=self.project,
            defaults={'auto_delete_on_unbind': True},
        )
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='delete-api-created.txt',
            mime_type='text/plain',
            size=5,
            sha256='apidel',
        )
        asset.file.save('delete-api-created.txt', ContentFile(b'hello'), save=True)
        storage = asset.file.storage
        storage_name = asset.file.name
        client = APIClient()
        client.force_authenticate(user=self.user)
        create_response = client.post('/api/ui-automation/page-steps-detailed/', {
            'page_step': self.page_step.id,
            'step_type': 0,
            'element': self.element.id,
            'step_sort': 5,
            'ope_key': 'upload',
            'ope_value': {'file_id': asset.id, 'file_name': 'delete-api-created.txt', 'value': f'file_id:{asset.id}'},
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(asset.references.count(), 1)

        delete_response = client.delete(f"/api/ui-automation/page-steps-detailed/{create_response.data['id']}/")
        self.assertIn(delete_response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(FileAsset.objects.filter(id=asset.id).exists())
        self.assertFalse(storage.exists(storage_name))


class UiModuleSortingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='testuser', password='password', email='test@example.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        
        self.project = Project.objects.create(name='Test Project', description='Test Description', creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        
        # Create hierarchy:
        # root1
        #   - child1_1 (order=1)
        #     - child1_1_1
        #   - child1_2 (order=2)
        # root2
        self.root1 = UiModule.objects.create(project=self.project, name='Root 1', creator=self.user, order=1)
        self.child1_1 = UiModule.objects.create(project=self.project, name='Child 1-1', parent=self.root1, creator=self.user, order=1)
        self.child1_1_1 = UiModule.objects.create(project=self.project, name='Child 1-1-1', parent=self.child1_1, creator=self.user, order=1)
        self.child1_2 = UiModule.objects.create(project=self.project, name='Child 1-2', parent=self.root1, creator=self.user, order=2)
        self.root2 = UiModule.objects.create(project=self.project, name='Root 2', creator=self.user, order=2)

    def test_get_max_depth(self):
        """测试模块子树的最大深度"""
        self.assertEqual(self.root1.get_max_depth(), 3)
        self.assertEqual(self.child1_1.get_max_depth(), 2)
        self.assertEqual(self.child1_1_1.get_max_depth(), 1)

    def test_move_api_sibling_reorder_before(self):
        """测试通过 API 移动模块到同级模块之前"""
        url = f'/api/ui-automation/modules/{self.child1_2.id}/move/'
        data = {
            'target_id': self.child1_1.id,
            'drop_position': -1 # before child1_1
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.child1_1.refresh_from_db()
        self.child1_2.refresh_from_db()
        
        self.assertEqual(self.child1_2.order, 1)
        self.assertEqual(self.child1_1.order, 2)
        self.assertEqual(self.child1_2.parent, self.root1)
        self.assertEqual(self.child1_1.parent, self.root1)

    def test_move_api_into_parent(self):
        """测试通过 API 移动模块到其他父模块下"""
        url = f'/api/ui-automation/modules/{self.child1_2.id}/move/'
        data = {
            'target_id': self.root2.id,
            'drop_position': 0 # inside root2
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.child1_2.refresh_from_db()
        self.assertEqual(self.child1_2.parent, self.root2)
        self.assertEqual(self.child1_2.level, 2)

    def test_move_api_circular_reference_protection(self):
        """测试循环引用保护：禁止移动到自己的子模块下"""
        url = f'/api/ui-automation/modules/{self.root1.id}/move/'
        data = {
            'target_id': self.child1_1_1.id,
            'drop_position': 0
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("无法移动模块到自身或其子模块下", response.data['error'])

    def test_move_api_depth_limit_protection(self):
        """测试5级深度保护"""
        child4 = UiModule.objects.create(project=self.project, name='Child 4', parent=self.child1_1_1, creator=self.user) # level 4
        child5 = UiModule.objects.create(project=self.project, name='Child 5', parent=child4, creator=self.user) # level 5
        
        url = f'/api/ui-automation/modules/{self.root1.id}/move/'
        data = {
            'target_id': self.root2.id,
            'drop_position': 0
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("超过5级限制", response.data['error'])


class UiStepBatchUpdatePreservesOverrideTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='batchuser', password='password', email='batch@example.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.project = Project.objects.create(name='Batch Project', description='Test Description', creator=self.user)
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.module = UiModule.objects.create(project=self.project, name='Root', creator=self.user, order=1)
        self.page = UiPage.objects.create(project=self.project, module=self.module, name='Login', url='https://example.com', creator=self.user)
        self.element = UiElement.objects.create(
            page=self.page,
            name='Username',
            locator_type='css',
            locator_value='#username',
            creator=self.user,
        )
        self.page_step = UiPageSteps.objects.create(
            project=self.project,
            page=self.page,
            module=self.module,
            name='Fill login form',
            creator=self.user,
        )
        self.other_page_step = UiPageSteps.objects.create(
            project=self.project,
            page=self.page,
            module=self.module,
            name='Submit login form',
            creator=self.user,
        )
        self.detail_one = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            step_type=0,
            element=self.element,
            step_sort=0,
            ope_key='fill',
            ope_value={'text': 'default-one'},
        )
        self.detail_two = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            step_type=0,
            element=self.element,
            step_sort=1,
            ope_key='type',
            ope_value={'text': 'default-two'},
        )
        self.test_case = UiTestCase.objects.create(
            project=self.project,
            module=self.module,
            name='Login case',
            creator=self.user,
        )
        self.case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.test_case,
            page_step=self.page_step,
            case_sort=0,
            case_data={
                str(self.detail_one.id): {'text': 'override-one'},
                str(self.detail_two.id): {'text': 'override-two'},
            },
        )
        self.other_case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.test_case,
            page_step=self.other_page_step,
            case_sort=1,
        )

    def test_page_step_detail_reorder_keeps_detail_ids(self):
        url = '/api/ui-automation/page-steps-detailed/batch_update/'
        response = self.client.post(url, {
            'page_step': self.page_step.id,
            'steps': [
                {
                    'id': self.detail_two.id,
                    'step_type': self.detail_two.step_type,
                    'element': self.element.id,
                    'ope_key': self.detail_two.ope_key,
                    'ope_value': self.detail_two.ope_value,
                },
                {
                    'id': self.detail_one.id,
                    'step_type': self.detail_one.step_type,
                    'element': self.element.id,
                    'ope_key': self.detail_one.ope_key,
                    'ope_value': self.detail_one.ope_value,
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            list(UiPageStepsDetailed.objects.filter(page_step=self.page_step).order_by('step_sort').values_list('id', flat=True)),
            [self.detail_two.id, self.detail_one.id],
        )
        self.detail_one.refresh_from_db()
        self.detail_two.refresh_from_db()
        self.assertEqual(self.detail_one.step_sort, 1)
        self.assertEqual(self.detail_two.step_sort, 0)

    def test_page_step_detail_reorder_keeps_upload_file_when_auto_delete_enabled(self):
        FileManagementSetting.objects.update_or_create(
            project=self.project,
            defaults={'auto_delete_on_unbind': True},
        )
        asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            original_name='reorder-upload.txt',
            mime_type='text/plain',
            size=5,
            sha256='reorder-upload',
        )
        asset.file.save('reorder-upload.txt', ContentFile(b'hello'), save=True)
        storage = asset.file.storage
        storage_name = asset.file.name
        upload_detail = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            step_type=0,
            element=self.element,
            step_sort=2,
            ope_key='upload',
            ope_value={
                'file_id': asset.id,
                'file_name': 'reorder-upload.txt',
                'value': f'file_id:{asset.id}',
            },
        )
        FileReference.objects.create(
            file=asset,
            project=self.project,
            ref_type=FileReference.REF_UI_PAGE_STEPS,
            ref_id=f'detail:{upload_detail.id}',
            created_by=self.user,
        )

        response = self.client.post('/api/ui-automation/page-steps-detailed/batch_update/', {
            'page_step': self.page_step.id,
            'steps': [
                {
                    'id': self.detail_two.id,
                    'step_type': self.detail_two.step_type,
                    'element': self.element.id,
                    'ope_key': self.detail_two.ope_key,
                    'ope_value': self.detail_two.ope_value,
                },
                {
                    'id': upload_detail.id,
                    'step_type': upload_detail.step_type,
                    'element': self.element.id,
                    'ope_key': upload_detail.ope_key,
                    'ope_value': upload_detail.ope_value,
                },
                {
                    'id': self.detail_one.id,
                    'step_type': self.detail_one.step_type,
                    'element': self.element.id,
                    'ope_key': self.detail_one.ope_key,
                    'ope_value': self.detail_one.ope_value,
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(FileAsset.objects.filter(id=asset.id).exists())
        self.assertTrue(storage.exists(storage_name))
        self.assertTrue(FileReference.objects.filter(
            file=asset,
            project=self.project,
            ref_type=FileReference.REF_UI_PAGE_STEPS,
            ref_id=f'detail:{upload_detail.id}',
        ).exists())
        upload_detail.refresh_from_db()
        self.assertEqual(upload_detail.step_sort, 1)

    def test_case_step_reorder_keeps_case_data_when_not_submitted(self):
        url = '/api/ui-automation/case-steps/batch_update/'
        expected_case_data = self.case_step.case_data

        response = self.client.post(url, {
            'test_case': self.test_case.id,
            'steps': [
                {
                    'id': self.other_case_step.id,
                    'page_step': self.other_case_step.page_step_id,
                },
                {
                    'id': self.case_step.id,
                    'page_step': self.case_step.page_step_id,
                },
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(UiCaseStepsDetailed.objects.filter(id=self.case_step.id).exists())
        self.case_step.refresh_from_db()
        self.other_case_step.refresh_from_db()
        self.assertEqual(self.case_step.case_sort, 1)
        self.assertEqual(self.other_case_step.case_sort, 0)
        self.assertEqual(self.case_step.case_data, expected_case_data)


class UiDeletionRestrictionTests(TestCase):
    """删除引用限制：删除顺序 测试用例 -> 步骤 -> 页面（元素）"""

    def setUp(self):
        self.user = User.objects.create_superuser(username='restrict_tester', password='secret')
        self.project = Project.objects.create(name='Deletion Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.module = UiModule.objects.create(project=self.project, name='Module D', creator=self.user)

        self.page_a = UiPage.objects.create(project=self.project, module=self.module, name='Page A', creator=self.user)
        self.element_a = UiElement.objects.create(
            page=self.page_a, name='Element A', locator_type='css',
            locator_value='#a', creator=self.user,
        )
        self.page_step_a = UiPageSteps.objects.create(
            project=self.project, page=self.page_a, module=self.module, name='Step A', creator=self.user,
        )
        UiPageStepsDetailed.objects.create(
            page_step=self.page_step_a, element=self.element_a, ope_key='click', step_sort=0,
        )

        # 跨页引用：页面 B 的元素被页面 A 下的另一个步骤引用
        self.page_b = UiPage.objects.create(project=self.project, module=self.module, name='Page B', creator=self.user)
        self.element_b = UiElement.objects.create(
            page=self.page_b, name='Element B', locator_type='css',
            locator_value='#b', creator=self.user,
        )
        self.page_step_a2 = UiPageSteps.objects.create(
            project=self.project, page=self.page_a, module=self.module, name='Step A2', creator=self.user,
        )
        UiPageStepsDetailed.objects.create(
            page_step=self.page_step_a2, element=self.element_b, ope_key='click', step_sort=0,
        )

        # 测试用例引用步骤 A
        self.test_case = UiTestCase.objects.create(project=self.project, module=self.module, name='Case 1', creator=self.user)
        self.case_step = UiCaseStepsDetailed.objects.create(
            test_case=self.test_case, page_step=self.page_step_a, case_sort=0,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_delete_case_referenced_step_is_rejected(self):
        response = self.client.delete(f'/api/ui-automation/page-steps/{self.page_step_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('步骤已被 1 个测试用例引用', response.data['error'])
        self.assertTrue(UiPageSteps.objects.filter(id=self.page_step_a.id).exists())

    def test_delete_unreferenced_step_succeeds(self):
        page_c = UiPage.objects.create(project=self.project, module=self.module, name='Page C', creator=self.user)
        page_step_c = UiPageSteps.objects.create(
            project=self.project, page=page_c, module=self.module, name='Step C', creator=self.user,
        )
        response = self.client.delete(f'/api/ui-automation/page-steps/{page_step_c.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(UiPageSteps.objects.filter(id=page_step_c.id).exists())

    def test_delete_page_with_steps_is_rejected(self):
        response = self.client.delete(f'/api/ui-automation/pages/{self.page_a.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('页面下存在 2 个页面步骤', response.data['error'])
        self.assertTrue(UiPage.objects.filter(id=self.page_a.id).exists())

    def test_delete_page_with_cross_page_referenced_element_is_rejected(self):
        # 页面 B 无步骤集合，但元素被页面 A 的步骤引用，仍不允许删除
        response = self.client.delete(f'/api/ui-automation/pages/{self.page_b.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('页面下的元素已被 1 个页面步骤引用', response.data['error'])
        self.assertTrue(UiPage.objects.filter(id=self.page_b.id).exists())

    def test_full_deletion_order_succeeds(self):
        """按顺序删除：用例 -> 步骤 -> 页面，最终可全部删除"""
        # 1. 删除用例步骤引用，再删除用例
        response = self.client.delete(f'/api/ui-automation/case-steps/{self.case_step.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        response = self.client.delete(f'/api/ui-automation/testcases/{self.test_case.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))

        # 2. 删除步骤（级联删除步骤详情）
        response = self.client.delete(f'/api/ui-automation/page-steps/{self.page_step_a.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        response = self.client.delete(f'/api/ui-automation/page-steps/{self.page_step_a2.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))

        # 3. 删除页面（级联删除元素）
        response = self.client.delete(f'/api/ui-automation/pages/{self.page_a.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        response = self.client.delete(f'/api/ui-automation/pages/{self.page_b.id}/')
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(UiPage.objects.filter(id__in=[self.page_a.id, self.page_b.id]).exists())


class UiCaptchaRecognizeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='captcha_tester', password='secret')
        self.project = Project.objects.create(name='Captcha Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.module = UiModule.objects.create(project=self.project, name='Auth Module', creator=self.user)
        self.page = UiPage.objects.create(project=self.project, module=self.module, name='Login', creator=self.user)
        self.img_element = UiElement.objects.create(
            page=self.page,
            name='Captcha Image',
            locator_type='xpath',
            locator_value='//img[@id="captcha_img"]',
            creator=self.user,
        )
        self.input_element = UiElement.objects.create(
            page=self.page,
            name='Captcha Input',
            locator_type='xpath',
            locator_value='//input[@id="captcha_code"]',
            locator_index=0,
            creator=self.user,
        )
        self.page_step = UiPageSteps.objects.create(
            project=self.project,
            page=self.page,
            module=self.module,
            name='Login Step',
            creator=self.user,
        )

    def test_execute_data_resolves_captcha_target_locator(self):
        detail = UiPageStepsDetailed.objects.create(
            page_step=self.page_step,
            element=self.img_element,
            ope_key='captcha_recognize',
            ope_value={
                'target_element_id': self.input_element.id,
                'retry_count': 3,
                'click_to_refresh': True,
            },
            step_sort=0,
        )
        response = UiPageStepsExecuteSerializer(self.page_step).data
        self.assertEqual(len(response['step_details']), 1)
        step_detail = response['step_details'][0]
        self.assertEqual(step_detail['ope_key'], 'captcha_recognize')
        self.assertEqual(step_detail['locator_value'], '//img[@id="captcha_img"]')
        
        target_locator = step_detail['ope_value']['target_locator']
        self.assertEqual(target_locator['element_id'], self.input_element.id)
        self.assertEqual(target_locator['locator_value'], '//input[@id="captcha_code"]')
        self.assertEqual(target_locator['locator_type'], 'xpath')
        self.assertEqual(target_locator['locator_index'], 0)

    def test_captcha_recognize_validation_requires_target_element(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        
        # 缺少 target_element_id
        res = client.post(
            '/api/ui-automation/page-steps-detailed/',
            {
                'page_step': self.page_step.id,
                'element': self.img_element.id,
                'ope_key': 'captcha_recognize',
                'ope_value': {'retry_count': 3},
                'step_sort': 0,
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('必须选择目标输入框元素', str(res.data))

        # 提供 target_element_id 成功
        res_ok = client.post(
            '/api/ui-automation/page-steps-detailed/',
            {
                'page_step': self.page_step.id,
                'element': self.img_element.id,
                'ope_key': 'captcha_recognize',
                'ope_value': {'target_element_id': self.input_element.id, 'retry_count': 3},
                'step_sort': 0,
            },
            format='json'
        )
        self.assertEqual(res_ok.status_code, status.HTTP_201_CREATED)



class UiIgnoreHttpsErrorsRuntimeTests(SimpleTestCase):
    """ignore_https_errors 三态在 effective_runtime 中的合并规则。"""

    def _resolve(self, env=None, run_options=None):
        from ui_automation.runtime_config import resolve_from_env_and_actuator

        return resolve_from_env_and_actuator(
            env=env,
            actuator_info={'browser_type': 'chromium'},
            run_options=run_options,
        )

    def test_unset_means_auto(self):
        effective = self._resolve(env={'name': 'e', 'base_url': 'https://a.local'})
        self.assertIsNone(effective['ignore_https_errors'])
        self.assertEqual(effective['source']['ignore_https_errors'], 'auto')

    def test_env_true_wins_over_auto(self):
        effective = self._resolve(env={'name': 'e', 'ignore_https_errors': True})
        self.assertIs(effective['ignore_https_errors'], True)
        self.assertEqual(effective['source']['ignore_https_errors'], 'env')

    def test_env_false_is_kept_not_dropped(self):
        effective = self._resolve(env={'name': 'e', 'ignore_https_errors': False})
        self.assertIs(effective['ignore_https_errors'], False)
        self.assertEqual(effective['source']['ignore_https_errors'], 'env')

    def test_run_options_overrides_env(self):
        effective = self._resolve(
            env={'name': 'e', 'ignore_https_errors': True},
            run_options={'ignore_https_errors': False},
        )
        self.assertIs(effective['ignore_https_errors'], False)
        self.assertEqual(effective['source']['ignore_https_errors'], 'run_options')

    def test_null_run_option_falls_back_to_env(self):
        effective = self._resolve(
            env={'name': 'e', 'ignore_https_errors': True},
            run_options={'ignore_https_errors': None},
        )
        self.assertIs(effective['ignore_https_errors'], True)
        self.assertEqual(effective['source']['ignore_https_errors'], 'env')

    def test_public_and_snapshot_include_key_but_no_db_secret(self):
        from ui_automation.runtime_config import (
            build_environment_snapshot,
            public_effective_runtime,
        )

        effective = self._resolve(env={'name': 'e', 'ignore_https_errors': True})
        self.assertIn('ignore_https_errors', public_effective_runtime(effective))
        self.assertIn('ignore_https_errors', build_environment_snapshot(effective))


class UiClientCertPayloadTests(TestCase):
    """证书任务载荷组装与回传脱敏。"""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='wharttest-ui-cert-test-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        from ui_automation.models import UiEnvironmentConfig

        self.UiEnvironmentConfig = UiEnvironmentConfig
        self.project = Project.objects.create(name='UI Cert Project')
        self.user = User.objects.create_user(username='ui-cert-user', password='x')
        self.asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=ContentFile(b'fake-pfx-bytes', name='client.p12'),
            original_name='client.p12',
            extension='.p12',
            size=14,
        )

    def _env(self, certificate=None):
        return self.UiEnvironmentConfig.objects.create(
            project=self.project,
            name='ui-env',
            base_url='https://ui.local',
            client_certificate=certificate,
            creator=self.user,
        )

    def test_no_certificate_returns_none(self):
        self.assertIsNone(build_env_client_cert_payload(self._env()))

    def test_payload_carries_files_and_passphrase(self):
        certificate = ClientCertificate.objects.create(
            name='ui-cert',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        certificate.set_passphrase('ui-pass')
        certificate.save(update_fields=['passphrase_encrypted'])

        payload = build_env_client_cert_payload(self._env(certificate))
        self.assertEqual(payload['cert_type'], 'pkcs12')
        self.assertEqual(payload['passphrase'], 'ui-pass')
        self.assertEqual(payload['cert_file']['file_id'], self.asset.id)
        self.assertEqual(payload['origins'], ['https://ui.local'])

    def test_sanitize_strips_passphrase_but_keeps_flag(self):
        from ui_automation.consumers import UiAutomationConsumer

        sanitized = UiAutomationConsumer._sanitize_result_args({
            'case_id': 1,
            'client_cert': {
                'cert_type': 'pkcs12',
                'passphrase': 'ui-pass',
                'cert_file': {'file_id': 9},
            },
        })
        self.assertNotIn('passphrase', sanitized['client_cert'])
        self.assertTrue(sanitized['client_cert']['has_passphrase'])
        self.assertEqual(sanitized['client_cert']['cert_file']['file_id'], 9)
        self.assertEqual(sanitized['case_id'], 1)

    def test_sanitize_does_not_mutate_original(self):
        from ui_automation.consumers import UiAutomationConsumer

        original = {'client_cert': {'passphrase': 'keep-me'}}
        UiAutomationConsumer._sanitize_result_args(original)
        self.assertEqual(original['client_cert']['passphrase'], 'keep-me')


class UiEnvironmentConfigCertificateApiTests(TestCase):
    """环境配置接口：证书不可回显口令，且必须同项目。"""

    def setUp(self):
        self.user = User.objects.create_superuser(username='env-admin', password='secret')
        self.project = Project.objects.create(name='Env Cert Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=ContentFile(b'bytes', name='c.p12'),
            original_name='c.p12',
            extension='.p12',
            size=5,
        )

    def _payload(self, **extra):
        payload = {
            'project': self.project.id,
            'name': 'env',
            'base_url': 'https://env.local',
            'ignore_https_errors': True,
        }
        payload.update(extra)
        return payload

    def test_create_env_with_certificate_returns_summary_without_passphrase(self):
        certificate = ClientCertificate.objects.create(
            name='cert-a',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        certificate.set_passphrase('top-secret')
        certificate.save(update_fields=['passphrase_encrypted'])

        response = self.client.post(
            '/api/ui-automation/env-configs/',
            self._payload(client_certificate=certificate.id),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        body = response.data
        self.assertNotIn('top-secret', str(body))
        self.assertIs(body['ignore_https_errors'], True)
        cert_info = body['client_cert_info']
        self.assertEqual(cert_info['id'], certificate.id)
        self.assertTrue(cert_info['has_passphrase'])

    def test_certificate_from_other_project_is_rejected(self):
        other_project = Project.objects.create(name='Other Project')
        foreign_cert = ClientCertificate.objects.create(
            name='foreign',
            project=other_project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=None,
            created_by=self.user,
        )
        response = self.client.post(
            '/api/ui-automation/env-configs/',
            self._payload(client_certificate=foreign_cert.id),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('client_certificate', response.data)

    def test_client_cert_warnings_empty_for_https_env(self):
        """https 环境 + 绑证书：预检无告警。"""
        certificate = ClientCertificate.objects.create(
            name='cert-ok',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        response = self.client.post(
            '/api/ui-automation/env-configs/',
            self._payload(client_certificate=certificate.id),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['client_cert_warnings'], [])

    def test_client_cert_warnings_when_base_url_not_https(self):
        """http 环境 + 绑证书：必须提前告警「证书不可能生效」，否则用户到录制才发现白屏。"""
        certificate = ClientCertificate.objects.create(
            name='cert-http',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        response = self.client.post(
            '/api/ui-automation/env-configs/',
            self._payload(base_url='http://plain.local', client_certificate=certificate.id),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        warnings = response.data['client_cert_warnings']
        self.assertTrue(warnings)
        self.assertIn('https', ' '.join(warnings))

    def test_client_cert_warnings_empty_without_certificate(self):
        response = self.client.post(
            '/api/ui-automation/env-configs/',
            self._payload(base_url='http://plain.local'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['client_cert_warnings'], [])


class UiClientCertificateOriginTests(SimpleTestCase):
    """origin 归一化：语义必须与执行器 WHartTest_Actuator/client_cert.py 完全一致。

    两侧对同一个 base_url 必须推导出同一个 origin，否则会出现「执行器能用、
    本地录制器不能用」这类极难定位的偏差。
    """

    def test_https_only(self):
        self.assertEqual(normalize_origin('http://a.local'), None)
        self.assertEqual(normalize_origin('ftp://a.local'), None)
        self.assertEqual(normalize_origin('file:///tmp/x'), None)
        self.assertEqual(normalize_origin('https://a.local'), 'https://a.local')

    def test_drops_path_query_fragment_userinfo(self):
        self.assertEqual(
            normalize_origin('https://u:p@a.local:8443/app/x?y=1#z'),
            'https://a.local:8443',
        )

    def test_explicit_443_is_folded(self):
        self.assertEqual(normalize_origin('https://a.local:443/x'), 'https://a.local')

    def test_non_default_port_kept(self):
        self.assertEqual(normalize_origin('https://192.168.3.112:9443'), 'https://192.168.3.112:9443')

    def test_ipv6_rebracketed(self):
        self.assertEqual(normalize_origin('https://[::1]:8443/x'), 'https://[::1]:8443')
        self.assertEqual(normalize_origin('https://[::1]/x'), 'https://[::1]')

    def test_invalid_inputs(self):
        for value in (None, '', '   ', 123, [], 'https://'):
            self.assertIsNone(normalize_origin(value))

    def test_parse_origins_dedupes_and_keeps_order(self):
        origins = parse_origins(
            'https://b.local,https://a.local',
            ['https://a.local/', 'http://ignored.local'],
            None,
        )
        self.assertEqual(origins, ['https://b.local', 'https://a.local'])

    def test_parse_origins_empty(self):
        self.assertEqual(parse_origins(None, '', []), [])


class UiRecorderClientCertPayloadTests(TestCase):
    """本地录制器侧的证书载荷：本地路径 + 预校验 + 三态 ignore。"""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='wharttest-recorder-cert-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        from ui_automation.models import UiEnvironmentConfig

        self.UiEnvironmentConfig = UiEnvironmentConfig
        self.project = Project.objects.create(name='Recorder Cert Project')
        self.user = User.objects.create_user(username='rec-cert', password='x')

    # ---- 测试材料 ----

    def _pkcs12_bytes(self, passphrase=None):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import pkcs12

        key, cert = _self_signed_pair()
        encryption = (
            serialization.BestAvailableEncryption(passphrase.encode('utf-8'))
            if passphrase
            else serialization.NoEncryption()
        )
        return pkcs12.serialize_key_and_certificates(
            b'wharttest', key, cert, None, encryption,
        )

    def _asset(self, data, name, extension):
        return FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=ContentFile(data, name=name),
            original_name=name,
            extension=extension,
            size=len(data),
        )

    def _env(self, certificate, base_url='https://192.168.3.112', **extra):
        return self.UiEnvironmentConfig.objects.create(
            project=self.project,
            name='rec-env',
            base_url=base_url,
            client_certificate=certificate,
            creator=self.user,
            **extra,
        )

    def _pkcs12_cert(self, passphrase='p@ss'):
        asset = self._asset(self._pkcs12_bytes(passphrase), 'client.p12', '.p12')
        certificate = ClientCertificate.objects.create(
            name='rec-p12',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=asset,
            created_by=self.user,
        )
        if passphrase:
            certificate.set_passphrase(passphrase)
            certificate.save(update_fields=['passphrase_encrypted'])
        return certificate

    # ---- PKCS#12 ----

    def test_pkcs12_entry_is_camelcase_with_passphrase(self):
        certificate = self._pkcs12_cert('p@ss')
        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(warnings, [])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['origin'], 'https://192.168.3.112')
        self.assertTrue(entry['pfxPath'].endswith('.p12'))
        self.assertEqual(entry['passphrase'], 'p@ss')
        # snake_case 会被 Playwright 静默忽略 —— 必须保证不出现
        self.assertNotIn('pfx_path', entry)
        self.assertNotIn('certPath', entry)

    def test_pkcs12_wrong_passphrase_degrades_with_warning(self):
        certificate = self._pkcs12_cert('right')
        certificate.set_passphrase('wrong')
        certificate.save(update_fields=['passphrase_encrypted'])

        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(entries, [])
        self.assertTrue(warnings)
        self.assertIn('PKCS#12', warnings[0])

    def test_missing_file_degrades_with_warning(self):
        certificate = ClientCertificate.objects.create(
            name='rec-missing',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=None,
            created_by=self.user,
        )
        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    # ---- PEM ----

    def test_pem_without_passphrase_uses_original_paths(self):
        cert_pem, key_pem = _self_signed_pems()
        cert_asset = self._asset(cert_pem, 'client.pem', '.pem')
        key_asset = self._asset(key_pem, 'client.key', '.key')
        certificate = ClientCertificate.objects.create(
            name='rec-pem',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PEM,
            cert_file=cert_asset,
            key_file=key_asset,
            created_by=self.user,
        )

        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(warnings, [])
        entry = entries[0]
        self.assertIn('certPath', entry)
        self.assertIn('keyPath', entry)
        self.assertNotIn('passphrase', entry)
        self.assertEqual(entry['keyPath'], key_asset.file.path)

    def test_pem_with_passphrase_decrypts_key_into_cache(self):
        """PEM 加密私钥：解密后落缓存再交给 Playwright，条目内不带 passphrase。"""
        from cryptography.hazmat.primitives import serialization

        cert_pem, key_pem = _self_signed_pems(encrypted_passphrase='k@y')
        cert_asset = self._asset(cert_pem, 'enc.pem', '.pem')
        key_asset = self._asset(key_pem, 'enc.key', '.key')
        certificate = ClientCertificate.objects.create(
            name='rec-pem-enc',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PEM,
            cert_file=cert_asset,
            key_file=key_asset,
            created_by=self.user,
        )
        certificate.set_passphrase('k@y')
        certificate.save(update_fields=['passphrase_encrypted'])

        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(warnings, [])
        entry = entries[0]
        self.assertNotIn('passphrase', entry)
        self.assertIn('client_cert_cache', entry['keyPath'].replace('\\', '/'))
        # 解密产物必须真的是「无口令可加载」的私钥
        with open(entry['keyPath'], 'rb') as fh:
            serialization.load_pem_private_key(fh.read(), password=None)

    def test_pem_wrong_passphrase_degrades_with_warning(self):
        cert_pem, key_pem = _self_signed_pems(encrypted_passphrase='k@y')
        certificate = ClientCertificate.objects.create(
            name='rec-pem-bad',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PEM,
            cert_file=self._asset(cert_pem, 'bad.pem', '.pem'),
            key_file=self._asset(key_pem, 'bad.key', '.key'),
            created_by=self.user,
        )
        certificate.set_passphrase('wrong')
        certificate.save(update_fields=['passphrase_encrypted'])

        entries, warnings = build_recorder_client_certificates(
            certificate, origins=['https://192.168.3.112'],
        )
        self.assertEqual(entries, [])
        self.assertTrue(warnings)

    # ---- 兜底与三态 ----

    def test_storage_backend_fallback_writes_to_cache(self):
        """本地 .path 不可用（S3 等）时应读出字节落缓存，而不是直接放弃。"""
        from unittest.mock import patch

        certificate = self._pkcs12_cert('p@ss')
        with patch(
            'client_certificates.services.asset_filesystem_path', return_value='',
        ):
            entries, warnings = build_recorder_client_certificates(
                certificate, origins=['https://192.168.3.112'],
            )
        self.assertEqual(warnings, [])
        self.assertTrue(entries)
        self.assertIn('client_cert_cache', entries[0]['pfxPath'].replace('\\', '/'))

    def test_no_origins_returns_warning(self):
        certificate = self._pkcs12_cert('p@ss')
        entries, warnings = build_recorder_client_certificates(certificate, origins=[])
        self.assertEqual(entries, [])
        self.assertTrue(warnings)
        self.assertIn('origin', warnings[0])

    def test_multiple_origins_produce_one_entry_each(self):
        certificate = self._pkcs12_cert('p@ss')
        entries, _ = build_recorder_client_certificates(
            certificate, origins=['https://a.local', 'https://b.local:8443'],
        )
        self.assertEqual([e['origin'] for e in entries], ['https://a.local', 'https://b.local:8443'])

    def test_ignore_https_errors_tristate(self):
        """None=auto（有证书才忽略）/ True / False 强制覆盖。"""
        class _Env:
            def __init__(self, value):
                self.ignore_https_errors = value

        entries = [{'origin': 'https://a.local'}]
        self.assertIs(resolve_recorder_ignore_https_errors(_Env(None), entries), True)
        self.assertIs(resolve_recorder_ignore_https_errors(_Env(None), []), False)
        self.assertIs(resolve_recorder_ignore_https_errors(_Env(True), []), True)
        self.assertIs(resolve_recorder_ignore_https_errors(_Env(False), entries), False)

    def test_build_payload_without_certificate(self):
        env = self._env(None)
        payload = build_recorder_https_payload(env)
        self.assertEqual(payload['client_certificates'], [])
        self.assertEqual(payload['warnings'], [])
        self.assertFalse(payload['ignore_https_errors'])

    def test_build_payload_auto_ignores_when_cert_applies(self):
        env = self._env(self._pkcs12_cert('p@ss'))
        payload = build_recorder_https_payload(env)
        self.assertEqual(len(payload['client_certificates']), 1)
        self.assertTrue(payload['ignore_https_errors'])
        self.assertEqual(payload['warnings'], [])

    def test_build_payload_http_base_url_warns_and_degrades(self):
        env = self._env(self._pkcs12_cert('p@ss'), base_url='http://plain.local')
        payload = build_recorder_https_payload(env)
        self.assertEqual(payload['client_certificates'], [])
        self.assertTrue(payload['warnings'])
        # 证书没生效 → auto 不应放宽 HTTPS 校验
        self.assertFalse(payload['ignore_https_errors'])

    def test_build_payload_uses_extra_urls_for_origin(self):
        env = self._env(self._pkcs12_cert('p@ss'), base_url='')
        payload = build_recorder_https_payload(env, extra_urls=['https://page.local/x'])
        self.assertEqual(
            [e['origin'] for e in payload['client_certificates']], ['https://page.local'],
        )

    def test_build_payload_without_origin_warns(self):
        env = self._env(self._pkcs12_cert('p@ss'), base_url='')
        payload = build_recorder_https_payload(env)
        self.assertEqual(payload['client_certificates'], [])
        self.assertTrue(payload['warnings'])

    def test_env_config_warnings_flags_disabled_certificate(self):
        certificate = self._pkcs12_cert('p@ss')
        certificate.is_active = False
        certificate.save(update_fields=['is_active'])
        env = self._env(certificate)
        warnings = env_config_certificate_warnings(env)
        self.assertTrue(any('禁用' in w for w in warnings))

    def test_env_config_warnings_empty_when_usable(self):
        env = self._env(self._pkcs12_cert('p@ss'))
        self.assertEqual(env_config_certificate_warnings(env), [])

    def test_recorder_start_params_carry_certificate(self):
        """端到端：环境配置绑定的证书必须真正出现在 recorder start 参数里。"""
        from unittest.mock import Mock, patch

        from ui_automation.recorder.session_manager import RecorderSessionMeta
        from ui_automation.views import _start_recorder_session

        env = self._env(self._pkcs12_cert('p@ss'))
        meta = RecorderSessionMeta(
            user_id='u1', project_id=self.project.id, page_id=None, page_step_id=None,
            create_elements=False, create_steps=False, base_url='https://192.168.3.112',
            viewport={'width': 1400, 'height': 900}, kind='record', env_config_id=env.id,
        )
        session = Mock()
        session.start = Mock(return_value=None)
        session.request = Mock(return_value={
            'ok': True, 'state': {'viewport': {'width': 1400, 'height': 900}},
        })
        with patch('ui_automation.recorder.session_manager.recorder_manager') as rm:
            rm.create_session.return_value = session
            _sid, _vp, _pre, warnings = _start_recorder_session(
                env_config=env, page=None, base_url='https://192.168.3.112',
                skill_dir='/tmp/x',
                request=type('R', (), {'user': type('U', (), {'username': 'u1'})()})(),
                meta=meta,
            )

        params = session.request.call_args_list[0].args[1]
        entries = params['client_certificates']
        self.assertEqual(entries[0]['origin'], 'https://192.168.3.112')
        self.assertIn('pfxPath', entries[0])
        self.assertIs(params['ignore_https_errors'], True)
        self.assertEqual(warnings, [])


def _self_signed_pair():
    """生成一张自签名证书 + 私钥（测试用，避免引入静态二进制夹具）。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'wharttest-test')])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def _self_signed_pems(encrypted_passphrase=None):
    """返回 (证书 PEM bytes, 私钥 PEM bytes)；给了口令则私钥为加密 PEM。"""
    from cryptography.hazmat.primitives import serialization

    key, certificate = _self_signed_pair()
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    encryption = (
        serialization.BestAvailableEncryption(encrypted_passphrase.encode('utf-8'))
        if encrypted_passphrase
        else serialization.NoEncryption()
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        encryption,
    )
    return cert_pem, key_pem


class UiEnvironmentConfigNullCertificateApiTests(TestCase):
    """「不关联客户端证书」应可正常保存。

    前端把「不关联」表达为 '' / 'null' / 'undefined' 等字符串，而 client_certificate
    是外键（期望主键 int），历史上会报「类型错误。期望为主键，获得的类型为 str」。
    同时必须保证 PATCH 下「字段缺失 = 不修改」的语义不被破坏。
    """

    def setUp(self):
        self.user = User.objects.create_superuser(username='env-null-admin', password='secret')
        self.project = Project.objects.create(name='Env Null Project')
        ProjectMember.objects.create(project=self.project, user=self.user, role='admin')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=ContentFile(b'bytes', name='n.p12'),
            original_name='n.p12',
            extension='.p12',
            size=5,
        )
        self.certificate = ClientCertificate.objects.create(
            name='cert-null',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        self.url = '/api/ui-automation/env-configs/'

    def _create_env(self, **extra):
        payload = {
            'project': self.project.id,
            'name': 'env-null',
            'base_url': 'https://env-null.local',
        }
        payload.update(extra)
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data['id']

    def _assert_cleared(self, env_id):
        from ui_automation.models import UiEnvironmentConfig
        env = UiEnvironmentConfig.objects.get(id=env_id)
        self.assertIsNone(env.client_certificate_id)

    def test_create_with_null_sentinel_string_ok(self):
        """POST 带 '' / 'null' / 'undefined' 均 201 且置空。"""
        for sentinel in ('', 'null', 'undefined'):
            with self.subTest(sentinel=sentinel):
                env_id = self._create_env(
                    name=f'env-{sentinel or "empty"}',
                    client_certificate=sentinel,
                )
                self._assert_cleared(env_id)

    def test_patch_empty_string_clears_relation(self):
        env_id = self._create_env(client_certificate=self.certificate.id)
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': ''}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['client_cert_info'])
        self._assert_cleared(env_id)

    def test_patch_null_string_clears_relation(self):
        env_id = self._create_env(client_certificate=self.certificate.id)
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': 'null'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['client_cert_info'])
        self._assert_cleared(env_id)

    def test_patch_undefined_string_clears_relation(self):
        env_id = self._create_env(client_certificate=self.certificate.id)
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': 'undefined'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['client_cert_info'])
        self._assert_cleared(env_id)

    def test_patch_without_certificate_field_keeps_relation(self):
        """字段缺失 = 不修改（关键回归：不得把「缺失」当成「置空」）。"""
        env_id = self._create_env(client_certificate=self.certificate.id)
        response = self.client.patch(
            f'{self.url}{env_id}/', {'is_default': True}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        cert_info = response.data['client_cert_info']
        self.assertIsNotNone(cert_info)
        self.assertEqual(cert_info['id'], self.certificate.id)

    def test_patch_nonexistent_certificate_still_400(self):
        env_id = self._create_env()
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': 999999}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('client_certificate', response.data)

    def test_patch_cross_project_certificate_still_400(self):
        other_project = Project.objects.create(name='Env Null Other')
        foreign_cert = ClientCertificate.objects.create(
            name='foreign-null',
            project=other_project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=None,
            created_by=self.user,
        )
        env_id = self._create_env()
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': foreign_cert.id}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('client_certificate', response.data)

    def test_patch_valid_certificate_sets_relation(self):
        env_id = self._create_env()
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': self.certificate.id}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['client_cert_info']['id'], self.certificate.id)

    def test_direct_json_null_still_works(self):
        """回归：显式 JSON null 后端的既有行为不变。"""
        env_id = self._create_env(client_certificate=self.certificate.id)
        response = self.client.patch(
            f'{self.url}{env_id}/', {'client_certificate': None}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self._assert_cleared(env_id)
