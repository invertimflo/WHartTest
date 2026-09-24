"""HTTPS 客户端证书（mTLS）项目级资源。

接口自动化环境（ApiEnvironment）与 UI 自动化环境（UiEnvironmentConfig）均以
外键引用本表，一处维护、多处复用，与 ApiDatabaseConfig 的范式保持一致。

证书形态只有两种：
  - ``pem``    ：cert_file（证书）+ key_file（私钥），私钥可带口令
  - ``pkcs12`` ：cert_file 为 .pfx/.p12 单文件，口令存 passphrase_encrypted

口令以 Fernet 密文存储（见 crypto.py），任何序列化输出都不得回显明文。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .crypto import decrypt_passphrase, encrypt_passphrase

# 扩展名约定：仅用于给出告警/校验，不做硬性阻断（与执行器 client_cert.py 保持一致）
PFX_EXTENSIONS = ('.pfx', '.p12')
CERT_EXTENSIONS = ('.pem', '.crt', '.cer', '.cert')
KEY_EXTENSIONS = ('.key', '.pem')


def validate_certificate_fields(cert_type, cert_file, key_file, project_id):
    """校验证书字段组合，返回 {field: message} 错误字典（空字典表示通过）。

    同时供 ``ClientCertificate.clean()`` 与 DRF 序列化器复用 —— DRF 默认不会
    调用 ``Model.clean()``，两处共用一份规则可避免行为漂移。
    """
    errors = {}

    if cert_type == ClientCertificate.CERT_TYPE_PEM:
        if not cert_file:
            errors['cert_file'] = _('PEM 证书需要选择证书文件。')
        if not key_file:
            errors['key_file'] = _('PEM 证书需要选择私钥文件。')
    elif cert_type == ClientCertificate.CERT_TYPE_PKCS12:
        if not cert_file:
            errors['cert_file'] = _('PKCS#12 证书需要选择 .pfx/.p12 文件。')
        else:
            ext = (getattr(cert_file, 'extension', '') or '').lower()
            if ext and ext not in PFX_EXTENSIONS:
                errors['cert_file'] = _(
                    'PKCS#12 证书文件扩展名应为 .pfx/.p12，当前为 %(ext)s。'
                ) % {'ext': ext}
    else:
        errors['cert_type'] = _('不支持的证书类型。')

    # 证书文件必须与证书同项目（跨项目引用会绕过项目权限）
    for field_name, asset in (('cert_file', cert_file), ('key_file', key_file)):
        if asset is not None and project_id and asset.project_id != project_id:
            errors[field_name] = _('证书文件必须属于同一项目。')

    return errors


class ClientCertificate(models.Model):
    """HTTPS 客户端证书（项目级资源）。"""

    CERT_TYPE_PEM = 'pem'
    CERT_TYPE_PKCS12 = 'pkcs12'
    CERT_TYPE_CHOICES = [
        (CERT_TYPE_PEM, _('PEM（证书 + 私钥）')),
        (CERT_TYPE_PKCS12, _('PKCS#12（.pfx/.p12）')),
    ]

    name = models.CharField(_("Name"), max_length=100)
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        related_name='client_certificates',
        verbose_name=_("Project"),
    )
    cert_type = models.CharField(
        _("Certificate Type"), max_length=20, choices=CERT_TYPE_CHOICES,
        default=CERT_TYPE_PEM,
    )
    cert_file = models.ForeignKey(
        'file_management.FileAsset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name=_("Certificate File"),
    )
    key_file = models.ForeignKey(
        'file_management.FileAsset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name=_("Private Key File"),
    )
    # Fernet 密文；空串表示未设置口令（无口令证书不应带空 passphrase 传给 Playwright）
    passphrase_encrypted = models.TextField(_("Encrypted Passphrase"), blank=True, default='')
    description = models.TextField(_("Description"), blank=True, default='')
    is_active = models.BooleanField(_("Active"), default=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_client_certificates', verbose_name=_("Created By"),
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Client Certificate")
        verbose_name_plural = _("Client Certificates")
        ordering = ['-created_at']
        unique_together = ('name', 'project')
        db_table = 'client_certificate'

    def __str__(self):
        return f"{self.project.name}-{self.name}" if self.project_id else self.name

    def clean(self):
        errors = validate_certificate_fields(
            self.cert_type,
            self.cert_file if self.cert_file_id else None,
            self.key_file if self.key_file_id else None,
            self.project_id,
        )
        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # 口令（密文存储；明文只在内存中出现）
    # ------------------------------------------------------------------

    def set_passphrase(self, raw):
        """设置口令明文（空值即清空）。"""
        self.passphrase_encrypted = encrypt_passphrase(raw)

    def get_passphrase(self):
        """取出口令明文；解密失败返回空串。"""
        return decrypt_passphrase(self.passphrase_encrypted)

    @property
    def has_passphrase(self):
        return bool(self.passphrase_encrypted)

    # ------------------------------------------------------------------
    # 便于调用方统一取文件
    # ------------------------------------------------------------------

    def managed_file_ids(self):
        """本证书引用的托管文件 id 列表（用于登记 FileReference，避免被自动清理误删）。"""
        return [fid for fid in (self.cert_file_id, self.key_file_id) if fid]
