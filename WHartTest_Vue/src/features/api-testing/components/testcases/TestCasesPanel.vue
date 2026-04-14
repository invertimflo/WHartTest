<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import { testcaseService } from '../../services/testcaseService'
import type { ApiTestCase } from '../../types/testcase'
import { useProjectStore } from '@/store/projectStore'
import { useEnvironmentStore } from '../../stores/environmentStore'
import TestCaseSearch from './TestCaseSearch.vue'
import TestCaseFilter from './TestCaseFilter.vue'
import TestCaseTable from './TestCaseTable.vue'
import ReferencedInterfacesDialog from './ReferencedInterfacesDialog.vue'

const projectStore = useProjectStore()
const environmentStore = useEnvironmentStore()
const router = useRouter()
const loading = ref(false)
const testcases = ref<ApiTestCase[]>([])

const emit = defineEmits(['run'])

interface QueryParams {
  name?: string
  description?: string
  priority?: string
  group?: number
  tags?: number[]
  ordering?: string
  page?: number
  page_size?: number
}

const queryParams = reactive<QueryParams>({
  name: '',
  description: '',
  priority: undefined,
  group: undefined,
  tags: undefined,
  ordering: '-created_at',
  page: 1,
  page_size: 10
})

const pagination = reactive({
  current: 1,
  page_size: 10,
  total: 0,
  showTotal: true,
  showJumper: true,
  showPageSize: true
})

const fetchTestCases = async (page: number = 1) => {
  if (!projectStore.currentProjectId) return
  try {
    loading.value = true
    queryParams.page = page
    queryParams.page_size = pagination.page_size

    const res = await testcaseService.list(projectStore.currentProjectId, queryParams)
    if (res.success && res.data) {
      testcases.value = Array.isArray(res.data) ? res.data : (res.data as any).results || []
      pagination.total = (res.data as any).count || testcases.value.length
      pagination.current = page
    } else {
      throw new Error(res.error || '获取测试用例列表失败')
    }
  } catch (error) {
    console.error('Failed to fetch test cases:', error)
    Message.error(error instanceof Error ? error.message : '获取测试用例列表失败')
    testcases.value = []
    pagination.total = 0
  } finally {
    loading.value = false
  }
}

watch(() => projectStore.currentProjectId, (newProjectId) => {
  if (newProjectId) {
    pagination.current = 1
    fetchTestCases(1)
  }
})

const handleSortChange = (dataIndex: string, direction: string) => {
  queryParams.ordering = direction === 'ascend' ? dataIndex : `-${dataIndex}`
  fetchTestCases()
}

const handlePageChange = (current: number) => {
  pagination.current = current
  fetchTestCases(current)
}

const handleSearch = () => {
  pagination.current = 1
  fetchTestCases(1)
}

const handleReset = () => {
  Object.assign(queryParams, {
    name: '',
    description: '',
    priority: undefined,
    group: undefined,
    tags: undefined,
    ordering: '-created_at',
    page: 1,
    page_size: pagination.page_size
  })
  pagination.current = 1
  fetchTestCases(1)
}

const updateSearchParams = (data: Pick<QueryParams, 'name' | 'description'>) => {
  Object.assign(queryParams, data)
}

const updateFilterParams = (data: Pick<QueryParams, 'priority' | 'group' | 'tags'>) => {
  Object.assign(queryParams, data)
}

const handleCreate = () => {
  router.push({ name: 'ApiTestCaseCreate' })
}

const handleEdit = (testcase: ApiTestCase) => {
  router.push({ name: 'ApiTestCaseEdit', params: { id: testcase.id } })
}

const handleRun = async (testcase: ApiTestCase) => {
  if (!environmentStore.currentEnvironmentId) {
    Message.warning('请先选择环境')
    return
  }

  if (!projectStore.currentProjectId) return

  try {
    loading.value = true
    const res = await testcaseService.run(projectStore.currentProjectId, testcase.id!, {
      environment_id: Number(environmentStore.currentEnvironmentId)
    })
    if (res.success) {
      Message.success('用例运行成功')
    } else {
      throw new Error(res.error || '运行用例失败')
    }
  } catch (error) {
    console.error('运行用例失败:', error)
    Message.error(error instanceof Error ? error.message : '运行用例失败')
  } finally {
    loading.value = false
  }
}

const handleReport = (testcase: ApiTestCase) => {
  router.push({ name: 'ApiTestCaseReports', params: { id: testcase.id } })
}

const referencedInterfacesVisible = ref(false)
const currentTestcase = ref<ApiTestCase | null>(null)

const handleLink = (testcase: ApiTestCase) => {
  currentTestcase.value = testcase
  referencedInterfacesVisible.value = true
}

const handleReferencedInterfacesClose = () => {
  currentTestcase.value = null
}

const handleDelete = async (testcase: ApiTestCase) => {
  if (!projectStore.currentProjectId) return

  Modal.confirm({
    title: '确认删除',
    content: `确定要删除测试用例「${testcase.name}」吗？删除后将同时删除所有测试步骤和执行记录，且无法恢复。`,
    okText: '确认删除',
    cancelText: '取消',
    okButtonProps: {
      status: 'danger'
    },
    async onOk() {
      try {
        loading.value = true
        await testcaseService.delete(projectStore.currentProjectId!, testcase.id!)
        Message.success('测试用例删除成功')
        await fetchTestCases(pagination.current)
      } catch (error: any) {
        console.error('删除测试用例失败:', error)
        Message.error('删除测试用例失败')
      } finally {
        loading.value = false
      }
    }
  })
}

const handlePageSizeChange = (size: number) => {
  pagination.page_size = size
  pagination.current = 1
  fetchTestCases(1)
}

// 初始加载
fetchTestCases()
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <!-- 搜索区域 -->
    <div class="bg-gray-800/50 rounded-lg shadow-dark px-6 py-5 space-y-4">
      <div class="flex items-center gap-4">
        <div class="flex-1">
          <TestCaseSearch
            :model-value="{ name: queryParams.name, description: queryParams.description }"
            @update:model-value="updateSearchParams"
            @search="handleSearch"
            @reset="handleReset"
          />
        </div>
        <div class="flex-1">
          <TestCaseFilter
            :model-value="{
              priority: queryParams.priority,
              group: queryParams.group,
              tags: queryParams.tags
            }"
            :project-id="projectStore.currentProjectId"
            @update:model-value="updateFilterParams"
            @search="handleSearch"
          />
        </div>
        <div class="flex items-center gap-2">
          <a-button class="custom-reset-button" @click="handleReset">
            重置
          </a-button>
          <a-button type="primary" class="custom-add-button" @click="handleCreate">
            新增用例
          </a-button>
        </div>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 bg-gray-800/50 rounded-lg shadow-dark overflow-hidden">
      <div class="p-6">
        <TestCaseTable
          :data="testcases"
          :loading="loading"
          @sort="handleSortChange"
          @run="handleRun"
          @link="handleLink"
          @report="handleReport"
          @edit="handleEdit"
          @delete="handleDelete"
        />
      </div>
    </div>

    <!-- 分页区域 -->
    <div class="bg-gray-800/50 rounded-lg shadow-dark px-6 py-5">
      <a-pagination
        v-model:current="pagination.current"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        show-total
        show-jumper
        show-page-size
        class="flex justify-end"
        @change="handlePageChange"
        @page-size-change="handlePageSizeChange"
      />
    </div>

    <!-- 关联接口弹窗 -->
    <ReferencedInterfacesDialog
      v-model:visible="referencedInterfacesVisible"
      :testcase-id="currentTestcase?.id || 0"
      :testcase-name="currentTestcase?.name || ''"
      @close="handleReferencedInterfacesClose"
    />
  </div>
</template>

<style scoped>
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
      background-color: rgba(30, 41, 59, 0.5) !important;
      border: 1px solid rgba(148, 163, 184, 0.1) !important;
      color: #e2e8f0 !important;

      &:hover, &:focus {
        border-color: rgba(59, 130, 246, 0.5) !important;
        background-color: rgba(30, 41, 59, 0.7) !important;
      }
    }
  }

  .arco-pagination-total {
    color: #94a3b8 !important;
  }

  .arco-select-view {
    background-color: rgba(30, 41, 59, 0.5) !important;
    border: 1px solid rgba(148, 163, 184, 0.1) !important;
    border-radius: 4px !important;

    &:hover {
      border-color: rgba(59, 130, 246, 0.5) !important;
      background-color: rgba(30, 41, 59, 0.7) !important;
    }
  }
}

.custom-reset-button {
  background: rgba(148, 163, 184, 0.1) !important;
  border: 1px solid rgba(148, 163, 184, 0.2) !important;
  color: #94a3b8 !important;
  padding: 0 24px !important;
  height: 36px !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  transition: all 0.3s ease !important;

  &:hover {
    background: rgba(148, 163, 184, 0.2) !important;
    border-color: rgba(148, 163, 184, 0.3) !important;
    color: #e2e8f0 !important;
    transform: translateY(-1px) !important;
  }

  &:active {
    transform: translateY(1px) !important;
  }
}

.custom-add-button {
  background: linear-gradient(to right, #3b82f6, #1d4ed8) !important;
  border: none !important;
  padding: 0 24px !important;
  height: 36px !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.3) !important;

  &:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4) !important;
    background: linear-gradient(to right, #2563eb, #60a5fa) !important;
  }

  &:active {
    transform: translateY(1px) !important;
    box-shadow: 0 1px 3px rgba(59, 130, 246, 0.3) !important;
  }
}
</style>
