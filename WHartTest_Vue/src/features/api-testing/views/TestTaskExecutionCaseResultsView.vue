<template>
  <div class="api-testing-container">
    <TestTaskExecutionCaseResults />
  </div>
</template>

<script setup lang="ts">
import TestTaskExecutionCaseResults from '../components/testtasks/TestTaskExecutionCaseResults.vue'
</script>

<style scoped>
.api-testing-container {
  height: 100%;
  background-color: rgb(17, 24, 39);
  border-radius: 8px;
  overflow: hidden;
}
</style>
