from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ClientCertificatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "client_certificates"
    verbose_name = _("Client Certificates")
