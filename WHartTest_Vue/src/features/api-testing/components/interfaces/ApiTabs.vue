<script setup lang="ts">
import { computed } from 'vue'
import { IconClose, IconPlus, IconSend } from '@arco-design/web-vue/es/icon'
import { useApiTabsStore } from '../../stores/apiTabsStore'
import type { ApiInterface } from '../../services/interfaceService'

const props = defineProps<{
  currentInterface?: ApiInterface
}>()

const emit = defineEmits<{
  'tab-change': [tabId: string]
}>()

const tabsStore = useApiTabsStore()

// 计算属性
const tabs = computed(() => tabsStore.tabs)
const activeTabId = computed(() => tabsStore.activeTabId)

// 切换页签
const handleTabClick = (tabId: string) => {
  tabsStore.activateTab(tabId)
  emit('tab-change', tabId)
}

// 关闭页签
const handleCloseTab = (e: Event, tabId: string) => {
  e.stopPropagation()
  tabsStore.removeTab(tabId)
}


// 获取页签显示名称
const getTabLabel = (tab: any) => {
  const method = tab.method || 'GET'
  const name = tab.name || '新接口'
  return `${method} ${name}`
}

// 获取页签颜色
const getMethodColor = (method: string) => {
  switch (method?.toUpperCase()) {
    case 'GET': return 'text-blue-500'
    case 'POST': return 'text-green-500'
    case 'PUT': return 'text-orange-500'
    case 'DELETE': return 'text-red-500'
    case 'PATCH': return 'text-purple-500'
    default: return 'text-gray-400'
  }
}
</script>

<template>
  <!-- 独立的卡片样式容器 -->
  <div class="api-tabs-card mx-0.5 mb-2 bg-gray-800 rounded-lg shadow-lg overflow-hidden">
    <div class="px-2 py-2">
      <div class="flex items-center gap-2 overflow-x-auto scrollbar-thin">
        <!-- 页签列表 -->
        <div
          v-for="tab in tabs"
          :key="tab.id"
          class="group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer min-w-max transition-all border"
          :class="tab.id === activeTabId
            ? 'bg-blue-500/20 border-blue-500/50 text-blue-400'
            : 'bg-gray-700/30 border-gray-700 text-gray-300 hover:bg-gray-700/50 hover:border-gray-600'"
          @click="handleTabClick(tab.id)"
        >
          <!-- 请求方法标签 -->
          <span
            class="text-xs font-bold"
            :class="tab.id === activeTabId ? 'opacity-100' : getMethodColor(tab.method)"
          >
            {{ tab.method }}
          </span>
          
          <!-- 接口名称 -->
          <span
            class="text-sm max-w-[180px] truncate"
            :class="tab.id === activeTabId ? 'font-medium' : ''"
            :title="tab.name"
          >
            {{ tab.name }}
          </span>
          
          <!-- 响应状态指示器 -->
          <div v-if="tab.response?.status" class="flex items-center">
            <div
              class="w-2 h-2 rounded-full animate-pulse"
              :class="{
                'bg-green-500': tab.response.status >= 200 && tab.response.status < 300,
                'bg-red-500': tab.response.status >= 400,
                'bg-yellow-500': tab.response.status >= 300 && tab.response.status < 400
              }"
            ></div>
          </div>
          
          <!-- 关闭按钮 - 只显示X -->
          <icon-close
            class="ml-1 w-3.5 h-3.5 cursor-pointer transition-all"
            :class="tab.id === activeTabId
              ? 'opacity-60 hover:opacity-100 hover:text-red-400'
              : 'opacity-0 group-hover:opacity-60 group-hover:hover:opacity-100 group-hover:hover:text-red-400'"
            @click="handleCloseTab($event, tab.id)"
            title="关闭页签"
          />
        </div>
        
        <!-- 提示文本（当没有页签时显示） -->
        <div v-if="tabs.length === 0" class="text-gray-500 text-sm py-1 px-3">
          请从左侧选择或创建接口开始调试
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
/* 自定义滚动条样式 */
.scrollbar-thin {
  scrollbar-width: thin;
  scrollbar-color: rgba(156, 163, 175, 0.3) transparent;
}

.scrollbar-thin::-webkit-scrollbar {
  height: 6px;
}

.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}

.scrollbar-thin::-webkit-scrollbar-thumb {
  background-color: rgba(156, 163, 175, 0.3);
  border-radius: 3px;
}

.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background-color: rgba(156, 163, 175, 0.5);
}
</style>