from rest_framework import serializers

from .models import ApiEnvironment, ApiEnvironmentVariable, ApiGlobalRequestHeader


class ApiEnvironmentVariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiEnvironmentVariable
        fields = [
            'id', 'name', 'value', 'type', 'description',
            'is_sensitive', 'created_at', 'updated_at', 'environment',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.is_sensitive:
            ret['value'] = '******'
        return ret


class ApiEnvironmentSerializer(serializers.ModelSerializer):
    variables = ApiEnvironmentVariableSerializer(source='api_variables', many=True, read_only=True)
    project_info = serializers.SerializerMethodField()
    parent_info = serializers.SerializerMethodField()
    database_config_info = serializers.SerializerMethodField()
    client_certificate_info = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.username', read_only=True, default=''
    )

    class Meta:
        model = ApiEnvironment
        fields = [
            'id', 'name', 'base_url', 'verify_ssl',
            'description', 'project', 'project_info',
            'parent', 'parent_info', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
            'variables', 'database_config', 'database_config_info',
            'client_certificate', 'client_certificate_info',
        ]
        read_only_fields = ['project', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'parent': {'required': False},
            'database_config': {'required': False},
            'client_certificate': {'required': False},
        }

    def validate(self, attrs):
        """关联资源必须与环境中同项目（create 与 update 共用）。"""
        instance = self.instance
        project_id = getattr(instance, 'project_id', None) or self._project_id()

        def _check(field, label):
            related = attrs.get(field, getattr(instance, field, None))
            if related is not None and project_id and related.project_id != project_id:
                raise serializers.ValidationError({
                    field: [f'{label} must belong to the same project.'],
                })

        _check('database_config', 'Database config')
        _check('client_certificate', 'Client certificate')
        return attrs

    def _project_id(self):
        view = self.context.get('view')
        project_pk = getattr(view, 'kwargs', {}).get('project_pk') if view is not None else None
        if project_pk:
            try:
                return int(project_pk)
            except (TypeError, ValueError):
                return None
        return None

    def get_client_certificate_info(self, obj):
        if not obj.client_certificate_id or obj.client_certificate is None:
            return None
        cert = obj.client_certificate
        return {
            'id': cert.id,
            'name': cert.name,
            'cert_type': cert.cert_type,
            'has_passphrase': cert.has_passphrase,
            'is_active': cert.is_active,
        }

    def get_project_info(self, obj):
        if obj.project:
            return {
                'id': obj.project.id,
                'name': obj.project.name,
            }
        return None

    def get_parent_info(self, obj):
        if obj.parent:
            return {
                'id': obj.parent.id,
                'name': obj.parent.name,
                'base_url': obj.parent.base_url,
                'description': obj.parent.description,
            }
        return None

    def get_database_config_info(self, obj):
        if obj.database_config:
            return {
                'id': obj.database_config.id,
                'name': obj.database_config.name,
                'db_type': obj.database_config.db_type,
                'host': obj.database_config.host,
            }
        return None


class ApiGlobalRequestHeaderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiGlobalRequestHeader
        fields = [
            'id', 'name', 'value',
            'description', 'is_enabled', 'project',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['project', 'created_by', 'created_at', 'updated_at']
