<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Environment } from '../../services/environmentService'
import {
  IconStorage,
  IconEdit,
  IconCopy,
  IconDelete,
  IconSettings,
  IconApps,
} from '@arco-design/web-vue/es/icon'

interface Props {
  environment: Environment
}

interface Emits {
  (e: 'edit'): void
  (e: 'clone'): void
  (e: 'delete'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 添加 watch 来调试变量数据
watch(() => props.environment.variables, (newVal) => {
  console.log('环境变量数据:', newVal)
}, { immediate: true, deep: true })
</script>

<template>
  <div class="h-full overflow-hidden">
    <div class="h-full overflow-y-auto overflow-x-hidden custom-scrollbar p-6 space-y-4">
      <!-- 顶部信息栏 -->
      <a-card class="!bg-[#1D2433] !border-gray-800 !rounded-lg">
        <div class="flex items-center justify-between flex-wrap gap-y-2">
          <div class="flex items-center gap-3 mr-2">
            <div class="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0">
              <icon-storage class="text-blue-500" />
            </div>
            <h2 class="text-lg font-medium text-gray-100">
              {{ environment.name }}
            </h2>
            <a-tag
              :color="environment.is_active ? 'green' : 'red'"
              size="small"
            >{{ environment.is_active ? '启用' : '禁用' }}</a-tag>
          </div>
          <div class="flex items-center gap-2 flex-shrink-0">
            <a-button type="outline" size="small" @click="emit('edit')">
              <template #icon><icon-edit /></template>
              编辑
            </a-button>
            <a-button type="outline" size="small" @click="emit('clone')">
              <template #icon><icon-copy /></template>
              克隆
            </a-button>
            <a-popconfirm
              content="确定要删除这个环境吗？"
              type="warning"
              position="left"
              @ok="emit('delete')"
            >
              <a-button type="outline" status="danger" size="small">
                <template #icon><icon-delete /></template>
                删除
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </a-card>

      <!-- 基本信息卡片 -->
      <a-card class="!bg-gray-900/30 !border-gray-700 !rounded-lg">
        <template #title>
          <div class="flex items-center gap-2">
            <icon-settings class="text-gray-400" />
            <span class="text-gray-300">基本信息</span>
          </div>
        </template>
        <div class="space-y-6 overflow-hidden">
          <!-- 所属项目 -->
          <div class="space-y-2">
            <div class="text-sm text-gray-400">所属项目</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 break-all">
              {{ environment.project_info?.name || environment.project_name }}
            </div>
          </div>
          <!-- 父环境 -->
          <div class="space-y-2" v-if="environment.parent_info">
            <div class="text-sm text-gray-400">父环境</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 break-all">
              {{ environment.parent_info.name }}
            </div>
          </div>
          <!-- 数据库配置 -->
          <div class="space-y-2" v-if="environment.database_config_info">
            <div class="text-sm text-gray-400">数据库配置</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 space-y-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">名称：</span>
                <span class="break-all">{{ environment.database_config_info.name }}</span>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">类型：</span>
                <span>{{ environment.database_config_info.db_type }}</span>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">主机：</span>
                <span>{{ environment.database_config_info.host }}</span>
              </div>
            </div>
          </div>
          <!-- 基础URL -->
          <div class="space-y-2">
            <div class="text-sm text-gray-400">基础 URL</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 break-all">
              {{ environment.base_url }}
            </div>
          </div>
          <!-- 描述 -->
          <div class="space-y-2" v-if="environment.description">
            <div class="text-sm text-gray-400">描述</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 whitespace-pre-wrap">
              {{ environment.description }}
            </div>
          </div>
          <!-- 创建信息 -->
          <div class="space-y-2">
            <div class="text-sm text-gray-400">创建信息</div>
            <div class="p-3 bg-gray-800/50 rounded-lg text-gray-300 space-y-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">创建人：</span>
                <span class="break-all">{{ environment.created_by_name }}</span>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">创建时间：</span>
                <span>{{ new Date(environment.created_at).toLocaleString('zh-CN') }}</span>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-gray-400">更新时间：</span>
                <span>{{ new Date(environment.updated_at).toLocaleString('zh-CN') }}</span>
              </div>
            </div>
          </div>
        </div>
      </a-card>

      <!-- 环境变量卡片 -->
      <a-card class="!bg-[#1D2433] !border-gray-800 !rounded-lg">
        <template #title>
          <div class="flex items-center gap-2">
            <icon-apps class="text-gray-400" />
            <span class="text-gray-300">环境变量</span>
          </div>
        </template>
        <div class="space-y-4 overflow-hidden">
          <div
            v-for="(variable, index) in environment.variables"
            :key="index"
            class="flex items-start gap-3 p-3 bg-gray-900/60 rounded-lg"
          >
            <div class="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center flex-shrink-0">
              <icon-apps class="text-purple-400" />
            </div>
            <div class="flex-1 min-w-0 overflow-hidden">
              <div class="flex items-center gap-2 mb-2 flex-wrap">
                <span class="text-sm font-medium text-gray-300">变量 #{{ index + 1 }}</span>
                <span class="text-xs text-gray-500">·</span>
                <span class="text-xs text-gray-400 truncate">{{ variable.description || '暂无描述' }}</span>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div class="space-y-1 overflow-hidden">
                  <div class="text-xs text-gray-400">变量名</div>
                  <div class="text-sm text-gray-300 break-all">{{ variable.name }}</div>
                </div>
                <div class="space-y-1 overflow-hidden">
                  <div class="text-xs text-gray-400">变量值</div>
                  <div class="text-sm text-gray-300 break-all">{{ variable.value }}</div>
                </div>
              </div>
            </div>
          </div>
          
          <!-- 无变量时的提示 -->
          <div
            v-if="!environment.variables?.length"
            class="text-center py-8 text-gray-400"
          >
            暂无环境变量
          </div>
        </div>
      </a-card>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
.custom-scrollbar {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
  
  &::-webkit-scrollbar {
    display: none; /* Chrome, Safari, Opera*/
  }
}
</style> 