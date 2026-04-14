<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useProjectStore } from '@/store/projectStore'
import {
  getGlobalHeaders,
  createGlobalHeader,
  updateGlobalHeader,
  deleteGlobalHeader,
  type GlobalHeader,
  type CreateGlobalHeaderData
} from '../../services/globalHeaderService'
import {
  IconPlus,
  IconSettings,
  IconEdit,
  IconDelete,
  IconCode,
  IconInfoCircle,
  IconExclamationCircle
} from '@arco-design/web-vue/es/icon'
import { VARIABLE_TYPES } from '../../services/environmentService'

const projectStore = useProjectStore()
const globalHeaders = ref<GlobalHeader[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const showEditModal = ref(false)
const formLoading = ref(false)

// 表单数据
const formData = ref<CreateGlobalHeaderData>({
  name: '',
  value: '',
  description: '',
  project: 0,
  is_enabled: true
})

// 当前编辑的请求头
const currentHeader = ref<GlobalHeader | null>(null)

// DOM元素引用
const headerCardRef = ref<HTMLElement[]>([])
const iconContainerRef = ref<HTMLElement[]>([])
const valueContainerRef = ref<HTMLElement[]>([])
const buttonGroupRef = ref<HTMLElement[]>([])
const containerRef = ref<HTMLElement | null>(null)

// 计算尺寸信息
const getElementsSizes = (index: number) => {
  const containerEl = containerRef.value
  const cardEl = headerCardRef.value[index]
  const iconEl = iconContainerRef.value[index]
  const valueEl = valueContainerRef.value[index]
  const buttonEl = buttonGroupRef.value[index]
  
  if (!containerEl || !cardEl || !iconEl || !valueEl || !buttonEl) {
    return {
      containerWidth: 0,
      cardWidth: 0,
      innerWidth: 0,
      iconWidth: 0,
      buttonWidth: 0,
      valueWidth: 0,
      gap: 12,
      totalGap: 24,
      availableWidth: 0,
      expectedValueWidth: 0,
      difference: 0
    }
  }
  
  // 容器宽度计算
  const containerWidth = containerEl.clientWidth
  // 卡片的内边距 (p-3 = 3*4 = 12px 每边)
  const cardPadding = 24
  // 列表的右边距 (pr-2 = 2*4 = 8px)
  const listRightPadding = 8
  
  // 可用内容宽度 = 容器宽度 - 滚动条宽度和内边距
  const availableContainerWidth = containerWidth - listRightPadding
  
  // 元素宽度
  const iconWidth = iconEl.offsetWidth
  const buttonWidth = buttonEl.offsetWidth
  const valueWidth = valueEl.offsetWidth
  
  // 间距 (gap-3 = 3*4 = 12px)
  const gap = 12
  // 总间距 = 图标和键值对之间的间距 + 键值对和按钮组之间的间距
  const totalGap = gap * 2
  
  // 期望的键值对宽度 = 可用容器宽度 - 内边距 - 图标宽度 - 按钮组宽度 - 间距
  const expectedValueWidth = availableContainerWidth - cardPadding - iconWidth - buttonWidth - totalGap
  
  // 实际与期望的差异
  const difference = valueWidth - expectedValueWidth
  
  return {
    containerWidth,
    listRightPadding,
    availableContainerWidth,
    cardWidth: cardEl.offsetWidth,
    cardPadding,
    iconWidth,
    buttonWidth,
    valueWidth,
    gap,
    totalGap,
    expectedValueWidth,
    difference
  }
}

// 应用计算宽度到所有键值对容器
const applyCalculatedWidths = () => {
  if (!headerCardRef.value.length || !containerRef.value) return
  
  // 使用requestAnimationFrame保证在下一帧渲染前更新
  requestAnimationFrame(() => {
    headerCardRef.value.forEach((_, index) => {
      const sizes = getElementsSizes(index)
      const valueEl = valueContainerRef.value[index]
      
      if (valueEl && sizes.expectedValueWidth > 0) {
        // 直接应用计算得到的期望宽度
        valueEl.style.width = `${sizes.expectedValueWidth}px`
      }
    })
  })
}

// 主动触发宽度计算和应用的防抖函数
let recalculateDebounceTimer: number | null = null
const debouncedRecalculateWidths = () => {
  if (recalculateDebounceTimer) {
    clearTimeout(recalculateDebounceTimer)
  }
  
  recalculateDebounceTimer = window.setTimeout(() => {
    applyCalculatedWidths()
  }, 100)
}

// 创建DOM元素监听器，用于测试不同宽度
const addSizeMonitor = () => {
  // 监听窗口大小变化
  window.addEventListener('resize', () => {
    debouncedRecalculateWidths()
  })
  
  // 创建MutationObserver监听DOM变化
  const observer = new MutationObserver(() => {
    debouncedRecalculateWidths()
  })
  
  observer.observe(document.querySelector('.custom-scrollbar') as HTMLElement, {
    childList: true,
    subtree: true
  })
}

// 监听容器宽度变化
const observeContainerWidth = () => {
  if (!containerRef.value) return
  
  const resizeObserver = new ResizeObserver(() => {
    // 当容器宽度变化时，重新应用计算宽度
    debouncedRecalculateWidths()
  })
  
  resizeObserver.observe(containerRef.value)
  
  return resizeObserver
}

// 获取全局请求头列表
const fetchGlobalHeaders = async () => {
  if (!projectStore.currentProjectId) {
    globalHeaders.value = []
    return
  }

  try {
    loading.value = true
    const response = await getGlobalHeaders(Number(projectStore.currentProjectId))
    globalHeaders.value = response.data.results
  } catch (error) {
    console.error('获取全局请求头列表失败:', error)
    Message.error('获取全局请求头列表失败')
  } finally {
    loading.value = false
  }
}

// 监听项目变化
watch(
  () => projectStore.currentProjectId,
  () => {
    fetchGlobalHeaders()
  }
)

// 创建全局请求头
const handleCreate = () => {
  resetForm()
  formData.value.project = Number(projectStore.currentProjectId)
  showCreateModal.value = true
}

// 提交创建表单
const submitCreate = async () => {
  try {
    formLoading.value = true
    await createGlobalHeader(formData.value)
    Message.success('创建全局请求头成功')
    showCreateModal.value = false
    await fetchGlobalHeaders()
  } catch (error: any) {
    console.error('创建全局请求头失败:', error)
    Message.error(error.message || '创建全局请求头失败')
  } finally {
    formLoading.value = false
  }
}

// 编辑全局请求头
const handleEdit = (header: GlobalHeader) => {
  currentHeader.value = header
  formData.value = {
    name: header.name,
    value: header.value,
    description: header.description,
    project: header.project,
    is_enabled: header.is_enabled
  }
  showEditModal.value = true
}

// 提交编辑表单
const submitEdit = async () => {
  if (!currentHeader.value) return

  try {
    formLoading.value = true
    await updateGlobalHeader(currentHeader.value.id, formData.value)
    Message.success('更新全局请求头成功')
    showEditModal.value = false
    await fetchGlobalHeaders()
  } catch (error: any) {
    console.error('更新全局请求头失败:', error)
    Message.error(error.message || '更新全局请求头失败')
  } finally {
    formLoading.value = false
  }
}

// 删除全局请求头
const handleDelete = (header: GlobalHeader) => {
  Modal.warning({
    title: '确认删除',
    content: `确定要删除全局请求头 "${header.name}" 吗？`,
    okText: '删除',
    cancelText: '取消',
    onOk: async () => {
      try {
        loading.value = true
        await deleteGlobalHeader(header.id)
        Message.success('删除全局请求头成功')
        await fetchGlobalHeaders()
      } catch (error) {
        console.error('删除全局请求头失败:', error)
        Message.error('删除全局请求头失败')
      } finally {
        loading.value = false
      }
    }
  })
}

// 重置表单
const resetForm = () => {
  formData.value = {
    name: '',
    value: '',
    description: '',
    project: Number(projectStore.currentProjectId),
    is_enabled: true
  }
}

// 切换启用状态
const toggleStatus = async (header: GlobalHeader) => {
  try {
    loading.value = true
    await updateGlobalHeader(header.id, {
      ...header,
      is_enabled: !header.is_enabled
    })
    Message.success(`${!header.is_enabled ? '启用' : '禁用'}全局请求头成功`)
    await fetchGlobalHeaders()
  } catch (error) {
    console.error('更新全局请求头状态失败:', error)
    Message.error('更新全局请求头状态失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchGlobalHeaders().then(() => {
    // 等待DOM更新
    setTimeout(() => {
      // 首次应用宽度
      applyCalculatedWidths()
      
      // 设置各种监听
      addSizeMonitor()
      observeContainerWidth()
    }, 300)
  })
})

// 监听数据变化
watch(globalHeaders, () => {
  // 在数据变化后应用宽度
  setTimeout(() => {
    applyCalculatedWidths()
  }, 300)
}, { deep: true })

// 暴露方法给父组件
defineExpose({
  handleCreate
})
</script>

<template>
  <div class="h-full overflow-hidden flex flex-col">
    <!-- 说明信息卡片 -->
    <div class="p-4 text-sm text-gray-400 space-y-2 bg-gray-900/30 mb-4 rounded-lg border border-gray-700 flex-shrink-0 info-card">
      <div class="flex items-start gap-2">
        <icon-info-circle class="text-blue-400 mt-0.5 flex-shrink-0" />
        <div>全局请求头会自动应用于所属项目的所有接口和测试用例</div>
      </div>
      <div class="flex items-start gap-2">
        <icon-code class="text-teal-400 mt-0.5 flex-shrink-0" />
        <div>您可以在值中使用 <code class="px-1 py-0.5 bg-gray-800 rounded">$变量名</code> 或 <code class="px-1 py-0.5 bg-gray-800 rounded">${变量名}</code> 引用环境变量</div>
      </div>
      <div class="flex items-start gap-2">
        <icon-exclamation-circle class="text-amber-400 mt-0.5 flex-shrink-0" />
        <div>如果出现同名请求头，接口定义的请求头优先级更高（不会被全局配置覆盖）</div>
      </div>
    </div>

    <!-- 请求头列表标题 -->
    <div class="flex items-center gap-2 mb-4 flex-shrink-0">
      <icon-code class="text-gray-400" />
      <span class="text-gray-300 font-medium">请求头列表</span>
      
      <a-button 
        size="mini" 
        type="text" 
        class="ml-auto"
        @click="handleCreate"
      >
        <template #icon>
          <icon-plus class="text-gray-400" />
        </template>
        添加请求头
      </a-button>
    </div>

    <!-- 请求头列表内容 -->
    <div 
      class="flex-1 overflow-y-auto overflow-x-hidden custom-scrollbar pr-2 relative"
      ref="containerRef"
    >
      <a-spin :loading="loading" class="h-full w-full">
        <div class="space-y-4 pb-4 h-full relative">
          <div
            v-for="(header, index) in globalHeaders"
            :key="header.id"
            class="header-card p-3 bg-gray-900/60 rounded-lg border border-gray-700 hover:border-teal-500 transition-all duration-300"
            :data-index="index"
            ref="headerCardRef"
          >
            <!-- 单行显示：图标 + 键值对 + 按钮组 -->
            <div class="flex items-center gap-3 w-full">
              <!-- 图标 -->
              <div 
                class="w-8 h-8 rounded-lg bg-teal-500/10 flex items-center justify-center flex-shrink-0 icon-container"
                :data-index="index"
                ref="iconContainerRef"
              >
                <icon-code class="text-teal-400" />
              </div>
              
              <!-- 键值对显示 -->
              <div 
                class="flex-1 min-w-0 px-3 py-2 bg-gray-800/50 rounded text-sm text-gray-300 overflow-hidden header-value-container"
                :title="`${header.name}: ${header.value}`"
                :data-index="index"
                ref="valueContainerRef"
              >
                <a-tooltip 
                  :content="`${header.name}: ${header.value}`" 
                  position="top"
                  trigger="hover"
                  :content-style="{ maxWidth: '500px', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }"
                >
                  <div class="header-value flex items-baseline overflow-hidden">
                    <span class="font-semibold text-teal-400 flex-shrink-0 mr-2 key-name">{{ header.name }}:</span>
                    <span class="flex-1 truncate key-value">{{ header.value }}</span>
                  </div>
                </a-tooltip>
              </div>
              
              <!-- 操作按钮组 -->
              <div 
                class="flex flex-shrink-0 flex-nowrap ml-auto button-group"
                :data-index="index"
                ref="buttonGroupRef"
              >
                <button 
                  class="toggle-capsule" 
                  :class="{ 'toggle-on': header.is_enabled }"
                  @click.stop="toggleStatus(header)"
                >
                  <span class="toggle-capsule-handle"></span>
                </button>
                <a-button
                  type="text"
                  size="mini"
                  @click.stop="handleEdit(header)"
                >
                  <template #icon><icon-edit /></template>
                  编辑
                </a-button>
                <a-button
                  type="text"
                  size="mini"
                  status="danger"
                  @click.stop="handleDelete(header)"
                >
                  <template #icon><icon-delete /></template>
                  删除
                </a-button>
              </div>
            </div>
            
            <!-- 描述信息（如果有） -->
            <div v-if="header.description" class="text-xs text-gray-400 break-all px-2 py-1 border-l-2 border-gray-700 pl-3 mt-2">
              {{ header.description }}
            </div>
          </div>
          
          <!-- 无数据时的提示 -->
          <div
            v-if="!globalHeaders.length"
            class="empty-state-container h-full w-full flex justify-center items-center"
          >
            <div class="empty-state-content text-center w-full py-10 px-4">
              <div class="mb-4">
                <div class="w-16 h-16 rounded-full bg-teal-500/10 flex items-center justify-center mx-auto">
                  <icon-code class="text-teal-400 text-2xl" />
                </div>
              </div>
              <div class="text-base text-gray-300 mb-2">暂无全局请求头</div>
              <div class="text-sm text-gray-400 mb-6 max-w-md mx-auto">
                您可以添加全局请求头，这些请求头将应用于所有接口请求
              </div>
              <a-button type="outline" @click="handleCreate">
                <template #icon><icon-plus /></template>
                添加请求头
              </a-button>
            </div>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- 创建全局请求头弹窗 -->
    <a-modal
      v-model:visible="showCreateModal"
      title="添加全局请求头"
      @cancel="showCreateModal = false"
      @ok="submitCreate"
      :ok-loading="formLoading"
      ok-text="创建"
      cancel-text="取消"
      :mask-closable="false"
      :unmount-on-close="false"
      modal-class="header-modal"
      :width="650"
    >
      <a-form :model="formData" layout="vertical">
        <a-form-item field="name" label="请求头名称" required>
          <a-input v-model="formData.name" placeholder="请输入请求头名称，如：Authorization" allow-clear />
        </a-form-item>
        <a-form-item field="value" label="请求头值" required>
          <a-textarea 
            v-model="formData.value" 
            placeholder="请输入请求头值，如：Bearer $token" 
            allow-clear
            :auto-size="{ minRows: 3, maxRows: 8 }"
            class="header-value-textarea"
          />
        </a-form-item>
        <a-form-item field="description" label="描述">
          <a-textarea v-model="formData.description" placeholder="请输入描述信息" />
        </a-form-item>
        <a-form-item field="is_enabled" label="状态" class="mb-0">
          <div class="flex items-center gap-2">
            <button 
              class="toggle-capsule form-toggle-capsule" 
              :class="{ 'toggle-on': formData.is_enabled }"
              @click.prevent="formData.is_enabled = !formData.is_enabled"
              type="button"
            >
              <span class="toggle-capsule-handle"></span>
            </button>
            <div class="text-sm ml-2">
              <span :class="formData.is_enabled ? 'text-green-500' : 'text-gray-400'">
                {{ formData.is_enabled ? '已启用' : '已禁用' }}
              </span>
              <span class="text-gray-400 ml-2">
                {{ formData.is_enabled ? '（请求头将应用于所有接口）' : '（请求头暂不生效）' }}
              </span>
            </div>
          </div>
        </a-form-item>
      </a-form>
      
      <div class="bg-blue-500/10 p-3 rounded-lg mt-2 border border-blue-500/20">
        <div class="flex items-start gap-2">
          <icon-info-circle class="text-blue-400 mt-0.5" />
          <div class="text-xs text-gray-300 w-full">
            <div class="font-medium mb-1 text-center">请求头使用说明</div>
            <div class="text-gray-400 text-center">
              <p>1. 全局请求头将应用于所有接口请求</p>
              <p>2. 可以使用环境变量，如：<code class="bg-gray-700 px-1 py-0.5 rounded">Bearer $token</code></p>
              <p>3. 请求头的优先级：接口级 > 全局级</p>
            </div>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- 编辑全局请求头弹窗 -->
    <a-modal
      v-model:visible="showEditModal"
      title="编辑全局请求头"
      @cancel="showEditModal = false"
      @ok="submitEdit"
      :ok-loading="formLoading"
      ok-text="保存"
      cancel-text="取消"
      :mask-closable="false"
      :unmount-on-close="false"
      modal-class="header-modal"
      :width="650"
    >
      <a-form :model="formData" layout="vertical">
        <a-form-item field="name" label="请求头名称" required>
          <a-input v-model="formData.name" placeholder="请输入请求头名称，如：Authorization" allow-clear />
        </a-form-item>
        <a-form-item field="value" label="请求头值" required>
          <a-textarea 
            v-model="formData.value" 
            placeholder="请输入请求头值，如：Bearer $token" 
            allow-clear
            :auto-size="{ minRows: 3, maxRows: 8 }"
            class="header-value-textarea"
          />
        </a-form-item>
        <a-form-item field="description" label="描述">
          <a-textarea v-model="formData.description" placeholder="请输入描述信息" />
        </a-form-item>
        <a-form-item field="is_enabled" label="状态" class="mb-0">
          <div class="flex items-center gap-2">
            <button 
              class="toggle-capsule form-toggle-capsule" 
              :class="{ 'toggle-on': formData.is_enabled }"
              @click.prevent="formData.is_enabled = !formData.is_enabled"
              type="button"
            >
              <span class="toggle-capsule-handle"></span>
            </button>
            <div class="text-sm ml-2">
              <span :class="formData.is_enabled ? 'text-green-500' : 'text-gray-400'">
                {{ formData.is_enabled ? '已启用' : '已禁用' }}
              </span>
              <span class="text-gray-400 ml-2">
                {{ formData.is_enabled ? '（请求头将应用于所有接口）' : '（请求头暂不生效）' }}
              </span>
            </div>
          </div>
        </a-form-item>
      </a-form>
      
      <div class="bg-blue-500/10 p-3 rounded-lg mt-2 border border-blue-500/20">
        <div class="flex items-start gap-2">
          <icon-info-circle class="text-blue-400 mt-0.5" />
          <div class="text-xs text-gray-300 w-full">
            <div class="font-medium mb-1 text-center">请求头使用说明</div>
            <div class="text-gray-400 text-center">
              <p>1. 全局请求头将应用于所有接口请求</p>
              <p>2. 可以使用环境变量，如：<code class="bg-gray-700 px-1 py-0.5 rounded">Bearer $token</code></p>
              <p>3. 请求头的优先级：接口级 > 全局级</p>
            </div>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style lang="postcss" scoped>
.custom-scrollbar {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
  
  &::-webkit-scrollbar {
    display: none; /* Chrome, Safari, Opera*/
  }

  /* 确保滚动容器在显示空状态时也能正确渲染 */
  &:has(.empty-state) {
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

.header-card {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: all 0.3s ease;
  
  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  }
  
  /* 请求头值样式 */
  .break-all {
    word-break: break-all;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    max-width: 100%;
  }
  
  .flex.items-center.gap-3 {
    display: flex;
    align-items: center;
    
    > div:first-child {
      flex: 0 0 auto; /* 图标固定宽度 */
    }
    
    > div:last-child {
      flex: 0 0 auto; /* 按钮组固定宽度 */
      width: auto;
      white-space: nowrap;
    }
    
    .header-value-container {
      flex: 1 1 auto; /* 键值对容器填充剩余空间 */
      min-width: 0;
    }
  }
  
  .header-value-container {
    position: relative;
    cursor: default;
    transition: all 0.2s ease;
    border: 1px solid transparent;
    max-width: 100%;
    overflow: hidden;
    box-sizing: border-box; /* 确保宽度计算包含内边距和边框 */
    
    &:hover {
      background-color: rgba(75, 85, 99, 0.5);
      border-color: rgba(20, 184, 166, 0.2);
    }
    
    .header-value {
      font-family: 'Consolas', 'Monaco', monospace;
      line-height: 1.5;
      display: flex;
      align-items: baseline;
      width: 100%;
      
      .key-name {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #2dd4bf; /* 蓝绿色 */
        transition: all 0.2s ease;
        flex: 0 0 auto;
        min-width: 80px;
        max-width: 120px;
      }
      
      .key-value {
        word-break: break-all;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: #d1d5db; /* 更亮的文本颜色 */
        flex: 1;
        min-width: 0;
      }
    }
  }
  
  /* 在小屏幕上调整布局 */
  @media (max-width: 500px) {
    .flex.items-center.gap-3 {
      gap: 0.5rem; /* 减小间距 */
    }
    
    .header-value-container {
      padding: 0.25rem 0.5rem; /* 减小内边距 */
      
      .key-name {
        min-width: 60px !important;
        max-width: 80px !important;
      }
    }
    
    .flex.flex-shrink-0.flex-nowrap {
      margin-left: 0.25rem; /* 减小左边距 */
      width: auto;
      flex-wrap: nowrap;
      
      .arco-btn {
        padding: 0 0.25rem; /* 减小按钮内边距 */
        
        .arco-icon {
          font-size: 14px; /* 减小图标大小 */
        }
        
        span {
          display: none; /* 隐藏按钮文本 */
        }
      }
      
      .toggle-capsule {
        margin-right: 0.25rem; /* 减小开关右边距 */
        transform: scale(0.8); /* 缩小开关大小 */
      }
    }
  }
  
  /* 在中等屏幕上的调整 */
  @media (min-width: 501px) and (max-width: 768px) {
    .flex.items-center.gap-3 {
      gap: 0.75rem; /* 适中间距 */
    }
    
    .header-value-container {
      .key-name {
        min-width: 70px !important;
        max-width: 100px !important;
      }
    }
    
    .flex.flex-shrink-0.flex-nowrap {
      .arco-btn {
        padding: 0 4px;
        font-size: 12px;
      }
    }
  }
  
  /* 在极小屏幕上调整布局 */
  @media (max-width: 400px) {
    .flex.items-center.gap-3 {
      gap: 0.25rem; /* 更小的间距 */
      
      > div:first-child {
        width: 24px !important;
        height: 24px !important;
        
        .arco-icon {
          font-size: 12px;
        }
      }
    }
    
    .flex.flex-shrink-0.flex-nowrap {
      .arco-btn {
        width: 24px;
        height: 24px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        
        .arco-icon {
          font-size: 12px;
        }
      }
      
      .toggle-capsule {
        width: 32px;
        height: 16px;
        
        .toggle-capsule-handle {
          width: 12px;
          height: 12px;
          top: 2px;
        }
        
        &.toggle-on .toggle-capsule-handle {
          left: calc(100% - 14px);
        }
      }
    }
  }
}

/* 空状态样式 - 新版本 */
.empty-state-container {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state-content {
  .w-16.h-16 {
    transition: all 0.3s ease;
    box-shadow: 0 0 15px rgba(20, 184, 166, 0.2);
    
    &:hover {
      transform: scale(1.05);
      box-shadow: 0 0 20px rgba(20, 184, 166, 0.3);
    }
  }
  
  :deep(.arco-btn-outline) {
    border-color: rgba(20, 184, 166, 0.5);
    color: rgba(20, 184, 166, 0.9);
    
    &:hover {
      background-color: rgba(20, 184, 166, 0.1);
      border-color: rgba(20, 184, 166, 0.8);
      color: rgba(20, 184, 166, 1);
    }
  }
}

/* 移除旧的empty-state样式 */
.empty-state {
  display: none; /* 完全隐藏旧样式，避免冲突 */
}

/* 当空状态显示时确保其父容器有正确的定位 */
.space-y-4.pb-4 {
  &.h-full {
    position: relative;
    min-height: 300px;
  }
}

.info-card {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  background: linear-gradient(to right, rgba(30, 41, 59, 0.7), rgba(30, 41, 59, 0.5));
  
  code {
    font-family: 'Consolas', 'Monaco', monospace;
    transition: all 0.2s ease;
    
    &:hover {
      background-color: rgba(30, 41, 59, 1);
    }
  }
}

:deep(.arco-tag-green) {
  background-color: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.35);
  color: #10b981;
}

:deep(.arco-tag-red) {
  background-color: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.35);
  color: #ef4444;
}

:deep(.arco-btn-text) {
  transition: all 0.2s ease;
  
  &:hover {
    background-color: rgba(255, 255, 255, 0.05);
    transform: translateY(-1px);
  }
}

.status-btn {
  border-radius: 12px;
  font-size: 12px;
  padding: 0 10px;
  height: 24px;
  line-height: 22px;
  transition: all 0.3s ease;
  
  &:hover {
    transform: translateY(-1px);
  }
  
  &.arco-btn-status-danger {
    background-color: rgba(239, 68, 68, 0.05);
    border-color: rgba(239, 68, 68, 0.4);
    color: #ef4444;
    
    &:hover {
      background-color: rgba(239, 68, 68, 0.1);
      border-color: rgba(239, 68, 68, 0.6);
    }
  }
  
  &.arco-btn-status-success {
    background-color: rgba(16, 185, 129, 0.1);
    border-color: rgba(16, 185, 129, 0.4);
    color: #10b981;
    
    &:hover {
      background-color: rgba(16, 185, 129, 0.2);
    }
  }
}

/* 胶囊开关按钮样式 */
.toggle-capsule {
  position: relative;
  width: 44px;
  height: 22px;
  border-radius: 11px;
  background-color: rgba(100, 100, 100, 0.3);
  border: none;
  cursor: pointer;
  transition: all 0.3s ease;
  padding: 0;
  outline: none;
  flex-shrink: 0;
  margin-right: 12px;
  
  .toggle-capsule-handle {
    position: absolute;
    left: 2px;
    top: 2px;
    width: 18px;
    height: 18px;
    border-radius: 9px;
    background-color: #fff;
    transition: all 0.3s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  }
  
  &.toggle-on {
    background-color: #10b981;
    
    .toggle-capsule-handle {
      left: calc(100% - 20px);
    }
  }
  
  &:hover {
    opacity: 0.9;
  }
  
  &.form-toggle-capsule {
    width: 48px;
    height: 24px;
    
    .toggle-capsule-handle {
      top: 3px;
      width: 18px;
      height: 18px;
    }
    
    &.toggle-on .toggle-capsule-handle {
      left: calc(100% - 21px);
    }
  }
  
  @media (max-width: 500px) {
    margin-right: 8px;
  }
}

.status-toggle {
  display: flex;
  
  .toggle-btn {
    border-radius: 16px;
    min-width: 70px;
    
    &:first-child {
      border-top-right-radius: 0;
      border-bottom-right-radius: 0;
    }
    
    &:last-child {
      border-top-left-radius: 0;
      border-bottom-left-radius: 0;
      margin-left: -1px;
    }
    
    &.arco-btn-status-danger {
      &.arco-btn-outline {
        color: #ef4444;
        border-color: rgba(239, 68, 68, 0.4);
      }
      
      &.arco-btn-primary {
        background-color: #ef4444;
        border-color: #ef4444;
      }
    }
    
    &.arco-btn-status-success {
      &.arco-btn-outline {
        color: #10b981;
        border-color: rgba(16, 185, 129, 0.4);
      }
      
      &.arco-btn-primary {
        background-color: #10b981;
        border-color: #10b981;
      }
    }
  }
}

:deep(.header-modal) {
  .arco-modal-body {
    padding: 16px;
  }
  
  .arco-form-item-content {
    overflow: visible;
  }
  
  .arco-textarea-wrapper {
    width: 100%;
  }
  
  .arco-textarea {
    resize: vertical;
    min-height: 60px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 13px;
  }
  
  .header-value-textarea {
    .arco-textarea {
      line-height: 1.5;
      padding: 8px;
    }
  }
  
  @media (max-width: 768px) {
    max-width: 95vw;
    
    .arco-modal-body {
      padding: 12px;
    }
  }
}

/* 胶囊状态标签 */
.capsule-status-tag {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
  
  &.status-on {
    background-color: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.3);
    color: #10b981;
  }
  
  &.status-off {
    background-color: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.3);
    color: #ef4444;
  }
}
</style> 