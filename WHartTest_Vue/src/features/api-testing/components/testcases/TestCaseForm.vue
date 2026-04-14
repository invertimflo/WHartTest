<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { testcaseService } from '../../services/testcaseService'
import { testReportService } from '../../services/testReportService'
import type { CreateTestCaseData, TestCaseStep } from '../../services/testcaseService'
import type { ApiTestReportDetail } from '../../types/testcase'
import { useProjectStore } from '@/store/projectStore'
import TestCaseHeader from './TestCaseHeader.vue'
import TestCaseStepList from './TestCaseStepList.vue'
import TestCaseStepDetail from './TestCaseStepDetail.vue'
import ExecutionSteps from '../test-reports/ExecutionSteps.vue'

interface Props {
  projectId: number
  mode?: 'create' | 'edit' | 'view'
  testCaseId?: number
}

const props = withDefaults(defineProps<Props>(), {
  mode: 'create'
})
const emit = defineEmits(['cancel', 'success', 'update:testCaseId'])

const projectStore = useProjectStore()

const currentTestCaseId = ref<number | undefined>(props.testCaseId)

const testCaseId = computed(() => {
  return currentTestCaseId.value || props.testCaseId
})

const loading = ref(false)
const activeStep = ref<TestCaseStep | null>(null)

// 报告相关
const showReport = ref(false)
const reportLoading = ref(false)
const latestReport = ref<any>(null)

// 初始化表单数据
const formData = reactive<CreateTestCaseData>({
  name: '',
  description: '',
  project: props.projectId,
  priority: 'P3',
  config: {
    base_url: '',
    variables: '',
    parameters: '',
    export: '',
    verify: ''
  },
  steps_info: []
})

const readonly = computed(() => props.mode === 'view')

interface TestCaseStepForHeader {
  id: number
  name: string
  interface_data: {
    extract?: Record<string, string>
  }
}

const steps = ref<TestCaseStep[]>([])

const stepsForHeader = computed<TestCaseStepForHeader[]>(() => {
  return steps.value.map(step => ({
    id: step.id || 0,
    name: step.name,
    interface_data: {
      extract: step.interface_data.extract as Record<string, string>
    }
  }))
})

const updateSteps = (newSteps: TestCaseStep[]) => {
  steps.value = newSteps.map(step => ({
    ...step,
    interface_info: {
      ...step.interface_info,
      module_info: step.interface_info.module_info || {
        id: step.interface_info.module?.id || 0,
        name: step.interface_info.module?.name || ''
      }
    }
  }))

  formData.steps_info = steps.value.map((step, index) => ({
    name: step.name,
    interface_id: step.interface_info.id || 0,
    order: step.order || index + 1,
    interface_data: {
      ...step.interface_data,
      module: step.interface_info.module_info?.id || step.interface_data.module || 0
    },
    config: step.config,
    sync_fields: step.sync_fields
  }))
}

const fetchTestCaseDetail = async () => {
  if (props.mode !== 'create' && testCaseId.value && projectStore.currentProjectId) {
    try {
      loading.value = true
      const res = await testcaseService.get(projectStore.currentProjectId, testCaseId.value)

      if (!res.success || !res.data) {
        throw new Error(res.error || '获取用例详情失败')
      }

      const testCase = res.data as any
      console.log('获取到的用例详情:', testCase)

      formData.name = testCase.name || ''
      formData.description = testCase.description || ''
      formData.priority = testCase.priority || 'P3'
      formData.group = testCase.group === null ? undefined : testCase.group
      formData.tags = testCase.tags || []
      formData.config = {
        base_url: testCase.config?.base_url || '',
        variables: testCase.config?.variables || '',
        parameters: testCase.config?.parameters || '',
        export: testCase.config?.export || '',
        verify: testCase.config?.verify || ''
      }

      updateSteps(testCase.steps || [])
    } catch (error) {
      console.error('获取用例详情失败:', error)
      Message.error(error instanceof Error ? error.message : '获取用例详情失败')
    } finally {
      loading.value = false
    }
  }
}

onMounted(() => {
  fetchTestCaseDetail()
})

const handleAddStep = () => {
  if (readonly.value) return

  const newStep: TestCaseStep = {
    id: 0,
    name: `步骤${steps.value.length + 1}`,
    order: steps.value.length + 1,
    interface_info: {
      id: 0,
      name: '',
      method: 'GET',
      url: '',
      module: { id: 0, name: '' },
      project: { id: props.projectId, name: '' }
    },
    interface_data: {
      method: 'GET',
      url: '',
      headers: {},
      params: {},
      body: {},
      validators: [],
      extract: {},
      setup_hooks: [],
      teardown_hooks: [],
      variables: {}
    },
    config: {
      variables: {},
      validators: [],
      extract: {},
      setup_hooks: [],
      teardown_hooks: []
    },
    sync_fields: [
      'method', 'url', 'headers', 'params', 'body',
      'setup_hooks', 'teardown_hooks', 'variables', 'validators', 'extract'
    ],
    last_sync_time: null
  }

  const newSteps = [...steps.value, newStep]
  updateSteps(newSteps)
  handleStepSelect(newSteps[newSteps.length - 1])
}

const handleStepSelect = (step: TestCaseStep | null) => {
  if (step) {
    showReport.value = false
    activeStep.value = {
      ...step,
      interface_info: {
        ...step.interface_info,
        module: step.interface_info.module || { id: 0, name: '' },
        module_info: step.interface_info.module_info || step.interface_info.module || { id: 0, name: '' },
        project: step.interface_info.project || { id: props.projectId, name: '' }
      },
      interface_data: {
        ...step.interface_data,
        headers: step.interface_data.headers || {},
        params: step.interface_data.params || {},
        body: step.interface_data.body || {},
        validators: step.interface_data.validators || [],
        extract: step.interface_data.extract || {},
        setup_hooks: step.interface_data.setup_hooks || [],
        teardown_hooks: step.interface_data.teardown_hooks || [],
        variables: step.interface_data.variables || {}
      },
      config: {
        ...step.config,
        variables: step.config?.variables || {},
        validators: step.config?.validators || [],
        extract: step.config?.extract || {},
        setup_hooks: step.config?.setup_hooks || [],
        teardown_hooks: step.config?.teardown_hooks || []
      }
    }
  } else {
    activeStep.value = null
  }
}

const handleStepDelete = (step: TestCaseStep) => {
  if (readonly.value) return
  const index = steps.value.findIndex(s => s === step)
  if (index !== -1) {
    const newSteps = [...steps.value]
    newSteps.splice(index, 1)
    newSteps.forEach((s, i) => { s.order = i + 1 })
    updateSteps(newSteps)
    if (activeStep.value === step) {
      activeStep.value = null
    }
  }
}

const validateForm = () => {
  if (!formData.name) {
    Message.error('请输入用例名称')
    return false
  }
  if (!formData.priority) {
    Message.error('请选择优先级')
    return false
  }
  return true
}

const handleSubmit = async (continueAction?: () => void) => {
  if (readonly.value) return false
  if (!validateForm()) return false
  if (!projectStore.currentProjectId) return false

  try {
    loading.value = true
    const submitData: CreateTestCaseData = {
      ...formData,
      steps_info: steps.value.map((step, index) => ({
        name: step.name,
        interface_id: step.interface_info.id || 0,
        interface_data: step.interface_data,
        config: step.config,
        sync_fields: step.sync_fields,
        order: index + 1
      }))
    }

    if (props.mode === 'edit' && testCaseId.value) {
      const res = await testcaseService.update(projectStore.currentProjectId, testCaseId.value, submitData as any)
      if (res.success) {
        Message.success('更新成功')
        await fetchTestCaseDetail()
      } else {
        throw new Error(res.error || '更新失败')
      }
    } else {
      const res = await testcaseService.create(projectStore.currentProjectId, submitData as any)
      if (res.success && res.data) {
        Message.success('创建成功，现在您可以添加测试步骤了')
        const newId = (res.data as any).id
        if (newId) {
          currentTestCaseId.value = newId
          emit('update:testCaseId', newId)
          emit('success', { id: newId, mode: 'created' })
        }
      } else {
        throw new Error(res.error || '创建失败')
      }
    }

    if (continueAction) {
      setTimeout(() => { continueAction() }, 500)
    }

    return true
  } catch (error) {
    Message.error(props.mode === 'edit' ? '更新失败' : '创建失败')
    return false
  } finally {
    loading.value = false
  }
}

const handleCancel = () => {
  emit('cancel')
}

const updateHeaderData = (data: Pick<CreateTestCaseData, 'name' | 'description' | 'priority' | 'group' | 'tags'>) => {
  Object.assign(formData, data)
}

const updateStepData = (step: TestCaseStep) => {
  const index = steps.value.findIndex(s => {
    if (activeStep.value) {
      if (!s.id) return s.order === activeStep.value.order
      return s.id === activeStep.value.id
    }
    return false
  })

  if (index !== -1) {
    const newSteps = [...steps.value]
    if (!steps.value[index].id) { step.id = 0 }
    newSteps[index] = step
    updateSteps(newSteps)
    activeStep.value = step
  }
}

// 运行用例
const runResultLoading = ref(false)

const handleRun = async (data: { testCaseId: number, environmentId: number }) => {
  if (!projectStore.currentProjectId) return
  try {
    runResultLoading.value = true
    const res = await testcaseService.run(projectStore.currentProjectId, data.testCaseId, {
      environment_id: data.environmentId
    })

    if (res.success && res.data) {
      Message.success('用例运行成功')
      const reportId = (res.data as any).report_id
      if (reportId) {
        await fetchReportDetail(Number(reportId))
        return
      }
      // Fallback: get latest report
      const historyRes = await testcaseService.historyReports(projectStore.currentProjectId!, data.testCaseId, {
        page: 1,
        page_size: 1
      })
      if (historyRes.success && historyRes.data) {
        const reports = Array.isArray(historyRes.data) ? historyRes.data : (historyRes.data as any).results || []
        if (reports.length > 0) {
          await fetchReportDetail(reports[0].id)
        } else {
          Message.warning('获取运行结果失败，请前往报告列表查看')
        }
      }
    } else {
      throw new Error(res.error || '运行用例失败')
    }
  } catch (error) {
    console.error('运行用例失败:', error)
    Message.error(error instanceof Error ? error.message : '运行用例失败')
  } finally {
    runResultLoading.value = false
  }
}

const fetchReportDetail = async (reportId: number) => {
  if (!projectStore.currentProjectId) return
  try {
    reportLoading.value = true
    const res = await testReportService.get(projectStore.currentProjectId, reportId)
    if (res.success && res.data) {
      latestReport.value = res.data
      showReport.value = true
      activeStep.value = null
    } else {
      Message.error('获取报告详情失败')
    }
  } catch (error) {
    console.error('获取报告详情失败:', error)
    Message.error('获取报告详情失败，请稍后重试')
  } finally {
    reportLoading.value = false
  }
}

const handleShowReport = async (tcId: number) => {
  if (!projectStore.currentProjectId) return
  try {
    reportLoading.value = true
    const res = await testcaseService.historyReports(projectStore.currentProjectId, tcId, {
      page: 1,
      page_size: 1
    })
    if (res.success && res.data) {
      const reports = Array.isArray(res.data) ? res.data : (res.data as any).results || []
      if (reports.length > 0) {
        await fetchReportDetail(reports[0].id)
      } else {
        Message.warning('该测试用例暂无报告，请先运行测试')
        showReport.value = false
      }
    }
  } catch (error) {
    console.error('获取报告列表失败:', error)
    Message.error('获取报告列表失败，请稍后重试')
  } finally {
    reportLoading.value = false
  }
}
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4 overflow-hidden">
    <!-- 顶部：基础信息 -->
    <div class="flex-shrink-0 form-card p-4">
      <test-case-header
        :model-value="{
          name: formData.name || '',
          description: formData.description || '',
          priority: formData.priority,
          group: formData.group !== undefined ? formData.group : null,
          tags: formData.tags || [],
          config: {
            base_url: formData.config?.base_url || '',
            variables: typeof formData.config?.variables === 'string' ? formData.config.variables : JSON.stringify(formData.config?.variables || {}),
            parameters: typeof formData.config?.parameters === 'string' ? formData.config.parameters : JSON.stringify(formData.config?.parameters || {}),
            export: Array.isArray(formData.config?.export) ? formData.config.export : [],
            verify: typeof formData.config?.verify === 'boolean' ? formData.config.verify : true
          }
        }"
        :loading="loading"
        :readonly="readonly"
        :project-id="projectId"
        :test-case-id="testCaseId"
        :steps="stepsForHeader"
        @update:model-value="updateHeaderData"
        @cancel="handleCancel"
        @save="handleSubmit"
        @run="handleRun"
        @show-report="handleShowReport"
      />
    </div>

    <!-- 主体内容：左侧步骤列表 + 右侧步骤详情 -->
    <div class="flex-1 flex gap-4 min-h-0">
      <!-- 左侧：步骤列表 -->
      <div class="w-[20%] form-card p-4 overflow-hidden">
        <test-case-step-list
          :steps="steps"
          :active-step="activeStep"
          :readonly="readonly"
          :test-case-id="testCaseId"
          :test-case="{
            name: formData.name || '',
            priority: formData.priority as 'P0' | 'P1' | 'P2' | 'P3',
            project: formData.project,
            description: formData.description,
            group: formData.group,
            tags: formData.tags || [],
            config: {
              base_url: formData.config?.base_url || '',
              variables: typeof formData.config?.variables === 'string' ? {} : (formData.config?.variables || {}),
              parameters: typeof formData.config?.parameters === 'string' ? {} : (formData.config?.parameters || {}),
              export: Array.isArray(formData.config?.export) ? formData.config.export : [],
              verify: typeof formData.config?.verify === 'boolean' ? formData.config.verify : true
            }
          }"
          @add="handleAddStep"
          @select="handleStepSelect"
          @delete="handleStepDelete"
          @update:steps="updateSteps"
          @save-test-case="(callback) => handleSubmit(callback)"
        />
      </div>

      <!-- 右侧：步骤详情或报告详情 -->
      <div class="flex-1 min-w-0 form-card overflow-hidden">
        <!-- 步骤详情 -->
        <test-case-step-detail
          v-if="activeStep && !showReport"
          :model-value="activeStep"
          :readonly="readonly"
          :test-case-id="testCaseId"
          @update:model-value="updateStepData"
        />

        <!-- 报告详情 -->
        <a-spin :loading="reportLoading" dot class="h-full" v-else-if="showReport && latestReport">
          <div class="h-full overflow-auto p-4">
            <execution-steps :report="latestReport" />
          </div>
        </a-spin>

        <!-- 空状态 -->
        <div v-else class="flex items-center justify-center h-full empty-text">
          {{ showReport ? '暂无报告数据' : (readonly ? '请选择步骤查看详情' : '请选择或添加步骤') }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.form-card {
  background-color: rgba(31, 41, 55, 0.5);
  border-radius: 0.5rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
}
.empty-text {
  color: rgb(107, 114, 128);
}
</style>
