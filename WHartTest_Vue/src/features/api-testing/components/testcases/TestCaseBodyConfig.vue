<script setup lang="ts">
import { ref, watch } from 'vue'
import { IconDelete, IconPlus } from '@arco-design/web-vue/es/icon'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import { useThemeStore } from '@/store/themeStore'

interface Props {
  body?: { type?: string; content?: any }
}

const props = withDefaults(defineProps<Props>(), {
  body: () => ({ type: 'none', content: null })
})

const emit = defineEmits(['update:body'])
const themeStore = useThemeStore()

type BodyType = 'none' | 'form-data' | 'x-www-form-urlencoded' | 'raw' | 'binary'
const bodyType = ref<BodyType>((props.body?.type as BodyType) || 'none')
const bodyContent = ref<any>(null)
const rawLanguage = ref('json')

const formDataList = ref<{ key: string; value: string; description: string; enabled: boolean }[]>([
  { key: '', value: '', description: '', enabled: true }
])

const initFormData = () => {
  if (props.body?.content) {
    if (Array.isArray(props.body.content)) {
      formDataList.value = [...props.body.content]
    } else if (typeof props.body.content === 'object') {
      formDataList.value = Object.entries(props.body.content).map(([key, value]) => ({
        key,
        value: typeof value === 'string' ? value : JSON.stringify(value),
        description: '',
        enabled: true
      }))
    }
  }
  if (formDataList.value.length === 0) {
    formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
  }
}

watch(() => props.body, (newBody) => {
  if (newBody) {
    bodyType.value = (newBody.type as BodyType) || 'none'
    if (newBody.type === 'form-data' || newBody.type === 'x-www-form-urlencoded') {
      formDataList.value = []
      initFormData()
    } else if (newBody.type === 'raw') {
      formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
      if (typeof newBody.content === 'object') {
        bodyContent.value = JSON.stringify(newBody.content, null, 2)
        rawLanguage.value = 'json'
      } else {
        bodyContent.value = newBody.content
        try { JSON.parse(newBody.content); rawLanguage.value = 'json' } catch { rawLanguage.value = 'text' }
      }
    } else if (newBody.type === 'binary') {
      formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
      bodyContent.value = newBody.content ?? null
    } else {
      bodyContent.value = null
      formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
    }
  }
}, { immediate: true, deep: true })

watch(bodyType, (newType) => {
  if (newType === 'none') {
    bodyContent.value = null
    formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
  } else if (newType === 'form-data' || newType === 'x-www-form-urlencoded') {
    bodyContent.value = null
    if (props.body?.type === newType) { initFormData() }
    else { formDataList.value = [{ key: '', value: '', description: '', enabled: true }] }
  } else if (newType === 'raw') {
    formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
    if (props.body?.type === 'raw') { bodyContent.value = props.body.content }
    else { bodyContent.value = rawLanguage.value === 'json' ? '{}' : '' }
  } else if (newType === 'binary') {
    formDataList.value = [{ key: '', value: '', description: '', enabled: true }]
    if (props.body?.type === 'binary') { bodyContent.value = props.body.content }
    else { bodyContent.value = null }
  }
  emit('update:body', { type: newType, content: getBody().content })
})

const addFormField = () => {
  formDataList.value.push({ key: '', value: '', description: '', enabled: true })
}

const deleteFormField = (index: number) => {
  formDataList.value.splice(index, 1)
  if (formDataList.value.length === 0) {
    formDataList.value.push({ key: '', value: '', description: '', enabled: true })
  }
}

const getBody = () => {
  if (bodyType.value === 'none') return { type: 'none', content: null }
  if (bodyType.value === 'form-data' || bodyType.value === 'x-www-form-urlencoded') {
    const formData: Record<string, string> = {}
    for (const item of formDataList.value) {
      if (item.enabled && item.key) formData[item.key] = item.value
    }
    return { type: bodyType.value, content: formData }
  }
  if (bodyType.value === 'raw') {
    let content = bodyContent.value
    if (rawLanguage.value === 'json' && typeof content === 'string') {
      try { content = JSON.parse(content) } catch (e) { console.warn('JSON parse failed:', e) }
    }
    return { type: 'raw', content }
  }
  if (bodyType.value === 'binary') return { type: 'binary', content: bodyContent.value }
  return { type: 'none', content: null }
}

defineExpose({ getBody })
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 顶部类型选择 -->
    <div class="flex-shrink-0 bg-gray-800 border-b border-gray-700">
      <a-radio-group v-model="bodyType" type="button" class="p-4 w-full">
        <a-radio value="none">none</a-radio>
        <a-radio value="form-data">form-data</a-radio>
        <a-radio value="x-www-form-urlencoded">x-www-form-urlencoded</a-radio>
        <a-radio value="raw">raw</a-radio>
        <a-radio value="binary">binary</a-radio>
      </a-radio-group>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 min-h-0 p-4">
      <!-- form-data -->
      <div v-if="bodyType === 'form-data' || bodyType === 'x-www-form-urlencoded'" class="h-[400px] flex flex-col">
        <div class="flex-1 min-h-0 overflow-y-auto space-y-2">
          <div v-for="(field, index) in formDataList" :key="index" class="flex items-center gap-2">
            <a-checkbox v-model="field.enabled" />
            <a-input v-model="field.key" placeholder="Key" allow-clear class="!w-[200px]" />
            <a-input v-model="field.value" placeholder="Value" allow-clear class="!w-[200px]" />
            <a-input v-model="field.description" placeholder="Description" allow-clear class="!flex-1" />
            <a-button type="text" status="danger" @click="deleteFormField(index)">
              <template #icon><icon-delete /></template>
            </a-button>
          </div>
        </div>
        <div class="flex-shrink-0 mt-2">
          <a-button type="outline" @click="addFormField">
            <template #icon><icon-plus /></template>
            添加字段
          </a-button>
        </div>
      </div>

      <!-- raw -->
      <div v-if="bodyType === 'raw'" class="flex-1 min-h-0">
        <div class="h-full flex flex-col gap-2">
          <div class="flex-shrink-0">
            <a-radio-group v-model="rawLanguage" type="button" size="small">
              <a-radio value="json">JSON</a-radio>
              <a-radio value="text">Text</a-radio>
              <a-radio value="javascript">JavaScript</a-radio>
              <a-radio value="html">HTML</a-radio>
              <a-radio value="xml">XML</a-radio>
            </a-radio-group>
          </div>
          <div class="flex-1">
            <VueMonacoEditor
              v-model:value="bodyContent"
              :language="rawLanguage"
              :theme="themeStore.isBlack ? 'vs-dark' : 'vs'"
              :options="{ minimap: { enabled: false }, fontSize: 14, automaticLayout: true }"
              style="height: 300px"
            />
          </div>
        </div>
      </div>

      <!-- binary -->
      <div v-if="bodyType === 'binary'" class="h-[400px] flex justify-center items-center">
        <div class="relative">
          <a-upload action="/" :auto-upload="false" :limit="1" @change="(fileList: any) => bodyContent = fileList[0]">
            <template #upload-button>
              <div class="border-2 border-dashed border-gray-600 rounded-lg p-4 text-center">
                <p class="text-gray-400">点击或拖拽文件到此处上传</p>
              </div>
            </template>
          </a-upload>
          <div v-if="bodyContent" class="text-gray-400 mt-4 text-center">
            已选择文件: {{ bodyContent.file?.name }} ({{ (bodyContent.file?.size / 1024).toFixed(2) }} KB)
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-radio-group-button) {
  @apply bg-gray-900/60 border-gray-700;

  .arco-radio-button {
    @apply border-gray-700 text-gray-400;

    &.arco-radio-button-checked {
      @apply text-blue-500 bg-blue-500/10;
    }
  }
}

:deep(.arco-input-wrapper) {
  @apply bg-gray-900/60 border-gray-700 !h-[32px];

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

:deep(.arco-upload) {
  @apply border border-gray-700 rounded p-4 bg-gray-900/60;
}

:deep(.monaco-editor) {
  @apply h-full w-full;

  .margin,
  .monaco-editor-background {
    @apply bg-gray-900/60;
  }
}

:deep(.monaco-editor .overflow-guard) {
  @apply h-full w-full;
}

:deep(.monaco-editor .monaco-scrollable-element) {
  @apply h-full w-full;
}

:deep(.monaco-editor .monaco-scrollable-element .monaco-editor-background) {
  @apply bg-gray-900/60;
}

/* 隐藏滚动条但保留滚动效果 */
.overflow-y-auto {
  scrollbar-width: none !important;
  -ms-overflow-style: none !important;
  &::-webkit-scrollbar {
    display: none !important;
  }
}

/* 恢复表单输入框的宽度 */
.flex.items-center.gap-2 {
  .arco-input-wrapper:nth-child(2),
  .arco-input-wrapper:nth-child(3) {
    @apply !w-[200px];
  }

  .arco-input-wrapper:nth-child(4) {
    @apply !flex-1;
  }
}
</style>
