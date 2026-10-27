# 「切换页面URL」默认改为开启
#
# 背景：switch_step_open_url 字段自初始版本引入后从未被执行链路读取，
# 存量值不具备实际语义（基本都是建步骤时自动填入的 False）。
# 本次改为默认开启以匹配「执行用例时按页面步骤自动跳转」的预期，
# 存量数据一并置 True，避免老用例升级后仍不跳转。
from django.db import migrations, models


def enable_switch_for_existing(apps, schema_editor):
    UiCaseStepsDetailed = apps.get_model('ui_automation', 'UiCaseStepsDetailed')
    UiCaseStepsDetailed.objects.filter(switch_step_open_url=False).update(
        switch_step_open_url=True
    )


def disable_switch_for_existing(apps, schema_editor):
    # 反向迁移：恢复历史默认值（仅回滚字段默认语义，不做数据还原）
    UiCaseStepsDetailed = apps.get_model('ui_automation', 'UiCaseStepsDetailed')
    UiCaseStepsDetailed.objects.filter(switch_step_open_url=True).update(
        switch_step_open_url=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0025_uienvironmentconfig_client_certificate_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uicasestepsdetailed',
            name='switch_step_open_url',
            field=models.BooleanField(default=True, verbose_name='切换URL'),
        ),
        migrations.RunPython(enable_switch_for_existing, disable_switch_for_existing),
    ]
