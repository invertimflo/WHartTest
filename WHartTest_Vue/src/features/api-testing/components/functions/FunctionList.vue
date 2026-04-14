<script setup lang="ts">
import { ref, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconPlus, IconSearch, IconCode, IconEdit, IconDelete } from '@arco-design/web-vue/es/icon'
import type { Function } from '../../services/functionService'

interface Props {
  loading?: boolean
  functions: Function[]
  selectedFunction: Function | null
}

interface Emits {
  (e: 'select', func: Function): void
  (e: 'create'): void
  (e: 'edit', func: Function): void
  (e: 'delete', func: Function): void
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

const emit = defineEmits<Emits>()

const searchKeyword = ref('')

// 过滤后的函数列表
const filteredFunctions = computed(() => {
  if (!searchKeyword.value) return props.functions

  const keyword = searchKeyword.value.toLowerCase()
  return props.functions.filter(func => 
    func.name.toLowerCase().includes(keyword) || 
    func.description?.toLowerCase().includes(keyword)
  )
})

// 处理编辑按钮点击
const handleEditClick = (func: Function, event: Event) => {
  event.stopPropagation()
  emit('edit', func)
}

// 处理删除按钮点击
const handleDeleteClick = (func: Function, event: Event) => {
  event.stopPropagation()
  emit('delete', func)
}
</script>

<template>
  <div class="w-56 flex flex-col">
    <div class="flex-1 bg-gray-800 rounded-lg shadow-lg overflow-hidden">
      <!-- 顶部标题和搜索栏 -->
      <div class="p-4 border-b border-gray-700/50">
        <div class="flex justify-between items-center mb-4">
          <div class="flex items-center gap-2">
            <h2 class="text-lg font-medium text-gray-100">函数列表</h2>
          </div>
          <a-button type="text" size="small" @click="emit('create')">
            <template #icon><icon-plus /></template>
            新建
          </a-button>
        </div>
        <a-input-search
          v-model="searchKeyword"
          placeholder="搜索函数..."
          allow-clear
        >
          <template #prefix>
            <icon-search />
          </template>
        </a-input-search>
      </div>

      <!-- 函数列表内容 -->
      <div class="flex-1 overflow-hidden">
        <a-spin :loading="loading" dot class="!block h-full">
          <div class="h-full overflow-y-auto">
            <div class="py-2">
              <a-empty v-if="filteredFunctions.length === 0" class="p-4">
                暂无函数数据
              </a-empty>
              <template v-else>
                <div class="space-y-1.5 m-2">
                  <div
                    v-for="func in filteredFunctions"
                    :key="func.id"
                    class="px-4 py-2 cursor-pointer transition-colors bg-[rgb(70,84,102,0.4)] hover:bg-[rgb(47,66,114,0.4)] rounded-lg"
                    :class="{ 
                      'bg-[rgb(47,66,114,0.4)]': selectedFunction?.id === func.id
                    }"
                    @click="emit('select', func)"
                  >
                    <div class="flex items-center justify-between">
                      <div class="flex items-center gap-2">
                        <IconCode class="text-blue-500 w-4 h-4" />
                        <span class="text-[#e5e6e8] truncate">{{ func.name }}</span>
                      </div>
                      <div class="flex items-center">
                        <a-button
                          type="text"
                          size="mini"
                          class="!p-0 !text-[#6b7785] hover:!text-[#86909c]"
                          @click="(e) => handleEditClick(func, e)"
                        >
                          <template #icon><icon-edit /></template>
                        </a-button>
                        <a-button
                          type="text"
                          size="mini"
                          class="!p-0 !text-[#6b7785] hover:!text-[#86909c]"
                          @click="(e) => handleDeleteClick(func, e)"
                        >
                          <template #icon><icon-delete /></template>
                        </a-button>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </a-spin>
      </div>
    </div>
  </div>
</template> 