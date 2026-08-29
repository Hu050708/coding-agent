<script setup lang="ts">
import type { Conversation } from '../../conversations/types'
import type { RunSummary } from '../../runs/types'
import AppIcon from '../../../shared/components/AppIcon.vue'

defineProps<{
  conversation: Conversation
  run: RunSummary | null
  stream: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'
  inspectorOpen: boolean
}>()

defineEmits<{ openSidebar: []; toggleInspector: [] }>()

const statusCopy: Record<string, string> = {
  starting: '正在启动',
  running: 'Agent 正在工作',
  waiting_approval: '等待确认',
  cancelling: '正在停止',
  completed: '模型已结束 · 待验证',
  failed: '运行失败 · 未验证',
  cancelled: '已停止 · 未验证',
  budget_exhausted: '达到运行上限 · 未验证',
  interrupted: '已中断 · 未验证',
}
</script>

<template>
  <header class="conversation-header">
    <button class="icon-button sidebar-trigger" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
      <AppIcon name="menu" />
    </button>
    <div class="title-block">
      <div class="title-line">
        <h1>{{ conversation.title || '新会话' }}</h1>
        <span class="local-chip">LOCAL</span>
      </div>
      <p>
        <span v-if="run" class="run-state" :class="run.status">{{ statusCopy[run.status] }}</span>
        <span v-else>本机会话 · 等待任务</span>
        <template v-if="stream === 'reconnecting'"> · 正在重连事件流</template>
      </p>
    </div>
    <div class="header-meta">
      <span class="model-name">{{ run?.model || 'DeepSeek' }}</span>
      <span class="context-boundary"><AppIcon name="shield" />当前工作区</span>
      <button
        class="icon-button inspector-trigger"
        :class="{ active: inspectorOpen }"
        type="button"
        :aria-label="inspectorOpen ? '隐藏运行检查器' : '打开运行检查器'"
        :aria-expanded="inspectorOpen"
        title="显示或隐藏运行检查器"
        @click="$emit('toggleInspector')"
      >
        <AppIcon name="panel-right" />
        <span v-if="run && !inspectorOpen" class="inspector-notice"><span class="sr-only">有运行信息</span></span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.conversation-header {
  display: flex;
  min-height: var(--header-height);
  flex: none;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: rgb(255 255 255 / 90%);
  backdrop-filter: blur(12px);
}

.sidebar-trigger {
  display: none;
}

.title-block {
  min-width: 0;
  flex: 1;
}

.title-line {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

h1,
p {
  margin: 0;
}

h1 {
  overflow: hidden;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

p {
  margin-top: 2px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.local-chip {
  flex: none;
  padding: 2px 5px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 8px;
  font-weight: 750;
  letter-spacing: 0.07em;
}

.run-state.running,
.run-state.starting {
  color: var(--accent);
}

.run-state.waiting_approval,
.run-state.budget_exhausted,
.run-state.cancelled {
  color: var(--warning);
}

.run-state.failed,
.run-state.interrupted {
  color: var(--danger);
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.model-name {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-boundary {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-subtle);
}

.context-boundary :deep(svg) {
  width: 12px;
  height: 12px;
}

.inspector-trigger {
  position: relative;
  display: grid;
}

.inspector-trigger.active {
  color: var(--accent);
  background: var(--accent-soft);
}

.inspector-notice {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 7px;
  height: 7px;
  border: 2px solid var(--surface);
  border-radius: 50%;
  background: var(--accent);
  box-sizing: content-box;
}

@media (max-width: 900px) {
  .sidebar-trigger {
    display: grid;
  }
}

@media (max-width: 640px) {
  .conversation-header {
    padding: 0 10px;
  }

  .model-name,
  .context-boundary,
  .local-chip {
    display: none;
  }
}
</style>
