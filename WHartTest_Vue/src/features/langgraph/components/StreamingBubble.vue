<template>
  <div v-if="hasVisibleContent" class="stream-bubble-group">
    <!-- 跨页面进入时的用户消息占位（历史尚未加载时） -->
    <MessageItem
      v-if="showUserMessage && userMessageObj"
      :message="userMessageObj"
      :floating-tool-image-src="floatingToolImageSrc"
      @toggle-expand="emit('toggle-expand', $event)"
      @quote="emit('quote', $event)"
      @retry="emit('retry', $event)"
      @delete="emit('delete', $event)"
      @preview-diagram="emit('preview-diagram', $event)"
      @preview-html="emit('preview-html', $event)"
      @tool-image-detected="emit('tool-image-detected', $event)"
      @float-tool-image="emit('float-tool-image', $event)"
    />

    <!-- 本轮已产生的工具 / 步骤消息 -->
    <MessageItem
      v-for="(message, index) in streamMessages"
      :key="`stream-msg-${index}`"
      :message="message"
      :floating-tool-image-src="floatingToolImageSrc"
      @toggle-expand="emit('toggle-expand', $event)"
      @quote="emit('quote', $event)"
      @retry="emit('retry', $event)"
      @delete="emit('delete', $event)"
      @preview-diagram="emit('preview-diagram', $event)"
      @preview-html="emit('preview-html', $event)"
      @tool-image-detected="emit('tool-image-detected', $event)"
      @float-tool-image="emit('float-tool-image', $event)"
    />

    <!-- 思考/等待态：让用户看到"进度"，而不是一片空白 -->
    <div v-if="showActivity" class="stream-activity">
      <span class="activity-dots"><i></i><i></i><i></i></span>
      <span class="activity-text">{{ activityText }}</span>
    </div>

    <!-- 错误提示 -->
    <MessageItem
      v-else-if="errorText"
      :message="errorMessageObj"
      :floating-tool-image-src="floatingToolImageSrc"
      @quote="emit('quote', $event)"
      @retry="emit('retry', $event)"
      @delete="emit('delete', $event)"
    />

    <!-- 正在输出的正文 -->
    <MessageItem
      v-else
      :message="aiMessage"
      :plain-text="plainTextMode"
      :floating-tool-image-src="floatingToolImageSrc"
      @quote="emit('quote', $event)"
      @retry="emit('retry', $event)"
      @delete="emit('delete', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import MessageItem from './MessageItem.vue';
import type { ToolFileAttachment } from '@/features/langgraph/utils/toolResultParser';
import { useAppI18n } from '@/composables/useAppI18n';

/**
 * 流式气泡（独立渲染单元）
 *
 * 设计目的
 * --------
 * 原实现把"正在输出的那条消息"混在历史消息数组里，每次流式 flush 都会重建整个
 * 数组并触发所有历史消息重渲染（各自重跑 markdown 解析）。本组件把流式部分
 * 拆成一个独立渲染单元，使它的高频更新**不影响**历史消息。
 *
 * 双模式渲染
 * ----------
 * - 纯文本模式（默认）：正文只做文本插值，成本与增量成正比；
 * - Markdown 快照模式：内容变长/出现代码块后，以固定节奏（400ms）取快照渲染，
 *   中途保持上一次快照，避免每个 token 都跑一次 marked + DOMParser + DOMPurify。
 *
 * 流式结束后内容会被父组件固化进历史消息，本组件随即卸载，最终 Markdown
 * 由 MessageItem 正常渲染一次。
 */

export interface StreamMessageLike {
  content: string;
  type: 'human' | 'ai' | 'tool' | 'system' | 'agent_step';
  time?: string;
  toolName?: string;
  imageDataUrl?: string;
  fileAttachments?: ToolFileAttachment[];
  isExpanded?: boolean;
  isThinkingProcess?: boolean;
  isThinkingExpanded?: boolean;
  stepNumber?: number;
  maxSteps?: number;
  stepStatus?: 'start' | 'complete' | 'error';
}

export interface StreamLike {
  content: string;
  error?: string;
  isComplete: boolean;
  messages: StreamMessageLike[];
  userMessage?: string;
  userMessageTime?: string;
  currentStep?: number;
  maxSteps?: number;
  phase?: string;
  waitingSeconds?: number;
}

interface ChatMessage {
  content: string;
  isUser: boolean;
  time: string;
  isLoading?: boolean;
  messageType?: 'human' | 'ai' | 'tool' | 'system' | 'agent_step' | 'step_separator';
  toolName?: string;
  isExpanded?: boolean;
  isStreaming?: boolean;
  imageDataUrl?: string;
  fileAttachments?: ToolFileAttachment[];
  isThinkingProcess?: boolean;
  isThinkingExpanded?: boolean;
  stepNumber?: number;
  maxSteps?: number;
  stepStatus?: 'start' | 'complete' | 'error';
}

const props = withDefaults(
  defineProps<{
    stream: StreamLike | null;
    floatingToolImageSrc?: string | null;
    showUserMessage?: boolean;
  }>(),
  {
    floatingToolImageSrc: null,
    showUserMessage: false,
  }
);

const emit = defineEmits<{
  'toggle-expand': [message: ChatMessage];
  'quote': [message: ChatMessage];
  'retry': [message: ChatMessage];
  'delete': [message: ChatMessage];
  'preview-diagram': [payload: { xml: string; sourceMessage: ChatMessage }];
  'preview-html': [payload: { html: string; sourceMessage: ChatMessage }];
  'tool-image-detected': [src: string];
  'float-tool-image': [src: string];
}>();

const { isEnglish } = useAppI18n();

const HIDDEN_TYPES = new Set(['step_separator']);
/** 低于该长度直接用纯文本渲染，够用且最省 */
const PLAIN_TEXT_LIMIT = 1200;
/** Markdown 快照刷新间隔 */
const SNAPSHOT_INTERVAL_MS = 400;

const content = computed(() => props.stream?.content || '');
const isStreaming = computed(() => !props.stream?.isComplete);
const errorText = computed(() => props.stream?.error || '');

const markdownMode = ref(false);
const snapshotContent = ref('');
let snapshotTimer: ReturnType<typeof setInterval> | null = null;

const stopSnapshotTimer = () => {
  if (snapshotTimer !== null) {
    clearInterval(snapshotTimer);
    snapshotTimer = null;
  }
};

const startSnapshotTimer = () => {
  if (snapshotTimer !== null) return;
  snapshotTimer = setInterval(() => {
    if (!isStreaming.value) {
      stopSnapshotTimer();
      return;
    }
    snapshotContent.value = content.value;
  }, SNAPSHOT_INTERVAL_MS);
};

watch(
  () => content.value,
  (value) => {
    if (!isStreaming.value) {
      stopSnapshotTimer();
      return;
    }
    // 内容变长或出现代码块后切到 Markdown 快照模式
    if (!markdownMode.value && (value.length >= PLAIN_TEXT_LIMIT || value.includes('```'))) {
      markdownMode.value = true;
      snapshotContent.value = value;
      startSnapshotTimer();
    }
  }
);

onUnmounted(stopSnapshotTimer);

const plainTextMode = computed(() => isStreaming.value && !markdownMode.value);

const streamMessages = computed<ChatMessage[]>(() => {
  const list = props.stream?.messages || [];
  return list
    .filter((msg) => !HIDDEN_TYPES.has(msg.type))
    .map((msg) => ({
      content: msg.content,
      isUser: false,
      time: msg.time || '',
      messageType: msg.type,
      toolName: msg.toolName,
      isExpanded: msg.isExpanded,
      imageDataUrl: msg.imageDataUrl,
      fileAttachments: msg.fileAttachments,
      isThinkingProcess: msg.isThinkingProcess,
      isThinkingExpanded: msg.isThinkingExpanded,
      stepNumber: msg.stepNumber,
      maxSteps: msg.maxSteps,
      stepStatus: msg.stepStatus,
    }));
});

const aiMessage = computed<ChatMessage>(() => ({
  content: plainTextMode.value ? content.value : snapshotContent.value || content.value,
  isUser: false,
  time: '',
  messageType: 'ai',
  isStreaming: isStreaming.value,
}));

const userMessageObj = computed<ChatMessage | null>(() => {
  const text = props.stream?.userMessage;
  if (!text) return null;
  return {
    content: text,
    isUser: true,
    time: props.stream?.userMessageTime || '',
    messageType: 'human',
  };
});

const errorMessageObj = computed<ChatMessage>(() => ({
  content: errorText.value,
  isUser: false,
  time: '',
  messageType: 'ai',
}));

const showActivity = computed(
  () => isStreaming.value && !errorText.value && content.value.trim() === ''
);

const activityText = computed(() => {
  const phase = props.stream?.phase;
  const waiting = props.stream?.waitingSeconds;
  const step = props.stream?.currentStep;
  const maxStep = props.stream?.maxSteps;

  if (isEnglish.value) {
    if (phase === 'summarizing') return 'Compacting context, please wait…';
    if (phase === 'tool') return step ? `Running tools (step ${step}${maxStep ? `/${maxStep}` : ''})…` : 'Running tools…';
    if (typeof waiting === 'number' && waiting > 5) return `Model is thinking (${waiting}s)…`;
    return 'Thinking…';
  }
  if (phase === 'summarizing') return '正在压缩上下文，请稍候…';
  if (phase === 'tool') return step ? `正在执行工具（第 ${step}${maxStep ? `/${maxStep}` : ''} 步）…` : '正在执行工具…';
  if (typeof waiting === 'number' && waiting > 5) return `模型思考中（已等待 ${waiting} 秒）…`;
  return '正在思考…';
});

const hasVisibleContent = computed(() => {
  if (!props.stream) return false;
  if (props.stream.messages && props.stream.messages.length > 0) return true;
  if (content.value || errorText.value) return true;
  if (props.showUserMessage && props.stream.userMessage) return true;
  return isStreaming.value;
});
</script>

<style scoped>
.stream-bubble-group {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 100%;
}

.stream-activity {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 12px;
  background: #f7f8fa;
  border: 1px solid #e5e6eb;
  align-self: flex-start;
  max-width: 85%;
}

.activity-dots {
  display: inline-flex;
  gap: 4px;
}

.activity-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #c9cdd4;
  animation: activity-bounce 1.4s infinite ease-in-out both;
}

.activity-dots i:nth-child(2) {
  animation-delay: 0.16s;
}

.activity-dots i:nth-child(3) {
  animation-delay: 0.32s;
}

.activity-text {
  font-size: 13px;
  color: #86909c;
}

@keyframes activity-bounce {
  0%,
  80%,
  100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
