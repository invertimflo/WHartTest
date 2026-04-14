<template>
  <div class="api-testing-container">
    <a-spin :loading="loading" class="h-full">
      <div v-if="testcase" class="h-full overflow-auto p-4">
        <TestCaseHistoryReports
          :testcase-id="Number(id)"
          :testcase-name="testcase.name"
          :pagination="pagination"
          @update:pagination="pagination = $event"
          @back="router.push('/api-testing')"
          @view-report="(report) => router.push({ name: 'ApiTestReportDetail', params: { id: report.id } })"
        />
      </div>
      <div v-else-if="!loading" class="flex items-center justify-center h-full text-gray-500">
        未找到测试用例
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/store/projectStore'
import { testcaseService } from '../services/testcaseService'
import type { ApiTestCase } from '../types/testcase'
import TestCaseHistoryReports from '../components/testcases/TestCaseHistoryReports.vue'

const props = defineProps<{ id: string | number }>()
const router = useRouter()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)
const testcase = ref<ApiTestCase | null>(null)
const loading = ref(false)

const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showTotal: true,
  showJumper: true,
  showPageSize: true,
})

onMounted(async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const res = await testcaseService.get(projectId.value, Number(props.id))
    if (res.success && res.data) testcase.value = res.data as ApiTestCase
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
