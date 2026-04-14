<script setup lang="ts">
import { ref, computed } from 'vue'
import { IconSettings, IconInfoCircle } from '@arco-design/web-vue/es/icon'

interface TestCaseConfigData {
  export?: string[]
  verify?: boolean
  base_url?: string
  variables?: string
  parameters?: string
  [key: string]: any
}

interface Props {
  modelValue: TestCaseConfigData
  readonly?: boolean
  steps?: {
    id: number
    name: string
    interface_data: {
      extract?: Record<string, string>
    }
  }[]
}

const props = defineProps<Props>()
const emit = defineEmits(['update:modelValue'])

const visible = ref(false)
const activeTab = ref('basic')

const config = ref<TestCaseConfigData>({
  export: [],
  verify: false,
  base_url: '',
  variables: '{}',
  parameters: '{}'
})

const extractVariables = computed(() => {
  const variables: Array<{
    stepId: number
    stepName: string
    key: string
    extract: string
  }> = []

  props.steps?.forEach(step => {
    if (step.interface_data.extract) {
      Object.entries(step.interface_data.extract).forEach(([key, extract]) => {
        variables.push({
          stepId: step.id,
          stepName: step.name,
          key,
          extract
        })
      })
    }
  })

  return variables
})

const handleOpen = () => {
  visible.value = true
  Object.assign(config.value, props.modelValue)
}

const handleSubmit = () => {
  emit('update:modelValue', { ...config.value })
  visible.value = false
}
</script>

<template>
  <div>
    <a-button
      class="!flex !items-center !gap-1"
      type="outline"
      size="small"
      status="normal"
      @click="handleOpen"
      :disabled="readonly"
    >
      <template #icon>
        <icon-settings class="!text-[#165DFF]" />
      </template>
      <span class="!text-[#165DFF]">用例配置</span>
    </a-button>

    <a-modal
      v-model:visible="visible"
      :width="800"
      title="用例配置"
      @ok="handleSubmit"
    >
      <a-tabs v-model:active-key="activeTab">
        <a-tab-pane key="basic" title="基础配置">
          <div class="space-y-4">
            <div class="flex items-center gap-4">
              <span class="w-24 text-gray-400">Base URL</span>
              <a-input
                v-model="config.base_url"
                placeholder="请输入基础URL"
                class="flex-1"
                allow-clear
              />
            </div>

            <div class="flex items-center gap-4">
              <span class="w-24 text-gray-400">SSL验证</span>
              <a-switch v-model="config.verify">
                <template #checked>开启</template>
                <template #unchecked>关闭</template>
              </a-switch>
            </div>

            <div class="flex items-start gap-4">
              <span class="w-24 text-gray-400 mt-2">变量定义</span>
              <a-textarea
                v-model="config.variables"
                placeholder="请输入JSON格式的变量定义"
                :auto-size="{ minRows: 3, maxRows: 8 }"
                class="flex-1 font-mono"
                allow-clear
              />
            </div>

            <div class="flex items-start gap-4">
              <span class="w-24 text-gray-400 mt-2">参数定义</span>
              <a-textarea
                v-model="config.parameters"
                placeholder="请输入JSON格式的参数定义"
                :auto-size="{ minRows: 3, maxRows: 8 }"
                class="flex-1 font-mono"
                allow-clear
              />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="dependencies" title="步骤依赖">
          <div class="space-y-4">
            <div class="flex items-center gap-2 mb-4">
              <icon-info-circle class="text-gray-400" />
              <span class="text-gray-400">展示步骤间的数据依赖关系，变量从步骤响应中提取后可在后续步骤中使用</span>
            </div>
            <a-table :data="extractVariables" :pagination="false" :bordered="false">
              <template #columns>
                <a-table-column title="步骤" data-index="step">
                  <template #cell="{ record }">
                    <span class="text-gray-300">{{ record.stepName }}</span>
                  </template>
                </a-table-column>
                <a-table-column title="变量名" data-index="key">
                  <template #cell="{ record }">
                    <div class="flex items-center gap-2">
                      <span class="font-mono text-[#165DFF]">${{ record.key }}</span>
                    </div>
                  </template>
                </a-table-column>
                <a-table-column title="提取规则" data-index="extract">
                  <template #cell="{ record }">
                    <span class="font-mono text-gray-400">{{ record.extract }}</span>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>
        </a-tab-pane>
      </a-tabs>
    </a-modal>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:global(.arco-modal-mask) {
  backdrop-filter: blur(4px) !important;
  @apply bg-black/60;
}

:deep(.arco-modal) {
  @apply bg-gray-900 rounded-lg;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1), 0 0 40px rgba(0, 0, 0, 0.8) !important;
  border: none !important;
}

:deep(.arco-modal-header) {
  @apply bg-transparent border-b border-gray-700 pb-4;
}

:deep(.arco-modal-title) {
  @apply text-gray-200;
}

:deep(.arco-modal-body) {
  @apply bg-transparent py-6;
}

:deep(.arco-modal-footer) {
  @apply bg-transparent border-t border-gray-700 pt-4;
}

:deep(.arco-tabs-nav) {
  @apply border-gray-700;
}

:deep(.arco-tabs-tab) {
  @apply text-gray-400;

  &.arco-tabs-tab-active {
    @apply text-[#165DFF];
  }
}

:deep(.arco-input-wrapper) {
  @apply bg-gray-900/60 border-gray-700;

  input {
    @apply text-gray-200;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-textarea-wrapper) {
  @apply bg-gray-900/60 border-gray-700;

  textarea {
    @apply text-gray-200;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-table) {
  @apply bg-transparent;
}

:deep(.arco-table-th) {
  @apply bg-gray-900/60 text-gray-400 border-gray-700;
  &::before {
    @apply bg-gray-700;
  }
}

:deep(.arco-table-td) {
  @apply bg-transparent text-gray-300 border-gray-700;
}

:deep(.arco-table-tr) {
  &:hover {
    .arco-table-td {
      @apply bg-gray-700/50;
    }
  }
}
</style>
