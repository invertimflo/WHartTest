<script setup lang="ts">
import { ref, onMounted, reactive, watch, h, computed } from 'vue'
import { useProjectStore } from '@/store/projectStore'
import { useEnvironmentStore } from '../../stores/environmentStore'
import { Message, Modal, Select, Option } from '@arco-design/web-vue'
import { useRouter } from 'vue-router'
import { IconEdit, IconDelete, IconPlayArrow, IconPlus, IconSearch, IconHistory } from '@arco-design/web-vue/es/icon'
import { 
  getTestTaskSuites, 
  deleteTestTaskSuite, 
  createTestTaskExecution,
  type TestTaskSuite 
} from '../../services/testTaskService'

const router = useRouter()
const projectStore = useProjectStore()
const environmentStore = useEnvironmentStore()
const loading = ref(false)
const testTaskSuites = ref<TestTaskSuite[]>([])

// 添加 state 定义
const state = reactive({
  selectedEnvironmentId: undefined as number | undefined,
  selectedEnvironment: undefined as any
})

// 分页
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0
})

// 搜索参数
const searchParams = ref({
  search: '',
  priority: undefined as number | undefined
})

// 获取测试任务集列表
const fetchTestTaskSuites = async () => {
  if (!projectStore.currentProjectId) {
    Message.warning('请先选择项目')
    return
  }

  loading.value = true
  try {
    const response = await getTestTaskSuites({
      project: projectStore.currentProjectId,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      search: searchParams.value.search || undefined,
      priority: searchParams.value.priority
    })
    testTaskSuites.value = response.data.results || []
    pagination.value.total = response.data.count || 0
  } catch (error) {
    console.error('获取测试任务集失败', error)
    Message.error('获取测试任务集失败')
  } finally {
    loading.value = false
  }
}

// 创建测试任务集
const createTestTaskSuite = () => {
  router.push({ name: 'ApiTestTaskCreate' })
}

// 查看测试任务集详情
const viewTestTaskSuite = (id: number) => {
  router.push({ name: 'ApiTestTaskDetail', params: { id } })
}

// 查看测试任务执行历史
const viewHistory = (id: number) => {
  router.push({ name: 'ApiTestTaskDetail', params: { id } })
}

// 编辑测试任务集
const handleEdit = (record: TestTaskSuite) => {
  router.push({
    name: 'ApiTestTaskEdit',
    params: { id: record.id }
  })
}

// 删除测试任务集
const handleDeleteTestTaskSuite = async (id: number) => {
  try {
    await deleteTestTaskSuite(id)
    Message.success('删除成功')
    fetchTestTaskSuites()
  } catch (error) {
    console.error('删除测试任务集失败', error)
    Message.error('删除测试任务集失败')
  }
}

// 运行任务
const handleRun = async (taskSuite: TestTaskSuite) => {
  if (!projectStore.currentProjectId) {
    Message.warning('请先选择项目')
    return
  }

  if (taskSuite.task_cases.length === 0) {
    Message.warning('当前任务集没有关联任何测试用例')
    return
  }

  try {
    loading.value = true
    
    // 确保环境列表已加载
    await environmentStore.fetchEnvironments(projectStore.currentProjectId)
    
    if (environmentStore.environments.length === 0) {
      Message.warning('当前项目没有可用的环境，请先创建环境')
      return
    }

    // 初始化选中的环境为第一个环境
    state.selectedEnvironmentId = environmentStore.environments[0].id
    state.selectedEnvironment = environmentStore.environments[0]

    // 打开弹窗
    Modal.open({
      title: '执行测试任务',
      titleAlign: 'start',
      width: 600,
      maskClosable: false,
      content: () => modalContent(taskSuite),
      okText: '开始执行',
      cancelText: '取消',
      okButtonProps: {
        type: 'primary',
        status: 'success'
      },
      async onOk() {
        if (!state.selectedEnvironmentId) {
          Message.warning('请选择执行环境')
          return false
        }

        try {
          loading.value = true
          const response = await createTestTaskExecution({
            task_suite_id: taskSuite.id,
            environment_id: state.selectedEnvironmentId
          })

          if (response.status === 'success') {
            Message.success('任务执行已启动')
            // 询问用户是否查看执行详情
            Modal.confirm({
              title: '执行已启动',
              content: '是否立即查看执行详情？',
              okText: '查看详情',
              cancelText: '留在当前页面',
              onOk: () => {
                router.push({
                  name: 'ApiTestTaskExecutionDetail',
                  params: { id: response.data.id }
                })
              }
            })
          } else {
            throw new Error(response.message || '启动任务执行失败')
          }
        } catch (error) {
          console.error('启动任务执行失败:', error)
          Message.error(error instanceof Error ? error.message : '启动任务执行失败')
        } finally {
          loading.value = false
        }
      }
    })
  } catch (error) {
    console.error('加载环境列表失败:', error)
    Message.error('加载环境列表失败')
  } finally {
    loading.value = false
  }
}

const modalContent = (taskSuite: TestTaskSuite) => {
  return h('div', {
    class: 'space-y-4'
  }, [
    // 任务信息
    h('div', { class: 'space-y-2' }, [
      h('div', { class: 'text-gray-400' }, '任务信息'),
      h('div', { class: 'bg-gray-700/30 p-4 rounded-lg space-y-2' }, [
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, '任务名称：'),
          h('span', { class: 'text-gray-200' }, taskSuite.name)
        ]),
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, '用例数量：'),
          h('span', { class: 'text-gray-200' }, `${taskSuite.task_cases.length} 个`)
        ])
      ])
    ]),
    
    // 环境选择
    h('div', { class: 'space-y-2' }, [
      h('div', { class: 'text-gray-400' }, '执行环境'),
      h(Select, {
        modelValue: state.selectedEnvironmentId,
        'onUpdate:modelValue': (value: number) => {
          state.selectedEnvironmentId = value
          state.selectedEnvironment = environmentStore.environments.find(env => env.id === value) || environmentStore.environments[0]
        },
        placeholder: '请选择执行环境',
        allowClear: false,
        class: 'w-full'
      }, {
        default: () => environmentStore.environments.map(env => 
          h(Option, {
            key: env.id,
            value: env.id,
            label: env.name
          })
        )
      })
    ]),

    // 环境详情
    state.selectedEnvironmentId && h('div', { class: 'space-y-2' }, [
      h('div', { class: 'text-gray-400' }, '环境详情'),
      h('div', { class: 'bg-gray-700/30 p-4 rounded-lg space-y-2' }, [
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, 'Base URL：'),
          h('span', { class: 'text-gray-200' }, state.selectedEnvironment.base_url)
        ]),
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, '变量数量：'),
          h('span', { class: 'text-gray-200' }, `${state.selectedEnvironment.variables?.length || 0} 个`)
        ]),
        state.selectedEnvironment.description && h('div', { class: 'flex items-start gap-2' }, [
          h('span', { class: 'text-gray-400' }, '环境描述：'),
          h('span', { class: 'text-gray-200' }, state.selectedEnvironment.description)
        ])
      ])
    ])
  ])
}

// 页码变化
const handlePageChange = (page: number) => {
  pagination.value.current = page
  fetchTestTaskSuites()
}

// 每页条数变化
const handlePageSizeChange = (pageSize: number) => {
  pagination.value.pageSize = pageSize
  pagination.value.current = 1
  fetchTestTaskSuites()
}

// 处理搜索
const handleSearch = (params: any) => {
  searchParams.value = { ...searchParams.value, ...params }
  pagination.value.current = 1
  fetchTestTaskSuites()
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 优先级颜色映射
const priorityColorMap: Record<string, string> = {
  'P0': 'red',
  'P1': 'orange',
  'P2': 'blue',
  'P3': 'gray'
}

// 优先级文本映射
const priorityTextMap: Record<string, string> = {
  'P0': '最高',
  'P1': '较高',
  'P2': '普通',
  'P3': '较低'
}

// 组件挂载时加载环境列表
onMounted(async () => {
  if (projectStore.currentProjectId) {
    fetchTestTaskSuites()
    // 加载环境列表
    try {
      await environmentStore.fetchEnvironments(projectStore.currentProjectId)
    } catch (error) {
      console.error('加载环境列表失败:', error)
    }
  }
})

// 监听项目变化时重新加载环境列表
watch(() => projectStore.currentProjectId, async (newProjectId) => {
  if (newProjectId) {
    try {
      await environmentStore.fetchEnvironments(newProjectId)
    } catch (error) {
      console.error('加载环境列表失败:', error)
    }
  }
})
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <!-- 搜索区域 -->
    <div class="bg-gray-800/85 rounded-lg shadow-dark px-6 py-5">
      <div class="flex items-center gap-4">
        <div class="flex-1 flex items-center gap-4">
          <a-input
            v-model="searchParams.search"
            placeholder="搜索任务名称或描述"
            allow-clear
            class="w-64"
            @press-enter="fetchTestTaskSuites"
          >
            <template #prefix>
              <icon-search />
            </template>
          </a-input>
          
          <a-select
            v-model="searchParams.priority"
            placeholder="优先级"
            allow-clear
            class="w-32"
            @change="fetchTestTaskSuites"
          >
            <a-option :value="0">低</a-option>
            <a-option :value="1">中</a-option>
            <a-option :value="2">高</a-option>
            <a-option :value="3">紧急</a-option>
          </a-select>
          
          <a-button type="outline" class="custom-reset-button" @click="() => {
            searchParams.search = '';
            searchParams.priority = undefined;
            fetchTestTaskSuites();
          }">
            重置
          </a-button>
          
          <a-button type="primary" class="custom-search-button" @click="fetchTestTaskSuites">
            搜索
          </a-button>
        </div>

        <a-button type="primary" class="custom-add-button" @click="createTestTaskSuite">
          <template #icon>
            <icon-plus />
          </template>
          新建测试任务
        </a-button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 bg-gray-800/85 rounded-lg shadow-dark overflow-hidden">
      <div class="p-6">
        <a-table
          :loading="loading"
          :data="testTaskSuites"
          :pagination="false"
          :bordered="false"
          :scroll="{ y: 'calc(100vh - 400px)' }"
          :sticky-header="true"
          class="custom-table"
        >
          <template #columns>
            <a-table-column title="ID" data-index="id" :width="80" align="center" />
            <a-table-column title="名称" data-index="name" :width="200" align="center">
              <template #cell="{ record }">
                <span 
                  class="name-link text-blue-400 hover:text-blue-500 cursor-pointer hover:underline" 
                  @click="viewTestTaskSuite(record.id)"
                >
                  {{ record.name }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="描述" data-index="description" :width="250" align="center">
              <template #cell="{ record }">
                <div class="text-gray-300">{{ record.description || '-' }}</div>
              </template>
            </a-table-column>
            <a-table-column title="优先级" data-index="priority" :width="100" align="center">
              <template #cell="{ record }">
                <a-tag :color="priorityColorMap[record.priority] || 'gray'">
                  {{ priorityTextMap[record.priority] || '未知' }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="关联用例数" data-index="task_cases" :width="120" align="center">
              <template #cell="{ record }">
                <div class="text-gray-300">{{ record.task_cases?.length || 0 }}</div>
              </template>
            </a-table-column>
            <a-table-column title="创建时间" data-index="created_at" :width="160" align="center">
              <template #cell="{ record }">
                <div class="text-gray-400">{{ formatDate(record.created_at) }}</div>
              </template>
            </a-table-column>
            <a-table-column title="更新时间" data-index="updated_at" :width="160" align="center">
              <template #cell="{ record }">
                <div class="text-gray-400">{{ formatDate(record.updated_at) }}</div>
              </template>
            </a-table-column>
            <a-table-column title="操作" align="center" :width="320" fixed="right">
              <template #cell="{ record }">
                <div class="flex items-center justify-center gap-2">
                  <a-button
                    type="primary"
                    size="mini"
                    class="btn-run"
                    @click="handleRun(record)"
                  >
                    <template #icon>
                      <icon-play-arrow />
                    </template>
                    执行
                  </a-button>
                  <a-button 
                    type="primary"
                    size="mini"
                    class="btn-history"
                    @click="viewHistory(record.id)"
                  >
                    <template #icon>
                      <icon-history />
                    </template>
                    历史
                  </a-button>
                  <a-button 
                    type="primary"
                    size="mini"
                    class="btn-edit"
                    @click="handleEdit(record)"
                  >
                    <template #icon>
                      <icon-edit />
                    </template>
                    编辑
                  </a-button>
                  <a-popconfirm
                    content="确定要删除这个测试任务集吗？"
                    position="left"
                    class="custom-popconfirm"
                    @ok="handleDeleteTestTaskSuite(record.id)"
                  >
                    <a-button
                      type="primary"
                      size="mini"
                      status="danger"
                      class="btn-delete"
                    >
                      <template #icon>
                        <icon-delete />
                      </template>
                      删除
                    </a-button>
                  </a-popconfirm>
                </div>
              </template>
            </a-table-column>
          </template>
          <template #empty>
            <div class="text-gray-400 py-8 flex justify-center items-center">
              暂无数据
            </div>
          </template>
        </a-table>
      </div>
    </div>

    <!-- 分页区域 -->
    <div class="bg-gray-800/85 rounded-lg shadow-dark px-6 py-5">
      <a-pagination
        v-model:current="pagination.current"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        show-total
        show-jumper
        show-page-size
        class="flex justify-end"
        @change="handlePageChange"
        @page-size-change="handlePageSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
/* 自定义滚动条 */
.custom-scrollbar {
  scrollbar-width: none !important;
  -ms-overflow-style: none !important;
  &::-webkit-scrollbar {
    display: none !important;
  }
}

/* 分页样式 */
:deep(.arco-pagination) {
  .arco-pagination-item {
    border-radius: 4px !important;
    color: #94a3b8 !important;
    background-color: transparent !important;
    border: 1px solid transparent !important;
    
    &:hover {
      color: #60a5fa !important;
      background-color: rgba(59, 130, 246, 0.1) !important;
      border-color: rgba(59, 130, 246, 0.2) !important;
    }
    
    &.arco-pagination-item-active {
      background-color: rgba(59, 130, 246, 0.2) !important;
      color: #60a5fa !important;
      border-color: rgba(59, 130, 246, 0.3) !important;
    }
  }

  .arco-pagination-jumper {
    .arco-input {
      border-radius: 4px !important;
      background-color: rgba(51, 65, 85, 0.25) !important;
      border: 1px solid rgba(148, 163, 184, 0.15) !important;
      color: #f1f5f9 !important;
      backdrop-filter: blur(4px) !important;

      &:hover, &:focus {
        border-color: rgba(59, 130, 246, 0.4) !important;
        background-color: rgba(51, 65, 85, 0.35) !important;
      }
    }
  }

  .arco-pagination-total {
    color: #cbd5e1 !important;
  }

  .arco-select-view {
    background-color: rgba(51, 65, 85, 0.25) !important;
    border: 1px solid rgba(148, 163, 184, 0.15) !important;
    border-radius: 4px !important;
    backdrop-filter: blur(4px) !important;

    &:hover {
      border-color: rgba(59, 130, 246, 0.4) !important;
      background-color: rgba(51, 65, 85, 0.35) !important;
    }
  }
}

.custom-add-button {
  @apply !bg-blue-500/20 !text-blue-400 !border-blue-500/30;
  padding: 0 24px !important;
  height: 36px !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 1px 3px rgba(59, 130, 246, 0.1) !important;

  &:hover {
    @apply !bg-blue-500/30 !text-blue-300 !border-blue-500/40;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 5px rgba(59, 130, 246, 0.2) !important;
  }

  &:active {
    transform: translateY(1px) !important;
    box-shadow: 0 1px 2px rgba(59, 130, 246, 0.1) !important;
  }
}

.custom-reset-button {
  background-color: transparent !important;
  border: 1px solid rgba(148, 163, 184, 0.3) !important;
  color: #cbd5e1 !important;
  transition: all 0.3s ease !important;
  border-radius: 8px !important;

  &:hover {
    border-color: rgba(148, 163, 184, 0.5) !important;
    color: #f1f5f9 !important;
    background-color: rgba(148, 163, 184, 0.1) !important;
  }
}

.custom-search-button {
  @apply !bg-blue-500/20 !text-blue-400 !border-blue-500/30;
  transition: all 0.3s ease !important;
  box-shadow: 0 1px 3px rgba(59, 130, 246, 0.1) !important;
  border-radius: 8px !important;

  &:hover {
    @apply !bg-blue-500/30 !text-blue-300 !border-blue-500/40;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 5px rgba(59, 130, 246, 0.2) !important;
  }

  &:active {
    transform: translateY(1px) !important;
    box-shadow: 0 1px 2px rgba(59, 130, 246, 0.1) !important;
  }
}

/* 表格样式 */
.custom-table :deep(.arco-table) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-container) {
  background-color: transparent !important;
  border: none !important;
}

.custom-table :deep(.arco-table-header) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-body) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-th) {
  background-color: rgba(30, 41, 59, 0.7) !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2) !important;
  color: #f1f5f9 !important;
  font-weight: 500 !important;
  text-align: center !important;
}

.custom-table :deep(.arco-table-td) {
  background-color: transparent !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15) !important;
  color: #e2e8f0 !important;
}

.custom-table :deep(.arco-table-tr) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-tr:nth-child(even)) {
  background-color: rgba(30, 41, 59, 0.3) !important;
}

.custom-table :deep(.arco-table-tr:nth-child(odd)) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-tr:hover) {
  background-color: rgba(30, 41, 59, 0.6) !important;
}

/* 表格中的操作按钮间距 */
.gap-2 {
  @apply !space-x-1;
}

/* 操作按钮样式 */
.btn-edit {
  @apply !bg-blue-500/20 hover:!bg-blue-500/30 !border-blue-500/30 !text-blue-400 !px-1.5;
  box-shadow: 0 1px 3px rgba(37, 99, 235, 0.1) !important;
  backdrop-filter: blur(4px) !important;
  background-color: rgba(15, 23, 42, 0.6) !important;
  
  &:hover {
    @apply !shadow-md !transform !scale-105 !text-blue-300;
    box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2) !important;
    background-color: rgba(15, 23, 42, 0.7) !important;
  }
}

.btn-run {
  @apply !bg-emerald-500/20 hover:!bg-emerald-500/30 !border-emerald-500/30 !text-emerald-400 !px-1.5;
  box-shadow: 0 1px 3px rgba(5, 150, 105, 0.1) !important;
  backdrop-filter: blur(4px) !important;
  background-color: rgba(15, 23, 42, 0.6) !important;
  
  &:hover {
    @apply !shadow-md !transform !scale-105 !text-emerald-300;
    box-shadow: 0 2px 4px rgba(5, 150, 105, 0.2) !important;
    background-color: rgba(15, 23, 42, 0.7) !important;
  }
}

.btn-history {
  @apply !bg-purple-500/20 hover:!bg-purple-500/30 !border-purple-500/30 !text-purple-400 !px-1.5;
  box-shadow: 0 1px 3px rgba(147, 51, 234, 0.1) !important;
  backdrop-filter: blur(4px) !important;
  background-color: rgba(15, 23, 42, 0.6) !important;
  
  &:hover {
    @apply !shadow-md !transform !scale-105 !text-purple-300;
    box-shadow: 0 2px 4px rgba(147, 51, 234, 0.2) !important;
    background-color: rgba(15, 23, 42, 0.7) !important;
  }
}

.btn-delete {
  @apply !bg-rose-500/20 hover:!bg-rose-500/30 !border-rose-500/30 !text-rose-400 !px-1.5;
  box-shadow: 0 1px 3px rgba(225, 29, 72, 0.1) !important;
  backdrop-filter: blur(4px) !important;
  background-color: rgba(15, 23, 42, 0.6) !important;
  
  &:hover {
    @apply !shadow-md !transform !scale-105 !text-rose-300;
    box-shadow: 0 2px 4px rgba(225, 29, 72, 0.2) !important;
    background-color: rgba(15, 23, 42, 0.7) !important;
  }
}

/* 确保所有按钮样式统一 */
.btn-edit, .btn-run, .btn-history, .btn-delete {
  @apply !h-8 !font-medium !rounded-md;
  transition: all 0.2s ease;
  position: relative;
  z-index: 1;
}

/* 弹窗样式 */
:deep(.custom-popconfirm) {
  .arco-popconfirm {
    @apply !p-2;
  }
  
  .arco-popconfirm-title {
    @apply !text-sm !mb-2;
  }
  
  .arco-btn {
    @apply !text-xs !h-6 !px-2;
  }
}

:deep(.arco-modal) {
  @apply !bg-gray-700/90;
  backdrop-filter: blur(8px) !important;
  
  .arco-modal-header {
    @apply !bg-gray-700/90 !border-gray-600/50 !pb-2;
    
    .arco-modal-title {
      @apply !text-gray-100;
    }
  }
  
  .arco-modal-content {
    @apply !bg-gray-700/90 !text-gray-100;
  }
  
  .arco-modal-footer {
    @apply !bg-gray-700/90 !border-gray-600/50 !pt-2;
  }
}

:deep(.arco-select) {
  @apply !bg-gray-600/80 !border-gray-500/50;
  width: 100%;
  backdrop-filter: blur(4px) !important;
  
  &:hover, &:focus {
    @apply !border-blue-500/70;
  }
  
  .arco-select-view {
    @apply !bg-gray-600/80 !text-gray-100 !border-gray-500/50;
    backdrop-filter: blur(4px) !important;
    
    &:hover {
      @apply !border-blue-500/70;
    }
  }
}

:deep(.arco-select-dropdown) {
  @apply !bg-gray-600/90;
  @apply !border-gray-500/50;
  backdrop-filter: blur(8px) !important;
  
  .arco-select-option {
    @apply !text-gray-100;
    
    &:hover {
      @apply !bg-gray-500/80;
    }
    
    &.arco-select-option-selected {
      @apply !bg-blue-500/30 !text-blue-300;
    }
  }
}

/* 名称链接样式 */
.name-link {
  transition: all 0.2s ease;
}
</style> 