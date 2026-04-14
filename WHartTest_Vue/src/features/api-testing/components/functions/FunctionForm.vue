<script setup lang="ts">
import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import type { Function } from '../../services/functionService'
import { testFunction } from '../../services/functionService'
import MonacoEditor from '@guolao/vue-monaco-editor'

const props = defineProps<{
  mode: 'create' | 'edit'
  loading?: boolean
  initialValues?: Function
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'submit', values: Partial<Function>): void
}>()

const form = ref({
  name: props.initialValues?.name || '',
  code: props.initialValues?.code || '',
  description: props.initialValues?.description || ''
})

const testArgs = ref('{}')
const testLoading = ref(false)
const testResult = ref('')

const codeEditorOptions = {
  minimap: { enabled: true },
  scrollBeyondLastLine: false,
  fontSize: 14,
  tabSize: 4,
  renderLineHighlight: 'all',
  roundedSelection: false,
  occurrencesHighlight: 'off',
  cursorBlinking: 'smooth',
  cursorSmoothCaretAnimation: 'on',
  smoothScrolling: true,
  mouseWheelZoom: true,
  padding: { top: 10, bottom: 10 }
}

const handleSubmit = () => {
  if (!form.value.name.trim()) {
    Message.warning('请输入函数名称')
    return
  }
  if (!form.value.code.trim()) {
    Message.warning('请输入函数代码')
    return
  }
  emit('submit', form.value)
}

const handleTest = async () => {
  if (!form.value.code.trim()) {
    Message.warning('请先输入函数代码')
    return
  }

  let parsedArgs
  try {
    parsedArgs = JSON.parse(testArgs.value)
  } catch (error) {
    Message.error('测试参数格式不正确，请输入有效的JSON')
    return
  }

  try {
    testLoading.value = true
    const response = await testFunction({
      code: form.value.code,
      test_args: parsedArgs
    })
    
    testResult.value = response.data?.result || '测试结果为空'
    Message.success('测试运行成功')
  } catch (error: any) {
    console.error('测试运行失败:', error)
    testResult.value = error.response?.data?.message || '测试运行失败'
    Message.error(error.response?.data?.message || '测试运行失败')
  } finally {
    testLoading.value = false
  }
}
</script>

<template>
  <div class="h-full flex flex-col bg-gray-900 rounded-lg overflow-hidden">
    <!-- 头部区域 -->
    <div class="px-6 py-4 border-b border-gray-800">
      <div class="flex justify-between items-center">
        <h2 class="text-xl font-semibold text-gray-100">
          {{ mode === 'create' ? '新建函数' : '编辑函数' }}
        </h2>
        <div class="flex gap-2">
          <a-button @click="emit('cancel')" class="!bg-gray-800 !border-gray-700 !text-gray-300">
            取消
          </a-button>
          <a-button
            type="primary"
            :loading="loading"
            @click="handleSubmit"
            class="!bg-blue-500 !border-blue-500 hover:!bg-blue-600 hover:!border-blue-600"
          >
            {{ mode === 'create' ? '创建' : '保存' }}
          </a-button>
        </div>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="p-6">
        <a-form :model="form" layout="vertical">
          <!-- 基本信息 -->
          <div class="grid grid-cols-2 gap-4 mb-6">
            <a-form-item field="name" label="函数名称" class="!mb-0">
              <a-input
                v-model="form.name"
                placeholder="请输入函数名称"
                class="!bg-gray-800/60 !border-gray-700"
              />
            </a-form-item>
            <a-form-item field="description" label="函数描述" class="!mb-0">
              <a-input
                v-model="form.description"
                placeholder="请输入函数描述"
                class="!bg-gray-800/60 !border-gray-700"
              />
            </a-form-item>
          </div>

          <!-- 代码编辑器 -->
          <div class="mb-6">
            <div class="text-gray-300 mb-2 text-sm">函数代码</div>
            <MonacoEditor
              v-model:value="form.code"
              language="python"
              theme="vs-dark"
              :options="codeEditorOptions"
              style="height: 400px; width: 100%; border: 1px solid rgb(55, 65, 81); border-radius: 0.25rem;"
            />
          </div>

          <!-- 测试区域 -->
          <div class="bg-gray-800/40 rounded-lg p-4">
            <div class="flex justify-between items-center mb-4">
              <h3 class="text-base font-medium text-gray-200">函数测试</h3>
              <a-button
                type="primary"
                size="small"
                :loading="testLoading"
                @click="handleTest"
                class="!bg-purple-500 !border-purple-500 hover:!bg-purple-600 hover:!border-purple-600"
              >
                运行测试
              </a-button>
            </div>
            
            <div class="mb-4">
              <div class="text-sm text-gray-400 mb-2">测试参数 (JSON格式)</div>
              <a-textarea
                v-model="testArgs"
                placeholder='{"arg1": "value1"}'
                :auto-size="{ minRows: 3, maxRows: 6 }"
                class="!bg-gray-800/60 !border-gray-700 !font-mono !text-sm"
              />
            </div>

            <div v-if="testResult">
              <div class="text-sm text-gray-400 mb-2">测试结果</div>
              <a-textarea
                v-model="testResult"
                :style="{ height: '150px' }"
                readonly
                class="!bg-gray-800/60 !border-gray-700"
              />
            </div>
          </div>
        </a-form>
      </div>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-form-item-label) {
  > label {
    @apply text-gray-300;
  }
}

:deep(.arco-form-item-content) {
  @apply h-full;
}

:deep(.arco-textarea),
:deep(.arco-input) {
  @apply text-gray-200;
  
  &::placeholder {
    @apply text-gray-500;
  }
}

:deep(.arco-btn) {
  @apply rounded-lg;
}

/* 滚动条样式 */
.overflow-y-auto {
  &::-webkit-scrollbar {
    @apply w-2;
  }
  
  &::-webkit-scrollbar-track {
    @apply bg-transparent;
  }
  
  &::-webkit-scrollbar-thumb {
    @apply bg-gray-700 rounded-full;
    
    &:hover {
      @apply bg-gray-600;
    }
  }
}
</style> 