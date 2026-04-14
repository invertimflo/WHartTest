<template>
  <div class="bg-gray-900/50 backdrop-blur-sm rounded-lg border border-gray-700/30">
    <div class="px-4 pt-2 border-b border-gray-700/30">
      <h3 class="text-lg font-medium text-gray-200 -mb-1">配置信息</h3>
    </div>
    <div class="px-4">
      <div class="space-y-3">
        <div class="config-item">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <p class="text-sm text-gray-400">配置变量</p>
              <span v-if="Object.keys(report?.summary?.in_out?.config_vars || {}).length" class="text-xs text-gray-500">
                ({{ Object.keys(report?.summary?.in_out?.config_vars || {}).length }}个)
              </span>
            </div>
            <div class="flex items-center gap-2">
              <a-button 
                v-if="Object.keys(report?.summary?.in_out?.config_vars || {}).length" 
                type="text" 
                size="mini" 
                @click="toggleDrawer('config_vars')"
              >
                <template #icon><icon-expand class="text-gray-400" /></template>
                查看全部
              </a-button>
              <a-tooltip position="left">
                <template #content>
                  <div class="text-sm">
                    <p>测试执行时的环境配置变量</p>
                  </div>
                </template>
                <icon-info-circle class="text-gray-400 cursor-help" />
              </a-tooltip>
            </div>
          </div>
          <div v-if="Object.keys(report?.summary?.in_out?.config_vars || {}).length" class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
            <div class="space-y-2 max-h-[200px] overflow-y-auto">
              <div v-for="(value, key, index) in report?.summary?.in_out?.config_vars" :key="key"
                   v-show="index < 3"
                   class="flex items-center justify-between px-2 py-1 rounded bg-gray-800/30">
                <span class="text-sm text-gray-400">{{ key }}</span>
                <div class="flex items-center gap-2">
                  <span class="text-sm text-blue-400 font-mono" :title="value">{{ value && typeof value === 'string' ? (value.length > 20 ? value.substring(0, 20) + '...' : value) : value }}</span>
                  <a-button type="text" size="mini" @click="copyToClipboard(value)">
                    <template #icon><icon-copy class="text-gray-400 hover:text-blue-400" /></template>
                  </a-button>
                </div>
              </div>
              <div v-if="Object.keys(report?.summary?.in_out?.config_vars || {}).length > 3" class="text-center text-xs text-gray-500 mt-2">
                显示前3项，共{{ Object.keys(report?.summary?.in_out?.config_vars || {}).length }}项
              </div>
            </div>
          </div>
          <div v-else class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
            <p class="text-sm text-gray-500 text-center">无配置变量</p>
          </div>
        </div>
        <div class="config-item">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <p class="text-sm text-gray-400">提取变量</p>
              <span v-if="Object.keys(report?.summary?.in_out?.export_vars || {}).length" class="text-xs text-gray-500">
                ({{ Object.keys(report?.summary?.in_out?.export_vars || {}).length }}个)
              </span>
            </div>
            <div class="flex items-center gap-2">
              <a-button 
                v-if="Object.keys(report?.summary?.in_out?.export_vars || {}).length" 
                type="text" 
                size="mini" 
                @click="toggleDrawer('export_vars')"
              >
                <template #icon><icon-expand class="text-gray-400" /></template>
                查看全部
              </a-button>
              <a-tooltip position="left">
                <template #content>
                  <div class="text-sm">
                    <p>测试执行过程中从响应中提取的变量</p>
                  </div>
                </template>
                <icon-info-circle class="text-gray-400 cursor-help" />
              </a-tooltip>
            </div>
          </div>
          <div v-if="Object.keys(report?.summary?.in_out?.export_vars || {}).length" class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
            <div class="space-y-2 max-h-[200px] overflow-y-auto">
              <div v-for="(value, key, index) in report?.summary?.in_out?.export_vars" :key="key"
                   v-show="index < 3"
                   class="flex items-center justify-between px-2 py-1 rounded bg-gray-800/30">
                <span class="text-sm text-gray-400">{{ key }}</span>
                <div class="flex items-center gap-2">
                  <span class="text-sm text-green-400 font-mono" :title="value">{{ value && typeof value === 'string' ? (value.length > 20 ? value.substring(0, 20) + '...' : value) : value }}</span>
                  <a-button type="text" size="mini" @click="copyToClipboard(value)">
                    <template #icon><icon-copy class="text-gray-400 hover:text-green-400" /></template>
                  </a-button>
                </div>
              </div>
              <div v-if="Object.keys(report?.summary?.in_out?.export_vars || {}).length > 3" class="text-center text-xs text-gray-500 mt-2">
                显示前3项，共{{ Object.keys(report?.summary?.in_out?.export_vars || {}).length }}项
              </div>
            </div>
          </div>
          <div v-else class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
            <p class="text-sm text-gray-500 text-center">无提取变量</p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 抽屉组件 - 用于显示完整的变量信息 -->
  <a-drawer
    :visible="drawerVisible"
    :width="800"
    @cancel="drawerVisible = false"
    :title="currentDrawerType === 'config_vars' ? '配置变量详情' : '提取变量详情'"
    :footer="false"
    class="custom-drawer"
    :mask="true"
    :mask-style="{ backgroundColor: 'transparent' }"
    :mask-closable="true"
    @close="drawerVisible = false"
  >
    <div class="p-6">
      <div v-if="currentDrawerType === 'config_vars' && Object.keys(report?.summary?.in_out?.config_vars || {}).length" class="space-y-3">
        <div v-for="(value, key) in report?.summary?.in_out?.config_vars" :key="key" class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
          <div class="flex items-start gap-3">
            <div class="flex-1">
              <div class="text-sm text-gray-400">{{ key }}</div>
              <div class="mt-2 bg-gray-900/50 p-2 rounded border border-gray-700/30">
                <div class="text-sm text-blue-400 font-mono break-all">{{ value }}</div>
              </div>
            </div>
            <a-button type="text" size="mini" @click="copyToClipboard(value)">
              <template #icon><icon-copy class="text-gray-400 hover:text-blue-400" /></template>
            </a-button>
          </div>
        </div>
      </div>
      <div v-else-if="currentDrawerType === 'export_vars' && Object.keys(report?.summary?.in_out?.export_vars || {}).length" class="space-y-3">
        <div v-for="(value, key) in report?.summary?.in_out?.export_vars" :key="key" class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30">
          <div class="flex items-start gap-3">
            <div class="flex-1">
              <div class="text-sm text-gray-400">{{ key }}</div>
              <div class="mt-2 bg-gray-900/50 p-2 rounded border border-gray-700/30">
                <div class="text-sm text-green-400 font-mono break-all">{{ value }}</div>
              </div>
            </div>
            <a-button type="text" size="mini" @click="copyToClipboard(value)">
              <template #icon><icon-copy class="text-gray-400 hover:text-green-400" /></template>
            </a-button>
          </div>
        </div>
      </div>
      <div v-else class="text-center text-gray-400">
        无数据
      </div>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { 
  IconInfoCircle, 
  IconCopy, 
  IconExpand 
} from '@arco-design/web-vue/es/icon'
import { Message } from '@arco-design/web-vue'
import type { TestReportResponse } from './TestReportDetail.vue'

defineProps<{
  report: TestReportResponse | null
}>()

// 抽屉组件状态控制
const drawerVisible = ref(false)
const currentDrawerType = ref<'config_vars' | 'export_vars' | null>(null)

/**
 * 切换抽屉的显示状态，并设置要显示的数据类型
 * @param type 数据类型（配置变量或提取变量）
 */
const toggleDrawer = (type: 'config_vars' | 'export_vars') => {
  currentDrawerType.value = type
  drawerVisible.value = true
}

/**
 * 将文本复制到剪贴板
 * @param text 要复制的文本
 */
const copyToClipboard = async (text: string) => {
  try {
    if (text === null || text === undefined) {
      Message.warning('复制内容为空')
      return
    }
    await navigator.clipboard.writeText(String(text))
    Message.success('复制成功')
  } catch (err) {
    Message.error('复制失败')
  }
}
</script>

<style scoped>
@reference "tailwindcss";
pre {
  scrollbar-width: none;
  -ms-overflow-style: none;
  &::-webkit-scrollbar {
    display: none;
  }
}

.config-item {
  @apply transition-all duration-200;

  &:hover {
    .bg-gray-800\/30 {
      @apply bg-gray-800/50 border-gray-600/50;
    }
  }
}

/* 自定义滚动条样式 */
.overflow-y-auto {
  scrollbar-width: thin;
  scrollbar-color: rgba(107, 114, 128, 0.3) transparent;
  
  &::-webkit-scrollbar {
    width: 4px;
  }
  
  &::-webkit-scrollbar-track {
    background: transparent;
  }
  
  &::-webkit-scrollbar-thumb {
    background-color: rgba(107, 114, 128, 0.3);
    border-radius: 4px;
  }
}

/* 自定义抽屉组件样式 */
:deep(.custom-drawer) {
  .arco-drawer-container {
    @apply !bg-transparent;
  }

  .arco-drawer-header {
    @apply !bg-gray-900 !border-b !border-gray-700/30;
    background-color: rgb(31, 41, 55) !important;
  }

  .arco-drawer-body {
    @apply !bg-gray-900;
    background-color: rgb(31, 41, 55) !important;
  }

  .arco-drawer-content {
    @apply !bg-gray-900;
    background-color: rgb(31, 41, 55) !important;
  }

  .arco-drawer-wrapper {
    @apply !bg-gray-900;
    background-color: rgb(31, 41, 55) !important;
  }
}

/* 全局样式覆盖 - 确保抽屉组件样式具有最高优先级 */
:global(.arco-drawer-container) {
  background-color: transparent !important;
}

:global(.arco-drawer-header),
:global(.arco-drawer-body),
:global(.arco-drawer-content),
:global(.arco-drawer-wrapper) {
  background-color: rgb(31, 41, 55) !important;
}
</style> 