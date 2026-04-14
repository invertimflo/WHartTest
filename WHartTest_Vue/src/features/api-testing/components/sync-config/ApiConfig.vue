<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { IconPlus } from '@arco-design/web-vue/es/icon'
import { syncApi, type ApiSyncConfig } from '../../services/syncService'
import { useProjectStore } from '@/store/projectStore'
import ApiConfigTable from './ApiConfigTable.vue'
import ApiConfigForm from './ApiConfigForm.vue'
import ApiConfigDetail from './ApiConfigDetail.vue'

const projectStore = useProjectStore()
const loading = ref(false)
const configs = ref<ApiSyncConfig[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)
const showCreateModal = ref(false)
const showDetailModal = ref(false)
const isEditing = ref(false)
const editingConfigId = ref<number | null>(null)
const selectedRowKeys = ref<number[]>([])
const currentConfig = ref<ApiSyncConfig | null>(null)

const fieldOptions = [
  { label: '请求方法', value: 'method' },
  { label: 'URL', value: 'url' },
  { label: '请求头', value: 'headers' },
  { label: '查询参数', value: 'params' },
  { label: '请求体', value: 'body' },
  { label: '前置钩子', value: 'setup_hooks' },
  { label: '后置钩子', value: 'teardown_hooks' },
  { label: '变量定义', value: 'variables' },
  { label: '断言规则', value: 'validators' },
  { label: '提取变量', value: 'extract' }
]

const fetchConfigs = async () => {
  if (!projectStore.currentProject?.id) {
    Message.error('请先选择项目')
    return
  }

  try {
    loading.value = true
    const { data } = await syncApi.getApiConfigs(projectStore.currentProject.id)
    configs.value = data.results
    total.value = data.count
  } catch (error) {
    Message.error('获取接口同步配置列表失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const handleEdit = async (record: ApiSyncConfig) => {
  try {
    // 确保先关闭已打开的窗口
    showCreateModal.value = false;
    showDetailModal.value = false;
    
    // 重置状态
    currentConfig.value = null;
    isEditing.value = true;
    editingConfigId.value = record.id;
    
    loading.value = true;
    console.log('获取配置详情，ID:', record.id);
    const response = await syncApi.getConfigDetail(record.id);
    
    // 确保我们使用的是响应中的data字段
    const configData = response.data;
    console.log('获取到的配置详情(原始):', configData);
    
    // 打印关键字段，帮助调试
    console.log('接口ID:', (configData as any).interface);
    console.log('用例ID:', (configData as any).testcase);
    console.log('步骤ID:', (configData as any).step);
    console.log('接口信息:', (configData as any).interface_info);
    console.log('用例信息:', (configData as any).testcase_info);
    console.log('步骤信息:', (configData as any).step_info);
    
    // 设置配置数据
    currentConfig.value = configData;
    
    // 延迟打开弹窗，确保之前的弹窗已关闭
    setTimeout(() => {
      showCreateModal.value = true;
    }, 100);
  } catch (error) {
    Message.error('获取配置详情失败');
    console.error(error);
  } finally {
    loading.value = false;
  }
}

const handleSubmit = async (formData: any) => {
  try {
    loading.value = true
    if (isEditing.value && editingConfigId.value) {
      await syncApi.updateApiConfig(editingConfigId.value, formData)
      Message.success('更新同步配置成功')
    } else {
      await syncApi.createApiConfig(formData)
      Message.success('创建同步配置成功')
    }
    
    // 关闭弹窗并重置状态
    showCreateModal.value = false
    isEditing.value = false
    editingConfigId.value = null
    currentConfig.value = null
    
    // 重新获取配置列表
    await fetchConfigs()
  } catch (error: any) {
    if (error.errors) {
      const errorMessages = Object.values(error.errors).flat()
      Message.error(errorMessages.join(', '))
    } else {
      Message.error(isEditing.value ? '更新同步配置失败' : '创建同步配置失败')
    }
    console.error(error)
  } finally {
    loading.value = false
  }
}

const handleViewDetail = async (record: ApiSyncConfig) => {
  try {
    // 确保先关闭已打开的窗口
    showCreateModal.value = false;
    showDetailModal.value = false;
    
    // 重置状态
    currentConfig.value = null;
    
    loading.value = true;
    const response = await syncApi.getConfigDetail(record.id);
    
    // 确保我们使用的是响应中的data字段
    const configData = response.data;
    console.log('查看详情，获取到的配置:', configData);
    
    // 设置配置数据
    currentConfig.value = configData;
    
    // 延迟打开弹窗，确保之前的弹窗已关闭
    setTimeout(() => {
      showDetailModal.value = true;
    }, 100);
  } catch (error) {
    Message.error('获取配置详情失败');
    console.error(error);
  } finally {
    loading.value = false;
  }
}

const handleDelete = async (record: ApiSyncConfig) => {
  Modal.warning({
    title: '确认删除',
    content: `确定要删除同步配置"${record.name}"吗？此操作不可恢复。`,
    okText: '确认删除',
    cancelText: '取消',
    async onOk() {
      try {
        loading.value = true
        await syncApi.deleteApiConfig(record.id)
        Message.success('删除成功')
        await fetchConfigs()
      } catch (error) {
        Message.error('删除失败')
        console.error(error)
      } finally {
        loading.value = false
      }
    }
  })
}

const handleSyncNow = async (record: ApiSyncConfig) => {
  try {
    loading.value = true
    await syncApi.syncNowConfig(record.id)
    Message.success('同步执行成功')
  } catch (error) {
    Message.error('同步执行失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchConfigs()
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  fetchConfigs()
}

// 处理新建配置
const handleCreate = () => {
  // 确保先关闭已打开的窗口
  showCreateModal.value = false;
  showDetailModal.value = false;
  
  // 重置状态
  currentConfig.value = null;
  isEditing.value = false;
  editingConfigId.value = null;
  
  // 延迟打开弹窗，确保之前的弹窗已关闭
  setTimeout(() => {
    showCreateModal.value = true;
  }, 100);
}

// 监听项目变化
watch(() => projectStore.currentProject?.id, (newProjectId) => {
  if (newProjectId) {
    fetchConfigs()
  } else {
    configs.value = []
    total.value = 0
  }
})

onMounted(() => {
  if (projectStore.currentProject?.id) {
    fetchConfigs()
  }
})
</script>

<template>
  <div class="h-full flex flex-col bg-gray-900">
    <!-- 页面头部 -->
    <div class="px-8 py-6 bg-gray-800/50 border-b border-gray-700">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-semibold text-gray-100">接口同步配置</h1>
        <a-button type="primary" :loading="loading" @click="handleCreate">
          <template #icon>
            <icon-plus />
          </template>
          新建配置
        </a-button>
      </div>
      <p class="mt-2 text-gray-400 text-sm">管理接口、用例和测试步骤之间的同步关系</p>
    </div>

    <!-- 主要内容区域 -->
    <div class="flex-1 overflow-hidden p-2">
      <div class="h-full overflow-auto custom-scrollbar">
        <api-config-table
          :loading="loading"
          :configs="configs"
          v-model:selectedRowKeys="selectedRowKeys"
          :fieldOptions="fieldOptions"
          @sync="handleSyncNow"
          @edit="handleEdit"
          @view="handleViewDetail"
          @delete="handleDelete"
          @create="handleCreate"
        />
      </div>
    </div>

    <!-- 分页区域 -->
    <div class="px-8 py-4 bg-gray-800/50 border-t border-gray-700">
      <a-pagination
        :total="total"
        v-model:current="currentPage"
        v-model:pageSize="pageSize"
        show-total
        show-jumper
        show-page-size
        class="justify-end"
        @change="handlePageChange"
        @pageSizeChange="handlePageSizeChange"
      />
    </div>

    <!-- 创建/编辑弹窗 -->
    <api-config-form
      :visible="showCreateModal"
      :loading="loading"
      :isEditing="isEditing"
      :fieldOptions="fieldOptions"
      :currentConfig="currentConfig"
      @update:visible="showCreateModal = $event"
      @submit="handleSubmit"
    />

    <!-- 详情弹窗 -->
    <api-config-detail
      :visible="showDetailModal"
      :config="currentConfig"
      :fieldOptions="fieldOptions"
      @update:visible="showDetailModal = $event"
    />
  </div>
</template>

<style scoped>
@reference "tailwindcss";
/* 添加自定义滚动条样式 */
.custom-scrollbar {
  scrollbar-width: thin;
  scrollbar-color: rgba(107, 114, 128, 0.3) transparent;
}

.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: rgba(107, 114, 128, 0.3);
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: rgba(107, 114, 128, 0.5);
}

:deep(.arco-pagination) {
  @apply flex items-center;
}

:deep(.arco-pagination-total) {
  @apply text-gray-400;
}

:deep(.arco-pagination-item) {
  @apply bg-gray-700 border-gray-600 text-gray-300;
}

:deep(.arco-pagination-item:hover) {
  @apply border-blue-500;
}

:deep(.arco-pagination-item-active) {
  @apply bg-blue-500 border-blue-500 text-white;
}

:deep(.arco-pagination-jumper) {
  @apply text-gray-400;
}

:deep(.arco-pagination-jumper .arco-input-wrapper) {
  @apply bg-gray-700 border-gray-600;
}

:deep(.arco-pagination-jumper .arco-input) {
  @apply text-gray-300;
}

:deep(.arco-select-view.arco-pagination-page-size-view) {
  @apply bg-gray-700 border-gray-600 text-gray-300;
}
</style> 