<script setup lang="ts">
import { computed } from 'vue'
import type { ApiModule } from '../../types/module'
import { IconRight, IconDown } from '@arco-design/web-vue/es/icon'

interface Props {
  module: ApiModule
  level?: number
  expandedIds: number[]
  selectedId?: number
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  level: 0,
  loading: false
})

const emit = defineEmits<{
  (e: 'select', module: ApiModule): void
  (e: 'toggle-expand', moduleId: number): void
}>()

const paddingLeft = computed(() => {
  return props.level * 4 + 6
})

const isExpanded = computed(() => {
  return props.expandedIds.includes(props.module.id)
})

const isSelected = computed(() => {
  return props.selectedId === props.module.id
})

const handleSelect = () => {
  emit('select', props.module)
}

const handleToggleExpand = () => {
  emit('toggle-expand', props.module.id)
}
</script>

<template>
  <div class="space-y-1">
    <!-- 当前模块 -->
    <div
      class="px-6 py-2 cursor-pointer transition-colors bg-[rgb(70,84,102,0.4)] hover:bg-[rgb(47,66,114,0.4)] rounded-lg"
      :class="{ 'bg-[rgb(47,66,114,0.4)]': isSelected }"
      :style="{ paddingLeft: `${paddingLeft}px` }"
      @click.stop="handleSelect"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <div class="w-4 flex items-center justify-center">
            <a-button
              v-if="module.children?.length"
              type="text"
              size="mini"
              class="!w-4 !h-4 !p-0 !min-w-0 !text-[#6b7785] hover:!text-[#86909c]"
              @click.stop="handleToggleExpand"
            >
              <template #icon>
                <icon-right v-if="!isExpanded" class="!w-3 !h-3" />
                <icon-down v-else class="!w-3 !h-3" />
              </template>
            </a-button>
            <div v-else class="w-4"></div>
          </div>
          <a-spin :loading="loading" dot>
            <span class="text-[#e5e6e8]">{{ module.name }}</span>
          </a-spin>
        </div>
      </div>
    </div>

    <!-- 子模块递归渲染 -->
    <div v-if="isExpanded && module.children?.length" class="space-y-1">
      <ModuleTreeSelect
        v-for="child in module.children"
        :key="child.id"
        :module="child"
        :level="level + 1"
        :expanded-ids="expandedIds"
        :selected-id="selectedId"
        :loading="loading"
        @select="emit('select', $event)"
        @toggle-expand="emit('toggle-expand', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
</style>
