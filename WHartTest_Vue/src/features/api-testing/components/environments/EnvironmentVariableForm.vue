<script setup lang="ts">
import { ref } from 'vue'
import type { NewEnvironmentVariableData, VariableType } from '../../services/environmentService'
import { VARIABLE_TYPES } from '../../services/environmentService'
import {
  IconPlus,
  IconCode,
  IconEdit,
  IconInfoCircle,
  IconLock,
} from '@arco-design/web-vue/es/icon'

interface Props {
  modelValue: NewEnvironmentVariableData
}

interface Emits {
  (e: 'update:modelValue', value: NewEnvironmentVariableData): void
  (e: 'submit'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const updateField = (field: keyof NewEnvironmentVariableData, value: string | number | boolean) => {
  emit('update:modelValue', {
    ...props.modelValue,
    [field]: value
  })
}

const handleSubmit = () => {
  if (!props.modelValue.name || !props.modelValue.value) {
    return
  }
  emit('submit')
}
</script>

<template>
  <div class="p-5 border border-dashed border-gray-700/50 rounded-lg space-y-4 hover:border-gray-600/50 transition-colors">
    <div class="flex items-center gap-2">
      <div class="w-6 h-6 rounded bg-purple-500/10 flex items-center justify-center">
        <icon-plus class="text-purple-400 text-sm" />
      </div>
      <span class="text-sm font-medium text-gray-300">添加新变量</span>
    </div>
    
    <div class="space-y-3">
      <a-input
        :model-value="modelValue.name"
        @update:model-value="val => updateField('name', val)"
        placeholder="变量名"
        allow-clear
        class="!bg-gray-900/60"
      >
        <template #prefix>
          <icon-code class="text-purple-400" />
        </template>
      </a-input>
      <a-input
        :model-value="modelValue.value"
        @update:model-value="val => updateField('value', val)"
        placeholder="变量值"
        allow-clear
        class="!bg-gray-900/60"
      >
        <template #prefix>
          <icon-edit class="text-purple-400" />
        </template>
      </a-input>

      <!-- 变量类型选择 -->
      <a-select
        :model-value="modelValue.type"
        @update:model-value="val => updateField('type', val)"
        placeholder="选择变量类型"
        class="!bg-gray-900/60"
      >
        <a-option
          v-for="item in VARIABLE_TYPES"
          :key="item.value"
          :value="item.value"
        >
          {{ item.label }}
        </a-option>
      </a-select>

      <a-input
        :model-value="modelValue.description"
        @update:model-value="val => updateField('description', val)"
        placeholder="变量描述（选填）"
        allow-clear
        class="!bg-gray-900/60"
      >
        <template #prefix>
          <icon-info-circle class="text-purple-400" />
        </template>
      </a-input>

      <!-- 敏感变量开关 -->
      <div class="flex items-center gap-3 p-3 bg-gray-900/40 rounded-lg">
        <a-switch
          :model-value="modelValue.is_sensitive"
          @update:model-value="val => updateField('is_sensitive', val)"
          class="!scale-110"
        />
        <div class="flex items-center gap-2">
          <icon-lock class="text-purple-400" />
          <span class="text-gray-300">敏感变量</span>
        </div>
      </div>
    </div>

    <div class="flex justify-end">
      <a-button
        type="outline"
        status="success"
        @click="handleSubmit"
      >
        <template #icon><icon-plus /></template>
        添加变量
      </a-button>
    </div>
  </div>
</template> 