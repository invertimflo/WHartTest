<script setup lang="ts">
import { ref, computed } from 'vue'
import { useClipboard } from '@vueuse/core'
import { Message } from '@arco-design/web-vue'
import { IconCopy } from '@arco-design/web-vue/es/icon'

interface ResponseData {
  status: number | null
  time: number | null
  size: number | null
  data: any
  request: any
  response: any
  validation_results: any
  extracted_variables: any
}

interface Props {
  response: ResponseData | null
}

const props = defineProps<Props>()
const { copy } = useClipboard()

const copyContent = async (content: string) => {
  await copy(content)
  Message.success('复制成功')
}

const responseContent = computed(() => {
  const content = props.response?.data?.response?.content
  if (!content) return ''
  if (typeof content === 'object') return JSON.stringify(content, null, 2)
  return content
})

const requestContent = computed(() => {
  if (!props.response?.data?.request) return ''
  return JSON.stringify(props.response.data.request, null, 2)
})

const responseHeadersContent = computed(() => {
  if (!props.response?.data?.response?.headers) return ''
  return JSON.stringify(props.response.data.response.headers, null, 2)
})

const statusCode = computed(() => props.response?.data?.response?.status_code)

const completeContent = computed(() => {
  if (!props.response) return ''
  return JSON.stringify(props.response, null, 2)
})

const responseActiveTab = ref('response')
</script>

<template>
  <div v-if="response" class="h-full flex flex-col">
    <!-- 顶部响应概要 -->
    <div class="flex items-center gap-4 px-4 pt-4 pb-2 border-t border-b border-gray-700">
      <div class="text-gray-400">响应内容</div>
      <div class="flex-1"></div>
      <div class="flex items-center gap-4 flex-shrink-0">
        <a-tag v-if="statusCode" :color="statusCode === 200 ? 'green' : 'red'" class="w-10 flex justify-center items-center">
          {{ statusCode }}
        </a-tag>
        <span v-if="response.time" class="text-gray-400">{{ response.time.toFixed(3) }} ms</span>
        <span v-if="response.size" class="text-gray-400">{{ response.size }} bytes</span>
      </div>
    </div>

    <!-- 响应内容页签 -->
    <div class="flex-1 overflow-hidden">
      <a-tabs v-model:active-key="responseActiveTab" class="h-full">
        <a-tab-pane key="response" title="响应体">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response.data?.response?.content" class="bg-gray-900/50 rounded-lg shadow-inner relative group">
                <div class="copy-button" @click="copyContent(responseContent)" title="复制">
                  <icon-copy />
                </div>
                <pre class="p-4 text-gray-300 font-mono text-sm leading-6 whitespace-pre-wrap break-all text-left">{{ responseContent }}</pre>
              </div>
              <a-empty v-else description="暂无响应数据" />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="headers" title="响应头">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response.data?.response?.headers" class="bg-gray-900/50 rounded-lg shadow-inner relative group">
                <div class="copy-button" @click="copyContent(responseHeadersContent)" title="复制">
                  <icon-copy />
                </div>
                <pre class="p-4 text-gray-300 font-mono text-sm leading-6 whitespace-pre-wrap break-all text-left">{{ responseHeadersContent }}</pre>
              </div>
              <a-empty v-else description="暂无响应头数据" />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="request" title="请求信息">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response.data?.request" class="bg-gray-900/50 rounded-lg shadow-inner relative group">
                <div class="copy-button" @click="copyContent(requestContent)" title="复制">
                  <icon-copy />
                </div>
                <pre class="p-4 text-gray-300 font-mono text-sm leading-6 whitespace-pre-wrap break-all text-left">{{ requestContent }}</pre>
              </div>
              <a-empty v-else description="暂无请求数据" />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="validation" title="验证结果">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response.data?.validation_results?.length" class="bg-gray-900/50 rounded-lg shadow-inner p-4">
                <div v-for="(result, index) in response.data.validation_results" :key="index"
                  class="flex flex-col p-3 rounded-md mb-3"
                  :class="{'bg-green-900/10': result.check_result === 'pass', 'bg-red-900/10': result.check_result !== 'pass'}"
                >
                  <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                      <a-tag :color="result.check_result === 'pass' ? 'green' : 'red'" class="!font-medium !flex-shrink-0">
                        {{ result.check_result === 'pass' ? '通过' : '失败' }}
                      </a-tag>
                      <span class="text-gray-300">{{ result.comparator }}: {{ result.check }}</span>
                    </div>
                  </div>
                  <div class="ml-1 flex flex-col gap-2">
                    <div class="flex flex-col gap-1">
                      <div class="text-gray-400 text-sm">实际值:
                        <span class="text-gray-300 font-mono">{{ result.check_value }}</span>
                      </div>
                    </div>
                    <div class="flex flex-col gap-1">
                      <div class="text-gray-400 text-sm">期望值:
                        <span class="text-gray-300 font-mono">{{ result.expect_value }}</span>
                      </div>
                    </div>
                    <div v-if="result.message" class="mt-1 text-red-400 text-sm">{{ result.message }}</div>
                  </div>
                </div>
              </div>
              <a-empty v-else description="暂无验证结果" />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="variables" title="提取变量">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response.data?.extracted_variables" class="bg-gray-900/50 rounded-lg shadow-inner p-4">
                <div v-for="(value, key) in response.data.extracted_variables" :key="key"
                  class="flex flex-col p-3 rounded-md mb-3 bg-gray-800/30 hover:bg-gray-800/50"
                >
                  <div class="flex items-center">
                    <span class="text-blue-400 font-medium font-mono">${{ key }}</span>
                  </div>
                  <div class="mt-2 text-gray-300 font-mono text-sm break-all">{{ value }}</div>
                </div>
              </div>
              <a-empty v-else description="暂无提取变量" />
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="complete" title="完整数据">
          <div class="h-full overflow-auto text-left">
            <div class="p-4">
              <div v-if="response" class="bg-gray-900/50 rounded-lg shadow-inner relative group">
                <div class="copy-button" @click="copyContent(completeContent)" title="复制">
                  <icon-copy />
                </div>
                <pre class="p-4 text-gray-300 font-mono text-sm leading-6 whitespace-pre-wrap break-all text-left">{{ completeContent }}</pre>
              </div>
              <a-empty v-else description="暂无响应数据" />
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>
  </div>

  <!-- 无响应时的提示 -->
  <div v-else class="h-full flex flex-col">
    <div class="flex items-center gap-4 px-4 pt-4 pb-2 border-t border-b border-gray-700">
      <div class="text-gray-400">响应内容</div>
    </div>
    <div class="flex-1 flex items-center justify-center">
      <div class="flex flex-col items-center justify-center text-gray-500">
        <div class="w-16 h-16 mb-4">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="100%" height="100%" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1Z" />
          </svg>
        </div>
        <div class="text-base">暂无响应数据</div>
        <div class="text-sm mt-2">点击调试按钮发送请求</div>
      </div>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-tabs) {
  @apply h-full flex flex-col;

  .arco-tabs-content {
    @apply flex-1 min-h-0;
  }

  .arco-tabs-content-item {
    @apply text-left;
  }

  .arco-tabs-header {
    @apply border-b border-gray-700;
  }

  .arco-tabs-nav-tab {
    @apply border-b-0;
  }

  .arco-tabs-tab {
    @apply text-gray-400;

    &.arco-tabs-tab-active {
      @apply text-blue-500;
    }
  }
}

:deep(.arco-tag) {
  &.arco-tag-green {
    @apply bg-green-500/20 text-green-500 border-green-500/20;
  }

  &.arco-tag-red {
    @apply bg-red-500/20 text-red-500 border-red-500/20;
  }
}

:deep(.arco-empty) {
  @apply py-8;
}

:deep(.arco-btn-text) {
  @apply bg-gray-800/80 p-2 rounded hover:bg-blue-500/20 hover:text-blue-500;
}

/* 复制按钮样式 */
.copy-button {
  @apply opacity-0 transition-opacity duration-300;
  @apply flex items-center justify-center w-8 h-8 bg-gray-800/80 rounded hover:bg-blue-500/20 hover:text-blue-500;

  :deep(svg) {
    @apply w-5 h-5 text-gray-300 hover:text-white;
  }
}

/* 当鼠标悬停在代码区域上时显示复制按钮 */
.group:hover .copy-button {
  @apply opacity-100;
}
</style>
