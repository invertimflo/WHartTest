<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { testcaseService } from '../../services/testcaseService'
import { useProjectStore } from '@/store/projectStore'

interface ReferencedInterface {
  interface: {
    id: number
    name: string
    method: string
    url: string
    module: { id: number; name: string } | null
    project: { id: number; name: string }
  }
  step: {
    id: number
    name: string
    order: number
  }
}

const props = defineProps<{
  visible: boolean
  testcaseId: number
  testcaseName: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', visible: boolean): void
  (e: 'close'): void
}>()

const projectStore = useProjectStore()
const loading = ref(false)
const interfaces = ref<ReferencedInterface[]>([])
const currentPage = ref(1)
const pageSize = ref(10)

const currentPageData = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return interfaces.value?.slice(start, end) || []
})

const fetchReferencedInterfaces = async () => {
  if (!projectStore.currentProjectId) return
  try {
    loading.value = true
    const res = await testcaseService.referencedInterfaces(projectStore.currentProjectId, props.testcaseId)
    if (res.success && res.data) {
      interfaces.value = []
      const data = Array.isArray(res.data) ? res.data : []
      data.forEach((item: any) => {
        if (item.steps && Array.isArray(item.steps)) {
          item.steps.forEach((step: {
            id: number
            name: string
            order: number
            sync_fields?: any[]
            last_sync_time?: string | null
          }) => {
            interfaces.value.push({
              interface: {
                id: item.id,
                name: item.name,
                method: item.method,
                url: item.url,
                module: typeof item.module === 'string'
                  ? { id: 0, name: item.module }
                  : (item.module || null),
                project: { id: props.testcaseId, name: props.testcaseName }
              },
              step: {
                id: step.id,
                name: step.name,
                order: step.order
              }
            })
          })
        }
      })
    } else {
      Message.error('获取关联接口失败')
    }
  } catch (error) {
    console.error('获取关联接口失败:', error)
    Message.error('获取关联接口失败')
  } finally {
    loading.value = false
  }
}

const getMethodColor = (method: string) => {
  const colorMap: Record<string, string> = {
    GET: 'blue',
    POST: 'green',
    PUT: 'orange',
    DELETE: 'red',
    PATCH: 'purple'
  }
  return colorMap[method] || 'gray'
}

const handleClose = () => {
  emit('update:visible', false)
  emit('close')
}

const handlePageChange = (page: number) => {
  currentPage.value = page
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
}

const resetPagination = () => {
  currentPage.value = 1
}

watch(
  () => props.visible,
  (newVal) => {
    if (newVal && props.testcaseId) {
      resetPagination()
      fetchReferencedInterfaces()
    } else {
      interfaces.value = []
    }
  }
)
</script>

<template>
  <a-modal
    :visible="visible"
    :width="1000"
    :mask-closable="true"
    :footer="false"
    unmount-on-close
    @update:visible="val => emit('update:visible', val)"
    @cancel="handleClose"
  >
    <template #title>
      <span>测试用例「{{ testcaseName }}」关联接口</span>
    </template>

    <div class="flex flex-col" style="max-height: calc(85vh - 120px)">
      <a-spin :loading="loading" class="flex-1 min-h-0">
        <div class="h-full flex flex-col">
          <div class="flex-1 overflow-auto">
            <a-table
              :data="currentPageData"
              :pagination="false"
              :bordered="false"
              size="small"
              class="!w-full"
              :scroll="{ y: '100%' }"
              :scrollbar="false"
            >
              <template #columns>
                <a-table-column title="序号" align="center" :width="80">
                  <template #cell="{ record }">
                    <div class="flex justify-center items-center">
                      <a-tag>{{ record.step.order }}</a-tag>
                    </div>
                  </template>
                </a-table-column>
                <a-table-column title="步骤名称" align="center" :width="200">
                  <template #cell="{ record }">
                    <a-typography-paragraph :ellipsis="{ rows: 1 }" class="!text-center !mb-0">
                      {{ record.step.name }}
                    </a-typography-paragraph>
                  </template>
                </a-table-column>
                <a-table-column title="接口名称" align="center" :width="200">
                  <template #cell="{ record }">
                    <a-typography-paragraph :ellipsis="{ rows: 1 }" class="!text-center !mb-0">
                      {{ record.interface.name }}
                    </a-typography-paragraph>
                  </template>
                </a-table-column>
                <a-table-column title="请求方法" align="center" :width="100">
                  <template #cell="{ record }">
                    <div class="flex justify-center items-center">
                      <a-tag :color="getMethodColor(record.interface.method)">
                        {{ record.interface.method }}
                      </a-tag>
                    </div>
                  </template>
                </a-table-column>
                <a-table-column title="接口地址" align="center" :width="200">
                  <template #cell="{ record }">
                    <a-typography-paragraph :ellipsis="{ rows: 1 }" class="!text-center !mb-0">
                      {{ record.interface.url }}
                    </a-typography-paragraph>
                  </template>
                </a-table-column>
                <a-table-column title="所属模块" align="center">
                  <template #cell="{ record }">
                    <span class="block text-center">{{ record.interface.module?.name || '-' }}</span>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>
          <div v-if="interfaces?.length > 0" class="flex justify-end pt-4 mt-auto border-t border-gray-700">
            <a-pagination
              v-model:current="currentPage"
              :total="interfaces?.length || 0"
              :page-size="pageSize"
              show-total
              show-page-size
              :page-size-options="[10, 20, 50, interfaces?.length || 0]"
              size="small"
              @change="handlePageChange"
              @page-size-change="handlePageSizeChange"
            />
          </div>
        </div>
      </a-spin>
    </div>
  </a-modal>
</template>

<style scoped>
@reference "tailwindcss";
.referenced-interfaces-dialog {
  @apply relative;
  z-index: 1000;
}

.dialog-card {
  @apply !bg-gray-800 !border-gray-700 rounded-xl overflow-hidden flex flex-col;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1), 0 8px 20px -4px rgba(0, 0, 0, 0.5) !important;
  animation: dialogSlideIn 0.2s ease-out;
}

@keyframes dialogSlideIn {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

:deep(.arco-card-header) {
  @apply !border-gray-700 !bg-gray-800/80 !backdrop-blur-sm;
  padding: 16px 8px !important;
  border-bottom-width: 1px !important;
}

:deep(.arco-card-body) {
  @apply !bg-gray-800/80 !backdrop-blur-sm !flex-1 !overflow-hidden;
  padding: 16px 8px !important;
}

/* 表格样式 */
:deep(.arco-table) {
  background: transparent !important;
}

/* 表格容器样式 */
:deep(.arco-table-container) {
  @apply !h-full;
  border: none !important;
  background: transparent !important;
}

:deep(.arco-table-body) {
  @apply !h-full !overflow-auto;
}

:deep(.arco-table-header) {
  @apply !sticky !top-0 !z-10;
  border: none !important;
  background: rgba(31, 41, 55, 0.8) !important;
  backdrop-filter: blur(8px) !important;
}

:deep(.arco-table-size-small .arco-table-th) {
  padding: 8px 4px !important;
  white-space: nowrap !important;
  background: transparent !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #94a3b8 !important;
  font-weight: 500 !important;
  height: 36px !important;
  line-height: 20px !important;
}

:deep(.arco-table-size-small .arco-table-td) {
  padding: 8px 4px !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #e2e8f0 !important;
  background: transparent !important;
  height: 36px !important;
  line-height: 20px !important;
}

:deep(.arco-table-td), :deep(.arco-table-th) {
  @apply !align-middle;
}

:deep(.arco-typography) {
  color: #e2e8f0 !important;
  margin-bottom: 0 !important;
}

/* 标签样式 */
:deep(.arco-tag) {
  border: none !important;
  font-weight: 500 !important;
  padding: 2px 8px !important;
  border-radius: 4px !important;
  font-size: 12px !important;
  line-height: 18px !important;
  transition: all 0.2s ease-in-out !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  min-width: 60px !important;

  &.arco-tag-blue {
    color: #60a5fa !important;
    background-color: rgba(59, 130, 246, 0.1) !important;
  }

  &.arco-tag-green {
    color: #4ade80 !important;
    background-color: rgba(74, 222, 128, 0.1) !important;
  }

  &.arco-tag-orange {
    color: #fb923c !important;
    background-color: rgba(251, 146, 60, 0.1) !important;
  }

  &.arco-tag-red {
    color: #f87171 !important;
    background-color: rgba(248, 113, 113, 0.1) !important;
  }

  &.arco-tag-purple {
    color: #c084fc !important;
    background-color: rgba(192, 132, 252, 0.1) !important;
  }
}

/* Loading 样式 */
:deep(.arco-spin) {
  .arco-spin-dot-list {
    .arco-spin-dot-item {
      background-color: #60a5fa !important;
    }
  }
}

/* 自定义表格样式 */
:deep(.custom-table) {
  .arco-table-body,
  .arco-scrollbar,
  .arco-scrollbar-container,
  .arco-table-body-wrapper,
  .arco-scrollbar__wrap,
  .arco-virtual-list,
  .arco-virtual-list-holder {
    &::-webkit-scrollbar {
      width: 0 !important;
      height: 0 !important;
      display: none !important;
    }
    scrollbar-width: none !important;
    -ms-overflow-style: none !important;
  }
}

/* 分页样式 */
:deep(.arco-pagination) {
  .arco-pagination-item {
    @apply !bg-transparent !border-gray-700 !text-gray-400;

    &:hover {
      @apply !border-blue-500 !text-blue-500 !bg-blue-500/10;
    }

    &.arco-pagination-item-active {
      @apply !border-blue-500 !text-blue-500 !bg-blue-500/10;
    }
  }

  .arco-pagination-total {
    @apply !text-gray-400;
  }

  .arco-select-view {
    @apply !bg-transparent !border-gray-700 !text-gray-400;

    &:hover {
      @apply !border-blue-500;
    }
  }

  .arco-pagination-jumper {
    .arco-input {
      @apply !bg-transparent !border-gray-700 !text-gray-400;

      &:hover {
        @apply !border-blue-500;
      }

      &:focus {
        @apply !border-blue-500 !ring-1 !ring-blue-500/20;
      }
    }
  }
}
</style>
