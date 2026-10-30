<template>
  <div v-if="visibleTasks.length > 0" class="generation-task-panel">
    <div class="panel-header" @click="collapsed = !collapsed">
      <span class="panel-title">
        {{ isEnglish ? 'Generation tasks' : '生成任务' }}
        <span class="panel-count">{{ visibleTasks.length }}</span>
      </span>
      <span class="panel-toggle">{{ collapsed ? (isEnglish ? 'Expand' : '展开') : (isEnglish ? 'Collapse' : '收起') }}</span>
    </div>

    <div v-if="!collapsed" class="panel-body">
      <div v-for="row in rows" :key="row.taskId" class="task-row" :class="`is-${row.status}`">
        <div class="task-line">
          <span class="task-dot"></span>
          <span class="task-title" :title="row.title">{{ row.title }}</span>
          <span class="task-elapsed">{{ row.elapsedText }}</span>
        </div>

        <div class="task-meta">
          <span v-if="row.status === 'running' && row.step > 0" class="task-chip">
            {{ isEnglish ? `Step ${row.step}${row.maxStep ? `/${row.maxStep}` : ''}` : `第 ${row.step}${row.maxStep ? `/${row.maxStep}` : ''} 步` }}
          </span>
          <span v-if="row.status === 'running' && row.progressText" class="task-chip is-muted">{{ row.progressText }}</span>
          <span v-if="row.status === 'done'" class="task-chip is-success">{{ isEnglish ? 'Completed' : '已完成' }}</span>
          <span v-if="row.status === 'failed'" class="task-chip is-danger" :title="row.error">{{ isEnglish ? 'Failed' : '失败' }}</span>
          <span v-if="row.status === 'cancelled'" class="task-chip is-muted">{{ isEnglish ? 'Cancelled' : '已取消' }}</span>
        </div>

        <div v-if="row.lastTool" class="task-tool" :title="row.lastTool">{{ row.lastTool }}</div>
        <div v-if="row.status === 'failed' && row.error" class="task-error">{{ row.error }}</div>

        <div class="task-actions">
          <a v-if="row.sessionId" href="javascript:;" class="task-action" @click="emit('view', row.taskId)">
            {{ isEnglish ? 'View chat' : '查看对话' }}
          </a>
          <a v-if="row.status === 'running'" href="javascript:;" class="task-action is-danger" @click="emit('cancel', row.taskId)">
            {{ isEnglish ? 'Cancel' : '取消' }}
          </a>
          <a v-if="row.status !== 'running'" href="javascript:;" class="task-action" @click="emit('dismiss', row.taskId)">
            {{ isEnglish ? 'Dismiss' : '清除' }}
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { activeStreams } from '@/features/langgraph/services/chatService';
import { useAppI18n } from '@/composables/useAppI18n';

/**
 * 测试用例生成任务进度面板
 *
 * 背景：原先提交生成后只弹一条 10 秒自动消失的通知，页面上没有任何常驻进度，
 * 用户在模型长时间思考时完全无法判断"是否还在跑"，很容易误以为页面卡死。
 * 这里提供一个常驻的悬浮面板，展示步数、耗时、当前阶段，并支持取消。
 */

export interface GenerationTask {
  taskId: string;
  sessionId: string;
  title: string;
  status: 'running' | 'done' | 'failed' | 'cancelled';
  startedAt: number;
  finishedAt?: number;
  error?: string;
}

const props = defineProps<{
  tasks: GenerationTask[];
}>();

const emit = defineEmits<{
  cancel: [taskId: string];
  view: [taskId: string];
  dismiss: [taskId: string];
}>();

const { isEnglish } = useAppI18n();

const collapsed = ref(false);
const now = ref(Date.now());
let tickTimer: ReturnType<typeof setInterval> | null = null;

const hasRunning = computed(() => props.tasks.some((task) => task.status === 'running'));

watch(
  hasRunning,
  (running) => {
    if (running && tickTimer === null) {
      tickTimer = setInterval(() => {
        now.value = Date.now();
      }, 1000);
    } else if (!running && tickTimer !== null) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  if (tickTimer !== null) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
});

const visibleTasks = computed(() =>
  props.tasks.filter((task) => task.status === 'running' || Date.now() - task.startedAt < 10 * 60 * 1000)
);

const formatElapsed = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
};

interface TaskRow {
  taskId: string;
  sessionId: string;
  title: string;
  status: GenerationTask['status'];
  error?: string;
  elapsedText: string;
  step: number;
  maxStep: number;
  progressText: string;
  lastTool: string;
}

const rows = computed<TaskRow[]>(() =>
  visibleTasks.value.map((task) => {
    const stream = task.sessionId ? activeStreams.value[task.sessionId] : undefined;

    let progressText = '';
    let lastTool = '';

    if (task.status === 'running' && stream) {
      const waiting = stream.waitingSeconds;
      if (stream.phase === 'summarizing') {
        progressText = isEnglish.value ? 'Compacting context…' : '正在压缩上下文…';
      } else if (stream.phase === 'tool') {
        progressText = isEnglish.value ? 'Running tools…' : '正在执行工具…';
      } else if (typeof waiting === 'number' && waiting > 5) {
        progressText = isEnglish.value ? `Thinking ${waiting}s…` : `模型思考中 ${waiting}s…`;
      }

      const toolMessages = (stream.messages || []).filter((msg) => msg.type === 'tool');
      const last = toolMessages[toolMessages.length - 1];
      if (last) {
        const name = last.toolName || (isEnglish.value ? 'Tool' : '工具');
        const snippet = (last.content || '').replace(/\s+/g, ' ').slice(0, 60);
        lastTool = snippet ? `${name} · ${snippet}` : name;
      }
    }

    return {
      taskId: task.taskId,
      sessionId: task.sessionId,
      title: task.title,
      status: task.status,
      error: task.error,
      elapsedText: formatElapsed((task.finishedAt ?? now.value) - task.startedAt),
      step: stream?.currentStep || 0,
      maxStep: stream?.maxSteps || 0,
      progressText,
      lastTool,
    };
  })
);
</script>

<style scoped>
.generation-task-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 340px;
  max-height: 45vh;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid #e5e6eb;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  z-index: 900;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #f2f3f5;
  cursor: pointer;
  user-select: none;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #1d2129;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.panel-count {
  font-size: 12px;
  font-weight: 500;
  color: #165dff;
  background: #e8f3ff;
  border-radius: 10px;
  padding: 0 6px;
}

.panel-toggle {
  font-size: 12px;
  color: #86909c;
}

.panel-body {
  overflow-y: auto;
  padding: 8px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-row {
  border: 1px solid #f2f3f5;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fcfcfd;
}

.task-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c9cdd4;
  flex-shrink: 0;
}

.is-running .task-dot {
  background: #165dff;
  animation: task-pulse 1.4s infinite ease-in-out;
}

.is-done .task-dot {
  background: #00b42a;
}

.is-failed .task-dot {
  background: #f53f3f;
}

.task-title {
  flex: 1;
  font-size: 13px;
  color: #1d2129;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-elapsed {
  font-size: 12px;
  color: #86909c;
  font-variant-numeric: tabular-nums;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.task-chip {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
  background: #e8f3ff;
  color: #165dff;
}

.task-chip.is-muted {
  background: #f2f3f5;
  color: #86909c;
}

.task-chip.is-success {
  background: #e8ffea;
  color: #00b42a;
}

.task-chip.is-danger {
  background: #ffece8;
  color: #f53f3f;
}

.task-tool {
  margin-top: 6px;
  font-size: 12px;
  color: #4e5969;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-error {
  margin-top: 6px;
  font-size: 12px;
  color: #f53f3f;
  word-break: break-word;
}

.task-actions {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}

.task-action {
  font-size: 12px;
  color: #165dff;
}

.task-action.is-danger {
  color: #f53f3f;
}

@keyframes task-pulse {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
