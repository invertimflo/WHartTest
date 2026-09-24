from django.contrib import admin

from .models import ClientCertificate


@admin.register(ClientCertificate)
class ClientCertificateAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'cert_type', 'has_passphrase', 'is_active', 'created_at')
    list_filter = ('cert_type', 'is_active', 'project')
    search_fields = ('name', 'description')
