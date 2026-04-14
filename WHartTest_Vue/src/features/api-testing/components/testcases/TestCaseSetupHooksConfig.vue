<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { functionService } from '../../services/functionService'
import { useProjectStore } from '@/store/projectStore'
import type { ApiCustomFunction } from '../../types/function'

interface Props {
  hooks?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  hooks: () => []
})

const emit = defineEmits(['update:hooks'])
const projectStore = useProjectStore()

const state = ref({
  selectedFunctions: [] as number[],
  functions: [] as ApiCustomFunction[],
  loading: false
})

const loadFunctions = async () => {
  if (!projectStore.currentProjectId) return
  state.value.loading = true
  try {
    const res = await functionService.list(projectStore.currentProjectId)
    if (res.success && res.data) {
      state.value.functions = Array.isArray(res.data) ? res.data : (res.data as any).results || []
    }
    if (props.hooks && props.hooks.length > 0) {
      state.value.selectedFunctions = props.hooks.map(hook => {
        const fid = typeof hook === 'string' ? parseInt(hook) : -1
        return isNaN(fid) ? -1 : fid
      }).filter(id => id !== -1)
    }
  } catch (error) {
    console.error('Failed to load functions:', error)
  } finally {
    state.value.loading = false
  }
}

watch(() => props.hooks, (newHooks) => {
  if (newHooks && newHooks.length > 0) {
    state.value.selectedFunctions = newHooks.map(hook => {
      const fid = typeof hook === 'string' ? parseInt(hook) : -1
      return isNaN(fid) ? -1 : fid
    }).filter(id => id !== -1)
  } else {
    state.value.selectedFunctions = []
  }
}, { immediate: true, deep: true })

watch(() => projectStore.currentProjectId, () => { loadFunctions() })

const getHooks = () => {
  if (state.value.selectedFunctions.length > 0) {
    return state.value.selectedFunctions.map(id => {
      const func = state.value.functions.find(f => f.id === id)
      return func ? String(func.id) : ''
    }).filter(Boolean)
  }
  return []
}

onMounted(() => { loadFunctions() })
defineExpose({ getHooks })
</script>

<template>
  <div class="h-full flex flex-col p-4 gap-4">
    <a-select
      v-model="state.selectedFunctions"
      :loading="state.loading"
      placeholder="选择前置函数"
      allow-clear
      multiple
    >
      <a-option v-for="func in state.functions" :key="func.id" :value="func.id">
        {{ func.name }}
      </a-option>
    </a-select>
    <div v-if="state.selectedFunctions.length > 0" class="flex flex-col gap-2">
      <div class="selected-label">已选择的函数：</div>
      <div class="flex flex-wrap gap-2">
        <a-tag
          v-for="id in state.selectedFunctions"
          :key="id"
          closable
          @close="state.selectedFunctions = state.selectedFunctions.filter(fid => fid !== id)"
        >
          {{ state.functions.find(f => f.id === id)?.name || `函数${id}` }}
        </a-tag>
      </div>
    </div>
  </div>
</template>

<style lang="postcss" scoped>
@reference "tailwindcss";
:deep(.arco-select-view) {
  @apply bg-gray-900/60 border-gray-700;

  input {
    @apply text-gray-200 bg-transparent;
    &::placeholder {
      @apply text-gray-500;
    }
  }
}

:deep(.arco-select-dropdown) {
  @apply bg-gray-800 border-gray-700;

  .arco-select-option {
    @apply text-gray-300;

    &:hover {
      @apply bg-gray-700;
    }

    &.arco-select-option-active {
      @apply bg-blue-500/20 text-blue-500;
    }
  }
}

:deep(.arco-tag) {
  @apply bg-blue-500/20 border-blue-500/50 text-blue-500;
}
</style>
