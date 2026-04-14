<template>
  <div class="api-testing-container">
    <a-spin :loading="loading" class="h-full">
      <div v-if="report" class="h-full overflow-auto p-4">
        <ReportHeader :report="(report as any)" :loading="loading" @back="router.push('/api-testing')" @export="handleExportReport" />
        <BasicInfo :report="(report as any)" />
        <StatusCards :report="(report as any)" :total-steps="totalSteps" :fail-rate="failRate" :error-rate="errorRate" />
        <ExecutionSteps :report="(report as any)" />
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
import { Message } from '@arco-design/web-vue'
import { useAppI18n } from '@/composables/useAppI18n'
import { useProjectStore } from '@/store/projectStore'
import { testReportService } from '../services/testReportService'
import type { ApiTestReport } from '../types/testcase'
import ReportHeader from '../components/test-reports/ReportHeader.vue'
import BasicInfo from '../components/test-reports/BasicInfo.vue'
import StatusCards from '../components/test-reports/StatusCards.vue'
import ExecutionSteps from '../components/test-reports/ExecutionSteps.vue'

const props = defineProps<{ id: string | number }>()
const router = useRouter()
const { isEnglish } = useAppI18n()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)
const report = ref<ApiTestReport | null>(null)
const loading = ref(false)

const totalSteps = computed(() => {
  if (!report.value) return 0
  return (report.value.success_count || 0) + (report.value.fail_count || 0) + (report.value.error_count || 0)
})
const failRate = computed(() => totalSteps.value ? Math.round(((report.value?.fail_count || 0) / totalSteps.value) * 100) : 0)
const errorRate = computed(() => totalSteps.value ? Math.round(((report.value?.error_count || 0) / totalSteps.value) * 100) : 0)

const pageText = computed(() => isEnglish.value
  ? { notFound: 'Report not found' }
  : { notFound: '未找到报告' }
)

const handleExportReport = () => {
  Message.info('导出功能开发中...')
}

onMounted(async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await testReportService.get(projectId.value, Number(props.id))
    if (res.success && res.data) report.value = res.data as ApiTestReport
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
