<script setup lang="ts">
import { ref, computed } from 'vue'
import { IconSearch } from '@arco-design/web-vue/es/icon'
import type { ApiModule } from '../../types/module'
import ModuleTreeSelect from './ModuleTreeSelect.vue'

const props = defineProps<{
  modules: ApiModule[]
  expandedIds: number[]
  selectedId?: number
  loading: boolean
}>()

const emit = defineEmits(['select', 'toggle-expand'])

const searchKeyword = ref('')

const filteredModules = computed(() => {
  if (!searchKeyword.value) return props.modules

  const keyword = searchKeyword.value.toLowerCase()
  return props.modules.filter(item =>
    item.name.toLowerCase().includes(keyword)
  )
})
</script>

<template>
  <div class="w-[280px] bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
    <div class="p-4 border-b border-gray-700">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[#e5e6e8]">模块列表</span>
      </div>
      <div class="flex items-center gap-2">
        <a-input-search
          v-model="searchKeyword"
          placeholder="搜索模块"
          allow-clear
        >
          <template #prefix>
            <icon-search />
          </template>
        </a-input-search>
      </div>
    </div>
    <div class="overflow-y-auto hide-scrollbar" style="height: 480px">
      <div class="p-2 space-y-1">
        <ModuleTreeSelect
          v-for="module in filteredModules"
          :key="module.id"
          :module="module"
          :expanded-ids="expandedIds"
          :selected-id="selectedId"
          :loading="loading"
          @select="$emit('select', $event)"
          @toggle-expand="$emit('toggle-expand', $event)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.hide-scrollbar {
  scrollbar-width: none;  /* Firefox */
  -ms-overflow-style: none;  /* IE and Edge */
}

.hide-scrollbar::-webkit-scrollbar {
  display: none;  /* Chrome, Safari and Opera */
}
</style>
