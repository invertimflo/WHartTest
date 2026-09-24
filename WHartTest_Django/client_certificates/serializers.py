import logging

from rest_framework import serializers

from file_management.services import serialize_file_for_runtime

from .models import ClientCertificate, validate_certificate_fields

logger = logging.getLogger(__name__)


class ClientCertificateSerializer(serializers.ModelSerializer):
    """客户端证书序列化器。

    口令走**只写**通道：
      - 传 ``passphrase`` 且非空 -> 设置口令
      - 传 ``clear_passphrase=true`` -> 清除口令
      - 两者都不传 -> 保持原口令不变
    任何情况下都不会把口令明文回显给前端，只暴露 ``has_passphrase`` 布尔位。
    """

    passphrase = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False,
        help_text='证书口令（仅写入，不会回显）',
    )
    clear_passphrase = serializers.BooleanField(write_only=True, required=False)
    has_passphrase = serializers.SerializerMethodField()
    cert_file_info = serializers.SerializerMethodField()
    key_file_info = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.username', read_only=True, default=''
    )

    class Meta:
        model = ClientCertificate
        fields = [
            'id', 'name', 'project', 'cert_type',
            'cert_file', 'cert_file_info', 'key_file', 'key_file_info',
            'passphrase', 'clear_passphrase', 'has_passphrase',
            'description', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'project', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'cert_file': {'required': False, 'allow_null': True},
            'key_file': {'required': False, 'allow_null': True},
        }

    def get_has_passphrase(self, obj):
        return obj.has_passphrase

    def get_cert_file_info(self, obj):
        if not obj.cert_file_id or obj.cert_file is None:
            return None
        return serialize_file_for_runtime(obj.cert_file)

    def get_key_file_info(self, obj):
        if not obj.key_file_id or obj.key_file is None:
            return None
        return serialize_file_for_runtime(obj.key_file)

    def _project_id(self):
        view = self.context.get('view')
        if view is not None:
            project_pk = getattr(view, 'kwargs', {}).get('project_pk')
            if project_pk:
                try:
                    return int(project_pk)
                except (TypeError, ValueError):
                    pass
        if self.instance is not None:
            return self.instance.project_id
        return None

    def validate(self, attrs):
        instance = self.instance
        cert_type = attrs.get(
            'cert_type', getattr(instance, 'cert_type', ClientCertificate.CERT_TYPE_PEM)
        )
        # PATCH 时未提交的字段回落实例值
        cert_file = attrs.get('cert_file', getattr(instance, 'cert_file', None))
        key_file = attrs.get('key_file', getattr(instance, 'key_file', None))

        errors = validate_certificate_fields(cert_type, cert_file, key_file, self._project_id())
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        passphrase = validated_data.pop('passphrase', None)
        validated_data.pop('clear_passphrase', None)
        instance = super().create(validated_data)
        if passphrase:
            instance.set_passphrase(passphrase)
            instance.save(update_fields=['passphrase_encrypted'])
        return instance

    def update(self, instance, validated_data):
        change_passphrase = 'passphrase' in validated_data
        clear_passphrase = bool(validated_data.pop('clear_passphrase', False))
        passphrase = validated_data.pop('passphrase', None)

        instance = super().update(instance, validated_data)
        if clear_passphrase:
            instance.set_passphrase('')
            instance.save(update_fields=['passphrase_encrypted'])
        elif change_passphrase and passphrase:
            instance.set_passphrase(passphrase)
            instance.save(update_fields=['passphrase_encrypted'])
        return instance
