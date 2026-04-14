<script setup lang="ts">
import { ref, watch } from 'vue'
import { IconDelete, IconPlus } from '@arco-design/web-vue/es/icon'

interface KeyValuePair {
  key: string
  value: string
  description: string
  enabled: boolean
}

interface Props {
  params?: Record<string, any> | KeyValuePair[]
}

const props = withDefaults(defineProps<Props>(), {
  params: () => []
})

const emit = defineEmits(['update:params'])

// 参数列表
const paramsList = ref<KeyValuePair[]>([{ key: '', value: '', description: '', enabled: true }])

// 初始化参数列表
const initParamsList = () => {
  if (Array.isArray(props.params)) {
    paramsList.value = [...props.params]
  } else {
    paramsList.value = Object.entries(props.params || {}).map(([key, value]) => ({
      key,
      value: String(value),
      description: '',
      enabled: true
    }))
  }
  if (paramsList.value.length === 0) {
    paramsList.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

watch(() => props.params, () => {
  initParamsList()
}, { immediate: true, deep: true })

const addParam = () => {
  paramsList.value.push({ key: '', value: '', description: '', enabled: true })
}

const deleteParam = (index: number) => {
  paramsList.value.splice(index, 1)
  if (paramsList.value.length === 0) {
    paramsList.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

const getParams = () => {
  const params: Record<string, string> = {}
  for (const param of paramsList.value) {
    if (param.enabled && param.key) {
      params[param.key] = param.value
    }
  }
  return params
}

defineExpose({ getParams })
</script>

<template>
  <div class="h-full flex flex-col p-4 space-y-2">
    <div class="flex-1 min-h-0 overflow-y-auto pr-2">
      <div class="space-y-2">
        <div
          v-for="(param, index) in paramsList"
          :key="index"
          class="flex items-center gap-2"
        >
          <a-checkbox v-model="param.enabled" />
          <a-input v-model="param.key" placeholder="Key" allow-clear />
          <a-input v-model="param.value" placeholder="Value" allow-clear />
          <a-input v-model="param.description" placeholder="Description" allow-clear />
          <a-button type="text" status="danger" @click="deleteParam(index)">
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>
    </div>
    <div>
      <a-button type="outline" @click="addParam">
        <template #icon><icon-plus /></template>
        添加参数
      </a-button>
    </div>
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
    @apply text-red-500 bg-red-500/10;
  }
}
</style>
