<script setup lang="ts">
import { ref, onMounted, computed, h, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/store/projectStore'
import { useEnvironmentStore } from '../../stores/environmentStore'
import { Message, Tag as ATag, Modal, Select, Option } from '@arco-design/web-vue'
import { 
  getTestTaskSuite, 
  createTestTaskSuite, 
  updateTestTaskSuite,
  getTestCases,
  createTestTaskExecution,
  type TestTaskSuiteForm,
  type TestCase
} from '../../services/testTaskService'

const props = defineProps({
  mode: {
    type: String,
    default: 'create',
    validator: (value: string) => ['create', 'edit', 'view'].includes(value)
  },
  id: {
    type: [String, Number],
    default: null
  }
})

const router = useRouter()
const projectStore = useProjectStore()
const environmentStore = useEnvironmentStore()
const loading = ref(false)
const submitting = ref(false)
const creatingAndExecuting = ref(false)

// 环境选择状态
const state = reactive({
  selectedEnvironmentId: undefined as number | undefined,
  selectedEnvironment: undefined as any
})

// 表单数据
const formData = ref<TestTaskSuiteForm>({
  name: '',
  description: '',
  priority: 'P2',
  fail_fast: false,
  project: projectStore.currentProjectId ? Number(projectStore.currentProjectId) : 0
})

// 测试用例列表
const testCases = ref<TestCase[]>([])
const selectedTestCases = ref<number[]>([])

// 表单规则
const rules = {
  name: [
    { required: true, message: '请输入任务名称' }
  ],
  priority: [
    { required: true, message: '请选择优先级' }
  ]
}

// 优先级选项（测试任务）
const priorityOptions = [
  { label: '最高', value: 'P0', color: 'red' },
  { label: '较高', value: 'P1', color: 'orange' },
  { label: '普通', value: 'P2', color: 'blue' },
  { label: '较低', value: 'P3', color: 'green' }
]

// 优先级颜色映射（测试用例）
const testCasePriorityColorMap = {
  'P0': 'red',
  'P1': 'orange',
  'P2': 'blue',
  'P3': 'green'
}

// 是否为只读模式
const isReadOnly = computed(() => props.mode === 'view')

// 获取测试任务详情
const fetchTestTaskSuite = async () => {
  if (!props.id) return

  loading.value = true
  try {
    const response = await getTestTaskSuite(Number(props.id))
    console.log('获取到的测试任务详情:', response)
    
    if (response && response.status === 'success' && response.data) {
      const { data } = response
      formData.value = {
        name: data.name,
        description: data.description || '',
        priority: data.priority,
        fail_fast: data.fail_fast,
        project: data.project
      }
      // 更新选中的测试用例，使用 testcase_id 而不是 testcase.id
      selectedTestCases.value = data.task_cases.map(tc => tc.testcase_id)
      console.log('已选中的测试用例:', selectedTestCases.value)
    } else {
      throw new Error(response?.message || '获取测试任务详情失败')
    }
  } catch (error) {
    console.error('获取测试任务详情失败', error)
    Message.error(error instanceof Error ? error.message : '获取测试任务详情失败')
  } finally {
    loading.value = false
  }
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

// 获取测试用例列表
const columns = [
  {
    title: '用例名称',
    dataIndex: 'name',
    align: 'center'
  },
  {
    title: '描述',
    dataIndex: 'description',
    align: 'center'
  },
  {
    title: '优先级',
    dataIndex: 'priority',
    align: 'center',
    render: ({ record }) => h(ATag, {
      color: testCasePriorityColorMap[record.priority]
    }, () => record.priority)
  },
  {
    title: '分组',
    dataIndex: 'group_info',
    align: 'center',
    render: ({ record }) => record.group_info?.name || '-'
  },
  {
    title: '标签',
    dataIndex: 'tags_info',
    align: 'center',
    render: ({ record }) => {
      if (!record.tags_info?.length) return '-'
      return h('div', {
        class: 'flex flex-wrap gap-1 justify-center'
      }, record.tags_info.map(tag => 
        h(ATag, {
          color: tag.color,
          class: 'whitespace-nowrap'
        }, () => tag.name)
      ))
    }
  },
  {
    title: '创建时间',
    dataIndex: 'created_at',
    align: 'center',
    render: ({ record }) => formatDate(record.created_at)
  },
  {
    title: '更新时间',
    dataIndex: 'updated_at',
    align: 'center',
    render: ({ record }) => formatDate(record.updated_at)
  }
]

// 搜索条件
const searchForm = ref({
  name: '',
  description: '',
  priority: undefined,
  group: undefined
})

// 重置搜索
const resetSearch = () => {
  searchForm.value = {
    name: '',
    description: '',
    priority: undefined,
    group: undefined
  }
  fetchTestCases()
}

// 执行搜索
const handleSearch = () => {
  fetchTestCases()
}

// 修改 fetchTestCases 函数
const fetchTestCases = async () => {
  if (!projectStore.currentProjectId) {
    Message.warning('请先选择项目')
    return
  }

  loading.value = true
  try {
    const response = await getTestCases({
      project: projectStore.currentProjectId,
      page: 1,
      page_size: 1000,
      name: searchForm.value.name,
      description: searchForm.value.description,
      priority: searchForm.value.priority,
      ordering: '-created_at'
    })
    testCases.value = response.data.results || []
  } catch (error) {
    console.error('获取测试用例列表失败', error)
    Message.error('获取测试用例列表失败')
  } finally {
    loading.value = false
  }
}

// 提交表单
const handleSubmit = async () => {
  if (!projectStore.currentProjectId) {
    Message.warning('请先选择项目')
    return
  }

  if (selectedTestCases.value.length === 0) {
    Message.warning('请至少选择一个测试用例')
    return
  }

  submitting.value = true
  try {
    if (props.mode === 'create') {
      await createTestTaskSuite({
        ...formData.value,
        test_cases: selectedTestCases.value
      })
      Message.success('创建成功')
    } else {
      await updateTestTaskSuite(Number(props.id), {
        ...formData.value,
        test_cases: selectedTestCases.value
      })
      Message.success('更新成功')
    }
    router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
  } catch (error) {
    console.error('提交失败', error)
    Message.error('提交失败')
  } finally {
    submitting.value = false
  }
}

// 创建并执行任务
const handleCreateAndExecute = async () => {
  if (!projectStore.currentProjectId) {
    Message.warning('请先选择项目')
    return
  }

  if (selectedTestCases.value.length === 0) {
    Message.warning('请至少选择一个测试用例')
    return
  }

  creatingAndExecuting.value = true
  try {
    // 1. 创建测试任务
    const createResponse = await createTestTaskSuite({
      ...formData.value,
      test_cases: selectedTestCases.value
    })
    
    if (createResponse.status !== 'success' || !createResponse.data) {
      throw new Error(createResponse.message || '创建测试任务失败')
    }
    
    const taskSuiteId = createResponse.data.id
    
    // 2. 加载环境列表
    await environmentStore.fetchEnvironments(projectStore.currentProjectId)
    
    if (environmentStore.environments.length === 0) {
      Message.warning('当前项目没有可用的环境，请先创建环境')
      router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
      return
    }

    // 初始化选中的环境为第一个环境
    state.selectedEnvironmentId = environmentStore.environments[0].id
    state.selectedEnvironment = environmentStore.environments[0]

    // 3. 打开环境选择弹窗
    Modal.open({
      title: '选择执行环境',
      titleAlign: 'start',
      width: 600,
      maskClosable: false,
      content: () => modalContent(),
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
          // 4. 执行测试任务
          const response = await createTestTaskExecution({
            task_suite_id: taskSuiteId,
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
              },
              onCancel: () => {
                router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
              }
            })
          } else {
            throw new Error(response.message || '启动任务执行失败')
          }
        } catch (error) {
          console.error('启动任务执行失败:', error)
          Message.error(error instanceof Error ? error.message : '启动任务执行失败')
          router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
        }
      },
      onCancel() {
        router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
      }
    })
  } catch (error) {
    console.error('创建并执行测试任务失败', error)
    Message.error(error instanceof Error ? error.message : '创建并执行测试任务失败')
  } finally {
    creatingAndExecuting.value = false
  }
}

// 环境选择弹窗内容
const modalContent = () => {
  return h('div', {
    class: 'space-y-4'
  }, [
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

// 返回列表页
const goBack = () => {
  router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
}

onMounted(async () => {
  if (projectStore.currentProjectId) {
    await fetchTestCases()
    if (props.mode !== 'create') {
      await fetchTestTaskSuite()
    }
  }
})
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <!-- 表单区域 -->
    <div class="flex-1 bg-gray-800/50 rounded-lg shadow-dark overflow-auto">
      <div class="p-6">
        <div class="flex justify-end gap-3 mb-6">
          <a-button type="outline" @click="goBack">返回</a-button>
          <a-button 
            v-if="!isReadOnly && props.mode === 'create'" 
            type="primary" 
            status="success"
            class="custom-create-execute-button"
            :loading="creatingAndExecuting" 
            @click="handleCreateAndExecute"
          >
            创建并执行
          </a-button>
          <a-button 
            v-if="!isReadOnly" 
            type="primary" 
            :loading="submitting" 
            @click="handleSubmit"
          >
            {{ props.mode === 'create' ? '创建' : '保存' }}
          </a-button>
        </div>

        <a-form 
          :model="formData" 
          :rules="rules" 
          layout="vertical"
          :disabled="loading || isReadOnly"
        >
          <!-- 基本信息 -->
          <div class="bg-gray-900/30 rounded-lg p-6 mb-6">
            <h3 class="text-lg font-medium mb-4 text-gray-200">基本信息</h3>
            <a-form-item field="name" label="任务名称">
              <a-input 
                v-model="formData.name" 
                placeholder="请输入任务名称" 
                allow-clear
              />
            </a-form-item>
            
            <a-form-item field="priority" label="优先级">
              <a-select 
                v-model="formData.priority" 
                placeholder="请选择优先级"
              >
                <a-option 
                  v-for="option in priorityOptions" 
                  :key="option.value" 
                  :value="option.value"
                >
                  <a-tag :color="option.color">{{ option.label }}</a-tag>
                </a-option>
              </a-select>
            </a-form-item>

            <a-form-item field="description" label="描述">
              <a-textarea 
                v-model="formData.description" 
                placeholder="请输入描述信息" 
                allow-clear
                :auto-size="{ minRows: 3, maxRows: 6 }"
              />
            </a-form-item>

            <a-form-item field="fail_fast">
              <a-checkbox v-model="formData.fail_fast">
                快速失败（遇到失败用例时立即停止执行）
              </a-checkbox>
            </a-form-item>
          </div>

          <!-- 测试用例选择部分 -->
          <a-divider>测试用例选择</a-divider>
          
          <!-- 搜索表单 -->
          <a-form layout="inline" :model="searchForm" class="mb-4">
            <a-form-item field="name" label="用例名称">
              <a-input
                v-model="searchForm.name"
                placeholder="请输入用例名称"
                allow-clear
              />
            </a-form-item>
            <a-form-item field="description" label="描述">
              <a-input
                v-model="searchForm.description"
                placeholder="请输入描述"
                allow-clear
              />
            </a-form-item>
            <a-form-item field="priority" label="优先级">
              <a-select
                v-model="searchForm.priority"
                placeholder="请选择优先级"
                allow-clear
              >
                <a-option v-for="option in priorityOptions" :key="option.value" :value="option.value">
                  <a-tag :color="option.color">{{ option.value }}</a-tag>
                </a-option>
              </a-select>
            </a-form-item>
            <a-form-item>
              <a-space>
                <a-button type="primary" @click="handleSearch">
                  搜索
                </a-button>
                <a-button @click="resetSearch">
                  重置
                </a-button>
              </a-space>
            </a-form-item>
          </a-form>

          <!-- 测试用例表格 -->
          <a-table
            :columns="columns"
            :data="testCases"
            :loading="loading"
            :pagination="false"
            row-key="id"
            v-model:selectedKeys="selectedTestCases"
            :row-selection="{
              type: 'checkbox',
              showCheckedAll: true
            }"
          >
            <template #name="{ record }">
              <a-tooltip :content="record.name">
                {{ record.name }}
              </a-tooltip>
            </template>
            
            <template #description="{ record }">
              <a-tooltip :content="record.description">
                {{ record.description || '-' }}
              </a-tooltip>
            </template>
          </a-table>
        </a-form>
      </div>
    </div>
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

.custom-table :deep(.arco-checkbox) {
  .arco-checkbox-mask {
    background-color: transparent !important;
    border-color: rgba(148, 163, 184, 0.3) !important;
  }

  &:hover .arco-checkbox-mask {
    border-color: #3b82f6 !important;
  }

  &.arco-checkbox-checked .arco-checkbox-mask {
    background-color: #3b82f6 !important;
    border-color: #3b82f6 !important;
  }
}

.test-task-form {
  padding: 24px;
}
.mb-4 {
  margin-bottom: 16px;
}

/* 创建并执行按钮样式 */
.custom-create-execute-button {
  @apply !bg-emerald-500/20 !text-emerald-400 !border-emerald-500/30;
  transition: all 0.3s ease !important;
  box-shadow: 0 1px 3px rgba(16, 185, 129, 0.1) !important;
  border-radius: 8px !important;

  &:hover {
    @apply !bg-emerald-500/30 !text-emerald-300 !border-emerald-500/40;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 5px rgba(16, 185, 129, 0.2) !important;
  }

  &:active {
    transform: translateY(1px) !important;
    box-shadow: 0 1px 2px rgba(16, 185, 129, 0.1) !important;
  }
}
</style> 