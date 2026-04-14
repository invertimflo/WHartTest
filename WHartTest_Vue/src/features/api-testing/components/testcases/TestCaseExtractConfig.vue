<script setup lang="ts">
import { ref, watch, onMounted, inject } from 'vue'
import { IconDelete, IconPlus, IconCode } from '@arco-design/web-vue/es/icon'
import { Message } from '@arco-design/web-vue'

interface Props {
  extract?: Record<string, string>
}

const props = withDefaults(defineProps<Props>(), {
  extract: () => ({})
})

const emit = defineEmits(['update:extract'])

const apiResponse = inject<any>('apiResponse', ref(null))

const drawerVisible = ref(false)
const currentEditingIndex = ref(-1)

interface ExtractRule {
  variable: string
  expression: string
  description: string
  enabled: boolean
}

const extractRules = ref<ExtractRule[]>([{ variable: '', expression: '', description: '', enabled: true }])

const initExtractRules = () => {
  if (props.extract && Object.keys(props.extract).length > 0) {
    extractRules.value = Object.entries(props.extract).map(([variable, expression]) => ({
      variable, expression, description: '', enabled: true
    }))
  } else {
    extractRules.value = [{ variable: '', expression: '', description: '', enabled: true }]
  }
}

watch(() => props.extract, (newExtract) => {
  if (newExtract && Object.keys(newExtract).length > 0) {
    extractRules.value = Object.entries(newExtract).map(([variable, expression]) => ({
      variable, expression, description: '', enabled: true
    }))
  } else {
    extractRules.value = [{ variable: '', expression: '', description: '', enabled: true }]
  }
})

const addRow = () => {
  extractRules.value.push({ variable: '', expression: '', description: '', enabled: true })
}

const removeRow = (index: number) => {
  extractRules.value.splice(index, 1)
  if (extractRules.value.length === 0) {
    extractRules.value.push({ variable: '', expression: '', description: '', enabled: true })
  }
}

const getJsonPaths = (obj: any, prefix = ''): { path: string; value: any }[] => {
  const paths: { path: string; value: any }[] = []
  if (obj === null || obj === undefined) return paths
  if (typeof obj === 'object') {
    for (const key of Object.keys(obj)) {
      const fullPath = prefix ? `${prefix}.${key}` : key
      paths.push({ path: fullPath, value: obj[key] })
      if (typeof obj[key] === 'object' && obj[key] !== null) {
        paths.push(...getJsonPaths(obj[key], fullPath))
      }
    }
  }
  return paths
}

const handleSelectPath = (path: string) => {
  if (currentEditingIndex.value >= 0 && currentEditingIndex.value < extractRules.value.length) {
    extractRules.value[currentEditingIndex.value].expression = path
    if (!extractRules.value[currentEditingIndex.value].variable.trim()) {
      const pathParts = path.split('.')
      let varName = pathParts[pathParts.length - 1]
      varName = varName.replace(/\[(\d+)\]/g, '_$1')
      extractRules.value[currentEditingIndex.value].variable = varName
    }
    Message.success('已设置提取表达式')
  }
  drawerVisible.value = false
}

const openResponseViewer = (index: number) => {
  currentEditingIndex.value = index
  drawerVisible.value = true
}

const getExtractRules = () => {
  const rules: Record<string, string> = {}
  extractRules.value
    .filter(rule => rule.enabled && rule.variable && rule.expression)
    .forEach(rule => { rules[rule.variable] = rule.expression })
  return rules
}

onMounted(() => { initExtractRules() })

defineExpose({ getExtractRules })
</script>

<template>
  <div class="h-full flex flex-col p-4 space-y-2">
    <div class="flex-1 min-h-0 overflow-y-auto pr-2">
      <div class="space-y-2">
        <div
          v-for="(rule, index) in extractRules"
          :key="index"
          class="flex items-center gap-2 w-full"
        >
          <a-checkbox v-model="rule.enabled" class="flex-shrink-0" />
          <div class="flex flex-1 gap-2">
            <div class="flex relative w-3/5">
              <a-input
                v-model="rule.expression"
                placeholder="提取表达式 (例如: body.data.id)"
                allow-clear
                class="w-full"
              />
              <a-button
                type="text"
                class="absolute right-0 top-0 bottom-0"
                @click="openResponseViewer(index)"
                :disabled="!apiResponse"
              >
                <template #icon><icon-code /></template>
              </a-button>
            </div>
            <div class="flex gap-2 w-2/5">
              <a-input v-model="rule.variable" placeholder="变量名" allow-clear class="w-full" />
            </div>
          </div>
          <a-button type="text" status="danger" @click="removeRow(index)" class="flex-shrink-0">
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>
    </div>
    <div>
      <a-button type="outline" @click="addRow">
        <template #icon><icon-plus /></template>
        添加提取规则
      </a-button>
    </div>

    <!-- 响应JSON路径选择抽屉 -->
    <a-drawer v-model:visible="drawerVisible" title="从响应中选择路径" :width="500" unmount-on-close>
      <div v-if="apiResponse" class="space-y-1">
        <div
          v-for="item in getJsonPaths(apiResponse)"
          :key="item.path"
          class="json-path-item"
          @click="handleSelectPath(item.path)"
        >
          <span class="json-path-key">{{ item.path }}</span>
          <span class="json-path-value">{{ typeof item.value === 'object' ? JSON.stringify(item.value) : String(item.value) }}</span>
        </div>
      </div>
      <a-empty v-else description="暂无响应数据，请先调试接口" />
    </a-drawer>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-input-wrapper) {
  @apply bg-gray-900/60 border-gray-700;

  input {
    @apply text-gray-200 bg-transparent;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-checkbox) {
  @apply text-gray-400;
}

:deep(.arco-btn-outline) {
  @apply border-gray-600 text-gray-300;

  &:hover {
    @apply border-blue-500 text-blue-500;
  }
}

:deep(.arco-btn-text) {
  @apply text-gray-400;

  &:hover {
    @apply text-blue-500 bg-blue-500/10;
  }

  &.arco-btn-status-danger {
    &:hover {
      @apply text-red-500 bg-red-500/10;
    }
  }
}
</style>
