<template>
  <div class="api-testing-container">
    <TestCaseForm
      v-if="projectId"
      :project-id="projectId"
      mode="create"
      @success="handleSuccess"
      @cancel="router.push('/api-testing')"
    />
    <div v-else class="flex items-center justify-center h-full text-gray-500">
      请先选择项目
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/store/projectStore'
import TestCaseForm from '../components/testcases/TestCaseForm.vue'

const router = useRouter()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

const handleSuccess = (payload: { id: number }) => {
  router.replace({ name: 'ApiTestCaseEdit', params: { id: payload.id } })
}
</script>

<style scoped>
.api-testing-container {
  height: 100%;
  background-color: rgb(17, 24, 39);
  border-radius: 8px;
  overflow: hidden;
}
</style>
