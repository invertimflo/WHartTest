<template>
  <div class="api-testing-container">
    <TestTaskForm :mode="mode" :id="id" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import TestTaskForm from '../components/testtasks/TestTaskForm.vue'

const props = defineProps<{ id?: string | number }>()
const router = useRouter()
const mode = computed(() => props.id ? 'edit' : 'create')
</script>

<style scoped>
.api-testing-container {
  height: 100%;
  background-color: rgb(17, 24, 39);
  border-radius: 8px;
  overflow: hidden;
}
</style>
