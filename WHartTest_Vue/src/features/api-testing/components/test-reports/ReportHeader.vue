<template>
  <div class="bg-gray-800/50 backdrop-blur-sm border-b border-gray-700/50 sticky top-0 z-10">
    <div class="px-6 py-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <a-button class="custom-back-button" @click="$emit('back')">
            <template #icon><icon-left /></template>
            返回
          </a-button>
          <div>
            <h2 class="text-xl font-medium text-gray-100">{{ report?.name }}</h2>
            <div class="flex items-center gap-2 mt-1">
              <icon-code class="text-gray-400" />
              <span class="text-gray-400">{{ report?.testcase_name }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <div class="flex flex-col items-end">
            <a-tag :color="getStatusColor(report?.status)" size="medium">
              {{ getStatusText(report?.status) }}
            </a-tag>
            <span class="text-xs text-gray-400 mt-1">执行时长: {{ formatDuration(report?.duration) }}</span>
          </div>
          <a-button type="outline" status="success" @click="$emit('export')">
            <template #icon><icon-download /></template>
            导出报告
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { IconLeft, IconCode, IconDownload } from '@arco-design/web-vue/es/icon'
import { formatDuration } from '@/utils/formatters'
import type { TestReportResponse } from './TestReportDetail.vue'

defineProps<{
  report: TestReportResponse | null
  loading: boolean
}>()

defineEmits<{
  (e: 'back'): void
  (e: 'export'): void
}>()

const getStatusColor = (status?: string) => {
  const statusMap: Record<string, string> = {
    success: 'green',
    failure: 'red',
    error: 'orange',
  }
  return statusMap[status || ''] || 'gray'
}

const getStatusText = (status?: string) => {
  const statusMap: Record<string, string> = {
    success: '成功',
    failure: '失败',
    error: '错误',
  }
  return statusMap[status || ''] || '未知'
}
</script>

<style scoped>
@reference "tailwindcss";
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