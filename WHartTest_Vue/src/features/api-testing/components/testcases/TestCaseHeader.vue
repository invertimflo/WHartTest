<script setup lang="ts">
import { ref } from 'vue'
import { IconFire, IconClose, IconCheck, IconPlayArrow, IconHistory } from '@arco-design/web-vue/es/icon'
import TestCaseBasicInfoComp from './TestCaseBasicInfo.vue'
import GroupManager from './GroupManager.vue'
import TagManager from './TagManager.vue'
import TestCaseConfigDialog from './TestCaseConfigDialog.vue'
import { useEnvironmentStore } from '../../stores/environmentStore'
import { Message } from '@arco-design/web-vue'

interface BasicInfoData {
  name: string
  description: string
  priority: string
  group: number | null
  tags: number[]
  config: Record<string, any>
  [key: string]: any
}

interface Props {
  modelValue: BasicInfoData
  loading?: boolean
  readonly?: boolean
  projectId: number
  testCaseId?: number
  steps?: {
    id: number
    name: string
    interface_data: {
      extract?: Record<string, string>
    }
  }[]
}

const props = defineProps<Props>()
const emit = defineEmits(['update:modelValue', 'cancel', 'save', 'run', 'show-report'])

const environmentStore = useEnvironmentStore()
const isRunning = ref(false)

const updateValue = (key: string, value: any) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

const handleCancel = () => {
  emit('cancel')
}

const handleSave = () => {
  emit('save')
}

const handleRun = async () => {
  if (!props.testCaseId) {
    Message.warning('请先保存用例')
    return
  }

  if (!environmentStore.currentEnvironmentId) {
    Message.warning('请先选择环境')
    return
  }

  emit('run', {
    testCaseId: props.testCaseId,
    environmentId: Number(environmentStore.currentEnvironmentId)
  })
}

const handleShowReport = () => {
  if (!props.testCaseId) {
    Message.warning('请先保存用例')
    return
  }

  emit('show-report', props.testCaseId)
}
</script>

<template>
  <div class="flex justify-between items-center">
    <div class="flex items-center gap-4 flex-wrap">
      <test-case-basic-info-comp
        :model-value="modelValue"
        @update:model-value="val => emit('update:modelValue', val)"
        :readonly="readonly"
      />

      <group-manager
        :model-value="modelValue.group"
        @update:model-value="val => updateValue('group', val)"
        :readonly="readonly"
        :project-id="projectId"
      />

      <tag-manager
        :model-value="modelValue.tags"
        @update:model-value="val => updateValue('tags', val)"
        :readonly="readonly"
        :project-id="projectId"
      />

      <a-select
        :model-value="modelValue.priority"
        @update:model-value="val => updateValue('priority', val)"
        placeholder="优先级"
        class="!w-24"
        :disabled="readonly"
      >
        <template #prefix>
          <icon-fire />
        </template>
        <a-option value="P0">P0</a-option>
        <a-option value="P1">P1</a-option>
        <a-option value="P2">P2</a-option>
        <a-option value="P3">P3</a-option>
      </a-select>

      <test-case-config-dialog
        :model-value="modelValue.config"
        @update:model-value="val => updateValue('config', val)"
        :readonly="readonly"
        :steps="props.steps"
      />
    </div>

    <div class="flex items-center gap-3">
      <a-button
        v-if="testCaseId"
        type="outline"
        size="small"
        status="normal"
        class="!flex !items-center !gap-1 !h-8 btn-run"
        :loading="isRunning"
        @click="handleRun"
      >
        <template #icon>
          <icon-play-arrow class="!text-[#10B981]" />
        </template>
        <span class="!text-[#10B981]">运行</span>
      </a-button>

      <a-button
        v-if="testCaseId"
        type="outline"
        size="small"
        status="normal"
        class="!flex !items-center !gap-1 !h-8 btn-report"
        @click="handleShowReport"
      >
        <template #icon>
          <icon-history class="!text-[#F97316]" />
        </template>
        <span class="!text-[#F97316]">报告</span>
      </a-button>

      <a-button
        type="outline"
        size="small"
        status="normal"
        class="!flex !items-center !gap-1 !h-8 btn-cancel"
        @click="handleCancel"
      >
        <template #icon>
          <icon-close class="!text-gray-400" />
        </template>
        <span class="!text-gray-400">取消</span>
      </a-button>

      <a-button
        v-if="!readonly"
        type="outline"
        size="small"
        status="normal"
        class="!flex !items-center !gap-1 !h-8 btn-save"
        :loading="loading"
        @click="handleSave"
      >
        <template #icon>
          <icon-check class="!text-[#8B5CF6]" />
        </template>
        <span class="!text-[#8B5CF6]">保存</span>
      </a-button>
    </div>
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

:deep(.arco-btn-dashed) {
  @apply border-gray-600 text-gray-400;

  &:hover {
    @apply border-blue-500 text-blue-500;
  }
}

:deep(.arco-btn-text) {
  @apply text-gray-400;

  &:hover {
    @apply text-blue-500 bg-blue-500/10;

    &[status="danger"] {
      @apply text-red-500 bg-red-500/10;
    }
  }
}

:deep(.arco-select-view) {
  @apply bg-gray-900/60 border-gray-700;

  input {
    @apply text-gray-200;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-select-dropdown) {
  @apply bg-gray-800 border-gray-700;

  .arco-select-option {
    @apply text-gray-300;

    &:hover {
      @apply bg-gray-700;
    }

    &.arco-select-option-active {
      @apply bg-blue-500/20 text-blue-500;
    }
  }
}

:deep(.arco-tag) {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  max-width: 60px !important;
  height: 22px !important;
  margin: 0 !important;
  padding: 0 4px !important;
  background: rgba(148, 163, 184, 0.1) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  border-radius: 2px !important;

  .arco-tag-content {
    flex: 1 !important;
    min-width: 0 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    font-size: 12px !important;
    line-height: 20px !important;
    text-align: center !important;
  }

  .arco-icon-hover {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }

  .arco-tag-close-btn {
    flex-shrink: 0 !important;
    margin-left: 4px !important;
    width: 12px !important;
    height: 12px !important;
    font-size: 12px !important;
    line-height: 12px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }
}

/* 运行按钮样式 */
.btn-run {
  border-color: rgba(16, 185, 129, 0.2) !important;
  background-color: rgba(16, 185, 129, 0.05) !important;
  line-height: 1 !important;
  padding: 4px 10px !important;

  &:hover {
    border-color: rgba(16, 185, 129, 0.4) !important;
    background-color: rgba(16, 185, 129, 0.1) !important;
  }
}

/* 报告按钮样式 */
.btn-report {
  border-color: rgba(249, 115, 22, 0.2) !important;
  background-color: rgba(249, 115, 22, 0.05) !important;
  line-height: 1 !important;
  padding: 4px 10px !important;

  &:hover {
    border-color: rgba(249, 115, 22, 0.4) !important;
    background-color: rgba(249, 115, 22, 0.1) !important;
  }
}

/* 取消按钮样式 */
.btn-cancel {
  border-color: rgba(148, 163, 184, 0.2) !important;
  background-color: rgba(148, 163, 184, 0.05) !important;
  line-height: 1 !important;
  padding: 4px 10px !important;

  &:hover {
    border-color: rgba(148, 163, 184, 0.4) !important;
    background-color: rgba(148, 163, 184, 0.1) !important;
  }
}

/* 保存按钮样式 */
.btn-save {
  border-color: rgba(139, 92, 246, 0.3) !important;
  background-color: rgba(139, 92, 246, 0.05) !important;
  line-height: 1 !important;
  padding: 4px 10px !important;

  &:hover {
    border-color: rgba(139, 92, 246, 0.5) !important;
    background-color: rgba(139, 92, 246, 0.1) !important;
  }
}
</style>
