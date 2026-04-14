<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconArrowLeft } from '@arco-design/web-vue/es/icon'
import { testcaseService } from '../../services/testcaseService'
import type { ApiTestCase } from '../../types/testcase'
import { useProjectStore } from '@/store/projectStore'
import TestCaseHistoryReports from './TestCaseHistoryReports.vue'

const props = defineProps<{
  testcaseId: number
}>()

const emit = defineEmits(['back', 'view-report'])

const projectStore = useProjectStore()
const loading = ref(false)
const testcase = ref<ApiTestCase | null>(null)

const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showTotal: true,
  showJumper: true,
  showPageSize: true
})

const fetchTestCase = async () => {
  if (!props.testcaseId || !projectStore.currentProjectId) return
  try {
    loading.value = true
    const res = await testcaseService.get(projectStore.currentProjectId, props.testcaseId)
    if (res.success && res.data) {
      testcase.value = res.data as ApiTestCase
    } else {
      throw new Error(res.error || '获取测试用例信息失败')
    }
  } catch (error) {
    console.error('获取测试用例信息失败:', error)
    Message.error(error instanceof Error ? error.message : '获取测试用例信息失败')
  } finally {
    loading.value = false
  }
}

const handleBack = () => {
  emit('back')
}

const handlePageChange = (current: number) => {
  pagination.value.current = current
}

const handleViewReport = (report: any) => {
  emit('view-report', report)
}

watch(() => props.testcaseId, () => {
  fetchTestCase()
})

onMounted(() => {
  fetchTestCase()
})
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <!-- 头部 -->
    <div class="report-card px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <a-button class="custom-back-button" @click="handleBack">
            <template #icon>
              <icon-arrow-left />
            </template>
            返回
          </a-button>
          <h2 class="report-title">
            测试用例「{{ testcase?.name || '加载中...' }}」历史报告
          </h2>
        </div>
      </div>
    </div>

    <!-- 报告列表 -->
    <div class="flex-1 report-card overflow-hidden">
      <div class="h-full p-6">
        <TestCaseHistoryReports
          v-if="testcase"
          ref="historyReportsRef"
          :testcase-id="testcase.id!"
          :pagination="pagination"
          @update:pagination="(val) => pagination = val"
          @view-report="handleViewReport"
        />
      </div>
    </div>

    <!-- 分页区域 -->
    <div class="report-card px-6 py-5">
      <a-pagination
        v-model:current="pagination.current"
        v-model:pageSize="pagination.pageSize"
        :total="pagination.total"
        show-total
        show-jumper
        show-page-size
        class="flex justify-end"
        @change="handlePageChange"
        @page-size-change="handlePageChange"
      />
    </div>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.report-card {
  @apply bg-gray-800/50 rounded-lg;
}

.report-title {
  @apply text-lg font-medium text-gray-100;
}

.custom-back-button {
  @apply !bg-gray-700/50 !border-gray-600 !text-gray-300;

  &:hover {
    @apply !bg-gray-700 !border-gray-500 !text-gray-200;
  }

  &:active {
    @apply !bg-gray-800 !border-gray-600 !text-gray-300;
  }
}
</style>
