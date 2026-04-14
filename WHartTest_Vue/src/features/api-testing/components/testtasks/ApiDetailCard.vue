<script setup lang="ts">
import { ref } from 'vue'
import { Message, Drawer } from '@arco-design/web-vue'
import { IconCopy, IconExpand, IconCheckCircleFill, IconCloseCircleFill } from '@arco-design/web-vue/es/icon'

interface ValidateExtractor {
  check: string
  expect: string
  message: string
  comparator: string
  check_value: string
  check_result: string
  expect_value: string
}

interface StepDetail {
  id: number
  step_name: string
  success: boolean
  elapsed: number
  request: {
    url: string
    method: string
    headers: Record<string, string>
    body?: any
  }
  response: {
    status_code: number
    headers: Record<string, string>
    body: any
    response_time_ms: number
  }
  validators: {
    success: boolean
    validate_extractor: ValidateExtractor[]
  }
  extracted_variables: Record<string, any>
  attachment: string
}

const props = defineProps<{
  detail: StepDetail
}>()

// 格式化 JSON
const formatJson = (json: any) => {
  try {
    return JSON.stringify(json, null, 2)
  } catch (error) {
    return json
  }
}

// 格式化持续时间
const formatDuration = (seconds: number) => {
  if (seconds === undefined || seconds === null || isNaN(seconds)) return '-'
  try {
    return `${Number(seconds).toFixed(2)}秒`
  } catch (error) {
    console.error('持续时间格式化错误:', error)
    return '-'
  }
}

// 根据HTTP状态码获取对应的颜色
const getResponseStatusColor = (status: number) => {
  if (status >= 500) return 'red'
  if (status >= 400) return 'orange'
  if (status >= 300) return 'blue'
  return 'green'
}

// 抽屉组件状态控制
const drawerVisible = ref(false)
const currentDrawerData = ref<any>(null)
const currentDrawerType = ref<'request' | 'response' | 'validators' | 'variables' | null>(null)

/**
 * 切换抽屉的显示状态，并设置要显示的数据
 * @param type 数据类型（请求、响应、验证器或变量）
 */
const toggleDrawer = (type: 'request' | 'response' | 'validators' | 'variables') => {
  if (type === 'request') {
    currentDrawerData.value = props.detail.request
  } else if (type === 'response') {
    currentDrawerData.value = props.detail.response
  } else if (type === 'validators') {
    currentDrawerData.value = props.detail.validators?.validate_extractor || []
  } else if (type === 'variables') {
    currentDrawerData.value = props.detail.extracted_variables || {}
  }
  currentDrawerType.value = type
  drawerVisible.value = true
}

/**
 * 将文本复制到剪贴板
 * @param text 要复制的文本
 */
const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    Message.success('复制成功')
  } catch (err) {
    Message.error('复制失败')
  }
}

// 计算验证器的统计信息
const getValidatorStats = (validators: Array<{ check_result: string }>) => {
  const pass = validators.filter(v => v.check_result === 'pass').length
  return { pass, total: validators.length }
}
</script>

<template>
  <div class="mt-4">
    <!-- 详细信息网格 - 包含请求、响应、断言和变量等四个卡片，使用4列网格布局 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <!-- 请求信息卡片 (网格第1列) - 显示HTTP请求详情 -->
      <div v-if="detail.request" class="step-info-card">
        <!-- 卡片标题栏 -->
        <div class="bg-blue-500/5 px-3 py-1.5 border-b border-gray-700/30">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-blue-400 text-sm">请求信息</span>
              <a-tag size="small">{{ detail.request.method }}</a-tag>
            </div>
            <div class="flex items-center gap-2">
              <a-button type="text" size="mini" @click="copyToClipboard(JSON.stringify(detail.request, null, 2))">
                <template #icon><icon-copy class="text-gray-400 hover:text-blue-400" /></template>
              </a-button>
              <a-button type="text" size="mini" @click="toggleDrawer('request')">
                <template #icon><icon-expand class="text-gray-400 hover:text-blue-400" /></template>
              </a-button>
            </div>
          </div>
        </div>
        <div class="p-2">
          <!-- 请求信息容器 - 用于显示请求的JSON数据 -->
          <pre class="bg-gray-800/30 p-2 rounded text-xs font-mono text-gray-300 overflow-x-auto border border-gray-700/30 max-h-[120px] whitespace-pre-wrap break-all card-content">{{ formatJson(detail.request) }}</pre>
        </div>
      </div>

      <!-- 响应信息卡片 (网格第2列) - 显示HTTP响应详情 -->
      <div v-if="detail.response" class="step-info-card">
        <!-- 卡片标题栏 -->
        <div class="bg-purple-500/5 px-3 py-1.5 border-b border-gray-700/30">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-purple-400 text-sm">响应信息</span>
              <a-tag size="small" :color="getResponseStatusColor(detail.response.status_code)">
                {{ detail.response.status_code }}
              </a-tag>
            </div>
            <div class="flex items-center gap-2">
              <a-button type="text" size="mini" @click="copyToClipboard(JSON.stringify(detail.response, null, 2))">
                <template #icon><icon-copy class="text-gray-400 hover:text-purple-400" /></template>
              </a-button>
              <a-button type="text" size="mini" @click="toggleDrawer('response')">
                <template #icon><icon-expand class="text-gray-400 hover:text-purple-400" /></template>
              </a-button>
            </div>
          </div>
        </div>
        <div class="p-2">
          <!-- 响应信息容器 - 用于显示响应的JSON数据 -->
          <pre class="bg-gray-800/30 p-2 rounded text-xs font-mono text-gray-300 overflow-x-auto border border-gray-700/30 max-h-[120px] whitespace-pre-wrap break-all card-content">{{ formatJson(detail.response) }}</pre>
        </div>
      </div>

      <!-- 断言结果卡片 (网格第3列) - 显示验证结果 -->
      <div v-if="detail.validators?.validate_extractor?.length" class="step-info-card">
        <!-- 卡片标题栏 -->
        <div class="bg-yellow-500/5 px-3 py-1.5 border-b border-gray-700/30">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-yellow-400 text-sm">断言结果</span>
              <a-tag size="small" :color="getValidatorStats(detail.validators.validate_extractor).pass === getValidatorStats(detail.validators.validate_extractor).total ? 'green' : 'red'">
                {{ getValidatorStats(detail.validators.validate_extractor).pass }}/{{ getValidatorStats(detail.validators.validate_extractor).total }}
              </a-tag>
            </div>
            <div class="flex items-center gap-2">
              <a-button type="text" size="mini" @click="copyToClipboard(JSON.stringify(detail.validators.validate_extractor, null, 2))">
                <template #icon><icon-copy class="text-gray-400 hover:text-yellow-400" /></template>
              </a-button>
              <a-button type="text" size="mini" @click="toggleDrawer('validators')">
                <template #icon><icon-expand class="text-gray-400 hover:text-yellow-400" /></template>
              </a-button>
            </div>
          </div>
        </div>
        <div class="p-2 max-h-[120px] overflow-y-auto card-content">
          <!-- 断言结果容器 - 用于显示验证器的结果列表 -->
          <div class="space-y-2">
            <div 
              v-for="(validator, vIndex) in detail.validators.validate_extractor" 
              :key="vIndex"
              class="validator-item p-2"
            >
              <div class="flex items-start gap-1.5">
                <icon-check-circle-fill 
                  v-if="validator.check_result === 'pass'"
                  class="text-green-500 mt-0.5 text-sm"
                />
                <icon-close-circle-fill
                  v-else
                  class="text-red-500 mt-0.5 text-sm"
                />
                <div class="flex-1">
                  <div class="flex items-center gap-1">
                    <span class="text-gray-300 text-xs">{{ validator.check }}</span>
                    <span class="text-gray-500 text-xs">({{ validator.comparator }})</span>
                  </div>
                  <div class="mt-1 space-y-1">
                    <div class="validator-value">
                      <span class="text-gray-400 text-xs">期望值:</span>
                      <span class="text-blue-400 text-xs font-mono">{{ validator.expect_value }}</span>
                    </div>
                    <div class="validator-value">
                      <span class="text-gray-400 text-xs">实际值:</span>
                      <span class="text-purple-400 text-xs font-mono">{{ validator.check_value }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 提取变量卡片 (网格第4列) - 显示从响应中提取的变量 -->
      <div v-if="detail.extracted_variables && Object.keys(detail.extracted_variables).length" class="step-info-card">
        <!-- 卡片标题栏 -->
        <div class="bg-green-500/5 px-3 py-1.5 border-b border-gray-700/30">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-green-400 text-sm">提取变量</span>
              <a-tag size="small" color="green">{{ Object.keys(detail.extracted_variables).length }}个</a-tag>
            </div>
            <div class="flex items-center gap-2">
              <a-button type="text" size="mini" @click="copyToClipboard(JSON.stringify(detail.extracted_variables, null, 2))">
                <template #icon><icon-copy class="text-gray-400 hover:text-green-400" /></template>
              </a-button>
              <a-button type="text" size="mini" @click="toggleDrawer('variables')">
                <template #icon><icon-expand class="text-gray-400 hover:text-green-400" /></template>
              </a-button>
            </div>
          </div>
        </div>
        <div class="p-2">
          <!-- 提取变量容器 - 用于显示从响应中提取的变量 -->
          <div class="space-y-2 max-h-[120px] overflow-y-auto card-content">
            <div v-for="(value, key) in detail.extracted_variables" :key="key" class="bg-gray-800/30 rounded p-2 border border-gray-700/30 hover:bg-gray-800/50 hover:border-gray-600/50 transition-all duration-200">
              <div class="flex items-center justify-between">
                <span class="text-gray-300 text-xs">{{ key }}</span>
                <a-button type="text" size="mini" @click="copyToClipboard(value)">
                  <template #icon><icon-copy class="text-gray-400 hover:text-green-400" /></template>
                </a-button>
              </div>
              <div class="mt-1 bg-gray-900/30 rounded px-2 py-1 border border-gray-700/30">
                <span class="text-green-400 text-xs font-mono break-all">{{ value }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 抽屉组件 - 用于显示完整的请求或响应详情 -->
    <a-drawer
      :visible="drawerVisible"
      :width="800"
      @cancel="drawerVisible = false"
      :title="currentDrawerType === 'request' ? '请求详情' : currentDrawerType === 'response' ? '响应详情' : currentDrawerType === 'validators' ? '验证器详情' : '变量详情'"
      :footer="false"
      class="custom-drawer"
      :mask="true"
      :mask-style="{ backgroundColor: 'transparent' }"
      :mask-closable="true"
      @close="drawerVisible = false"
    >
      <div class="p-6">
        <!-- 根据不同的抽屉类型显示不同的内容 -->
        <template v-if="currentDrawerType === 'validators'">
          <div class="space-y-3">
            <div 
              v-for="(validator, vIndex) in currentDrawerData" 
              :key="vIndex"
              class="validator-item p-3"
            >
              <div class="flex items-start gap-2">
                <icon-check-circle-fill 
                  v-if="validator.check_result === 'pass'"
                  class="text-green-500 mt-0.5"
                />
                <icon-close-circle-fill
                  v-else
                  class="text-red-500 mt-0.5"
                />
                <div class="flex-1">
                  <div class="flex items-center gap-1">
                    <span class="text-gray-300">{{ validator.check }}</span>
                    <span class="text-gray-500">({{ validator.comparator }})</span>
                  </div>
                  <div class="mt-2 space-y-2">
                    <div class="validator-value">
                      <span class="text-gray-400">期望值:</span>
                      <span class="text-blue-400 font-mono">{{ validator.expect_value }}</span>
                    </div>
                    <div class="validator-value">
                      <span class="text-gray-400">实际值:</span>
                      <span class="text-purple-400 font-mono">{{ validator.check_value }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
        <template v-else-if="currentDrawerType === 'variables'">
          <div class="space-y-3">
            <div v-for="(value, key) in currentDrawerData" :key="key" class="bg-gray-800/30 rounded-lg p-3 border border-gray-700/30 hover:bg-gray-800/50 hover:border-gray-600/50 transition-all duration-200">
              <div class="flex items-start justify-between">
                <div class="flex items-center gap-2">
                  <span class="text-gray-300 font-medium">{{ key }}</span>
                </div>
                <a-button type="text" size="mini" @click="copyToClipboard(value)">
                  <template #icon><icon-copy class="text-gray-400 hover:text-green-400" /></template>
                </a-button>
              </div>
              <div class="mt-2 bg-gray-900/50 rounded-lg p-3 border border-gray-700/30">
                <div class="text-green-400 font-mono break-all">{{ value }}</div>
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <pre class="bg-gray-900/80 backdrop-blur-sm rounded-lg p-4 text-sm font-mono text-gray-300 whitespace-pre-wrap break-all border border-gray-700/30">{{ JSON.stringify(currentDrawerData, null, 2) }}</pre>
        </template>
      </div>
    </a-drawer>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.step-info-card {
  @apply bg-gray-900/30 rounded-lg border border-gray-700/30 overflow-hidden;
}

.validator-item {
  @apply bg-gray-800/30 rounded border border-gray-700/30 hover:bg-gray-800/50 hover:border-gray-600/50 transition-all duration-200;
}

.validator-value {
  @apply flex items-center gap-2;
}

.card-content {
  scrollbar-width: thin;
  scrollbar-color: rgba(75, 85, 99, 0.5) rgba(31, 41, 55, 0.5);
}

.card-content::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.card-content::-webkit-scrollbar-track {
  @apply bg-gray-900/30 rounded;
}

.card-content::-webkit-scrollbar-thumb {
  @apply bg-gray-600/50 rounded;
}

.card-content::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500/50;
}

:deep(.arco-drawer-header) {
  @apply !bg-gray-800 !border-gray-700;
}

:deep(.arco-drawer-title) {
  @apply !text-gray-200;
}

:deep(.arco-drawer-body) {
  @apply !bg-gray-800 !p-0;
}

:deep(.arco-drawer-mask) {
  @apply !bg-gray-900/70 !backdrop-blur-sm;
}
</style> 