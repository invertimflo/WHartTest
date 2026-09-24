import logging

from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from file_management.models import FileReference
from file_management.services import sync_file_references
from wharttest_django.api_permissions import IsProjectMemberForResource
from wharttest_django.pagination import StandardPagination
from wharttest_django.permissions import HasModelPermission
from wharttest_django.viewsets import BaseModelViewSet

from .models import ClientCertificate
from .serializers import ClientCertificateSerializer
from .services import validate_certificate

logger = logging.getLogger(__name__)


class ClientCertificateViewSet(BaseModelViewSet):
    """客户端证书（项目级资源）管理视图。"""

    serializer_class = ClientCertificateSerializer
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'cert_type']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def get_permissions(self):
        return [
            permissions.IsAuthenticated(),
            HasModelPermission(),
            IsProjectMemberForResource(),
        ]

    def get_queryset(self):
        project_pk = self.kwargs.get('project_pk')
        return ClientCertificate.objects.select_related(
            'project', 'created_by', 'cert_file', 'key_file'
        ).filter(project_id=project_pk)

    def perform_create(self, serializer):
        from projects.models import Project

        project = get_object_or_404(Project, pk=self.kwargs.get('project_pk'))
        instance = serializer.save(created_by=self.request.user, project=project)
        self._sync_references(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._sync_references(instance)

    def _sync_references(self, instance):
        """登记/回收文件引用，避免证书文件被"零引用自动清理"误删。"""
        file_ids = instance.managed_file_ids()
        try:
            # 先清掉旧引用（同步函数会自动删除不在列表中的引用）
            sync_file_references(
                file_ids,
                instance.project,
                FileReference.REF_CLIENT_CERT,
                instance.id,
                self.request.user,
            )
        except Exception as exc:  # noqa: BLE001 - 引用登记失败不应阻断证书保存
            logger.warning('客户端证书 %s 文件引用登记失败：%s', instance.id, exc)

    @action(detail=True, methods=['post'], url_path='validate')
    def validate_certificate_action(self, request, **kwargs):
        """试加载证书并返回告警列表（不阻断保存，供前端"校验"按钮使用）。"""
        certificate = self.get_object()
        warnings = validate_certificate(certificate)
        return Response({
            'valid': not warnings,
            'warnings': warnings,
        })
