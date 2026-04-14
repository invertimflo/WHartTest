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
  headers?: Record<string, any> | KeyValuePair[]
}

const props = withDefaults(defineProps<Props>(), {
  headers: () => []
})

const emit = defineEmits(['update:headers'])

const headersList = ref<KeyValuePair[]>([{ key: '', value: '', description: '', enabled: true }])

const initHeadersList = () => {
  if (Array.isArray(props.headers)) {
    headersList.value = [...props.headers]
  } else {
    headersList.value = Object.entries(props.headers || {}).map(([key, value]) => ({
      key,
      value: String(value),
      description: '',
      enabled: true
    }))
  }
  if (headersList.value.length === 0) {
    headersList.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

watch(() => props.headers, () => {
  initHeadersList()
}, { immediate: true, deep: true })

const addHeader = () => {
  headersList.value.push({ key: '', value: '', description: '', enabled: true })
}

const deleteHeader = (index: number) => {
  headersList.value.splice(index, 1)
  if (headersList.value.length === 0) {
    headersList.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

const getHeaders = () => {
  const headers: Record<string, string> = {}
  for (const header of headersList.value) {
    if (header.enabled && header.key) {
      headers[header.key] = header.value
    }
  }
  return headers
}

defineExpose({ getHeaders })
</script>

<template>
  <div class="h-full flex flex-col p-4 space-y-2">
    <div class="flex-1 min-h-0 overflow-y-auto pr-2">
      <div class="space-y-2">
        <div
          v-for="(header, index) in headersList"
          :key="index"
          class="flex items-center gap-2"
        >
          <a-checkbox v-model="header.enabled" />
          <a-input v-model="header.key" placeholder="Key" allow-clear />
          <a-input v-model="header.value" placeholder="Value" allow-clear />
          <a-input v-model="header.description" placeholder="Description" allow-clear />
          <a-button type="text" status="danger" @click="deleteHeader(index)">
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>
    </div>
    <div>
      <a-button type="outline" @click="addHeader">
        <template #icon><icon-plus /></template>
        添加请求头
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
