<script setup lang="ts">
import { IconPlus, IconClose, IconDragDotVertical } from '@arco-design/web-vue/es/icon'
import type { TestCaseStep } from '../../services/testcaseService'
import { addTestCaseSteps, deleteTestCaseStep, updateTestCaseStepOrder } from '../../services/testcaseService'
import type { CreateTestCaseData } from '../../services/testcaseService'
import type { ApiInterface } from '../../types/interface'
import { Message } from '@arco-design/web-vue'
import draggable from 'vuedraggable'
import { ref } from 'vue'
import ApiSelectDialog from './ApiSelectDialog.vue'

type Step = TestCaseStep

interface Props {
  steps: Step[]
  activeStep: Step | null
  testCaseId?: number
  readonly?: boolean
  testCase?: {
    name: string
    priority: 'P0' | 'P1' | 'P2' | 'P3'
    project: number
    description?: string
    group?: number
    tags?: number[]
    config?: {
      base_url: string
      variables: Record<string, any>
      parameters: Record<string, any>
      export: string[]
      verify: boolean
    }
  }
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false
})
const emit = defineEmits(['add', 'select', 'delete', 'update:steps', 'save-test-case'])

const dropdownVisible = ref(false)
const apiSelectVisible = ref(false)
const isDragging = ref(false)
const draggedStep = ref<Step | null>(null)
const originalOrder = ref<number>(0)

const stepTypes = [
  { label: '引用接口', value: 'reference', icon: '↓' },
  { label: '自定义接口', value: 'custom_api', icon: '⚡' },
]

const handleAddStep = (type: string) => {
  if (!props.testCaseId) {
    Message.info('正在自动保存用例基础信息...')
    emit('save-test-case', () => {
      setTimeout(() => {
        handleAddStep(type)
      }, 800)
    })
    return
  }

  if (type === 'reference') {
    apiSelectVisible.value = true
  } else if (type === 'custom_api') {
    const step: TestCaseStep = {
      id: 0,
      name: `自定义接口`,
      order: props.steps.length + 1,
      interface_info: {
        id: 0,
        name: '',
        method: 'GET',
        url: '',
        module: {
          id: 0,
          name: ''
        },
        project: {
          id: props.testCase?.project || 0,
          name: ''
        }
      },
      interface_data: {
        method: 'GET',
        url: '',
        body: {
          type: 'none',
          content: null
        },
        params: [],
        headers: [],
        variables: {},
        validators: [],
        extract: {},
        setup_hooks: [],
        teardown_hooks: []
      },
      config: {
        variables: {},
        validators: [],
        extract: {},
        setup_hooks: [],
        teardown_hooks: []
      },
      sync_fields: [
        'method',
        'url',
        'headers',
        'params',
        'body',
        'setup_hooks',
        'teardown_hooks',
        'variables',
        'validators',
        'extract'
      ],
      last_sync_time: null
    }
    const updatedSteps = [...props.steps, step]
    emit('update:steps', updatedSteps)
    emit('select', updatedSteps[updatedSteps.length - 1])
  } else {
    emit('add', type)
  }
  dropdownVisible.value = false
}

const handleApiSelect = async (selectedInterfaces: ApiInterface[]) => {
  try {
    const testCaseData: CreateTestCaseData = {
      name: props.testCase?.name || '未命名用例',
      priority: props.testCase?.priority || 'P3',
      project: props.testCase?.project || 0,
      description: props.testCase?.description || '',
      group: props.testCase?.group,
      tags: props.testCase?.tags || [],
      config: props.testCase?.config || {
        base_url: '',
        variables: {},
        parameters: {},
        export: [],
        verify: true
      },
      steps_info: selectedInterfaces.map((api, index) => ({
        name: api.name,
        order: props.steps.length + index + 1,
        interface_id: api.id!,
        interface_data: {
          method: api.method,
          url: api.url,
          headers: api.headers || [],
          params: api.params || [],
          body: api.body || { type: 'none', content: null },
          validators: api.validators || [],
          extract: api.extract || {},
          setup_hooks: (api.setup_hooks || []).map((hook: any) =>
            typeof hook === 'string' ? hook : JSON.stringify(hook)
          ),
          teardown_hooks: (api.teardown_hooks || []).map((hook: any) =>
            typeof hook === 'string' ? hook : JSON.stringify(hook)
          ),
          variables: api.variables || {}
        }
      }))
    }

    const response = await addTestCaseSteps(props.testCaseId!, testCaseData)
    Message.success('添加步骤成功')

    emit('update:steps', response.data.steps)

    if (response.data.steps.length > 0) {
      emit('select', response.data.steps[response.data.steps.length - 1])
    }

    apiSelectVisible.value = false
  } catch (error) {
    console.error('Failed to add steps:', error)
    Message.error('添加步骤失败')
  }
}

const handleSelectStep = (step: Step) => {
  emit('select', step)
}

const handleDeleteStep = async (step: Step, event: Event) => {
  event.stopPropagation()

  if (!props.testCaseId || !step.id) {
    const updatedSteps = props.steps.filter(s => s !== step)
    updatedSteps.forEach((s, index) => {
      s.order = index + 1
    })
    emit('update:steps', updatedSteps)
    if (props.activeStep === step) {
      emit('select', null)
    }
    return
  }

  try {
    await deleteTestCaseStep(props.testCaseId, step.id)
    Message.success('步骤删除成功')
    const updatedSteps = props.steps.filter(s => s.id !== step.id)
    updatedSteps.forEach((s, index) => {
      s.order = index + 1
    })
    emit('update:steps', updatedSteps)
    if (props.activeStep?.id === step.id) {
      emit('select', null)
    }
  } catch (error) {
    Message.error('步骤删除失败')
  }
}

const handleDragStart = (evt: any) => {
  isDragging.value = true
  const draggedIndex = evt.oldIndex
  draggedStep.value = props.steps[draggedIndex]
  originalOrder.value = draggedStep.value?.order || draggedIndex + 1
}

const handleDragEnd = async (evt: any) => {
  isDragging.value = false

  if (!draggedStep.value || !props.testCaseId || !draggedStep.value.id) {
    props.steps.forEach((step, index) => {
      step.order = index + 1
    })
    draggedStep.value = null
    return
  }

  const newIndex = evt.newIndex
  const newOrder = newIndex + 1

  if (originalOrder.value === newOrder) {
    draggedStep.value = null
    return
  }

  try {
    await updateTestCaseStepOrder(props.testCaseId, {
      step_id: draggedStep.value.id,
      order: newOrder
    })

    props.steps.forEach((step, index) => {
      step.order = index + 1
    })

    Message.success('步骤顺序已更新')
  } catch (error) {
    console.error('Failed to update step order:', error)
    Message.error('更新步骤顺序失败')

    const currentIndex = props.steps.findIndex(s => s.id === draggedStep.value?.id)
    if (currentIndex !== -1 && originalOrder.value) {
      const targetIndex = originalOrder.value - 1
      const [movedStep] = props.steps.splice(currentIndex, 1)
      props.steps.splice(targetIndex, 0, movedStep)

      props.steps.forEach((step, index) => {
        step.order = index + 1
      })

      emit('update:steps', [...props.steps])
    }
  } finally {
    draggedStep.value = null
    originalOrder.value = 0
  }
}

const getMethodColor = (method?: string) => {
  switch(method?.toUpperCase()) {
    case 'GET': return 'text-green-500'
    case 'POST': return 'text-blue-500'
    case 'PUT': return 'text-yellow-500'
    case 'DELETE': return 'text-red-500'
    default: return 'text-gray-500'
  }
}

const formatUrl = (url?: string): string => {
  if (!url) return '未设置URL'

  if (url.includes('?')) {
    const [path, query] = url.split('?')

    let displayPath = path
    if (path.length > 12) {
      const pathParts = path.split('/').filter(Boolean)
      if (pathParts.length > 1) {
        displayPath = `/${pathParts[0]}/.../${pathParts[pathParts.length - 1]}`
      } else if (pathParts.length === 1) {
        displayPath = `/${pathParts[0].substring(0, 5)}...`
      } else {
        displayPath = '/...'
      }
    }

    return `${displayPath}?${query.substring(0, 8)}...`
  }

  if (url.length > 20) {
    const pathParts = url.split('/').filter(Boolean)
    if (pathParts.length > 1) {
      return `/${pathParts[0]}/.../${pathParts[pathParts.length - 1]}`
    } else if (pathParts.length === 1) {
      return `/${pathParts[0].substring(0, 8)}...`
    }
  }

  return url
}
</script>

<template>
  <div class="h-full">
    <div class="flex justify-between items-center mb-4">
      <div class="flex items-center">
        <a-tag>{{ steps.length }}个步骤</a-tag>
      </div>
    </div>
    <div class="space-y-3 max-h-[calc(100vh-20rem)] overflow-y-auto hide-scrollbar">
      <template v-if="steps.length">
        <draggable
          :list="steps"
          :animation="150"
          item-key="name"
          handle=".drag-handle"
          class="space-y-3"
          :disabled="readonly"
          @update:modelValue="(steps: Step[]) => $emit('update:steps', steps)"
          @start="handleDragStart"
          @end="handleDragEnd"
        >
          <template #item="{ element: step, index }">
            <div
              class="rounded-lg cursor-pointer transition-all border group"
              :class="[
                activeStep?.id === step.id || (activeStep?.order === step.order && !step.id)
                  ? 'bg-blue-500/20 border-blue-500/50'
                  : 'bg-gray-800/50 hover:bg-gray-800 border-gray-700'
              ]"
              @click="handleSelectStep(step)"
            >
              <div class="p-4 flex items-center gap-3">
                <icon-drag-dot-vertical
                  class="drag-handle text-gray-500 flex-shrink-0"
                  :class="readonly ? 'cursor-not-allowed opacity-50' : 'cursor-move'"
                />
                <span class="w-7 h-7 flex items-center justify-center bg-blue-500 rounded-lg text-white flex-shrink-0">
                  {{ index + 1 }}
                </span>
                <div class="flex-1 min-w-0 overflow-hidden">
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-gray-300 font-medium">{{ step.name }}</span>
                  </div>
                  <div class="flex items-center gap-2 text-sm">
                    <span :class="[getMethodColor(step.interface_info?.method), 'flex-shrink-0']">
                      {{ step.interface_info?.method || 'METHOD' }}
                    </span>
                    <span
                      class="text-gray-400 truncate max-w-[calc(100%-4rem)]"
                      :title="step.interface_info?.url || '未设置URL'"
                    >
                      {{ formatUrl(step.interface_info?.url) }}
                    </span>
                  </div>
                  <div class="flex flex-wrap gap-2 mt-2">
                    <a-tag size="small" color="arcoblue" :class="{'!opacity-30': !Object.keys(step.interface_data?.variables || {}).length}">
                      {{ Object.keys(step.interface_data?.variables || {}).length }}个变量
                    </a-tag>
                    <a-tag size="small" color="orange" :class="{'!opacity-30': !Object.keys(step.interface_data?.extract || {}).length}">
                      {{ Object.keys(step.interface_data?.extract || {}).length }}个提取
                    </a-tag>
                    <a-tag size="small" color="green" :class="{'!opacity-30': !step.interface_data?.validators?.length}">
                      {{ step.interface_data?.validators?.length || 0 }}个断言
                    </a-tag>
                  </div>
                </div>
                <icon-close
                  class="text-gray-400 hover:text-red-500 transition-all cursor-pointer text-lg flex-shrink-0"
                  :style="{ fontSize: '18px' }"
                  @click="handleDeleteStep(step, $event)"
                />
              </div>
            </div>
          </template>
        </draggable>
      </template>
      <a-trigger
        trigger="hover"
        position="bottom"
        :popup-visible="dropdownVisible"
        @popup-visible-change="visible => dropdownVisible = visible"
        class="add-step-trigger"
        :popup-translate="[0, 8]"
      >
        <div
          class="rounded-lg cursor-pointer transition-all border border-dashed border-gray-700 hover:border-blue-500 bg-gray-800/50 hover:bg-gray-800"
        >
          <div class="p-4 flex items-center justify-center gap-2 text-gray-400 hover:text-blue-500">
            <icon-plus />
            <span>添加步骤</span>
          </div>
        </div>
        <template #content>
          <a-menu class="!bg-[rgb(55,65,81)] !border-gray-700 min-w-[180px]">
            <a-menu-item
              v-for="type in stepTypes"
              :key="type.value"
              @click="handleAddStep(type.value)"
            >
              <div class="flex items-center h-full w-full">
                <span class="w-5 h-5 flex items-center justify-center bg-[rgb(45,55,71)] rounded-lg text-sm ml-2">{{ type.icon }}</span>
                <span class="text-sm flex-1 text-center">{{ type.label }}</span>
                <span class="w-5"></span>
              </div>
            </a-menu-item>
          </a-menu>
        </template>
      </a-trigger>
    </div>
  </div>

  <ApiSelectDialog
    v-model:visible="apiSelectVisible"
    :test-case-id="testCaseId"
    :test-case="testCase"
    @select="handleApiSelect"
  />
</template>

<style scoped>
@reference "tailwindcss";
.hide-scrollbar {
  scrollbar-width: none;  /* Firefox */
  -ms-overflow-style: none;  /* IE and Edge */
  overflow-x: hidden;  /* 防止水平滚动 */
}

.hide-scrollbar::-webkit-scrollbar {
  display: none;  /* Chrome, Safari and Opera */
}

:deep(.arco-menu-item) {
  @apply text-gray-300 hover:text-blue-500 hover:bg-[rgb(45,55,71)];
  height: 32px !important;
  line-height: 32px !important;
  padding: 0 !important;
  margin: 2px 0 !important;
}

:deep(.arco-menu) {
  padding: 6px !important;
}

:deep(.arco-menu-item:first-child) {
  margin-top: 0 !important;
}

:deep(.arco-menu-item:last-child) {
  margin-bottom: 0 !important;
}

:deep(.arco-menu-selected) {
  @apply !bg-[rgb(45,55,71)] !text-blue-500;
}

.add-step-trigger {
  :deep(.arco-trigger-popup) {
    margin-bottom: 8px !important;
  }
}
</style>
