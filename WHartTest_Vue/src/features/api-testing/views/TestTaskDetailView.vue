<template>
  <div class="api-testing-container">
    <a-spin :loading="loading" class="h-full">
      <div v-if="suite" class="h-full overflow-auto p-4">
        <TestTaskExecutionHistory :suite="suite" :project-id="projectId!" />
      </div>
      <div v-else-if="!loading" class="flex items-center justify-center h-full text-gray-500">
        {{ pageText.notFound }}
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppI18n } from '@/composables/useAppI18n'
import { useProjectStore } from '@/store/projectStore'
import { testTaskService } from '../services/testTaskService'
import type { ApiTestTaskSuite } from '../types/testtask'
import TestTaskExecutionHistory from '../components/testtasks/TestTaskExecutionHistory.vue'

const props = defineProps<{ id: string | number }>()
const router = useRouter()
const { isEnglish } = useAppI18n()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)
const suite = ref<ApiTestTaskSuite | null>(null)
const loading = ref(false)

const pageText = computed(() => isEnglish.value
  ? { notFound: 'Task not found' }
  : { notFound: '未找到任务' }
)

onMounted(async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await testTaskService.getSuite(projectId.value, Number(props.id))
    if (res.success && res.data) suite.value = res.data as ApiTestTaskSuite
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.api-testing-container {
  height: 100%;
  background-color: rgb(17, 24, 39);
  border-radius: 8px;
  overflow: hidden;
}
</style>
