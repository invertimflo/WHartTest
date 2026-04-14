import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { ApiEnvironment } from '../types/environment';
import { environmentService } from '../services/environmentService';

export const useEnvironmentStore = defineStore('apiEnvironment', () => {
  const environments = ref<ApiEnvironment[]>([]);
  const currentEnvironmentId = ref<number | null>(null);
  const loading = ref(false);

  const currentEnvironment = computed(() =>
    environments.value.find((e) => e.id === currentEnvironmentId.value) ?? null,
  );

  const environmentOptions = computed(() =>
    environments.value
      .filter((e) => e.is_active)
      .map((e) => ({ label: e.name, value: e.id })),
  );

  async function fetchEnvironments(projectId: number) {
    loading.value = true;
    try {
      const res = await environmentService.list(projectId);
      if (res.success && res.data) {
        environments.value = Array.isArray(res.data) ? res.data : [];
      }
    } finally {
      loading.value = false;
    }
  }

  function setCurrentEnvironment(id: number | null) {
    currentEnvironmentId.value = id;
  }

  function $reset() {
    environments.value = [];
    currentEnvironmentId.value = null;
    loading.value = false;
  }

  return {
    environments,
    currentEnvironmentId,
    currentEnvironment,
    environmentOptions,
    loading,
    fetchEnvironments,
    setCurrentEnvironment,
    $reset,
  };
});
