<script setup lang="ts">
import { ref, computed } from 'vue'
import { IconSearch } from '@arco-design/web-vue/es/icon'
import type { ApiInterface } from '../../types/interface'

const props = defineProps<{
  interfaces: ApiInterface[]
  selectedKeys: number[]
  loading: boolean
  currentModuleName?: string
}>()

const emit = defineEmits(['selection-change', 'row-click', 'confirm'])

const searchKeyword = ref('')

const filteredInterfaces = computed(() => {
  if (!searchKeyword.value) return props.interfaces

  const keyword = searchKeyword.value.toLowerCase()
  return props.interfaces.filter(item =>
    item.name.toLowerCase().includes(keyword) ||
    item.url.toLowerCase().includes(keyword)
  )
})
</script>

<template>
  <div class="flex-1 bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
    <div class="p-4 border-b border-gray-700">
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <span class="text-[#e5e6e8]">接口列表</span>
          <span v-if="currentModuleName" class="text-sm text-gray-400">{{ currentModuleName }}</span>
        </div>
        <a-button
          type="primary"
          :disabled="!selectedKeys.length"
          @click="$emit('confirm')"
        >
          确定
        </a-button>
      </div>
      <div class="flex items-center gap-2">
        <a-input-search
          v-model="searchKeyword"
          placeholder="搜索接口名称或URL"
          allow-clear
        >
          <template #prefix>
            <icon-search />
          </template>
        </a-input-search>
      </div>
    </div>
    <div class="overflow-y-auto hide-scrollbar" style="height: 400px">
      <div class="p-2">
        <a-table
          v-if="interfaces.length > 0"
          :data="filteredInterfaces"
          :loading="loading"
          :pagination="false"
          :bordered="false"
          :row-selection="{
            type: 'checkbox',
            showCheckedAll: true,
            selectedRowKeys: selectedKeys,
            onlyCurrent: false
          }"
          :row-key="'id'"
          @selection-change="(selectedRowKeys: (string | number)[]) => {
            const newKeys = selectedRowKeys.map(key => Number(key))
            $emit('selection-change', newKeys)
          }"
          row-class="cursor-pointer"
          @row-click="(record) => $emit('row-click', record)"
          class="interface-table"
        >
          <template #columns>
            <a-table-column title="ID" data-index="id" :width="80">
              <template #cell="{ record }">
                <span class="cell-secondary">{{ record.id }}</span>
              </template>
            </a-table-column>
            <a-table-column title="接口名称" data-index="name">
              <template #cell="{ record }">
                <span class="cell-primary">{{ record.name }}</span>
              </template>
            </a-table-column>
            <a-table-column title="请求方法" data-index="method" :width="100">
              <template #cell="{ record }">
                <a-tag
                  :color="record.method === 'GET' ? 'green' : record.method === 'POST' ? 'blue' : record.method === 'PUT' ? 'orange' : 'red'"
                  size="small"
                  class="!min-w-[50px] !text-center !font-medium"
                >
                  {{ record.method }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="URL" data-index="url">
              <template #cell="{ record }">
                <span class="cell-secondary">{{ record.url }}</span>
              </template>
            </a-table-column>
          </template>
        </a-table>
        <div v-else class="text-center py-8 empty-text">
          请选择左侧模块查看接口列表
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.interface-table {
  --checkbox-size: 16px;
}

.interface-table :deep(.arco-checkbox) {
  background-color: transparent;
  border: 1px solid #4c5155;
  border-radius: 2px;
  width: var(--checkbox-size);
  height: var(--checkbox-size);
  display: flex;
  align-items: center;
  justify-content: center;
}

.interface-table :deep(.arco-checkbox:hover) {
  border-color: #165dff;
}

.interface-table :deep(.arco-checkbox-checked) {
  background-color: #165dff;
  border-color: #165dff;
}

.interface-table :deep(.arco-checkbox-checked .arco-checkbox-icon) {
  color: #fff;
  font-size: calc(var(--checkbox-size) * 0.75);
}

.interface-table :deep(.arco-table-th) {
  background-color: transparent !important;
  border-color: #4c5155 !important;
}

.interface-table :deep(.arco-table-td) {
  background-color: transparent !important;
  border-color: #4c5155 !important;
}

.interface-table :deep(.arco-table-tr) {
  background-color: transparent !important;
}

.interface-table :deep(.arco-table-tr:hover) {
  background-color: rgba(255, 255, 255, 0.04) !important;
}

.interface-table :deep(.arco-table-tr-checked) {
  background-color: rgba(22, 93, 255, 0.1) !important;
}

.hide-scrollbar {
  scrollbar-width: none;  /* Firefox */
  -ms-overflow-style: none;  /* IE and Edge */
}

.hide-scrollbar::-webkit-scrollbar {
  display: none;  /* Chrome, Safari and Opera */
}
</style>
