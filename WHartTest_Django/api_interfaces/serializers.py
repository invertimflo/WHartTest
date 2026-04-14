from rest_framework import serializers
from .models import ApiInterface, ApiInterfaceResult


class ApiInterfaceModuleInfoSerializer(serializers.Serializer):
    """Lightweight module serializer for embedding in interface detail."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent = serializers.IntegerField(source='parent_id', allow_null=True)


class ApiInterfaceSerializer(serializers.ModelSerializer):
    module_info = ApiInterfaceModuleInfoSerializer(source='module', read_only=True)

    class Meta:
        model = ApiInterface
        fields = '__all__'
        read_only_fields = ['project', 'created_by', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Strip module_info from list responses, only include in detail
        request = self.context.get('request')
        if request and not self.context.get('view', {}).kwargs.get('pk'):
            data.pop('module_info', None)
        return data

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        name = attrs.get('name')
        project = attrs.get('project') or (instance.project if instance else None)

        if name and project:
            query = ApiInterface.objects.filter(name=name, project=project)
            if instance:
                query = query.exclude(pk=instance.pk)
            if query.exists():
                raise serializers.ValidationError(
                    {"name": [f"An interface named '{name}' already exists in this project."]}
                )

        module = attrs.get('module')
        if module and project and module.project_id != project.id:
            raise serializers.ValidationError(
                {"module": "Module must belong to the same project."}
            )

        setup_hooks = attrs.get('setup_hooks', [])
        if not isinstance(setup_hooks, list):
            raise serializers.ValidationError({"setup_hooks": "Must be a list."})

        teardown_hooks = attrs.get('teardown_hooks', [])
        if not isinstance(teardown_hooks, list):
            raise serializers.ValidationError({"teardown_hooks": "Must be a list."})

        variables = attrs.get('variables', {})
        if not isinstance(variables, dict):
            raise serializers.ValidationError({"variables": "Must be a dict."})

        validators = attrs.get('validators', [])
        if not isinstance(validators, list):
            raise serializers.ValidationError({"validators": "Must be a list."})

        supported_comparators = [
            'eq', 'ne', 'gt', 'ge', 'gte', 'lt', 'le', 'lte',
            'contains', 'contained_by', 'type_match', 'regex_match',
            'startswith', 'endswith', 'str_eq',
            'length_equal', 'length_greater_than', 'length_less_than',
            'length_greater_or_equals', 'length_less_or_equals',
        ]

        for validator in validators:
            if not isinstance(validator, dict):
                raise serializers.ValidationError({"validators": "Each validator must be a dict."})
            if "check" in validator and "expect" in validator:
                continue
            valid_format = False
            for key in validator.keys():
                if key in supported_comparators:
                    if not isinstance(validator[key], list) or len(validator[key]) != 2:
                        raise serializers.ValidationError({
                            "validators": f"Validator '{key}' must be a list of [field, expected_value]."
                        })
                    valid_format = True
                    break
            if not valid_format:
                raise serializers.ValidationError({
                    "validators": (
                        f"Validator must use a supported comparator: "
                        f"{', '.join(supported_comparators)}, or use check/expect format."
                    )
                })

        extract = attrs.get('extract', {})
        if not isinstance(extract, dict):
            raise serializers.ValidationError({"extract": "Must be a dict."})

        return attrs


class ApiInterfaceResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiInterfaceResult
        fields = '__all__'
        read_only_fields = ['executed_by', 'executed_at']
