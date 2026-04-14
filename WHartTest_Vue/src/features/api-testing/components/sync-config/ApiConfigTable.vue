<script setup lang="ts">
import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconEmpty } from '@arco-design/web-vue/es/icon'
import type { TableColumnData } from '@arco-design/web-vue'
import type { ApiSyncConfig } from '../../services/syncService'

const props = defineProps<{
  loading: boolean
  configs: ApiSyncConfig[]
  selectedRowKeys: number[]
  fieldOptions: { label: string; value: string }[]
}>()

const emit = defineEmits<{
  (e: 'update:selectedRowKeys', value: number[]): void
  (e: 'sync', record: ApiSyncConfig): void
  (e: 'edit', record: ApiSyncConfig): void
  (e: 'view', record: ApiSyncConfig): void
  (e: 'delete', record: ApiSyncConfig): void
  (e: 'create'): void
}>()

const columns: TableColumnData[] = [
  {
    title: '序号',
    width: 60,
    align: 'center',
    slotName: 'index'
  },
  {
    title: '接口名称',
    width: 150,
    align: 'center',
    render: ({ record }) => record.interface_info?.name || '-'
  },
  {
    title: '用例名称',
    width: 150,
    align: 'center',
    render: ({ record }) => record.testcase_info?.name || '-'
  },
  {
    title: '步骤名称',
    width: 150,
    align: 'center',
    render: ({ record }) => record.step_info?.name || '-'
  },
  {
    title: '同步字段',
    width: 390,
    align: 'center',
    slotName: 'sync_fields'
  },
  {
    title: '同步模式',
    width: 100,
    align: 'center',
    render: ({ record }) => record.sync_mode === 'auto' ? '自动同步' : '手动同步'
  },
  {
    title: '状态',
    width: 60,
    align: 'center',
    slotName: 'status'
  },
  {
    title: '创建信息',
    width: 210,
    align: 'center',
    slotName: 'created_info'
  },
  {
    title: '操作',
    width: 120,
    align: 'center',
    slotName: 'operations'
  }
]
</script>

<template>
  <div class="bg-gray-800 rounded-lg shadow-xl border border-gray-700/50">
    <a-table
      :loading="loading"
      :data="configs"
      :columns="columns"
      :pagination="false"
      :bordered="false"
      :stripe="true"
      row-key="id"
      :rowSelection="{
        type: 'checkbox',
        showCheckedAll: true,
        selectedRowKeys,
        onChange: (selectedKeys: number[]) => emit('update:selectedRowKeys', selectedKeys)
      }"
      class="custom-table"
    >
      <template #empty>
        <div class="flex flex-col items-center justify-center py-16">
          <icon-empty class="text-gray-600 w-16 h-16 mb-4" />
          <div class="text-gray-400 mb-4">暂无同步配置</div>
          <a-button type="outline" size="large" @click="emit('create')">
            <template #icon>
              <icon-plus />
            </template>
            新建配置
          </a-button>
        </div>
      </template>

      <template #sync_fields="{ record }">
        <div class="flex flex-col gap-2">
          <!-- 第一行：请求相关字段 -->
          <div class="flex flex-wrap gap-1.5">
            <template v-for="field in record.sync_fields" :key="field">
              <a-tag
                v-if="['method', 'url', 'headers', 'params', 'body'].includes(field)"
                color="arcoblue"
                size="medium"
                class="rounded-md"
              >
                {{ fieldOptions.find(opt => opt.value === field)?.label || field }}
              </a-tag>
            </template>
          </div>
          <!-- 第二行：钩子和其他字段 -->
          <div class="flex flex-wrap gap-1.5">
            <template v-for="field in record.sync_fields" :key="field">
              <a-tag
                v-if="['setup_hooks', 'teardown_hooks', 'variables', 'validators', 'extract'].includes(field)"
                color="arcoblue"
                size="medium"
                class="rounded-md"
              >
                {{ fieldOptions.find(opt => opt.value === field)?.label || field }}
              </a-tag>
            </template>
          </div>
        </div>
      </template>

      <template #status="{ record }">
        <a-tag 
          :color="record.sync_enabled ? 'green' : 'red'"
          size="medium"
          class="rounded-md"
        >
          {{ record.sync_enabled ? '已启用' : '已禁用' }}
        </a-tag>
      </template>

      <template #created_info="{ record }">
        <div class="flex flex-col gap-1 text-sm">
          <div class="flex items-center gap-1">
            <span class="text-gray-400">创建者：</span>
            <span>{{ record.created_by_info?.username || '-' }}</span>
          </div>
          <div class="flex items-center gap-1">
            <span class="text-gray-400">时间：</span>
            <span>{{ record.created_at ? new Date(record.created_at).toLocaleString() : '-' }}</span>
          </div>
        </div>
      </template>

      <template #index="{ rowIndex }">
        <span class="text-gray-400">{{ rowIndex + 1 }}</span>
      </template>

      <template #operations="{ record }">
        <div class="flex items-center justify-center gap-0">
          <a-button
            type="text"
            size="mini"
            class="h-6 leading-6 px-2"
            :loading="loading"
            @click="emit('sync', record)"
          >
            同步
          </a-button>
          <a-button
            type="text"
            size="mini"
            class="h-6 leading-6 px-2"
            :loading="loading"
            @click="emit('edit', record)"
          >
            编辑
          </a-button>
          <a-button
            type="text"
            size="mini"
            class="h-6 leading-6 px-2"
            :loading="loading"
            @click="emit('view', record)"
          >
            详情
          </a-button>
          <a-button
            type="text"
            size="mini"
            class="h-6 leading-6 px-2 mt-0.5"
            status="danger"
            :loading="loading"
            @click="emit('delete', record)"
          >
            删除
          </a-button>
        </div>
      </template>
    </a-table>
  </div>
</template>

<style scoped>
@reference "tailwindcss";
:deep(.custom-table) {
  @apply bg-transparent;
}

:deep(.custom-table .arco-table-container) {
  @apply border-0;
}

:deep(.custom-table .arco-table-th) {
  @apply bg-gray-900/50 text-gray-300 border-gray-700 font-medium text-sm py-4;
}

:deep(.custom-table .arco-table-td) {
  @apply bg-transparent text-gray-300 border-gray-700/50;
}

:deep(.custom-table .arco-table-tr:hover .arco-table-td) {
  @apply bg-gray-700/30;
}
</style> 