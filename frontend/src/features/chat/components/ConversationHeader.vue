<script setup lang="ts">
import type { Conversation, RunSummary } from '../../../shared/api/types'
import AppIcon from '../../../shared/components/AppIcon.vue'

defineProps<{
  conversation: Conversation
  run: RunSummary | null
  stream: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'
}>()

defineEmits<{ openSidebar: [] }>()

const statusCopy: Record<string, string> = {
  starting: '正在启动',
  running: 'Agent 正在工作',
  waiting_approval: '等待确认',
  cancelling: '正在停止',
  completed: '已完成',
  failed: '运行失败',
  cancelled: '已停止',
  budget_exhausted: '达到运行上限',
  interrupted: '已中断',
}
</script>

<template>
  <header class="conversation-header">
    <button class="icon-button sidebar-trigger" type="button" aria-label="打开侧栏" @click="$emit('openSidebar')">
      <AppIcon name="menu" />
    </button>
    <div class="title-block">
      <h1>{{ conversation.title || '新会话' }}</h1>
      <p>
        <span v-if="run" class="run-state" :class="run.status">{{ statusCopy[run.status] }}</span>
        <span v-else>本机会话</span>
        <template v-if="stream === 'reconnecting'"> · 正在重连事件流</template>
      </p>
    </div>
    <div class="header-meta">
      <span>{{ run?.model || 'DeepSeek' }}</span>
      <span class="local-chip">LOCAL</span>
    </div>
  </header>
</template>

<style scoped>
.conversation-header {
  display: flex;
  height: var(--header-height);
  align-items: center;
  gap: 12px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  background: rgb(255 255 255 / 88%);
  backdrop-filter: blur(10px);
}

.sidebar-trigger {
  display: none;
}

.title-block {
  min-width: 0;
  flex: 1;
}

h1,
p {
  margin: 0;
}

h1 {
  overflow: hidden;
  font-size: 14px;
  font-weight: 630;
  text-overflow: ellipsis;
  white-space: nowrap;
}

p {
  margin-top: 1px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.run-state.running,
.run-state.starting {
  color: var(--accent);
}

.run-state.waiting_approval {
  color: var(--warning);
}

.run-state.failed,
.run-state.interrupted {
  color: var(--danger);
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.local-chip {
  padding: 2px 5px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  color: var(--ink-soft);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

@media (max-width: 900px) {
  .sidebar-trigger {
    display: grid;
  }
}

@media (max-width: 640px) {
  .conversation-header {
    padding: 0 12px;
  }

  .header-meta > span:first-child {
    display: none;
  }
}
</style>
