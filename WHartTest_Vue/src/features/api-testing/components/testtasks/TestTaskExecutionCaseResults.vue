<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message, Tag as ATag, Collapse as ACollapse, CollapseItem as ACollapseItem, 
         Progress as AProgress, Tooltip as ATooltip } from '@arco-design/web-vue'
import { IconExclamationCircleFill } from '@arco-design/web-vue/es/icon'
import { getTestTaskExecutionCaseResults, getTestTaskExecution } from '../../services/testTaskService'
import ApiDetailCard from './ApiDetailCard.vue'

interface ValidateExtractor {
  check: string
  expect: string
  message: string
  comparator: string
  check_value: string
  check_result: string
  expect_value: string
}

interface StepDetail {
  id: number
  step_name: string
  success: boolean
  elapsed: number
  request: {
    url: string
    method: string
    headers: Record<string, string>
    body?: any
  }
  response: {
    status_code: number
    headers: Record<string, string>
    body: any
    response_time_ms: number
  }
  validators: {
    success: boolean
    validate_extractor: ValidateExtractor[]
  }
  extracted_variables: Record<string, any>
  attachment: string
}

interface TestReport {
  id: number
  name: string
  status: string
  success_count: number
  fail_count: number
  error_count: number
  duration: number
  start_time: string
  summary: {
    success: boolean
    step_results: any[]
  }
  details: StepDetail[]
  success_rate: string
  environment_info: {
    name: string
    base_url: string
    project: {
      name: string
    }
  }
  executed_by_info: {
    username: string
  }
}

interface CaseResult {
  id: number
  testcase: number
  testcase_name: string
  status: string
  start_time: string
  end_time: string
  duration: number
  error_message: string
  report: TestReport
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const caseResults = ref<CaseResult[]>([])
const expandedStepIds = ref<Record<number, number[]>>({})

// 获取用例执行结果
const fetchCaseResults = async () => {
  const id = route.params.id
  if (!id) {
    Message.warning('未指定执行记录ID')
    return
  }

  loading.value = true
  try {
    const { data } = await getTestTaskExecutionCaseResults(Number(id))
    if (data) {
      caseResults.value = data as any
    }
  } catch (error) {
    console.error('获取用例执行结果失败', error)
    Message.error(error instanceof Error ? error.message : '获取用例执行结果失败')
  } finally {
    loading.value = false
  }
}

// 返回历史记录页面
const goBack = async () => {
  try {
    const executionId = Number(route.params.id);
    const response = await getTestTaskExecution(executionId);
    if (response?.status === 'success' && response.data?.task_suite) {
      router.push({ name: 'ApiTestTaskDetail', params: { id: response.data.task_suite } });
    } else {
      router.push({ path: '/api-testing', query: { tab: 'testtasks' } });
    }
  } catch {
    router.push({ path: '/api-testing', query: { tab: 'testtasks' } });
  }
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    // 检查日期是否有效
    if (isNaN(date.getTime())) {
      return '-'
    }
    return date.toLocaleString('zh-CN')
  } catch (error) {
    console.error('日期格式化错误:', error)
    return '-'
  }
}

// 格式化持续时间
const formatDuration = (seconds: number) => {
  if (seconds === undefined || seconds === null || isNaN(seconds)) return '-'
  try {
    return `${Number(seconds).toFixed(2)}秒`
  } catch (error) {
    console.error('持续时间格式化错误:', error)
    return '-'
  }
}

// 展开行渲染函数
const expandedRowRender = (record: any) => {
  // 如果 report 为 null，显示错误信息
  if (!record.report) {
    return h('div', { 
      class: 'bg-gray-900/30 rounded-lg p-4 mt-4' 
    }, [
      h('div', { class: 'flex items-center gap-2' }, [
        h('span', { class: 'text-red-400' }, '错误信息：'),
        h('span', { class: 'text-red-300' }, record.error_message || '未知错误')
      ])
    ])
  }

  try {
    // 确保该记录在 expandedStepIds 中有对应的数组
    if (!expandedStepIds.value[record.id]) {
      expandedStepIds.value[record.id] = []
    }

    return h('div', { 
      class: 'bg-gray-900/30 rounded-lg p-4 mt-4' 
    }, [
      // 添加基本信息
      h('div', { class: 'mb-4 grid grid-cols-2 gap-4' }, [
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, '报告名称：'),
          h('span', { class: 'text-gray-200' }, record.report.name || '-')
        ]),
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'text-gray-400' }, '项目名称：'),
          h('span', { class: 'text-gray-200' }, 
            record.report.environment_info?.project?.name || '-'
          )
        ])
      ]),
      // 步骤详情
      record.report.details && record.report.details.length > 0 ? 
        h(ACollapse, {
          class: 'custom-collapse',
          modelValue: expandedStepIds.value[record.id],
          'onUpdate:modelValue': (val: number[]) => {
            expandedStepIds.value[record.id] = val
          }
        }, () => record.report.details.map((detail: StepDetail) => 
          h(ACollapseItem, {
            key: detail.id,
            name: detail.id,
            header: detail.step_name,
          }, {
            default: () => [
              // 使用ApiDetailCard组件展示接口详情
              h(ApiDetailCard, {
                detail: detail
              })
            ],
            extra: () => h('div', { class: 'flex items-center gap-4' }, [
              h(ATag, {
                color: detail.success ? 'green' : 'red'
              }, () => detail.success ? '成功' : '失败'),
              h('span', { class: 'text-gray-400' }, formatDuration(detail.elapsed || 0))
            ])
          })
        ))
        : h('div', { class: 'text-gray-400 text-center py-4' }, '暂无步骤详情')
    ])
  } catch (error) {
    console.error('展开行渲染函数发生错误:', error)
    return h('div', { 
      class: 'bg-gray-900/30 rounded-lg p-4 mt-4' 
    }, [
      h('div', { class: 'flex items-center gap-2' }, [
        h('span', { class: 'text-red-400' }, '错误信息：'),
        h('span', { class: 'text-red-300' }, record.error_message || '未知错误')
      ])
    ])
  }
}

onMounted(() => {
  fetchCaseResults()
})
</script>

<template>
  <div class="h-full flex flex-col gap-4 p-4">
    <!-- 标题区域 -->
    <div class="bg-gray-800/85 rounded-lg shadow-dark px-6 py-5 flex justify-between items-center">
      <div class="flex items-center gap-2">
        <h2 class="text-xl font-medium text-gray-100">
          测试任务执行结果
        </h2>
        <a-tag v-if="route.params.id" color="blue">ID: {{ route.params.id }}</a-tag>
      </div>
      <a-button type="outline" @click="goBack">返回</a-button>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 bg-gray-800/85 rounded-lg shadow-dark overflow-hidden">
      <a-spin :loading="loading" class="!block h-full">
        <div class="h-full overflow-auto">
          <template v-if="caseResults.length > 0">
            <!-- 汇总信息卡片 -->
            <div class="p-6 border-b border-gray-700/50">
              <div class="bg-gray-900/30 rounded-lg p-6">
                <h3 class="text-lg font-medium text-gray-200 mb-4">执行概况</h3>
                <div class="grid grid-cols-4 gap-6">
                  <!-- 总用例数 -->
                  <div class="bg-gray-800/50 rounded-lg p-4">
                    <div class="flex flex-col items-center">
                      <span class="text-gray-400 text-sm">总用例数</span>
                      <span class="text-gray-100 text-2xl font-semibold mt-2">
                        {{ caseResults.length }}
                      </span>
                    </div>
                  </div>
                  <!-- 成功用例 -->
                  <div class="bg-green-900/20 rounded-lg p-4">
                    <div class="flex flex-col items-center">
                      <span class="text-green-400 text-sm">成功用例</span>
                      <span class="text-green-300 text-2xl font-semibold mt-2">
                        {{ caseResults.filter(r => r.status === 'success').length }}
                      </span>
                    </div>
                  </div>
                  <!-- 失败用例 -->
                  <div class="bg-amber-900/20 rounded-lg p-4">
                    <div class="flex flex-col items-center">
                      <span class="text-amber-400 text-sm">失败用例</span>
                      <span class="text-amber-300 text-2xl font-semibold mt-2">
                        {{ caseResults.filter(r => r.status === 'fail' || r.status === 'failure').length }}
                      </span>
                    </div>
                  </div>
                  <!-- 错误用例 -->
                  <div class="bg-red-900/20 rounded-lg p-4">
                    <div class="flex flex-col items-center">
                      <span class="text-red-400 text-sm">错误用例</span>
                      <span class="text-red-300 text-2xl font-semibold mt-2">
                        {{ caseResults.filter(r => r.status === 'error').length }}
                      </span>
                    </div>
                  </div>
                </div>
                <!-- 执行时间信息 -->
                <div class="mt-4 grid grid-cols-2 gap-4">
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400">开始时间：</span>
                    <span class="text-gray-200">{{ formatDate(caseResults[0]?.start_time || '') }}</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400">总执行时长：</span>
                    <span class="text-gray-200">{{ formatDuration(caseResults.reduce((sum, r) => sum + (r.duration || 0), 0)) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 用例列表 -->
            <div class="p-6">
              <h3 class="text-lg font-medium text-gray-200 mb-4">用例详情</h3>
              <a-table 
                :data="caseResults" 
                :pagination="false" 
                :bordered="false"
                row-key="id"
                :expandable="{
                  expandedRowRender
                }"
                class="custom-table"
              >
                <template #columns>
                  <a-table-column 
                    title="ID" 
                    data-index="id"
                    :width="80"
                    align="center"
                  />
                  <a-table-column 
                    title="用例名称" 
                    data-index="testcase_name"
                    :width="250"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                  >
                    <template #cell="{ record }">
                      <div class="flex items-center gap-2">
                        <span class="text-gray-200">{{ record.testcase_name }}</span>
                        <a-tooltip v-if="record.error_message" position="right">
                          <template #content>
                            <span class="text-red-300">{{ record.error_message }}</span>
                          </template>
                          <icon-exclamation-circle-fill class="text-red-500" />
                        </a-tooltip>
                      </div>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="状态" 
                    align="center"
                    :width="100"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                    :sort-field="(record: any) => record.status"
                  >
                    <template #cell="{ record }">
                      <a-tag :color="record.status === 'success' ? 'green' : (record.status === 'fail' || record.status === 'failure') ? 'orange' : 'red'">
                        {{ record.status === 'success' ? '成功' : (record.status === 'fail' || record.status === 'failure') ? '失败' : '错误' }}
                      </a-tag>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="执行环境" 
                    :width="120"
                  >
                    <template #cell="{ record }">
                      <span class="text-gray-400 text-sm">{{ record.report?.environment_info?.name || '-' }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="执行人" 
                    :width="100"
                  >
                    <template #cell="{ record }">
                      <span class="text-gray-400 text-sm">{{ record.report?.executed_by_info?.username || '-' }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="执行时间" 
                    align="center"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                    :width="180"
                    :sort-field="(record: any) => new Date(record.start_time).getTime()"
                  >
                    <template #cell="{ record }">
                        <span class="text-gray-400 text-sm">{{ formatDate(record.start_time) }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="执行时长" 
                    align="center"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                    :width="100"
                    :sort-field="(record: any) => record.duration"
                  >
                    <template #cell="{ record }">
                        <span class="text-gray-400 text-sm">{{ formatDuration(record.duration) }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="步骤统计" 
                    align="center"
                    :width="250"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                    :sort-field="(record: any) => record.report?.success_count || 0"
                  >
                    <template #cell="{ record }">
                      <div class="flex items-center gap-2 justify-center">
                        <a-space v-if="record.report">
                          <a-tag color="green">成功: {{ record.report.success_count }}</a-tag>
                          <a-tag color="orange">失败: {{ record.report.fail_count }}</a-tag>
                          <a-tag color="red">错误: {{ record.report.error_count }}</a-tag>
                        </a-space>
                        <a-tag v-else color="red">数据异常</a-tag>
                      </div>
                    </template>
                  </a-table-column>
                  <a-table-column 
                    title="成功率" 
                    align="center"
                    :width="100"
                    :sortable="{
                      sortDirections: ['ascend', 'descend']
                    }"
                    :sort-field="(record: any) => Number(record.report?.success_rate || 0)"
                  >
                    <template #cell="{ record }">
                      <template v-if="record.report">
                        <a-progress
                          :percent="Number(record.report.success_rate || 0)"
                          :stroke-color="Number(record.report.success_rate || 0) === 1 ? '#00b42a' : '#ff7d00'"
                          :size="'small'"
                        />
                      </template>
                      <span v-else class="text-gray-400 text-sm">-</span>
                    </template>
                  </a-table-column>
                </template>
              </a-table>
            </div>
          </template>
          <div v-else class="h-full flex items-center justify-center">
            <div class="text-gray-400 text-lg">暂无执行结果数据</div>
          </div>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<style scoped lang="postcss">
@reference "tailwindcss";
/* 自定义滚动条 */
.custom-scrollbar {
  scrollbar-width: none !important;
  -ms-overflow-style: none !important;
  &::-webkit-scrollbar {
    display: none !important;
  }
}

:deep(.arco-collapse) {
  @apply !bg-transparent !border-none;
}

:deep(.arco-collapse-item) {
  @apply !bg-gray-900/30 !rounded-lg !mb-4 !border-none;
}

:deep(.arco-collapse-item-header) {
  @apply !bg-transparent !border-b !border-gray-700/50;
}

:deep(.arco-collapse-item-content) {
  @apply !bg-transparent !text-gray-300;
}

:deep(.arco-tabs) {
  @apply !text-gray-300;
}

:deep(.arco-tabs-nav) {
  @apply !border-gray-700/50;
}

:deep(.arco-tabs-nav-tab) {
  @apply !border-none;
}

:deep(.arco-tabs-nav-tab-list) {
  @apply !border-none;
}

:deep(.arco-tabs-tab) {
  @apply !text-gray-400;
}

:deep(.arco-tabs-tab-active) {
  @apply !text-blue-400;
}

:deep(.arco-tabs-content) {
  @apply !border-none;
}

pre {
  @apply !bg-gray-800/50 !rounded !p-2 !overflow-auto;
  max-height: 300px;
}

/* 优化表格样式 */
:deep(.custom-table) {
  @apply !bg-transparent;
}

:deep(.custom-table .arco-table-th) {
  @apply !bg-gray-800/50 !text-gray-300 !border-gray-700/50 !font-medium;
}

:deep(.custom-table .arco-table-td) {
  @apply !bg-transparent !text-gray-300 !border-gray-700/50;
}

:deep(.custom-table .arco-table-tr:hover .arco-table-td) {
  @apply !bg-gray-800/30;
}

:deep(.custom-table .arco-table-tr-expand) {
  @apply !bg-transparent;
}

:deep(.custom-table .arco-table-expand-content) {
  @apply !bg-transparent !border-none;
}

:deep(.custom-table .arco-table-expand-icon) {
  @apply !text-gray-400;
}

:deep(.custom-table .arco-table-th-item-title) {
  @apply !text-gray-300;
}

:deep(.custom-table .arco-table-sorter) {
  @apply !text-gray-400;
}

:deep(.custom-table .arco-table-sorter-icon) {
  @apply !text-gray-500;
}

:deep(.custom-table .arco-table-sorter-icon.active) {
  @apply !text-blue-400;
}

/* 进度条样式 */
:deep(.arco-progress-line-text) {
  @apply !text-gray-300;
}

:deep(.arco-progress-line-trail) {
  @apply !bg-gray-700/50;
}

/* spin组件样式 */
:deep(.arco-spin) {
  @apply !h-full;
}

:deep(.arco-spin-children) {
  @apply !h-full;
}

:deep(.arco-spin-loading) {
  @apply !bg-gray-900/60;
}
</style> 