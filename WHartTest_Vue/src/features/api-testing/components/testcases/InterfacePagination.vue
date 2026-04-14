<script setup lang="ts">
defineProps<{
  current: number
  pageSize: number
  total: number
}>()

defineEmits(['change', 'page-size-change'])
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 px-4 py-3">
    <a-pagination
      :current="current"
      :page-size="pageSize"
      :total="total"
      @update:current="$emit('change', $event)"
      @update:page-size="$emit('page-size-change', $event)"
      show-total
      show-jumper
      show-page-size
      class="flex justify-end"
    />
  </div>
</template>

<style scoped>
:deep(.arco-pagination) {
  .arco-pagination-item {
    border-radius: 4px !important;
    color: #94a3b8 !important;
    background-color: transparent !important;
    border: 1px solid transparent !important;

    &:hover {
      color: #60a5fa !important;
      background-color: rgba(59, 130, 246, 0.1) !important;
      border-color: rgba(59, 130, 246, 0.2) !important;
    }

    &.arco-pagination-item-active {
      background-color: rgba(59, 130, 246, 0.2) !important;
      color: #60a5fa !important;
      border-color: rgba(59, 130, 246, 0.3) !important;
    }
  }

  .arco-pagination-jumper {
    .arco-input {
      border-radius: 4px !important;
      background-color: rgba(30, 41, 59, 0.5) !important;
      border: 1px solid rgba(148, 163, 184, 0.1) !important;
      color: #e2e8f0 !important;

      &:hover, &:focus {
        border-color: rgba(59, 130, 246, 0.5) !important;
        background-color: rgba(30, 41, 59, 0.7) !important;
      }
    }
  }

  .arco-pagination-total {
    color: #94a3b8 !important;
  }

  .arco-select-view {
    background-color: rgba(30, 41, 59, 0.5) !important;
    border: 1px solid rgba(148, 163, 184, 0.1) !important;
    border-radius: 4px !important;

    &:hover {
      border-color: rgba(59, 130, 246, 0.5) !important;
      background-color: rgba(30, 41, 59, 0.7) !important;
    }
  }
}
</style>
