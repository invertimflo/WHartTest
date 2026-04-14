<script setup lang="ts">
import { IconClose } from '@arco-design/web-vue/es/icon'

defineEmits(['close'])
</script>

<template>
  <div class="bg-gray-800 rounded-lg border border-gray-700 px-4 py-3 flex justify-between items-center">
    <span class="text-[#e5e6e8] font-medium">添加接口</span>
    <a-button class="!bg-transparent !border-0 !p-0 hover:!bg-gray-600/50" @click="$emit('close')">
      <template #icon>
        <icon-close />
      </template>
    </a-button>
  </div>
</template>

<style scoped>
</style>
