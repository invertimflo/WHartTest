<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { 
  IconCode, 
  IconFolder, 
  IconFile, 
  IconCheckCircle,
  IconRobot,
  IconBug,
  IconCalendar, 
  IconDashboard,
  IconCloseCircle,
  IconRight,
  IconUp,
  IconDown
} from '@arco-design/web-vue/es/icon'
import { Message } from '@arco-design/web-vue'
import { getDashboardSummary } from '../../services/dashboardService'
import type { DashboardSummary, RecentTask } from '../../services/dashboardService'

// 扩展DashboardSummary类型以包含recent_reports
interface ExtendedDashboardSummary extends Omit<DashboardSummary, 'recent_reports'> {
  recent_reports?: RecentReport[]
}

// 定义RecentReport接口
interface RecentReport {
  id: number
  name: string
  status: string
  start_time: string
  duration: number
  success_count: number
  fail_count: number
  error_count: number
  testcase__name: string
  success_rate: number
}

const router = useRouter()
const loading = ref(false)
const dashboardData = ref<ExtendedDashboardSummary | null>(null)

// 获取仪表盘数据
const fetchDashboardData = async () => {
  try {
    loading.value = true
    const res = await getDashboardSummary()
    dashboardData.value = res.data
  } catch (error) {
    console.error('获取仪表盘数据失败:', error)
    Message.error('获取仪表盘数据失败')
  } finally {
    loading.value = false
  }
}

// 计算统计卡片数据
const statistics = computed(() => {
  if (!dashboardData.value) return []
  
  return [
    {
      title: '测试用例',
      value: dashboardData.value.total_testcases,
      key: 'cases',
      icon: IconCode,
      trend: '+12%',
      trendType: 'up',
      color: 'from-blue-500 to-blue-600'
    },
    {
      title: '接口数量',
      value: dashboardData.value.total_interfaces,
      key: 'interfaces',
      icon: IconFolder,
      trend: '+3%',
      trendType: 'up',
      color: 'from-purple-500 to-purple-600'
    },
    {
      title: '项目数量',
      value: dashboardData.value.total_projects,
      key: 'projects',
      icon: IconFile,
      trend: '+8%',
      trendType: 'up',
      color: 'from-green-500 to-green-600'
    },
    {
      title: '测试任务',
      value: dashboardData.value?.total_tasks || 0,
      key: 'tasks',
      icon: IconCalendar,
      trend: '+5%',
      trendType: 'up',
      color: 'from-orange-500 to-orange-600'
    },
    {
      title: '测试成功率',
      value: dashboardData.value ? `${(dashboardData.value.success_rate * 100).toFixed(1)}%` : '0%',
      key: 'success_rate',
      icon: IconCheckCircle,
      trend: '+2.1%',
      trendType: 'up',
      color: 'from-yellow-500 to-yellow-600'
    }
  ]
})

// 获取最近5条任务数据
const recentTasks = computed(() => {
  if (!dashboardData.value || !dashboardData.value.recent_tasks) return []
  return dashboardData.value.recent_tasks.slice(0, 5)
})

// 获取最近5条报告数据
const recentReports = computed(() => {
  if (!dashboardData.value || !dashboardData.value.recent_reports) return []
  return dashboardData.value.recent_reports.slice(0, 5)
})

// 格式化日期
const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffDay > 0) {
    return `${diffDay}天前`
  } else if (diffHour > 0) {
    return `${diffHour}小时前`
  } else if (diffMin > 0) {
    return `${diffMin}分钟前`
  } else {
    return '刚刚'
  }
}

// 格式化持续时间（秒）为可读格式
const formatDuration = (seconds: number) => {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}秒`
  } else {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}分${remainingSeconds.toFixed(0)}秒`
  }
}

// 跳转到任务详情
const goToTaskDetail = (taskId: number) => {
  router.push({ name: 'ApiTestTaskExecutionDetail', params: { id: taskId } })
}

// 跳转到报告详情
const goToReportDetail = (reportId: number) => {
  router.push({ name: 'ApiTestReportDetail', params: { id: reportId } })
}

// 跳转到测试用例页面
const goToTestCases = () => {
  router.push({ path: '/api-testing', query: { tab: 'testcases' } })
}

// 跳转到测试任务页面
const goToTestTasks = () => {
  router.push({ path: '/api-testing', query: { tab: 'testtasks' } })
}

// 跳转到接口管理页面
const goToApis = () => {
  router.push({ path: '/api-testing', query: { tab: 'interfaces' } })
}

// 跳转到项目管理页面
const goToProjects = () => {
  router.push({ name: 'ProjectManagement' })
}

// 跳转到测试报告页面
const goToTestReports = () => {
  router.push({ path: '/api-testing', query: { tab: 'reports' } })
}

// 跳转到环境管理页面
const goToEnvironments = () => {
  router.push({ path: '/api-testing', query: { tab: 'environments' } })
}

// 跳转到函数管理页面
const goToFunctions = () => {
  router.push({ path: '/api-testing', query: { tab: 'functions' } })
}

onMounted(() => {
  fetchDashboardData()
})
</script>

<template>
  <div class="h-full w-full overflow-auto">
    <div class="p-4 sm:p-6 w-full box-border">

        

      
      <a-spin :loading="loading" class="w-full" tip="加载中...">
    <!-- 统计卡片 -->
        <div class="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-4 w-full box-border">
          <div 
            v-for="item in statistics" 
            :key="item.key"
            class="bg-gradient-to-br rounded-lg p-4 sm:p-5 relative overflow-hidden group hover:scale-[1.02] transition-all duration-300 border border-white/10 hover:border-white/20 shadow-xl cursor-pointer"
            :class="item.color"
          >
            <!-- 背景装饰 -->
            <div class="absolute right-0 bottom-0 opacity-10 transition-transform group-hover:scale-110">
              <component :is="item.icon" :style="{ fontSize: '80px' }" />
            </div>
            
            <!-- 内容 -->
            <div class="relative">
              <div class="flex items-center gap-2 mb-2">
                <component :is="item.icon" class="text-xl" />
                <span class="text-sm opacity-90">{{ item.title }}</span>
              </div>
              <div class="text-2xl sm:text-3xl font-bold mb-2">{{ item.value }}</div>
              <div class="flex items-center text-sm">
                <icon-up v-if="item.trendType === 'up'" class="mr-1" />
                <icon-down v-else class="mr-1" />
                <span>{{ item.trend }} 较上周</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 下方内容区域 -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 w-full box-border">
          <!-- 左侧快速导航 -->
          <div class="bg-gray-700 rounded-lg p-4 sm:p-6 shadow-xl border border-white/10 box-border">
            <div class="text-lg font-medium mb-6">快速导航</div>
            <div class="space-y-4">
              <div 
                class="flex items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 backdrop-blur-sm cursor-pointer box-border"
                @click="goToTestCases"
              >
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm bg-blue-500/20 text-blue-500">
                    <IconCode />
                  </div>
                  <div>
                    <div class="font-medium">测试用例</div>
                    <div class="text-sm text-gray-400">
                      {{ dashboardData?.total_testcases || 0 }} 个用例
                    </div>
                  </div>
                </div>
                <IconRight class="text-gray-400" />
              </div>
              
              <div 
                class="flex items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 backdrop-blur-sm cursor-pointer box-border"
                @click="goToApis"
              >
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm bg-purple-500/20 text-purple-500">
                    <IconRobot />
                  </div>
                  <div>
                    <div class="font-medium">接口管理</div>
                    <div class="text-sm text-gray-400">
                      {{ dashboardData?.total_interfaces || 0 }} 个接口
                    </div>
                  </div>
                </div>
                <IconRight class="text-gray-400" />
              </div>
              
              <div 
                class="flex items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 backdrop-blur-sm cursor-pointer box-border"
                @click="goToProjects"
              >
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm bg-green-500/20 text-green-500">
                    <IconFolder />
                  </div>
                  <div>
                    <div class="font-medium">项目管理</div>
                    <div class="text-sm text-gray-400">
                      {{ dashboardData?.total_projects || 0 }} 个项目
                    </div>
                  </div>
                </div>
                <IconRight class="text-gray-400" />
              </div>
              
              <div 
                class="flex items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 backdrop-blur-sm cursor-pointer box-border"
                @click="goToEnvironments"
              >
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm bg-cyan-500/20 text-cyan-500">
                    <IconFolder />
                  </div>
                  <div>
                    <div class="font-medium">环境管理</div>
                    <div class="text-sm text-gray-400">配置测试环境</div>
                  </div>
                </div>
                <IconRight class="text-gray-400" />
              </div>
              
              <div 
                class="flex items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 backdrop-blur-sm cursor-pointer box-border"
                @click="goToFunctions"
              >
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm bg-amber-500/20 text-amber-500">
                    <IconCode />
                  </div>
                  <div>
                    <div class="font-medium">函数管理</div>
                    <div class="text-sm text-gray-400">自定义测试函数</div>
                  </div>
                </div>
                <IconRight class="text-gray-400" />
              </div>
            </div>
          </div>

          <!-- 中间测试报告情况 -->
          <div class="bg-gray-700 rounded-lg p-4 sm:p-6 shadow-xl border border-white/10 box-border">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6">
              <div class="text-lg font-medium mb-2 sm:mb-0">测试报告情况</div>
              <a-button type="outline" class="hover:border-blue-500 hover:text-blue-500 transition-colors" @click="goToTestReports">
                查看全部
                <template #icon>
                  <icon-right />
                </template>
              </a-button>
            </div>
            
            <div class="space-y-4">
              <div 
                v-for="(item, index) in recentReports" 
                :key="index"
                class="flex flex-col sm:flex-row items-start sm:items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 cursor-pointer box-border"
                @click="goToReportDetail(item.id)"
              >
                <div class="flex items-center gap-3 sm:gap-4 mb-3 sm:mb-0">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm"
                    :class="item.status === 'success' ? 'bg-green-500/20 text-green-500' : 'bg-red-500/20 text-red-500'"
                  >
                    <icon-check-circle v-if="item.status === 'success'" />
                    <icon-close-circle v-else />
                  </div>
                  <div class="max-w-[180px] sm:max-w-none">
                    <div class="font-medium truncate">{{ item.testcase__name }}</div>
                    <div class="text-sm text-gray-400">{{ formatDate(item.start_time) }} · {{ formatDuration(item.duration) }}</div>
                  </div>
                </div>
                <div class="flex items-center gap-4 sm:gap-8 w-full sm:w-auto justify-between sm:justify-start">
                  <div class="text-right">
                    <div class="font-medium">通过率</div>
                    <div class="text-sm" :class="item.success_rate === 1 ? 'text-green-500' : 'text-yellow-500'">
                      {{ (item.success_rate * 100).toFixed(0) }}%
                    </div>
                  </div>
                  <a-button shape="circle" size="small" class="hover:border-blue-500 hover:text-blue-500 transition-colors">
                    <template #icon>
                      <icon-right />
                    </template>
                  </a-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧执行列表 -->
          <div class="bg-gray-700 rounded-lg p-4 sm:p-6 shadow-xl border border-white/10 box-border">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6">
              <div class="text-lg font-medium mb-2 sm:mb-0">最近执行情况</div>
              <a-button type="outline" class="hover:border-blue-500 hover:text-blue-500 transition-colors" @click="goToTestTasks">
            查看全部
            <template #icon>
              <icon-right />
            </template>
          </a-button>
        </div>
        
        <div class="space-y-4">
          <div 
                v-for="(item, index) in recentTasks" 
            :key="index"
                class="flex flex-col sm:flex-row items-start sm:items-center justify-between p-3 sm:p-4 rounded-lg bg-gray-800/50 hover:bg-gray-750 transition-all hover:translate-x-1 border border-white/5 hover:border-white/10 cursor-pointer box-border"
                @click="goToTaskDetail(item.id)"
              >
                <div class="flex items-center gap-3 sm:gap-4 mb-3 sm:mb-0">
                  <div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg flex items-center justify-center backdrop-blur-sm"
                    :class="item.status === 'completed' && item.success_rate === 1 ? 'bg-green-500/20 text-green-500' : 'bg-red-500/20 text-red-500'"
                  >
                    <icon-check-circle v-if="item.status === 'completed' && item.success_rate === 1" />
                <icon-close-circle v-else />
              </div>
                  <div class="max-w-[180px] sm:max-w-none">
                    <div class="font-medium truncate">{{ item.task_suite__name }}</div>
                    <div class="text-sm text-gray-400">{{ formatDate(item.created_at) }}</div>
              </div>
            </div>
                <div class="flex items-center gap-4 sm:gap-8 w-full sm:w-auto justify-between sm:justify-start">
              <div class="text-right">
                <div class="font-medium">通过率</div>
                    <div class="text-sm" :class="item.success_rate === 1 ? 'text-green-500' : 'text-yellow-500'">
                      {{ (item.success_rate * 100).toFixed(0) }}%
                </div>
              </div>
              <a-button shape="circle" size="small" class="hover:border-blue-500 hover:text-blue-500 transition-colors">
                <template #icon>
                  <icon-right />
                </template>
              </a-button>
            </div>
          </div>
            </div>
          </div>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<style scoped>
.hover\:bg-gray-750:hover {
  background-color: rgba(31, 41, 55, 0.7);
}

.backdrop-blur-sm {
  backdrop-filter: blur(8px);
}

/* 隐藏滚动条但保持可滚动 - 全局应用 */
:deep(::-webkit-scrollbar) {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}

/* Firefox */
* {
  scrollbar-width: none !important;
}

/* IE */
* {
  -ms-overflow-style: none !important;
}

/* 确保主容器可以滚动但无滚动条 */
.h-full.w-full.overflow-auto {
  scrollbar-width: none !important;
  -ms-overflow-style: none !important;
}

.h-full.w-full.overflow-auto::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}

.shadow-xl {
  box-shadow: 0 -4px 10px -1px rgba(0, 0, 0, 0.2),
              0 10px 25px -5px rgba(0, 0, 0, 0.4),
              -8px 0 15px -3px rgba(0, 0, 0, 0.3),
              8px 0 15px -3px rgba(0, 0, 0, 0.3);
}
</style> 