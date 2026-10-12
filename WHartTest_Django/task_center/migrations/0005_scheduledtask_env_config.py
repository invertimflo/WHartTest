from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0025_uienvironmentconfig_client_certificate_and_more'),
        ('task_center', '0004_remove_executing_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduledtask',
            name='env_config',
            field=models.ForeignKey(
                blank=True,
                help_text='模块为"UI自动化"时可选：绑定环境后，执行时自动使用该环境配置（含基础 URL、登录态与客户端证书），客户端证书随任务自动下发到执行器',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='scheduled_tasks',
                to='ui_automation.uienvironmentconfig',
                verbose_name='UI 环境',
            ),
        ),
    ]
