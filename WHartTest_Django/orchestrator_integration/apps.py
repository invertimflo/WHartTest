from django.apps import AppConfig


class OrchestratorIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orchestrator_integration'

    def ready(self):
        """LLM 配置变更时立刻失效进程内短缓存。

        对话热路径上会给 `LLMConfig.objects.get(is_active=True)` 加 30s TTL 缓存，
        这里在保存/删除时主动失效，避免管理员切换模型后需要等待缓存过期。
        """
        from django.db.models.signals import post_delete, post_save

        def _invalidate_llm_config_cache(sender, **kwargs):
            try:
                from orchestrator_integration.agent_loop_view import (
                    _invalidate_llm_config_cache as _invalidate,
                )

                _invalidate()
            except Exception:
                # 缓存失效失败不应影响配置保存本身
                pass

        try:
            from langgraph_integration.models import LLMConfig
        except Exception:
            return

        post_save.connect(
            _invalidate_llm_config_cache,
            sender=LLMConfig,
            dispatch_uid="orchestrator_invalidate_llm_config_on_save",
        )
        post_delete.connect(
            _invalidate_llm_config_cache,
            sender=LLMConfig,
            dispatch_uid="orchestrator_invalidate_llm_config_on_delete",
        )
