<script setup lang="ts">
import { ref, onMounted, watch, h } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { IconRefresh } from '@arco-design/web-vue/es/icon'
import { syncApi, type SyncHistory } from '../../services/syncService'
import type { TableColumnData } from '@arco-design/web-vue'
import { useProjectStore } from '@/store/projectStore'
const projectStore = useProjectStore()
const loading = ref(false)
const histories = ref<SyncHistory[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)
const showDetailModal = ref(false)
const currentHistory = ref<SyncHistory | null>(null)
const diffFields = ref<Array<{ key: string; oldValue: any; newValue: any; changed: boolean }>>([])
const showUnchanged = ref(false)

const columns: TableColumnData[] = [
  {
    title: '序号',
    width: 80,
    align: 'center',
    slotName: 'index'
  },
  {
    title: '配置名称',
    slotName: 'config_name'
  },
  {
    title: '同步字段',
    slotName: 'sync_fields'
  },
  {
    title: '同步状态',
    width: 100,
    slotName: 'status'
  },
  {
    title: '创建信息',
    slotName: 'created_info'
  },
  {
    title: '操作',
    width: 100,
    slotName: 'operations'
  }
]

const fetchHistories = async () => {
  if (!projectStore.currentProject?.id) {
    Message.error('请先选择项目')
    return
  }

  try {
    loading.value = true
    const response = await syncApi.getHistories({
      project_id: projectStore.currentProject.id,
      page: currentPage.value,
      page_size: pageSize.value
    })
    
    // 打印原始响应，帮助调试
    console.log('同步历史API响应:', response);
    
    // 确保我们使用的是响应中的data字段
    const responseData = response.data;
    
    // 检查API返回的数据结构
    if ((responseData as any).results) {
      // 新的API结构
      histories.value = (responseData as any).results;
      total.value = (responseData as any).count || 0;
    } else if (responseData.histories) {
      // 旧的API结构
      histories.value = responseData.histories;
      total.value = responseData.total || 0;
    } else {
      console.error('未知的API响应结构:', responseData);
      histories.value = [];
      total.value = 0;
    }
  } catch (error) {
    Message.error('获取同步历史失败')
    console.error(error)
    histories.value = [];
    total.value = 0;
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchHistories()
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  fetchHistories()
}

const handleViewDetail = async (record: SyncHistory) => {
  try {
    loading.value = true
    const response = await syncApi.getHistoryDetail(record.id)
    currentHistory.value = response.data
    processDiffData() // 处理数据对比
    showDetailModal.value = true
  } catch (error) {
    Message.error('获取历史详情失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const handleRollback = async (record: SyncHistory) => {
  const configName = record.sync_config_info?.name || record.config?.name || '此历史记录';
  
  Modal.warning({
    title: '确认回滚',
    content: `确定要回滚到"${configName}"吗？此操作可能影响当前配置。`,
    okText: '确认回滚',
    cancelText: '取消',
    async onOk() {
      try {
        loading.value = true
        await syncApi.rollbackHistory(record.id)
        Message.success('回滚成功')
        await fetchHistories()
      } catch (error) {
        Message.error('回滚失败')
        console.error(error)
      } finally {
        loading.value = false
      }
    }
  })
}

// 处理数据对比
const processDiffData = () => {
  if (!currentHistory.value) return
  
  const oldData = currentHistory.value.old_data || {}
  const newData = currentHistory.value.new_data || {}
  const allKeys = new Set([...Object.keys(oldData), ...Object.keys(newData)])
  
  diffFields.value = Array.from(allKeys).map(key => {
    const oldValue = oldData[key]
    const newValue = newData[key]
    return {
      key,
      oldValue,
      newValue,
      changed: JSON.stringify(oldValue) !== JSON.stringify(newValue)
    }
  }).sort((a, b) => {
    // 把变更的字段排在前面
    if (a.changed && !b.changed) return -1
    if (!a.changed && b.changed) return 1
    return a.key.localeCompare(b.key)
  })
}

// 格式化值的显示
const formatValue = (value: any): string => {
  if (value === undefined) return '未设置'
  if (value === null) return 'null'
  if (typeof value === 'object') {
    try {
      const formatted = JSON.stringify(value, null, 1)
        .split('\n')
        .map((line, index) => {
          const indentMatch = line.match(/^(\s*)/)
          const indent = indentMatch ? indentMatch[1].length : 0
          
          // 处理键值对行
          if (line.includes(':')) {
            const [key, ...rest] = line.split(':')
            const value = rest.join(':')
            return `${' '.repeat(indent)}<span class="text-blue-400">${key.replace(/[",]/g, '')}</span>:${value}`
          }
          
          // 处理数组项
          if (line.trim().startsWith('"')) {
            return `${' '.repeat(indent)}<span class="text-green-400">${line}</span>`
          }
          
          // 处理数字
          if (/^(\s*)-?\d+/.test(line)) {
            return `${' '.repeat(indent)}<span class="text-yellow-400">${line}</span>`
          }
          
          // 处理布尔值和 null
          if (/true|false|null/.test(line)) {
            return `${' '.repeat(indent)}<span class="text-purple-400">${line}</span>`
          }
          
          // 处理括号和逗号
          return line.replace(/[{}\[\],]/g, match => `<span class="text-gray-500">${match}</span>`)
        })
        .join('\n')
      return formatted
    } catch (e) {
      return String(value)
    }
  }
  return String(value)
}

// 获取字段说明
const getFieldDescription = (key: string): string => {
  const descriptions: Record<string, string> = {
    name: '配置名称',
    description: '配置描述',
    status: '状态',
    created_at: '创建时间',
    updated_at: '更新时间',
    method: '请求方法',
    url: '请求地址',
    headers: '请求头',
    params: '查询参数',
    body: '请求体',
    setup_hooks: '前置钩子',
    teardown_hooks: '后置钩子',
    variables: '变量定义',
    validators: '断言规则',
    extract: '提取变量',
    // 添加更多同步字段的中文映射
    request_type: '请求类型',
    timeout: '超时时间',
    verify: 'SSL验证',
    allow_redirects: '允许重定向',
    base_url: '基础URL',
    json: 'JSON数据',
    data: '表单数据',
    files: '文件数据',
    auth: '认证信息',
    cookies: 'Cookie信息',
    proxies: '代理设置',
    env: '环境变量',
    export: '导出变量',
    validate: '验证规则',
    retry_times: '重试次数',
    retry_interval: '重试间隔',
    weight: '权重',
    priority: '优先级',
    skip: '是否跳过',
    times: '执行次数'
  }
  return descriptions[key] || key
}

watch(() => projectStore.currentProject?.id, (newProjectId: number | undefined) => {
  if (newProjectId) {
    currentPage.value = 1
    fetchHistories()
  } else {
    histories.value = []
    total.value = 0
  }
})

onMounted(() => {
  if (projectStore.currentProject?.id) {
    fetchHistories()
  }
})
</script>

<template>
  <div>
    <div class="flex justify-end mb-6">
      <a-button type="outline" :loading="loading" @click="fetchHistories">
        <template #icon>
          <icon-refresh />
        </template>
        刷新
      </a-button>
    </div>

    <a-table
      :loading="loading"
      :data="histories"
      :columns="columns"
      :pagination="{
        total,
        current: currentPage,
        pageSize,
        showTotal: true,
        showJumper: true,
        showPageSize: true
      }"
      :bordered="true"
      :stripe="true"
      class="custom-table"
      @page-change="handlePageChange"
      @page-size-change="handlePageSizeChange"
    >
      <template #index="{ rowIndex }">
        {{ (currentPage - 1) * pageSize + rowIndex + 1 }}
      </template>

      <template #config_name="{ record }">
        <span>{{ record.sync_config_info?.name || record.config?.name || '-' }}</span>
      </template>

      <template #sync_fields="{ record }">
        <div class="flex flex-wrap gap-1">
          <a-tag
            v-for="field in record.sync_fields"
            :key="field"
            color="arcoblue"
            size="small"
          >
            {{ getFieldDescription(field) }}
          </a-tag>
        </div>
      </template>

      <template #status="{ record }">
        <a-tag 
          :color="record.sync_status === 'success' || record.status === 'success' ? 'green' : 'red'"
          size="medium"
          class="min-w-[60px] text-center"
        >
          {{ (record.sync_status === 'success' || record.status === 'success') ? '成功' : '失败' }}
        </a-tag>
        <a-tooltip v-if="record.error_message">
          <template #content>
            {{ record.error_message }}
          </template>
          <icon-exclamation-circle class="text-red-500 ml-1" />
        </a-tooltip>
      </template>

      <template #created_info="{ record }">
        <div class="flex flex-col gap-1 text-sm">
          <span>操作者：{{ record.operator_info?.username || record.created_by_info?.username || '-' }}</span>
          <span>时间：{{ record.sync_time ? new Date(record.sync_time).toLocaleString() : (record.created_at ? new Date(record.created_at).toLocaleString() : '-') }}</span>
        </div>
      </template>

      <template #operations="{ record }">
        <div class="flex gap-2">
          <a-button
            type="text"
            size="mini"
            :loading="loading"
            @click="handleViewDetail(record)"
          >
            详情
          </a-button>
          <a-button
            v-if="record.sync_status === 'success' || record.status === 'success'"
            type="text"
            status="warning"
            size="mini"
            :loading="loading"
            @click="handleRollback(record)"
          >
            回滚
          </a-button>
        </div>
      </template>
    </a-table>

    <!-- 详情弹窗 -->
    <a-modal
      v-model:visible="showDetailModal"
      title="同步历史详情"
      :width="900"
      class="custom-card"
      @cancel="currentHistory = null"
    >
      <!-- 自定义描述列表 -->
      <div class="bg-gray-900/30 p-3 rounded-lg">
        <div class="grid grid-cols-4 gap-3">
          <!-- 配置名称 -->
          <div class="border border-gray-700 rounded">
            <div class="bg-gray-800/70 py-2 px-3 font-medium text-gray-400 border-b border-gray-700">
              配置名称
            </div>
            <div class="bg-gray-800/30 py-2 px-3 text-gray-300">
              {{ currentHistory?.sync_config_info?.name || currentHistory?.config?.name || '-' }}
            </div>
          </div>
          
          <!-- 同步状态 -->
          <div class="border border-gray-700 rounded">
            <div class="bg-gray-800/70 py-2 px-3 font-medium text-gray-400 border-b border-gray-700">
              同步状态
            </div>
            <div class="bg-gray-800/30 py-2 px-3 text-gray-300">
              <span 
                :class="[
                  'px-2 py-0.5 rounded text-white', 
                  (currentHistory?.sync_status === 'success' || currentHistory?.status === 'success') 
                    ? 'bg-green-500' 
                    : 'bg-red-500'
                ]"
              >
                {{ (currentHistory?.sync_status === 'success' || currentHistory?.status === 'success') ? '成功' : '失败' }}
              </span>
            </div>
          </div>
          
          <!-- 操作人 -->
          <div class="border border-gray-700 rounded">
            <div class="bg-gray-800/70 py-2 px-3 font-medium text-gray-400 border-b border-gray-700">
              操作人
            </div>
            <div class="bg-gray-800/30 py-2 px-3 text-gray-300 text-xs">
              <div>{{ currentHistory?.operator_info?.username || currentHistory?.created_by_info?.username || '-' }}</div>
              <div class="text-gray-400 mt-0.5">
                {{ currentHistory?.sync_time 
                  ? new Date(currentHistory.sync_time).toLocaleString() 
                  : (currentHistory?.created_at ? new Date(currentHistory.created_at).toLocaleString() : '-') }}
              </div>
            </div>
          </div>
          
          <!-- 错误信息 -->
          <div class="border border-gray-700 rounded">
            <div class="bg-gray-800/70 py-2 px-3 font-medium text-gray-400 border-b border-gray-700">
              错误信息
            </div>
            <div class="bg-gray-800/30 py-2 px-3 text-gray-300 text-xs overflow-auto max-h-[60px]">
              {{ currentHistory?.error_message || '-' }}
            </div>
          </div>
          
          <!-- 同步字段 -->
          <div class="border border-gray-700 rounded col-span-4">
            <div class="bg-gray-800/70 py-1.5 px-3 font-medium text-gray-400 border-b border-gray-700 flex items-center justify-between">
              <span>同步字段</span>
              <span class="text-xs font-normal">共 {{ currentHistory?.sync_fields?.length || 0 }} 个字段</span>
            </div>
            <div class="bg-gray-800/30 p-2">
              <div v-if="currentHistory?.sync_fields?.length" class="flex flex-wrap gap-1.5">
                <a-tag
                  v-for="field in currentHistory.sync_fields"
                  :key="field"
                  color="arcoblue"
                  size="small"
                >
                  {{ getFieldDescription(field) }}
                </a-tag>
              </div>
              <div v-else class="text-gray-400 text-sm">暂无同步字段</div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 显示新旧数据对比 -->
      <div v-if="currentHistory?.old_data || currentHistory?.new_data" class="mt-3">
        <div class="mb-3">
          <div class="flex items-center justify-between">
            <h3 class="text-gray-400 text-sm font-medium flex items-center">
              <span class="inline-block w-1.5 h-1.5 bg-blue-500 rounded-full mr-1.5"></span>
              数据变更详情
            </h3>
            <a-button
              type="text"
              size="mini"
              class="text-gray-400 hover:text-gray-300"
              @click="showUnchanged = !showUnchanged"
            >
              {{ showUnchanged ? '收起未变更字段' : '显示未变更字段' }}
            </a-button>
          </div>
        </div>
        
        <div class="bg-gray-900/30 rounded-lg border border-gray-700/50">
          <!-- 表头 -->
          <div class="grid grid-cols-12 gap-3 py-1.5 px-3 bg-gray-800/50 border-b border-gray-700/50">
            <div class="col-span-2 text-gray-400 text-xs font-medium">字段名称</div>
            <div class="col-span-5 text-gray-400 text-xs font-medium flex items-center">
              <span class="inline-block w-1.5 h-1.5 bg-red-500/70 rounded-full mr-1.5"></span>
              变更前
            </div>
            <div class="col-span-5 text-gray-400 text-xs font-medium flex items-center">
              <span class="inline-block w-1.5 h-1.5 bg-green-500/70 rounded-full mr-1.5"></span>
              变更后
            </div>
          </div>
          
          <!-- 字段列表 -->
          <div class="divide-y divide-gray-700/50">
            <div
              v-for="field in diffFields"
              :key="field.key"
              v-show="field.changed || showUnchanged"
              :class="[
                'grid grid-cols-12 gap-3 py-2 px-3',
                field.changed ? 'bg-blue-500/5' : '',
                'hover:bg-gray-800/30'
              ]"
            >
              <!-- 字段名称 -->
              <div class="col-span-2 flex flex-col justify-center">
                <div class="text-sm text-gray-300 font-medium">
                  {{ getFieldDescription(field.key) }}
                </div>
                <div class="text-xs text-gray-500 mt-0.5">
                  {{ field.key }}
                </div>
              </div>
              
              <!-- 旧值 -->
              <div class="col-span-5">
                <div 
                  :class="[
                    'rounded p-1 text-sm font-mono leading-5',
                    field.changed ? 'bg-red-500/10 text-red-300' : 'bg-gray-800/30 text-gray-400'
                  ]"
                >
                  <pre class="whitespace-pre-wrap break-all text-left" v-html="formatValue(field.oldValue)"></pre>
                </div>
              </div>
              
              <!-- 新值 -->
              <div class="col-span-5">
                <div 
                  :class="[
                    'rounded p-1 text-sm font-mono leading-5',
                    field.changed ? 'bg-green-500/10 text-green-300' : 'bg-gray-800/30 text-gray-400'
                  ]"
                >
                  <pre class="whitespace-pre-wrap break-all text-left" v-html="formatValue(field.newValue)"></pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
.custom-card {
  @apply bg-gray-800 rounded-lg shadow-lg border border-gray-700/50;
}

:deep(.arco-table) {
  @apply bg-transparent;
}

:deep(.arco-table-th) {
  @apply bg-gray-950 text-gray-200 border-gray-700;
}

:deep(.arco-table-td) {
  @apply bg-gray-800 text-gray-300 border-gray-700;
}

:deep(.arco-table-tr:hover .arco-table-td) {
  @apply bg-gray-700;
}

:deep(.arco-modal) {
  @apply bg-gray-800;
}

:deep(.arco-modal-header) {
  @apply bg-gray-800 border-gray-700;
}

:deep(.arco-modal-title) {
  @apply text-gray-200;
}

:deep(.arco-modal-body) {
  @apply p-4;
}

:deep(.arco-modal-footer) {
  @apply border-t border-gray-700 py-2;
}

.json-key {
  @apply text-blue-400;
}

.json-string {
  @apply text-green-400;
}

.json-number {
  @apply text-yellow-400;
}

.json-boolean {
  @apply text-purple-400;
}

.json-null {
  @apply text-red-400;
}

.json-diff-old {
  @apply bg-red-500/70;
}

.json-diff-new {
  @apply bg-green-500/70;
}

.diff-panel {
  @apply flex flex-col;
}

.diff-content {
  @apply h-[350px] overflow-auto p-3;
}
</style>