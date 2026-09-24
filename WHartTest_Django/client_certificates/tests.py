"""client_certificates 单元测试。

覆盖范围：
  1. 口令加解密往返与密钥失效降级
  2. 证书材料转换：PEM(无口令) / 带口令 PEM / PKCS#12 / 文件缺失 / 口令错误
  3. httprunner 的 cert 通道（Config.cert 能落到 TConfig，TRequest 有空位）
  4. 环境 payload 组装、public 版本脱敏
  5. 序列化器：口令只写不回显
  6. ApiEnvironment 沿 parent 链继承证书
"""

import datetime
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from file_management.models import FileAsset
from projects.models import Project

from .crypto import decrypt_passphrase, encrypt_passphrase
from .models import ClientCertificate
from .serializers import ClientCertificateSerializer
from .services import materialize_for_requests, validate_certificate

TEST_PASSPHRASE = 'p@ssw0rd'


# ----------------------------------------------------------------------
# 测试数据构造
# ----------------------------------------------------------------------

def _make_key_and_cert():
    """生成一对自签测试密钥/证书（不依赖 openssl）。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'test.local')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _cert_pem(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key, password: bytes = None) -> bytes:
    encryption = BestAvailableEncryption(password) if password else serialization.NoEncryption()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        encryption,
    )


def _pkcs12_bytes(key, cert, password: bytes = None) -> bytes:
    return pkcs12.serialize_key_and_certificates(
        name=b'test',
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=(
            BestAvailableEncryption(password) if password else serialization.NoEncryption()
        ),
    )


class CryptoTest(SimpleTestCase):
    """口令加解密。"""

    def test_roundtrip(self):
        token = encrypt_passphrase('secret-口令')
        self.assertNotIn('secret', token)
        self.assertEqual(decrypt_passphrase(token), 'secret-口令')

    def test_empty_values(self):
        self.assertEqual(encrypt_passphrase(''), '')
        self.assertEqual(encrypt_passphrase(None), '')
        self.assertEqual(decrypt_passphrase(''), '')
        self.assertEqual(decrypt_passphrase(None), '')

    def test_corrupted_token_degrades_to_empty(self):
        self.assertEqual(decrypt_passphrase('not-a-valid-fernet-token'), '')


class HttprunnerCertChannelTest(SimpleTestCase):
    """httprunner 的 cert 通道。"""

    def test_config_cert_reaches_struct(self):
        from httprunner.config import Config

        config = Config('t').verify(False).cert(('/tmp/a.pem', '/tmp/b.pem'))
        struct = config.struct()
        self.assertEqual(struct.cert, ('/tmp/a.pem', '/tmp/b.pem'))

    def test_config_cert_defaults_to_none(self):
        from httprunner.config import Config

        self.assertIsNone(Config('t').struct().cert)

    def test_request_model_has_cert_slot(self):
        from httprunner.models import TRequest

        request = TRequest(method='GET', url='/x')
        self.assertIn('cert', request.dict())
        self.assertIsNone(request.cert)


class _MediaRootMixin:
    """把 MEDIA_ROOT 指向临时目录，避免测试污染真实存储。"""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='wharttest-cert-test-')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


class MaterializeForRequestsTest(_MediaRootMixin, TestCase):
    """证书材料转换与降级。"""

    def setUp(self):
        self.project = Project.objects.create(name='cert-test-project')
        self.user = User.objects.create_user(username='cert-tester', password='x')
        self.key, self.cert = _make_key_and_cert()

    def _asset(self, name: str, content: bytes) -> FileAsset:
        return FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=SimpleUploadedFile(name, content),
            original_name=name,
            extension='.' + name.rsplit('.', 1)[-1],
            size=len(content),
        )

    def _pem_cert(self, key_content: bytes, with_passphrase: bool = False) -> ClientCertificate:
        certificate = ClientCertificate.objects.create(
            name='pem-cert',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PEM,
            cert_file=self._asset('client.pem', _cert_pem(self.cert)),
            key_file=self._asset('client.key', key_content),
            created_by=self.user,
        )
        if with_passphrase:
            certificate.set_passphrase(TEST_PASSPHRASE)
            certificate.save(update_fields=['passphrase_encrypted'])
        return certificate

    # ---- PEM ----

    def test_pem_without_passphrase_returns_path_tuple(self):
        certificate = self._pem_cert(_key_pem(self.key))
        result = materialize_for_requests(certificate)
        self.assertIsInstance(result, tuple)
        cert_path, key_path = result
        # FileAsset 存储名带 uuid，只校验扩展名与文件真实存在
        self.assertTrue(cert_path.endswith('.pem'))
        self.assertTrue(key_path.endswith('.key'))
        self.assertTrue(os.path.exists(cert_path))
        self.assertTrue(os.path.exists(key_path))

    def test_pem_with_passphrase_returns_combined_pem(self):
        certificate = self._pem_cert(_key_pem(self.key, TEST_PASSPHRASE.encode()), with_passphrase=True)
        result = materialize_for_requests(certificate)

        self.assertIsInstance(result, str)
        with open(result, 'rb') as fh:
            content = fh.read()
        # 合并产物必须同时含证书与"未加密"私钥
        self.assertIn(b'BEGIN CERTIFICATE', content)
        self.assertIn(b'BEGIN PRIVATE KEY', content)
        self.assertNotIn(b'ENCRYPTED', content)
        # 产出的私钥应能被"无口令"加载（否则 requests 用不了）
        key_part = content[content.index(b'-----BEGIN PRIVATE KEY-----'):]
        serialization.load_pem_private_key(key_part, password=None)

    def test_pem_wrong_passphrase_degrades_to_none(self):
        certificate = self._pem_cert(_key_pem(self.key, b'other-secret'), with_passphrase=True)
        self.assertIsNone(materialize_for_requests(certificate))

    # ---- PKCS#12 ----

    def test_pkcs12_with_passphrase_returns_combined_pem(self):
        certificate = ClientCertificate.objects.create(
            name='pfx-cert',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self._asset(
                'client.p12',
                _pkcs12_bytes(self.key, self.cert, TEST_PASSPHRASE.encode()),
            ),
            created_by=self.user,
        )
        certificate.set_passphrase(TEST_PASSPHRASE)
        certificate.save(update_fields=['passphrase_encrypted'])

        result = materialize_for_requests(certificate)
        self.assertIsInstance(result, str)
        with open(result, 'rb') as fh:
            content = fh.read()
        self.assertIn(b'BEGIN CERTIFICATE', content)
        self.assertIn(b'BEGIN PRIVATE KEY', content)

    def test_pkcs12_wrong_passphrase_degrades_to_none(self):
        certificate = ClientCertificate.objects.create(
            name='pfx-bad-pass',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self._asset(
                'client.p12',
                _pkcs12_bytes(self.key, self.cert, TEST_PASSPHRASE.encode()),
            ),
            created_by=self.user,
        )
        certificate.set_passphrase('wrong-pass')
        certificate.save(update_fields=['passphrase_encrypted'])
        self.assertIsNone(materialize_for_requests(certificate))

    # ---- 降级 ----

    def test_missing_file_degrades_to_none(self):
        certificate = self._pem_cert(_key_pem(self.key))
        certificate.key_file.file.delete(save=False)
        self.assertIsNone(materialize_for_requests(certificate))

    def test_none_certificate_returns_none(self):
        self.assertIsNone(materialize_for_requests(None))

    # ---- 校验 ----

    def test_validate_returns_no_warning_for_valid_pkcs12(self):
        certificate = ClientCertificate.objects.create(
            name='pfx-ok',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self._asset('ok.p12', _pkcs12_bytes(self.key, self.cert, TEST_PASSPHRASE.encode())),
            created_by=self.user,
        )
        certificate.set_passphrase(TEST_PASSPHRASE)
        certificate.save(update_fields=['passphrase_encrypted'])
        self.assertEqual(validate_certificate(certificate), [])

    def test_validate_reports_bad_passphrase(self):
        certificate = ClientCertificate.objects.create(
            name='pfx-bad',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self._asset('bad.p12', _pkcs12_bytes(self.key, self.cert, b'right-pass')),
            created_by=self.user,
        )
        certificate.set_passphrase('wrong-pass')
        certificate.save(update_fields=['passphrase_encrypted'])
        warnings = validate_certificate(certificate)
        self.assertTrue(warnings)


class ClientCertificateSerializerTest(_MediaRootMixin, TestCase):
    """序列化器：口令只写不回显。"""

    def setUp(self):
        self.project = Project.objects.create(name='serializer-project')
        self.user = User.objects.create_user(username='serializer-user', password='x')
        self.key, self.cert = _make_key_and_cert()
        self.asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=SimpleUploadedFile('c.p12', _pkcs12_bytes(self.key, self.cert, TEST_PASSPHRASE.encode())),
            original_name='c.p12',
            extension='.p12',
            size=10,
        )

    def _create(self, data):
        serializer = ClientCertificateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save(project=self.project, created_by=self.user)

    def test_create_with_passphrase_never_echoes_it(self):
        instance = self._create({
            'name': 'pfx',
            'cert_type': ClientCertificate.CERT_TYPE_PKCS12,
            'cert_file': self.asset.id,
            'passphrase': TEST_PASSPHRASE,
        })
        payload = ClientCertificateSerializer(instance).data
        self.assertNotIn('passphrase', payload)
        self.assertTrue(payload['has_passphrase'])
        self.assertEqual(instance.get_passphrase(), TEST_PASSPHRASE)

    def test_update_without_passphrase_keeps_existing(self):
        instance = self._create({
            'name': 'pfx',
            'cert_type': ClientCertificate.CERT_TYPE_PKCS12,
            'cert_file': self.asset.id,
            'passphrase': TEST_PASSPHRASE,
        })
        serializer = ClientCertificateSerializer(instance, data={'name': 'pfx-renamed'}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        instance.refresh_from_db()
        self.assertEqual(instance.name, 'pfx-renamed')
        self.assertEqual(instance.get_passphrase(), TEST_PASSPHRASE)

    def test_clear_passphrase(self):
        instance = self._create({
            'name': 'pfx',
            'cert_type': ClientCertificate.CERT_TYPE_PKCS12,
            'cert_file': self.asset.id,
            'passphrase': TEST_PASSPHRASE,
        })
        serializer = ClientCertificateSerializer(instance, data={'clear_passphrase': True}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        instance.refresh_from_db()
        self.assertFalse(instance.has_passphrase)

    def test_pem_requires_both_files(self):
        serializer = ClientCertificateSerializer(data={
            'name': 'bad-pem',
            'cert_type': ClientCertificate.CERT_TYPE_PEM,
            'cert_file': self.asset.id,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('key_file', serializer.errors)


class ApiEnvironmentCertificateTest(_MediaRootMixin, TestCase):
    """环境 payload 组装与证书继承。"""

    def setUp(self):
        from api_environments.models import ApiEnvironment

        self.ApiEnvironment = ApiEnvironment
        self.project = Project.objects.create(name='env-project')
        self.user = User.objects.create_user(username='env-user', password='x')
        self.key, self.cert = _make_key_and_cert()
        self.asset = FileAsset.objects.create(
            project=self.project,
            owner=self.user,
            file=SimpleUploadedFile('c.p12', _pkcs12_bytes(self.key, self.cert, TEST_PASSPHRASE.encode())),
            original_name='c.p12',
            extension='.p12',
            size=10,
        )
        self.certificate = ClientCertificate.objects.create(
            name='env-cert',
            project=self.project,
            cert_type=ClientCertificate.CERT_TYPE_PKCS12,
            cert_file=self.asset,
            created_by=self.user,
        )
        self.certificate.set_passphrase(TEST_PASSPHRASE)
        self.certificate.save(update_fields=['passphrase_encrypted'])

    def test_payload_contains_client_cert(self):
        from api_environments.services import build_environment_payload, public_environment_payload

        env = self.ApiEnvironment.objects.create(
            name='env-a', base_url='https://a.local', project=self.project,
            client_certificate=self.certificate, created_by=self.user,
        )
        payload = build_environment_payload(env)
        self.assertIsInstance(payload['client_cert'], str)
        self.assertNotIn('client_cert', public_environment_payload(payload))

    def test_payload_without_certificate_is_none(self):
        from api_environments.services import build_environment_payload

        env = self.ApiEnvironment.objects.create(
            name='env-b', base_url='https://b.local', project=self.project, created_by=self.user,
        )
        self.assertIsNone(build_environment_payload(env)['client_cert'])

    def test_certificate_inherited_from_parent(self):
        parent = self.ApiEnvironment.objects.create(
            name='parent', base_url='https://p.local', project=self.project,
            client_certificate=self.certificate, created_by=self.user,
        )
        child = self.ApiEnvironment.objects.create(
            name='child', base_url='https://c.local', project=self.project,
            parent=parent, created_by=self.user,
        )
        self.assertEqual(child.get_client_certificate().id, self.certificate.id)
