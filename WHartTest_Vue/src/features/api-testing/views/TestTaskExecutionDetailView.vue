<template>
  <div class="api-testing-container">
    <TestTaskExecutionDetail />
  </div>
</template>

<script setup lang="ts">
import TestTaskExecutionDetail from '../components/testtasks/TestTaskExecutionDetail.vue'
</script>

<style scoped>
.api-testing-container {
  height: 100%;
  background-color: rgb(17, 24, 39);
  border-radius: 8px;
  overflow: hidden;
}
</style>
