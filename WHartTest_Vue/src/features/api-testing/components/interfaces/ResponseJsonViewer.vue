<script setup lang="ts">
import { ref, computed, watch, h } from 'vue'
import { IconCopy, IconClose, IconPlayArrow } from '@arco-design/web-vue/es/icon'
import { useClipboard } from '@vueuse/core'
import { Message } from '@arco-design/web-vue'
import jmespath from 'jmespath'

interface Props {
  visible: boolean
  responseData: any
  fieldType?: 'extract' | 'assert'
}

const props = defineProps<Props>()
const emit = defineEmits(['update:visible', 'select-path'])

// 复制功能
const { copy } = useClipboard()
const copyContent = async (content: string) => {
  await copy(content)
  Message.success('复制成功')
}

// 关闭抽屉
const closeDrawer = () => {
  emit('update:visible', false)
}

// 测试提取表达式相关
const testExpression = ref('')
const testResult = ref<{ success: boolean; value: any; error?: string } | null>(null)
const isTestAreaExpanded = ref(false)

// 格式化的JSON数据
const formattedData = computed(() => {
  try {
    if (!props.responseData) return null
    
    const content = props.responseData?.response?.content
    if (!content) return null
    
    return content
  } catch (error) {
    console.error('解析响应数据失败:', error)
    return null
  }
})

// 测试表达式
const runTest = () => {
  if (!testExpression.value) {
    Message.warning('请先输入提取表达式')
    return
  }
  
  if (!formattedData.value) {
    Message.warning('暂无响应数据')
    return
  }
  
  try {
    // 处理表达式
    let expression = testExpression.value
    let data = formattedData.value
    
    // 如果表达式以 body. 开头，则移除前缀
    if (expression.startsWith('body.')) {
      expression = expression.substring(5)
    }
    
    // 执行 JMESPath 查询
    const result = jmespath.search(data, expression)
    
    // 存储测试结果
    testResult.value = {
      success: true,
      value: result
    }
    
    // 根据不同模式显示不同的成功消息
    if (props.fieldType === 'extract') {
      Message.success('提取测试成功')
    } else if (props.fieldType === 'assert') {
      Message.success('断言表达式有效')
    }
  } catch (error: any) {
    testResult.value = {
      success: false,
      value: null,
      error: error.message || '表达式解析失败'
    }
    Message.error(`测试失败: ${error.message || '表达式解析失败'}`)
  }
}

// 格式化测试结果显示
const formatTestResult = (result: any) => {
  if (result === null) return 'null'
  if (result === undefined) return 'undefined'
  if (typeof result === 'string') return `"${result}"`
  if (typeof result === 'object') {
    try {
      return JSON.stringify(result, null, 2)
    } catch {
      return String(result)
    }
  }
  return String(result)
}

// 应用测试的表达式
const applyExpression = () => {
  if (testExpression.value && testResult.value?.success) {
    // 确保表达式包含 body. 前缀（如果需要）
    let expression = testExpression.value
    if (!expression.startsWith('body.')) {
      expression = `body.${expression}`
    }
    
    // 将结果转换为字符串
    let valueStr = testResult.value.value
    if (typeof valueStr === 'object' && valueStr !== null) {
      valueStr = JSON.stringify(valueStr)
    } else {
      valueStr = String(valueStr)
    }
    
    emit('select-path', expression, valueStr)
    
    if (props.fieldType === 'extract') {
      Message.success('已应用提取表达式')
    } else if (props.fieldType === 'assert') {
      Message.success('已应用断言表达式和预期值')
    }
    
    // 清空测试区域
    testExpression.value = ''
    testResult.value = null
    isTestAreaExpanded.value = false
  }
}

// 展开的节点路径
const expandedPaths = ref<string[]>([])

// 判断指定路径是否展开
const isExpanded = (path: string) => {
  return expandedPaths.value.includes(path)
}

// 切换节点展开状态
const toggleExpand = (path: string) => {
  const index = expandedPaths.value.indexOf(path)
  if (index === -1) {
    expandedPaths.value.push(path)
  } else {
    expandedPaths.value.splice(index, 1)
  }
}

// 选择一个路径
const selectPath = (path: string, data: any) => {
  // 将路径格式转换为JMESPath格式 (例如 body.data.users[0].name)
  let jmesPath = path;
  
  // 如果需要添加前缀，可以在这里处理
  if (!path.startsWith('body')) {
    jmesPath = `body.${path}`;
  }
  
  // 准备值
  let value = data;
  if (typeof value === 'string') {
    // 对于字符串，去掉JSON.stringify添加的引号
    value = value;
  } else if (typeof value === 'object' && value !== null) {
    // 对于对象和数组，转换为JSON字符串
    value = JSON.stringify(value);
  } else {
    // 其他类型转为字符串
    value = String(value);
  }
  
  // 设置到测试表达式输入框
  testExpression.value = path
  isTestAreaExpanded.value = true
  
  // 自动运行测试
  runTest()
}

// 定义不同数据类型的样式
const getValueClass = (value: any) => {
  if (value === null) return 'text-gray-500'
  if (typeof value === 'number') return 'text-blue-400'
  if (typeof value === 'boolean') return 'text-purple-400'
  if (typeof value === 'string') return 'text-green-400'
  return 'text-gray-300'
}

// 格式化值，处理长字符串
const formatValue = (value: any) => {
  if (typeof value === 'string') {
    // 不再截断字符串，完整显示
    return JSON.stringify(value);
  }
  return JSON.stringify(value);
}

// 递归渲染JSON节点
const renderJsonNode = (data: any, path: string = '', isRoot: boolean = true): any => {
  if (data === null || data === undefined) {
    return h('div', { class: 'flex items-center' }, [
      h('span', { class: 'text-gray-500' }, 'null'),
      !isRoot && h('span', {
        class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded',
        onClick: () => selectPath(path, data)
      }, props.fieldType === 'extract' ? '选择' : '断言')
    ])
  }
  
  if (typeof data !== 'object') {
    // 计算内容是否需要换行
    const content = formatValue(data);
    const needsWrapping = content.length > 40; // 大致估计一行的字符数

    return h('div', { class: 'flex items-center flex-wrap' }, [
      h('span', { 
        class: `${getValueClass(data)} break-all ${needsWrapping ? 'max-w-[calc(100%-70px)]' : ''}`,
      }, content),
      !isRoot && h('span', {
        class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded whitespace-nowrap flex-shrink-0',
        onClick: () => selectPath(path, data)
      }, props.fieldType === 'extract' ? '选择' : '断言')
    ])
  }
  
  if (Array.isArray(data)) {
    if (data.length === 0) {
      return h('div', { class: 'flex items-center' }, [
        h('span', { class: 'text-gray-500 flex-shrink-0' }, '[]'),
        !isRoot && h('span', {
          class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded flex-shrink-0',
          onClick: () => selectPath(path, data)
        }, props.fieldType === 'extract' ? '选择' : '断言')
      ])
    }
    
    const isNodeExpanded = isExpanded(path)
    
    // 计算数组标题是否需要预留空间
    const arrayTitle = `Array[${data.length}]`;
    const needsArrayTitleWrapping = arrayTitle.length > 20;
    
    return h('div', { class: 'flex flex-col max-w-full' }, [
      h('div', { 
        class: 'flex items-center cursor-pointer hover:text-blue-400 flex-wrap',
        onClick: () => toggleExpand(path)
      }, [
        h('span', { class: 'mr-1 flex-shrink-0' }, isNodeExpanded ? '▼' : '▶'),
        h('span', { 
          class: `text-gray-300 break-all ${needsArrayTitleWrapping ? 'max-w-[calc(100%-90px)]' : ''}`
        }, arrayTitle),
        !isRoot && h('span', {
          class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded flex-shrink-0',
          onClick: (e: Event) => { e.stopPropagation(); selectPath(path, data) }
        }, props.fieldType === 'extract' ? '提取' : '选择断言')
      ]),
      
      isNodeExpanded && h('div', { class: 'pl-4 border-l border-gray-700 ml-2 max-w-full' }, 
        data.map((item: any, index: number) => h('div', { 
          key: index, 
          class: 'flex items-start py-1 max-w-full flex-wrap' 
        }, [
          h('span', { class: 'text-gray-400 mr-1 flex-shrink-0 whitespace-nowrap' }, `${index}:`),
          h('div', { 
            class: `flex-1 min-w-0 ${index > 999 ? 'max-w-[calc(100%-30px)]' : ''}`
          }, [
          renderJsonNode(item, `${path}[${index}]`, false)
          ])
        ]))
      )
    ])
  }
  
  // 处理对象
  const keys = Object.keys(data)
  if (keys.length === 0) {
    return h('div', { class: 'flex items-center' }, [
      h('span', { class: 'text-gray-500 flex-shrink-0' }, '{}'),
      !isRoot && h('span', {
        class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded flex-shrink-0',
        onClick: () => selectPath(path, data)
      }, props.fieldType === 'extract' ? '提取' : '选择断言')
    ])
  }
  
  const isNodeExpanded = isExpanded(path)
  
  // 计算对象标题是否需要预留空间
  const objectTitle = `Object {${keys.length}}`;
  const needsObjectTitleWrapping = objectTitle.length > 20;
  
  return h('div', { class: 'flex flex-col max-w-full' }, [
    h('div', {
      class: 'flex items-center cursor-pointer hover:text-blue-400 flex-wrap',
      onClick: () => toggleExpand(path)
    }, [
      h('span', { class: 'mr-1 flex-shrink-0' }, isNodeExpanded ? '▼' : '▶'),
      h('span', { 
        class: `text-gray-300 break-all ${needsObjectTitleWrapping ? 'max-w-[calc(100%-90px)]' : ''}`
      }, objectTitle),
      !isRoot && h('span', {
        class: 'ml-2 text-xs text-gray-500 hover:text-blue-400 cursor-pointer px-1 py-0.5 bg-blue-500/10 rounded flex-shrink-0',
        onClick: (e: Event) => { e.stopPropagation(); selectPath(path, data) }
      }, props.fieldType === 'extract' ? '提取' : '选择断言')
    ]),
    
    isNodeExpanded && h('div', { class: 'pl-4 border-l border-gray-700 ml-2 max-w-full' },
      keys.map(key => h('div', { 
        key, 
        class: 'flex items-start py-1 max-w-full flex-wrap' 
      }, [
        h('div', { class: 'flex items-center mr-1 flex-shrink-0' }, [
          h('span', { class: 'text-gray-400 mr-1 whitespace-nowrap' }, `${key}:`)
        ]),
        h('div', { 
          class: `flex items-start flex-1 min-w-0 ${key.length > 15 ? 'max-w-[calc(100%-30px)]' : ''}`
        }, [
          renderJsonNode(data[key], path ? `${path}.${key}` : key, false)
        ])
      ]))
    )
  ])
}

// 展开所有节点
const expandAllNodes = (data: any, basePath: string = '') => {
  if (!data || typeof data !== 'object') return
  
  // 添加当前路径到展开列表
  if (basePath) {
    expandedPaths.value.push(basePath)
  }
  
  // 如果是数组，递归展开每个元素
  if (Array.isArray(data)) {
    data.forEach((item, index) => {
      const path = basePath ? `${basePath}[${index}]` : `[${index}]`
      expandAllNodes(item, path)
    })
  } 
  // 如果是对象，递归展开每个属性
  else if (data && typeof data === 'object') {
    Object.keys(data).forEach(key => {
      const path = basePath ? `${basePath}.${key}` : key
      expandAllNodes(data[key], path)
    })
  }
}

// 监听数据变化时自动展开所有节点
watch(() => props.responseData, (newData) => {
  // 重置展开状态
  expandedPaths.value = ['']
  
  // 如果有数据，展开所有节点
  if (newData?.response?.content) {
    expandAllNodes(newData.response.content, '')
  }
}, { immediate: true })

// 监听抽屉关闭时清空测试数据
watch(() => props.visible, (visible) => {
  if (!visible) {
    testExpression.value = ''
    testResult.value = null
    isTestAreaExpanded.value = false
  }
})
</script>

<template>
  <a-drawer
    :visible="visible"
    :width="700"
    :footer="false"
    @cancel="closeDrawer"
    unmountOnClose
    placement="right"
    :mask-closable="true"
  >
    <template #title>
      <div class="flex justify-between items-center">
        <span>响应数据 - {{ fieldType === 'extract' ? '提取器' : '断言' }}</span>
        <a-button type="text" @click="closeDrawer">
          <template #icon><icon-close /></template>
        </a-button>
      </div>
    </template>
    
    <div class="p-4 h-full overflow-auto">
      <!-- 测试区域 (用于提取和断言) -->
      <div class="mb-4">
        <div v-if="isTestAreaExpanded" class="mt-3 space-y-3">
          <div class="flex gap-2">
            <a-input
              v-model="testExpression"
              :placeholder="fieldType === 'extract' ? '输入提取表达式进行测试 (例如: data.results[0].id)' : '输入断言表达式进行测试 (例如: body.data.code)'"
              allow-clear
              class="flex-1"
              @press-enter="runTest"
            />
            <a-button type="primary" @click="runTest">
              <template #icon><icon-play-arrow /></template>
              测试
            </a-button>
          </div>
          
          <!-- 测试结果展示 -->
          <div v-if="testResult">
            <div v-if="testResult.success" class="bg-green-500/10 border border-green-500/30 rounded-md p-3">
              <div class="flex items-center justify-between mb-2">
                <span class="text-green-400 text-sm">✓ {{ fieldType === 'extract' ? '提取成功' : '表达式有效' }}</span>
                <a-button
                  size="mini"
                  type="primary"
                  status="success"
                  @click="applyExpression"
                >
                  {{ fieldType === 'extract' ? '应用此表达式' : '应用到断言' }}
                </a-button>
              </div>
              <div class="bg-gray-900/50 rounded p-2 max-h-32 overflow-auto">
                <pre class="text-gray-300 text-xs font-mono whitespace-pre-wrap">{{ formatTestResult(testResult.value) }}</pre>
              </div>
            </div>
            <div v-else class="bg-red-500/10 border border-red-500/30 rounded-md p-3">
              <div class="text-red-400 text-sm mb-1">✗ {{ fieldType === 'extract' ? '提取失败' : '表达式无效' }}</div>
              <div class="text-red-300 text-xs">{{ testResult.error }}</div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 响应数据展示 -->
      <div v-if="formattedData" class="bg-gray-900/50 rounded-lg shadow-inner p-4 relative overflow-auto">
        <div
          class="absolute right-2 top-2 cursor-pointer copy-button text-gray-400 hover:text-blue-400"
          @click="copyContent(JSON.stringify(formattedData, null, 2))"
          title="复制"
        >
          <icon-copy />
        </div>
        
        <div class="font-mono text-sm break-all">
          <div class="mt-4">
            <div v-if="formattedData" class="overflow-x-auto content-container">
              <component :is="renderJsonNode(formattedData, '')" />
            </div>
            <div v-else class="text-gray-500">
              无数据
            </div>
          </div>
        </div>
      </div>
      <a-empty v-else description="暂无响应数据" />
      
      <div class="mt-4 bg-gray-900/30 rounded-lg p-4">
        <h3 class="font-medium text-gray-300 mb-2">使用说明</h3>
        <ul class="text-sm text-gray-400 list-disc pl-4">
          <li class="mb-1">点击对象或数组前的箭头可以展开/折叠节点</li>
          <li class="mb-1">点击值后面的"{{ fieldType === 'extract' ? '选择' : '断言' }}"按钮可以选择该路径进行测试</li>
          <li class="mb-1">使用测试区域可以调试{{ fieldType === 'extract' ? '提取' : '断言' }}表达式，测试成功后可应用到{{ fieldType === 'extract' ? '提取规则' : '断言配置' }}中</li>
          <li class="mb-1">选择的路径会自动转换为JMESPath表达式</li>
          <li>路径格式示例: <code class="bg-gray-800 px-1 py-0.5 rounded">body.data.users[0].name</code></li>
        </ul>
      </div>
    </div>
  </a-drawer>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-drawer) {
  @apply bg-gray-800;
}

:deep(.arco-drawer-header) {
  @apply border-gray-700 bg-gray-800 text-gray-300;
}

:deep(.arco-drawer-body) {
  @apply bg-gray-800 text-gray-300;
}

:deep(.arco-empty-description) {
  @apply text-gray-500;
}

:deep(.arco-input-wrapper) {
  @apply bg-gray-900/60 border-gray-700;
  
  input {
    @apply text-gray-200 bg-transparent;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-btn-primary) {
  @apply bg-blue-600 border-blue-600;
  
  &:hover {
    @apply bg-blue-700 border-blue-700;
  }
}

:deep(.arco-btn-primary.arco-btn-status-success) {
  @apply bg-green-600 border-green-600;
  
  &:hover {
    @apply bg-green-700 border-green-700;
  }
}

.font-mono {
  word-break: break-all;
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

/* 优化内容容器样式 */
.overflow-x-auto {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
  overflow-x: auto;
  max-width: 100%;
  display: block;
  padding-right: 8px; /* 为滚动条预留空间 */
}

/* 添加内容容器样式 */
.content-container {
  max-height: 500px;
  overflow-y: auto;
}

.overflow-x-auto::-webkit-scrollbar {
  height: 6px;
  width: 6px;
}

.overflow-x-auto::-webkit-scrollbar-track {
  background: transparent;
}

.overflow-x-auto::-webkit-scrollbar-thumb {
  background-color: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

.overflow-x-auto::-webkit-scrollbar-thumb:hover {
  background-color: rgba(255, 255, 255, 0.3);
}

code {
  font-family: monospace;
}

pre {
  margin: 0;
  font-family: 'Monaco', 'Courier New', monospace;
}
</style>