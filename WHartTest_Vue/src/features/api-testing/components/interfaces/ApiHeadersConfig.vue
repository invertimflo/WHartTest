<script setup lang="ts">
import { ref, watch } from 'vue'
import { IconDelete, IconPlus } from '@arco-design/web-vue/es/icon'
import type { KeyValuePair } from '../../services/interfaceService'

interface Props {
  headers?: KeyValuePair[]
}

const props = defineProps<Props>()

const headers = ref<KeyValuePair[]>([{ key: '', value: '', description: '', enabled: true }])

// 监听props变化
watch(() => props.headers, (newHeaders) => {
  if (newHeaders && newHeaders.length > 0) {
    headers.value = newHeaders
  } else {
    headers.value = [{ key: '', value: '', description: '', enabled: true }]
  }
}, { immediate: true })

// 添加Header行
const addRow = () => {
  headers.value.push({ key: '', value: '', description: '', enabled: true })
}

// 删除Header行
const removeRow = (index: number) => {
  headers.value.splice(index, 1)
  // 如果删除后没有行了，添加一个空行
  if (headers.value.length === 0) {
    headers.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

// 向父组件暴露headers数据
defineExpose({
  getHeaders: () => headers.value.filter(header => header.key || header.value)
})
</script>

<template>
  <div class="h-full flex flex-col p-4 space-y-2">
    <div class="flex-1 min-h-0 overflow-y-auto pr-2">
      <div class="space-y-2">
        <div
          v-for="(header, index) in headers"
          :key="index"
          class="flex items-center gap-2"
        >
          <a-checkbox v-model="header.enabled" />
          <a-input
            v-model="header.key"
            placeholder="Key"
            allow-clear
          />
          <a-input
            v-model="header.value"
            placeholder="Value"
            allow-clear
          />
          <a-input
            v-model="header.description"
            placeholder="Description"
            allow-clear
          />
          <a-button
            type="text"
            status="danger"
            @click="removeRow(index)"
          >
            <template #icon><icon-delete /></template>
          </a-button>
        </div>
      </div>
    </div>
    <div>
      <a-button type="outline" @click="addRow">
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
</style>