<script setup lang="ts">
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconSearch } from '@arco-design/web-vue/es/icon'
import type { TableRowSelection } from '@arco-design/web-vue'
import type { TestCase } from '../../services/testTaskService'

const props = defineProps<{
  visible: boolean
  loading: boolean
  testCases: TestCase[]
  pagination: {
    current: number
    pageSize: number
    total: number
  }
  existingIds?: number[] // 已添加的测试用例ID列表
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'add': [selectedIds: number[]]
  'pageChange': [current: number]
  'pageSizeChange': [pageSize: number]
}>()

// 使用计算属性处理 visible 的双向绑定
const modalVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
})

// 选中的测试用例
const selectedTestCases = ref<(string | number)[]>([])
// 搜索关键词
const searchKeyword = ref('')

// 处理分页变化
const handlePageChange = (current: number) => {
  emit('pageChange', current)
}

// 处理每页条数变化
const handlePageSizeChange = (pageSize: number) => {
  emit('pageSizeChange', pageSize)
}

// 添加测试用例
const handleAdd = async () => {
  if (selectedTestCases.value.length === 0) {
    Message.warning('请选择要添加的测试用例')
    return
  }
  // 将 selectedTestCases 转换为数字数组
  emit('add', selectedTestCases.value.map(id => Number(id)))
  selectedTestCases.value = []
}

// 关闭弹窗
const handleClose = () => {
  modalVisible.value = false
  selectedTestCases.value = []
  searchKeyword.value = ''
}

// 优先级颜色映射
const testCasePriorityColorMap: Record<string, string> = {
  'P0': 'red',
  'P1': 'orange',
  'P2': 'blue',
  'P3': 'green'
}

// 过滤测试用例
const filteredTestCases = computed(() => {
  if (!searchKeyword.value) return props.testCases
  
  const keyword = searchKeyword.value.toLowerCase()
  return props.testCases.filter(item => 
    (item.name?.toLowerCase().includes(keyword) || 
    item.description?.toLowerCase().includes(keyword))
  )
})
</script>

<template>
  <a-modal
    v-model:visible="modalVisible"
    title="添加测试用例"
    :mask-closable="false"
    :footer="false"
    class="custom-modal"
    :align-center="false"
    :width="1200"
    @cancel="handleClose"
  >
    <a-spin :loading="loading">
      <div class="flex flex-col gap-4">
        <!-- 搜索框 -->
        <div class="bg-[#1d2633] rounded p-3">
          <a-input-search
            v-model="searchKeyword"
            placeholder="搜索测试用例名称或描述"
            class="custom-search"
          >
            <template #prefix>
              <icon-search />
            </template>
          </a-input-search>
        </div>
        
        <!-- 测试用例列表 -->
        <div class="bg-[#1d2633] rounded p-3 flex flex-col">
          <div class="text-gray-300 font-medium mb-3">测试用例列表</div>
          
          <div class="flex-1 overflow-x-auto overflow-y-auto hide-scrollbar" style="max-height: 400px">
            <a-table
              v-if="filteredTestCases.length > 0"
              :scroll="{ y: '100%' }"
              :data="filteredTestCases"
              :pagination="false"
              :bordered="false"
              :row-selection="{
                type: 'checkbox',
                showCheckedAll: true,
                selectedRowKeys: selectedTestCases
              } as TableRowSelection"
              :row-class="(record) => props.existingIds?.includes(record.id) ? 'has-added' : ''"
              :row-key="'id'"
              @selection-change="selectedTestCases = $event"
              class="custom-table"
            >
              <template #columns>
                <a-table-column title="ID" data-index="id">
                  <template #cell="{ record }">
                    <div class="flex items-center gap-2">
                      <span>{{ record.id }}</span>
                      <a-tag v-if="props.existingIds?.includes(record.id)" size="small" class="added-tag">
                        已添加
                      </a-tag>
                    </div>
                  </template>
                </a-table-column>
                <a-table-column title="用例名称" data-index="name" ellipsis tooltip />
                <a-table-column title="描述" data-index="description" ellipsis tooltip />
                <a-table-column title="优先级" data-index="priority" align="center">
                  <template #cell="{ record }">
                    <a-tag :color="testCasePriorityColorMap[record.priority]">
                      {{ record.priority }}
                    </a-tag>
                  </template>
                </a-table-column>
              </template>
            </a-table>
            <div v-else class="text-gray-400 text-center mt-20">
              没有找到匹配的测试用例
            </div>
          </div>
          
          <!-- 分页 -->
          <div class="flex justify-end mt-3 pt-3 border-t border-gray-700">
            <a-pagination
              :total="pagination.total"
              :current="pagination.current"
              :page-size="pagination.pageSize"
              :page-size-options="[10, 20, 30, 50]"
              @change="handlePageChange"
              @page-size-change="handlePageSizeChange"
              class="custom-pagination"
              size="small"
              show-total
              show-jumper
              show-page-size
            />
          </div>
        </div>
        
        <!-- 底部按钮 -->
        <div class="flex justify-end gap-2">
          <a-button @click="handleClose">取消</a-button>
          <a-button type="primary" @click="handleAdd" :disabled="selectedTestCases.length === 0">
            确定添加 ({{ selectedTestCases.length }})
          </a-button>
        </div>
      </div>
    </a-spin>
  </a-modal>
</template>

<style scoped>
/* 隐藏滚动条但保持滚动功能 */
.hide-scrollbar {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}

.hide-scrollbar::-webkit-scrollbar {
  display: none; /* Chrome, Safari and Opera */
}

/* 弹窗样式 */
:deep(.custom-modal) {
  width: 80% !important;
  min-width: 1200px !important;
  max-width: 2400px !important;
  margin: 50px auto !important;
}

:deep(.custom-modal .arco-modal-body) {
  padding: 20px !important;
  background-color: #141b26 !important;
  width: 100% !important;
  box-sizing: border-box !important;
  overflow: hidden !important;
}

/* 搜索框样式 */
.custom-search :deep(.arco-input-wrapper) {
  background-color: rgba(70, 84, 102, 0.4) !important;
  border-color: transparent !important;
}

.custom-search :deep(.arco-input-wrapper:hover),
.custom-search :deep(.arco-input-wrapper.arco-input-focus) {
  background-color: rgba(70, 84, 102, 0.4) !important;
  border-color: #3b82f6 !important;
}

.custom-search :deep(.arco-input) {
  color: #e2e8f0 !important;
}

.custom-search :deep(.arco-input-search-btn) {
  background-color: transparent !important;
  border-color: transparent !important;
  color: #94a3b8 !important;
}

/* 表格样式 */
.custom-table :deep(.arco-table) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-container) {
  background-color: transparent !important;
  border: none !important;
  width: 100% !important;
  min-width: fit-content !important;
}

.custom-table :deep(.arco-table) {
  width: 100% !important;
  min-width: fit-content !important;
}

.custom-table :deep(.arco-table-header) {
  background-color: transparent !important;
  table-layout: fixed !important;
}

.custom-table :deep(.arco-table-body) {
  background-color: transparent !important;
  table-layout: fixed !important;
}

.custom-table :deep(.arco-table-td) {
  padding: 8px 16px !important;
  height: 40px !important;
  line-height: 24px !important;
  color: #cbd5e1 !important;
}

.custom-table :deep(.arco-table-th) {
  background-color: rgba(30, 41, 59, 0.5) !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1) !important;
  color: #e2e8f0 !important;
  font-weight: 500 !important;
  text-align: center !important;
  padding: 12px !important;
}


.custom-table :deep(.arco-table-tr) {
  background-color: transparent !important;
}

.custom-table :deep(.arco-table-tr:has([class*="added-tag"])) {
  background-color: rgba(51, 65, 85, 0.4) !important;
  
  td {
    color: #94a3b8 !important;
  }
  
  &:hover {
    background-color: rgba(51, 65, 85, 0.4) !important;
  }
}

.custom-table :deep(.arco-table-tr:hover) {
  background-color: rgba(30, 41, 59, 0.5) !important;
}

.custom-table :deep(.arco-table-tr-checked) {
  background-color: rgba(22, 93, 255, 0.1) !important;
}

/* 已添加行样式 */
.custom-table :deep(.has-added) {
  background-color: rgba(51, 65, 85, 0.3) !important;
  
  td {
    color: #94a3b8 !important;
  }
  
  &:hover {
    background-color: rgba(51, 65, 85, 0.3) !important;
  }
  
  .arco-checkbox {
    cursor: not-allowed;
  }
}

/* 已添加标签样式 */
.custom-table :deep(.added-tag) {
  background-color: #475569 !important;
  border: none !important;
  color: #f1f5f9 !important;
  font-size: 12px !important;
  padding: 0 8px !important;
  height: 20px !important;
  line-height: 20px !important;
  font-weight: 500 !important;
}

/* 禁用行样式 */
.custom-table :deep(.disabled-row) {
  opacity: 0.5 !important;
  cursor: not-allowed !important;
  background-color: rgba(30, 41, 59, 0.3) !important;
}

.custom-table :deep(.disabled-row:hover) {
  background-color: rgba(30, 41, 59, 0.3) !important;
}

.custom-table :deep(.disabled-row .arco-checkbox) {
  cursor: not-allowed !important;
}

/* 分页样式 */
.custom-pagination :deep(.arco-pagination-item) {
  background-color: transparent !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #94a3b8 !important;
  min-width: 28px !important;
  height: 28px !important;
  line-height: 28px !important;
}

.custom-pagination :deep(.arco-pagination-item:hover),
.custom-pagination :deep(.arco-pagination-item-active) {
  border-color: #3b82f6 !important;
  color: #3b82f6 !important;
}

.custom-pagination :deep(.arco-select-view) {
  background-color: transparent !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #94a3b8 !important;
  height: 28px !important;
  line-height: 28px !important;
}

.custom-pagination :deep(.arco-select-view:hover) {
  border-color: #3b82f6 !important;
}

.custom-pagination :deep(.arco-pagination-jumper) {
  height: 28px !important;
  line-height: 28px !important;
}

.custom-pagination :deep(.arco-pagination-jumper input) {
  background-color: transparent !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  color: #94a3b8 !important;
  height: 28px !important;
}

.custom-pagination :deep(.arco-pagination-jumper input:hover),
.custom-pagination :deep(.arco-pagination-jumper input:focus) {
  border-color: #3b82f6 !important;
}

.custom-pagination :deep(.arco-pagination-total) {
  height: 28px !important;
  line-height: 28px !important;
}
</style>
