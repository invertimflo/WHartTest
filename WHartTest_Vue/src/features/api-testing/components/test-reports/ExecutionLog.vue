<template>
  <div class="bg-gray-900/50 backdrop-blur-sm rounded-lg border border-gray-700/30">
    <div class="px-4 py-3 border-b border-gray-700/30">
      <span class="text-gray-300 text-base font-medium">执行日志</span>
    </div>
    <div class="p-4">
      <div class="bg-gray-800/30 rounded-lg border border-gray-700/30 transition-all duration-200 hover:bg-gray-800/50 hover:border-gray-600/50">
        <pre class="p-4 text-sm font-mono text-gray-300 overflow-x-auto whitespace-pre-wrap">{{ report?.summary?.log }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TestReportResponse } from './TestReportDetail.vue'

defineProps<{
  report: TestReportResponse | null
}>()
</script>

<style scoped>
pre {
  scrollbar-width: none;
  -ms-overflow-style: none;
  &::-webkit-scrollbar {
    display: none;
  }
}
</style> 