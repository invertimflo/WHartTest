<script setup lang="ts">
import { ref } from 'vue'
import type { EnvironmentVariable } from '../../services/environmentService'
import {
  IconCode,
  IconEdit,
  IconDelete,
  IconInfoCircle,
  IconLock,
} from '@arco-design/web-vue/es/icon'

interface Props {
  variables: EnvironmentVariable[]
}

interface Emits {
  (e: 'edit', index: number): void
  (e: 'delete', index: number): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const getTypeLabel = (type: string) => {
  const types: Record<string, string> = {
    string: 'String',
    integer: 'Integer',
    float: 'Float',
    boolean: 'Boolean',
    json: 'JSON',
    list: 'List',
    dict: 'Dict',
  }
  return types[type] || type
}
</script>

<template>
  <div class="overflow-y-auto max-h-[calc(100vh-24rem)]">
    <div
      v-for="(variable, index) in variables"
      :key="index"
      class="flex items-start gap-3 p-3 bg-gray-900/60 rounded-lg border border-gray-800/60 hover:border-gray-700/60 transition-colors mb-2 group"
    >
      <!-- 左侧图标 -->
      <div class="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
        <icon-code class="text-purple-400" />
      </div>

      <!-- 中间内容 -->
      <div class="flex-1 min-w-0">
        <!-- 标题和描述 -->
        <div class="mb-2">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-gray-300">变量 #{{ index + 1 }}</span>
            <span class="text-xs text-gray-500">·</span>
            <span class="text-xs text-gray-400 truncate">{{ variable.description || '暂无描述' }}</span>
            <a-tag v-if="variable.is_sensitive" size="small" status="danger">
              <template #icon><icon-lock /></template>
              敏感
            </a-tag>
          </div>
        </div>

        <!-- 变量信息 -->
        <div class="grid grid-cols-3 gap-4">
          <div class="space-y-1">
            <div class="text-xs text-gray-400">变量名</div>
            <div class="text-sm text-gray-300 truncate">{{ variable.name }}</div>
          </div>
          <div class="space-y-1">
            <div class="text-xs text-gray-400">变量值</div>
            <div class="text-sm text-gray-300 truncate">
              <span v-if="variable.is_sensitive">******</span>
              <span v-else>{{ variable.value }}</span>
            </div>
          </div>
          <div class="space-y-1">
            <div class="text-xs text-gray-400">类型</div>
            <div class="text-sm text-gray-300">{{ getTypeLabel(variable.type) }}</div>
          </div>
        </div>
      </div>

      <!-- 右侧操作按钮 -->
      <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <a-button
          type="text"
          size="mini"
          @click="emit('edit', index)"
        >
          <template #icon><icon-edit class="text-gray-400" /></template>
        </a-button>
        <a-button
          type="text"
          status="danger"
          size="mini"
          @click="emit('delete', index)"
        >
          <template #icon><icon-delete /></template>
        </a-button>
      </div>
    </div>
  </div>
</template> 