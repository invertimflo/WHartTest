<script setup lang="ts">
interface QueryParams {
  name: string
  description: string
}

interface Props {
  modelValue: QueryParams
}

const props = defineProps<Props>()
const emit = defineEmits(['update:modelValue', 'search', 'reset'])

const updateValue = (key: keyof QueryParams, value: string) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

const handleSearch = () => {
  emit('search')
}

const handleReset = () => {
  emit('reset')
}
</script>

<template>
  <div class="flex items-center gap-4">
    <a-input-search
      :model-value="modelValue.name"
      @update:model-value="(val: string) => updateValue('name', val)"
      placeholder="搜索用例名称"
      class="flex-1"
      allow-clear
      @search="handleSearch"
      @press-enter="handleSearch"
      @clear="handleReset"
    />
    <a-input
      :model-value="modelValue.description"
      @update:model-value="(val: string) => updateValue('description', val)"
      placeholder="搜索用例描述"
      class="flex-1"
      allow-clear
      @press-enter="handleSearch"
    />
  </div>
</template>

<style scoped>
:deep(.arco-input-wrapper) {
  background-color: rgba(30, 41, 59, 0.5) !important;
  border-color: rgba(148, 163, 184, 0.1) !important;

  &:hover, &:focus-within {
    border-color: #60a5fa !important;
  }

  .arco-input {
    color: #e2e8f0 !important;
  }

  .arco-input-prefix, .arco-input-suffix {
    color: #94a3b8 !important;
  }
}
</style>
