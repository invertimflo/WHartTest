<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  IconClose,
  IconEdit,
  IconCode,
  IconDelete,
  IconSettings,
  IconCopy,
} from '@arco-design/web-vue/es/icon'
import MonacoEditor from '@guolao/vue-monaco-editor'
import type { Function } from '../../services/functionService'

interface Props {
  loading?: boolean
  functionData: Function
}

interface Emits {
  (e: 'close'): void
  (e: 'edit', func: Function): void
  (e: 'delete', func: Function): void
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

const emit = defineEmits<Emits>()

// 只读代码内容（用于 v-model:value 绑定）
const codeContent = ref(props.functionData.code)

const editorOptions = {
  minimap: { enabled: true },
  readOnly: true,
  scrollBeyondLastLine: false,
  fontSize: 14,
  tabSize: 4,
  renderLineHighlight: 'all',
  roundedSelection: false,
  occurrencesHighlight: 'off',
  padding: { top: 10, bottom: 10 }
}

// 监听函数数据变化
watch(
  () => props.functionData,
  (newData) => {
    codeContent.value = newData.code
  },
  { deep: true }
)

// 处理编辑按钮点击
const handleEdit = () => {
  emit('edit', props.functionData)
}

// 处理删除按钮点击
const handleDelete = () => {
  emit('delete', props.functionData)
}

// 复制函数名称到剪贴板
const handleCopyName = () => {
  navigator.clipboard.writeText(props.functionData.name)
}
</script>

<template>
  <div class="h-full overflow-hidden">
    <a-spin :loading="loading" dot class="!block h-full">
      <div class="h-full overflow-y-auto overflow-x-hidden custom-scrollbar p-6 space-y-4">
        <!-- 顶部信息栏 -->
        <a-card class="!bg-[#1D2433] !border-gray-800 !rounded-lg">
          <div class="flex items-center justify-between flex-wrap gap-y-2">
            <div class="flex items-center gap-3 mr-2">
              <div class="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0">
                <icon-code class="text-blue-500" />
              </div>
              <h2 class="text-lg font-medium text-gray-100">
                {{ functionData.name }}
              </h2>
              <a-tag
                :color="functionData.is_active ? 'green' : 'red'"
                size="small"
              >{{ functionData.is_active ? '启用' : '禁用' }}</a-tag>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <a-button type="outline" size="small" @click="handleEdit">
                <template #icon><icon-edit /></template>
                编辑
              </a-button>
              <a-button type="outline" size="small" @click="handleCopyName">
                <template #icon><icon-copy /></template>
                复制名称
              </a-button>
              <a-popconfirm
                content="确定要删除这个函数吗？"
                type="warning"
                position="left"
                @ok="handleDelete"
              >
                <a-button type="outline" status="danger" size="small">
                  <template #icon><icon-delete /></template>
                  删除
                </a-button>
              </a-popconfirm>
              <a-button type="text" size="small" @click="emit('close')">
                <template #icon><icon-close /></template>
              </a-button>
            </div>
          </div>
        </a-card>

        <!-- 基本信息卡片 -->
        <a-card class="!bg-gray-900/30 !border-gray-700 !rounded-lg">
          <template #title>
            <div class="flex items-center gap-2">
              <icon-settings class="text-gray-400" />
              <span class="text-gray-300">基本信息</span>
            </div>
          </template>
          <div class="space-y-6 overflow-hidden">
            <!-- 函数名称 -->
            <div class="space-y-2">
              <div class="text-sm text-gray-400">函数名称</div>
              <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 break-all">
                {{ functionData.name }}
              </div>
            </div>
            <!-- 函数描述 -->
            <div class="space-y-2">
              <div class="text-sm text-gray-400">函数描述</div>
              <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 whitespace-pre-wrap">
                {{ functionData.description || '暂无描述' }}
              </div>
            </div>
            <!-- 创建信息 -->
            <div class="space-y-2">
              <div class="text-sm text-gray-400">创建信息</div>
              <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 space-y-2">
                <div class="flex items-center gap-2 flex-wrap" v-if="functionData.created_by">
                  <span class="text-gray-400">创建人：</span>
                  <span class="break-all">{{ functionData.created_by_name || '-' }}</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-gray-400">创建时间：</span>
                  <span>{{ functionData.created_at ? new Date(functionData.created_at).toLocaleString('zh-CN') : '-' }}</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-gray-400">更新时间：</span>
                  <span>{{ functionData.updated_at ? new Date(functionData.updated_at).toLocaleString('zh-CN') : '-' }}</span>
                </div>
              </div>
            </div>
          </div>
        </a-card>

        <!-- 函数代码卡片 -->
        <a-card class="!bg-[#1D2433] !border-gray-800 !rounded-lg">
          <template #title>
            <div class="flex items-center gap-2">
              <icon-code class="text-gray-400" />
              <span class="text-gray-300">函数代码</span>
            </div>
          </template>
          <MonacoEditor
            v-model:value="codeContent"
            language="python"
            theme="vs-dark"
            :options="editorOptions"
            style="height: 500px; width: 100%; border: 1px solid rgb(55, 65, 81); border-radius: 0.25rem;"
          />
        </a-card>
      </div>
    </a-spin>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";

.custom-scrollbar {
  scrollbar-width: none;
  -ms-overflow-style: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

:deep(.arco-btn-text) {
  @apply text-gray-400;

  &:hover {
    @apply text-gray-200 bg-gray-700/50;
  }
}

:deep(.arco-card-header) {
  @apply border-b border-gray-700/50;
}

:deep(.arco-card-header-title) {
  @apply text-gray-300;
}

:deep(.arco-card-body) {
  text-align: left;
}
</style>
