<script setup lang="ts">
import { ref, onMounted, reactive, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Message, Modal, Select } from '@arco-design/web-vue'
import { Option } from '@arco-design/web-vue/es/select'
import { IconEdit, IconDelete, IconPlayArrow, IconPlus } from '@arco-design/web-vue/es/icon'
import { 
  getTestTaskSuite, 
  deleteTestTaskSuite, 
  createTestTaskExecution,
  removeTestCaseFromSuite,
  addTestCaseToSuite,
  getTestCases,
  type TestTaskSuite,
  type TestCase 
} from '../../services/testTaskService'
import AddTestCaseModal from './AddTestCaseModal.vue'
import { useEnvironmentStore } from '../../stores/environmentStore'
import { useProjectStore } from '@/store/projectStore'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const testTaskSuite = ref<TestTaskSuite | null>(null)
const environmentStore = useEnvironmentStore()
const projectStore = useProjectStore()

// 环境选择状态
const state = reactive({
  selectedEnvironmentId: 0,
  selectedEnvironment: null as any
})

// 添加用例相关
const addVisible = ref(false)
const addLoading = ref(false)
const testCases = ref<TestCase[]>([])
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0
})

// 从测试任务集中移除测试用例
const removeTestCase = async (testcaseId: number) => {
  try {
    await removeTestCaseFromSuite(Number(route.params.id), testcaseId)
    Message.success('移除成功')
    // 重新加载测试任务集详情
    await fetchTestTaskSuite()
  } catch (error) {
    console.error('移除测试用例失败', error)
    Message.error('移除测试用例失败')
  }
}

// 获取测试任务集详情
const fetchTestTaskSuite = async () => {
  const id = Number(route.params.id)
  if (!id) {
    console.error('无效的任务ID')
    Message.error('无效的任务ID')
    return
  }

  loading.value = true
  try {
    console.log('开始获取测试任务集详情，ID:', id)
    const response = await getTestTaskSuite(id)
    console.log('获取到的响应:', response)
    
    if (response && response.status === 'success' && response.data) {
      console.log('设置测试任务集数据:', response.data)
      testTaskSuite.value = response.data
      console.log('数据设置完成，当前值:', testTaskSuite.value)
    } else {
      console.error('响应异常:', response)
      throw new Error(response?.message || '获取测试任务集详情失败')
    }
  } catch (error) {
    console.error('获取测试任务集详情失败', error)
    if (error instanceof Error) {
      console.error('错误详情:', error.message)
      Message.error(error.message)
    } else {
      console.error('未知错误:', error)
      Message.error('获取测试任务集详情失败')
    }
  } finally {
    loading.value = false
  }
}

// 编辑测试任务集
const handleEdit = () => {
  router.push({
    name: 'ApiTestTaskEdit',
    params: { id: route.params.id }
  })
}

// 删除测试任务集
const handleDelete = async () => {
  try {
    await deleteTestTaskSuite(Number(route.params.id))
    Message.success('删除成功')
    router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
  } catch (error) {
    console.error('删除测试任务集失败', error)
    Message.error('删除测试任务集失败')
  }
}

// 执行测试任务集
const handleRun = async () => {
  if (!testTaskSuite.value) {
    Message.warning('测试任务集数据不存在')
    return
  }

  if (testTaskSuite.value.task_cases.length === 0) {
    Message.warning('当前任务集没有关联任何测试用例')
    return
  }

  try {
    loading.value = true
    
    // 确保环境列表已加载
    await environmentStore.fetchEnvironments(testTaskSuite.value.project)
    
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
      content: () => modalContent(testTaskSuite.value!),
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
            task_suite_id: testTaskSuite.value!.id,
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

// 环境选择弹窗内容
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
  ])
}

// 返回列表页
const goBack = () => {
  router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
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

// 优先级文本映射
const priorityTextMap: Record<string, string> = {
  'P0': '最高',
  'P1': '较高',
  'P2': '普通',
  'P3': '较低'
}

// 优先级颜色映射
const priorityColorMap: Record<string, string> = {
  'P0': 'red',
  'P1': 'orange',
  'P2': 'blue',
  'P3': 'green'
}

// 测试用例优先级颜色映射
const testCasePriorityColorMap: Record<string, string> = {
  'P0': 'red',
  'P1': 'orange',
  'P2': 'blue',
  'P3': 'green'
}

// 获取可添加的测试用例列表
const fetchTestCases = async () => {
  if (!testTaskSuite.value?.project) return
  
  addLoading.value = true
  try {
    const response = await getTestCases({
      project: testTaskSuite.value.project,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      ordering: '-created_at'
    })
    testCases.value = response.data.results
    pagination.value.total = response.data.count
  } catch (error) {
    console.error('获取测试用例列表失败', error)
    Message.error('获取测试用例列表失败')
  } finally {
    addLoading.value = false
  }
}

// 打开添加用例弹窗
const openAddDialog = async () => {
  pagination.value.current = 1
  addVisible.value = true
  await fetchTestCases()
}

// 处理分页变化
const handlePageChange = (current: number) => {
  pagination.value.current = current
  fetchTestCases()
}

// 处理每页条数变化
const handlePageSizeChange = (pageSize: number) => {
  pagination.value.pageSize = pageSize
  pagination.value.current = 1
  fetchTestCases()
}

// 处理添加测试用例
const handleAdd = async (selectedIds: number[]) => {
  try {
    await addTestCaseToSuite(Number(route.params.id), selectedIds)
    Message.success('添加成功')
    addVisible.value = false
    // 重新加载测试任务集详情
    await fetchTestTaskSuite()
  } catch (error) {
    console.error('添加测试用例失败', error)
    Message.error('添加测试用例失败')
  }
}

onMounted(() => {
  fetchTestTaskSuite()
})
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <a-spin :loading="loading" class="flex-1">
      <!-- 头部操作区 -->
      <div class="bg-gray-800/50 rounded-lg shadow-dark px-6 py-4 mb-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-4">
            <h2 class="text-xl font-medium text-gray-100">
              {{ testTaskSuite?.name }}
            </h2>
            <a-tag :color="priorityColorMap[testTaskSuite?.priority || 'P2']">
              {{ priorityTextMap[testTaskSuite?.priority || 'P2'] }}
            </a-tag>
          </div>
          <div class="flex gap-3">
            <a-button type="outline" @click="goBack">返回</a-button>
            <a-button type="primary" status="success" class="transparent-btn" @click="handleRun">
              <template #icon><icon-play-arrow /></template>
              执行
            </a-button>
            <a-button type="primary" class="transparent-btn" @click="handleEdit">
              <template #icon><icon-edit /></template>
              编辑
            </a-button>
            <a-popconfirm
              content="确定要删除这个测试任务集吗？"
              @ok="handleDelete"
            >
              <a-button type="primary" status="danger" class="transparent-btn">
                <template #icon><icon-delete /></template>
                删除
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>

      <!-- 基本信息 -->
      <div class="bg-gray-800/50 rounded-lg shadow-dark px-6 py-5 mb-4">
        <h3 class="text-lg font-medium text-gray-100 mb-4">基本信息</h3>
        <div class="grid grid-cols-2 gap-6">
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">描述</div>
            <div class="text-gray-100">{{ testTaskSuite?.description || '-' }}</div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">快速失败</div>
            <div class="text-gray-100">
              {{ testTaskSuite?.fail_fast ? '是' : '否' }}
            </div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">所属项目</div>
            <div class="text-gray-100">{{ testTaskSuite?.project_name }}</div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">创建人</div>
            <div class="text-gray-100">{{ testTaskSuite?.created_by_name }}</div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">创建时间</div>
            <div class="text-gray-100">{{ formatDate(testTaskSuite?.created_at || '') }}</div>
          </div>
          <div class="flex flex-col gap-2">
            <div class="text-gray-400">更新时间</div>
            <div class="text-gray-100">{{ formatDate(testTaskSuite?.updated_at || '') }}</div>
          </div>
        </div>
      </div>

      <!-- 测试用例列表 -->
      <div class="bg-gray-800/50 rounded-lg shadow-dark px-6 py-5">
        <div class="flex justify-between items-center mb-4">
          <div class="flex items-center gap-4">
            <h3 class="text-lg font-medium text-gray-100">测试用例列表</h3>
            <div class="text-gray-400">
              共 {{ testTaskSuite?.task_cases?.length || 0 }} 个用例
            </div>
          </div>
          <div>
            <a-button
              type="outline"
              size="small"
              @click="openAddDialog"
            >
              <template #icon><icon-plus /></template>
              添加用例
            </a-button>
          </div>
        </div>
        
        <a-table
          :data="testTaskSuite?.task_cases || []"
          :pagination="false"
          :bordered="false"
          :scroll="{ y: 'calc(100vh - 600px)' }"
          :sticky-header="true"
          class="custom-table"
          stripe
        >
          <template #columns>
            <a-table-column title="序号" data-index="order" :width="80" align="center" />
            <a-table-column title="用例名称" data-index="testcase_name" :width="200" align="center">
              <template #cell="{ record }">
                <span class="text-blue-400 hover:text-blue-500 cursor-pointer">
                  {{ record.testcase_name }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="描述" data-index="description" align="center">
              <template #cell="{ record }">
                <div class="text-gray-300">{{ record.description || '-' }}</div>
              </template>
            </a-table-column>
            <a-table-column title="优先级" data-index="priority" :width="100" align="center">
              <template #cell="{ record }">
                <a-tag :color="testCasePriorityColorMap[record.priority]">
                  {{ record.priority }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="100" align="center">
              <template #cell="{ record }">
                <a-popconfirm
                  content="确定要移除这个测试用例吗？"
                  @ok="() => removeTestCase(record.testcase_id)"
                  position="left"
                  popup-container="body"
                  class="custom-popconfirm"
                >
                  <a-button
                    type="text"
                    status="danger"
                    size="mini"
                  >
                    <template #icon><icon-delete /></template>
                  </a-button>
                </a-popconfirm>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </a-spin>

    <!-- 添加用例弹窗组件 -->
    <AddTestCaseModal
      v-model:visible="addVisible"
      :loading="addLoading"
      :test-cases="testCases"
      :pagination="{
        current: pagination.current,
        pageSize: pagination.pageSize,
        total: pagination.total
      }"
      :existing-ids="testTaskSuite?.task_cases?.map(tc => tc.testcase_id) || []"
      @page-change="handlePageChange"
      @page-size-change="handlePageSizeChange"
      @add="handleAdd"
    />
  </div>
</template>

<style scoped>
@reference "tailwindcss";
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
  background-color: rgba(30, 41, 59, 0.5) !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1) !important;
  color: #e2e8f0 !important;
  font-weight: 500 !important;
  text-align: center !important;
}

.custom-table :deep(.arco-table-td) {
  background-color: transparent !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1) !important;
  color: #cbd5e1 !important;
}

.custom-table :deep(.arco-table-tr) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-tr:hover) {
  background-color: rgba(30, 41, 59, 0.5) !important;
}

/* 按钮样式 */
:deep(.arco-btn-outline) {
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  color: #94a3b8 !important;
  
  &:hover {
    border-color: rgba(59, 130, 246, 0.5) !important;
    color: #60a5fa !important;
    background-color: rgba(59, 130, 246, 0.1) !important;
  }
}

/* 透明按钮样式 */
:deep(.transparent-btn) {
  opacity: 0.85 !important;
  backdrop-filter: blur(2px) !important;
}

:deep(.transparent-btn:hover) {
  opacity: 1 !important;
}

/* 弹窗样式 */
:deep(.custom-popconfirm .arco-trigger-popup) {
  @apply text-sm;
  max-width: 200px;
}

:deep(.custom-popconfirm .arco-popconfirm-message) {
  @apply text-sm mb-2;
}

:deep(.custom-popconfirm .arco-btn) {
  @apply text-sm h-7 px-3;
}
</style>