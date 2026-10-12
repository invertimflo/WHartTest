from rest_framework import serializers
from .models import ScheduledTask, TaskExecution
from ui_automation.models import UiTestCase


class ScheduledTaskSerializer(serializers.ModelSerializer):
    schedule_display = serializers.SerializerMethodField()
    creator_name = serializers.SerializerMethodField()
    test_suite_name = serializers.SerializerMethodField()
    env_config_name = serializers.SerializerMethodField()
    ui_testcase_ids = serializers.PrimaryKeyRelatedField(
        source='ui_testcases', many=True,
        queryset=UiTestCase.objects.all(), required=False
    )

    class Meta:
        model = ScheduledTask
        fields = [
            'id', 'name', 'description', 'project', 'module',
            'execution_target', 'schedule_type', 'once_datetime',
            'daily_time', 'weekly_days', 'weekly_time', 'hourly_minute',
            'retry_enabled', 'retry_count', 'retry_interval',
            'status', 'last_run_at', 'creator', 'creator_name',
            'schedule_display', 'created_at', 'updated_at',
            'test_suite', 'test_suite_name', 'ui_testcase_ids',
            'actuator_id', 'env_config', 'env_config_name',
        ]
        read_only_fields = [
            'project', 'status', 'last_run_at', 'creator', 'creator_name',
            'schedule_display', 'created_at', 'updated_at',
            'test_suite_name', 'env_config_name',
        ]

    def get_schedule_display(self, obj):
        return obj.get_schedule_display_text()

    def get_creator_name(self, obj):
        if obj.creator:
            return obj.creator.get_full_name() or obj.creator.username
        return None

    def get_test_suite_name(self, obj):
        if obj.test_suite:
            return obj.test_suite.name
        return None

    def get_env_config_name(self, obj):
        if obj.env_config:
            return obj.env_config.name
        return None

    def validate_name(self, value):
        if len(value) > 50:
            raise serializers.ValidationError('任务名称最大长度为50字符')
        return value

    def validate(self, attrs):
        schedule_type = attrs.get('schedule_type', getattr(self.instance, 'schedule_type', None))
        module = attrs.get('module', getattr(self.instance, 'module', None))

        # 模块关联验证
        if module == ScheduledTask.TaskModule.TEST_SUITE:
            if not attrs.get('test_suite') and not getattr(self.instance, 'test_suite', None):
                raise serializers.ValidationError({'test_suite': '测试套件模块必须关联一个测试套件'})

        # UI 环境必须属于当前项目（project 由视图按 URL 注入，为只读字段）
        env_config = attrs.get('env_config', getattr(self.instance, 'env_config', None))
        project_id = getattr(self.instance, 'project_id', None)
        if project_id is None:
            view = self.context.get('view')
            if view is not None:
                project_id = view.kwargs.get('project_pk')
        if env_config is not None and project_id is not None:
            if str(env_config.project_id) != str(project_id):
                raise serializers.ValidationError({'env_config': 'UI 环境必须属于当前项目'})

        if schedule_type == ScheduledTask.ScheduleType.ONCE:
            if not attrs.get('once_datetime') and not getattr(self.instance, 'once_datetime', None):
                raise serializers.ValidationError({'once_datetime': '仅执行一次时必须指定执行时间'})
        elif schedule_type == ScheduledTask.ScheduleType.DAILY:
            if not attrs.get('daily_time') and not getattr(self.instance, 'daily_time', None):
                raise serializers.ValidationError({'daily_time': '每天执行时必须指定时间'})
        elif schedule_type == ScheduledTask.ScheduleType.WEEKLY:
            weekly_days = attrs.get('weekly_days', getattr(self.instance, 'weekly_days', None))
            if not weekly_days:
                raise serializers.ValidationError({'weekly_days': '每周执行时必须选择至少一天'})
            if not attrs.get('weekly_time') and not getattr(self.instance, 'weekly_time', None):
                raise serializers.ValidationError({'weekly_time': '每周执行时必须指定时间'})
        elif schedule_type == ScheduledTask.ScheduleType.HOURLY:
            hourly_minute = attrs.get('hourly_minute', getattr(self.instance, 'hourly_minute', None))
            if hourly_minute is None:
                raise serializers.ValidationError({'hourly_minute': '每小时执行时必须指定分钟数'})

        return attrs


class TaskExecutionSerializer(serializers.ModelSerializer):
    duration = serializers.SerializerMethodField()

    class Meta:
        model = TaskExecution
        fields = [
            'id', 'execution_id', 'task', 'trigger_type', 'status',
            'started_at', 'finished_at', 'duration', 'log', 'error_message',
        ]
        read_only_fields = fields

    def get_duration(self, obj):
        return obj.duration_display
