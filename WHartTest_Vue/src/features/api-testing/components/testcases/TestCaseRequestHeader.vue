<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { IconSend, IconSave, IconRight, IconDown, IconQuestionCircle } from '@arco-design/web-vue/es/icon'
import { Message } from '@arco-design/web-vue'
import { useEnvironmentStore } from '../../stores/environmentStore'
import type { ApiInterface } from '../../types/interface'
import type { ApiModule } from '../../types/module'

interface Props {
  modules?: ApiModule[]
  modelValue: {
    method: string
    url: string
    name: string
    module: number | null
    interface?: ApiInterface | null
  }
  savingLoading?: boolean
  sendingLoading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  modules: () => [],
  savingLoading: false,
  sendingLoading: false
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'save',
  'save-step'
])

const environmentStore = useEnvironmentStore()

const currentEnvironmentBaseUrl = computed(() => {
  const currentEnv = (environmentStore as any).environments?.find(
    (env: any) => env.id === Number(environmentStore.currentEnvironmentId)
  )
  return currentEnv?.base_url || ''
})

const expandedModules = ref<number[]>([])

const processModules = (modules: ApiModule[], level = 0): (ApiModule & { level: number })[] => {
  return modules.reduce((acc: (ApiModule & { level: number })[], mod) => {
    acc.push({ ...mod, level })
    if (mod.children?.length && expandedModules.value.includes(mod.id)) {
      acc.push(...processModules(mod.children, level + 1))
    }
    return acc
  }, [])
}

const toggleModule = (moduleId: number, event: Event) => {
  event.preventDefault()
  event.stopPropagation()
  const index = expandedModules.value.indexOf(moduleId)
  if (index === -1) {
    expandedModules.value.push(moduleId)
  } else {
    expandedModules.value.splice(index, 1)
  }
}

const processedModules = computed(() => {
  return processModules(props.modules)
})

const apiName = computed({
  get: () => props.modelValue.name || '',
  set: (value) => {
    emit('update:modelValue', {
      ...props.modelValue,
      name: value
    })
  }
})

const selectedModule = computed({
  get: () => props.modelValue.module || undefined,
  set: (value) => {
    emit('update:modelValue', {
      ...props.modelValue,
      module: value || null
    })
  }
})

const requestUrl = computed({
  get: () => props.modelValue.url || '',
  set: (value) => {
    emit('update:modelValue', {
      ...props.modelValue,
      url: value
    })
  }
})

const selectedMethod = ref('GET')

watch(() => props.modelValue.method, (newMethod) => {
  if (newMethod && newMethod !== selectedMethod.value) {
    selectedMethod.value = newMethod
  }
}, { immediate: true })

watch(selectedMethod, (newMethod) => {
  if (newMethod !== props.modelValue.method) {
    emit('update:modelValue', {
      ...props.modelValue,
      method: newMethod
    })
  }
})

const httpMethods = [
  { label: 'GET', value: 'GET', color: 'method-get' },
  { label: 'POST', value: 'POST', color: 'method-post' },
  { label: 'PUT', value: 'PUT', color: 'method-put' },
  { label: 'DELETE', value: 'DELETE', color: 'method-delete' },
  { label: 'PATCH', value: 'PATCH', color: 'method-patch' }
]

const popupVisible = ref(false)

const handleSend = () => {
  if (!requestUrl.value) {
    Message.warning('请输入请求路径')
    return
  }
  emit('send', {
    method: selectedMethod.value,
    url: requestUrl.value,
    name: apiName.value,
    module: selectedModule.value
  })
}

const handleSave = () => {
  if (!selectedModule.value) {
    Message.warning('请选择模块')
    return
  }
  if (!apiName.value) {
    Message.warning('请输入步骤名称')
    return
  }
  if (!requestUrl.value) {
    Message.warning('请输入请求路径')
    return
  }
  emit('save', {
    method: selectedMethod.value,
    url: requestUrl.value,
    name: apiName.value,
    module: selectedModule.value
  })
}

const handleSaveStep = () => {
  if (!selectedModule.value) {
    Message.warning('请选择模块')
    return
  }
  if (!apiName.value) {
    Message.warning('请输入步骤名称')
    return
  }
  if (!requestUrl.value) {
    Message.warning('请输入请求路径')
    return
  }

  emit('save-step', {
    method: selectedMethod.value,
    url: requestUrl.value,
    name: apiName.value,
    module: selectedModule.value
  })
}

const selectMethod = (method: string) => {
  selectedMethod.value = method
  popupVisible.value = false
}

const getCurrentMethodColor = () => {
  return httpMethods.find(m => m.value === selectedMethod.value)?.color || 'method-default'
}
</script>

<template>
  <div class="p-4 border-b border-gray-700">
    <div class="flex gap-2 mb-3">
      <a-dropdown
        trigger="click"
        position="bl"
        v-model:popup-visible="popupVisible"
      >
        <div :class="['method-button', getCurrentMethodColor()]">
          {{ selectedMethod }}
        </div>
        <template #content>
          <div class="method-dropdown">
            <div
              v-for="method in httpMethods"
              :key="method.value"
              :class="['method-button', method.color]"
              @click="selectMethod(method.value)"
            >
              {{ method.value }}
            </div>
          </div>
        </template>
      </a-dropdown>

      <a-input
        v-model="requestUrl"
        placeholder="请输入请求路径"
        size="large"
        allow-clear
        class="menu-item rounded-lg flex-1"
      >
        <template #prefix v-if="currentEnvironmentBaseUrl">
          <span class="text-gray-500">{{ currentEnvironmentBaseUrl }}</span>
        </template>
      </a-input>

      <a-button-group>
        <a-button
          type="outline"
          size="large"
          :loading="props.sendingLoading"
          @click="handleSend"
          status="success"
          class="btn-debug"
        >
          <template #icon><icon-send /></template>
          运行调试
          <a-tooltip content="点击将自动保存接口并添加为用例的引用步骤，然后运行调试">
            <icon-question-circle class="ml-1 text-xs opacity-70" />
          </a-tooltip>
        </a-button>
        <a-button
          type="outline"
          size="large"
          :loading="props.savingLoading"
          @click="handleSaveStep"
          status="success"
        >
          <template #icon><icon-save /></template>
          保存步骤
        </a-button>
        <a-button
          type="outline"
          size="large"
          :loading="props.savingLoading"
          @click="handleSave"
        >
          <template #icon><icon-save /></template>
          保存接口
        </a-button>
      </a-button-group>
    </div>

    <div class="flex gap-2">
      <div class="border border-gray-600 rounded-lg" style="width: 20%">
        <a-select
          v-model="selectedModule"
          placeholder="请选择模块"
          size="large"
          allow-clear
          :style="{ width: '100%' }"
        >
          <a-option
            v-for="mod in processedModules"
            :key="mod.id"
            :value="mod.id"
          >
            <div class="flex items-center gap-2" :style="{ paddingLeft: `${mod.level * 16}px` }">
              <div
                v-if="mod.children?.length"
                class="w-4 h-4 flex items-center justify-center cursor-pointer"
                @click="toggleModule(mod.id, $event)"
              >
                <icon-right v-if="!expandedModules.includes(mod.id)" class="!w-3 !h-3 !text-[#6b7785]" />
                <icon-down v-else class="!w-3 !h-3 !text-[#6b7785]" />
              </div>
              <span v-else class="w-4"></span>
              {{ mod.name }}
            </div>
          </a-option>
        </a-select>
      </div>

      <a-input
        v-model="apiName"
        placeholder="请输入步骤名称"
        size="large"
        allow-clear
        :style="{ width: '80%' }"
        class="rounded-lg"
      />
    </div>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
/* 输入框menu-item样式 */
.menu-item {
  box-shadow: inset 0 1px 0 0 rgba(148, 163, 184, 0.2) !important;
  background-color: rgba(17, 24, 39, 0.8) !important;
  border: 1px solid rgba(75, 85, 99, 0.4) !important;
}

/* 请求方法按钮样式 */
.method-button {
  @apply flex items-center justify-center rounded text-white font-medium text-sm cursor-pointer;
  width: 82px;
  height: 32px;
  font-size: 13px;
  letter-spacing: 0.5px;
  transition: all 0.2s ease-in-out;
}

/* 请求方法颜色 */
.method-get { background-color: rgba(59, 130, 246, 0.8); }
.method-post { background-color: rgba(34, 197, 94, 0.8); }
.method-put { background-color: rgba(249, 115, 22, 0.8); }
.method-delete { background-color: rgba(239, 68, 68, 0.8); }
.method-patch { background-color: rgba(239, 68, 68, 0.8); }
.method-default { background-color: rgba(75, 85, 99, 1); }

.method-button:hover {
  transform: translateY(-1px);
  opacity: 1;
}

.method-dropdown {
  @apply flex flex-col items-center;
  min-width: 82px;
}

.method-dropdown .method-button {
  height: 28px;
  padding: 0;
  width: 65px !important;
  margin: 2px 1px 2px 0 !important;
}

/* 输入框样式 */
:deep(.arco-input-wrapper) {
  @apply bg-gray-900/60 border-gray-700;

  input {
    @apply text-gray-200;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-input-prefix) {
  margin-right: 4px;
  padding-right: 8px;
  border-right: 1px solid rgba(75, 85, 99, 0.4);
}

/* 按钮样式 */
:deep(.arco-btn-outline) {
  @apply border-gray-600 text-gray-300;

  &:hover {
    @apply border-blue-500 text-blue-500;
  }
}

/* 运行调试按钮样式 */
:deep(.btn-debug) {
  @apply text-[#10B981] border-[#10B981]/30;
  background-color: rgba(16, 185, 129, 0.05) !important;

  &:hover {
    @apply text-[#10B981] border-[#10B981]/50;
    background-color: rgba(16, 185, 129, 0.1) !important;
  }
}

/* 下拉菜单样式 */
:global(.arco-dropdown-list) {
  @apply bg-gray-800 rounded-lg;
  padding: 2px 0 !important;
  width: 80px !important;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2) !important;
  border: 1px solid rgba(75, 85, 99, 0.4) !important;
}

/* 模块选择下拉框样式 */
:deep(.arco-select) {
  @apply bg-gray-900/60;

  .arco-select-view {
    box-shadow: inset 0 1px 0 0 rgba(148, 163, 184, 0.2) !important;
    background-color: rgba(17, 24, 39, 0.8) !important;
    border: 1px solid rgba(75, 85, 99, 0.4) !important;
    @apply rounded-lg;

    &:hover {
      border-color: rgba(75, 85, 99, 0.6) !important;
    }
  }

  .arco-select-view-value {
    @apply text-gray-200;
  }

  input {
    @apply text-gray-200 bg-transparent;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-select-dropdown) {
  @apply bg-gray-800 border-gray-700 rounded-lg;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1) !important;
  border: 1px solid rgba(75, 85, 99, 0.4) !important;
  padding: 4px !important;
  margin: 4px 0 !important;

  .arco-select-option {
    @apply text-gray-300 rounded-lg px-2 py-1 my-1;

    &:hover {
      @apply bg-gray-700;
    }

    &.arco-select-option-active,
    &.arco-select-option-selected {
      @apply bg-blue-500/20 text-blue-500;
    }
  }
}

/* 模块树形结构样式 */
:deep(.arco-select-dropdown .arco-select-option) {
  @apply p-0;
  background: transparent !important;
  margin: 2px 0 !important;
  border-radius: 4px !important;

  &:hover {
    background: rgb(47, 66, 114, 0.4) !important;
  }

  &.arco-select-option-active,
  &.arco-select-option-selected {
    background: rgb(47, 66, 114, 0.4) !important;
  }
}

:deep(.arco-select-dropdown .arco-select-option .arco-btn) {
  @apply bg-transparent;
  border: none !important;

  &:hover {
    @apply bg-transparent;
  }

  .arco-icon {
    @apply text-[#6b7785];

    &:hover {
      @apply text-[#86909c];
    }
  }
}
</style>
