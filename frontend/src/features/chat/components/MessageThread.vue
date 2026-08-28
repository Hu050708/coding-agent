<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { ChatMessage, RunEventEnvelope, RunSummary } from '../../../shared/api/types'
import ActivitySpine from './ActivitySpine.vue'

const props = defineProps<{
  messages: ChatMessage[]
  run: RunSummary | null
  events: RunEventEnvelope[]
  actionBusy: boolean
}>()

defineEmits<{ approve: []; reject: [] }>()

const scroller = ref<HTMLElement | null>(null)
const runAssistantMessageId = computed(
  () =>
    props.messages.find(
      (message) => message.role === 'assistant' && message.run_id === props.run?.id,
    )?.id ?? null,
)

function displayTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date)
}

async function scrollToEnd(): Promise<void> {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

watch(
  () => [props.messages.length, props.events.length, props.run?.status],
  () => void scrollToEnd(),
  { immediate: true },
)
</script>

<template>
  <div ref="scroller" class="message-scroller" aria-live="polite">
    <div class="message-column">
      <div v-if="messages.length === 0 && !run" class="thread-empty">
        <span class="empty-glyph" aria-hidden="true">›_</span>
        <h2>把任务交给 Coding Agent</h2>
        <p>描述要修改的代码、预期结果和限制。Agent 会在当前工作区内读取、编辑并运行必要检查。</p>
        <div class="prompt-notes">
          <span>先解释问题，再说目标</span>
          <span>明确哪些文件不能改</span>
          <span>需要时指定测试命令</span>
        </div>
      </div>

      <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
        <div class="message-label">
          <span>{{ message.role === 'user' ? '你' : 'Coding Agent' }}</span>
          <time :datetime="message.created_at">{{ displayTime(message.created_at) }}</time>
        </div>
        <ActivitySpine
          v-if="run && message.id === runAssistantMessageId"
          :events="events"
          :status="run.status"
          :approval="run.pending_approval"
          :action-busy="actionBusy"
          @approve="$emit('approve')"
          @reject="$emit('reject')"
        />
        <div class="message-content">{{ message.content }}</div>
      </article>

      <article v-if="run && !runAssistantMessageId" class="message assistant active-turn">
        <div class="message-label">
          <span>Coding Agent</span>
          <span v-if="run.status === 'running'" class="working-label">working</span>
        </div>
        <ActivitySpine
          :events="events"
          :status="run.status"
          :approval="run.pending_approval"
          :action-busy="actionBusy"
          @approve="$emit('approve')"
          @reject="$emit('reject')"
        />
        <div v-if="run.final_content" class="message-content">{{ run.final_content }}</div>
      </article>

      <div class="scroll-spacer" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.message-scroller {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.message-column {
  width: min(780px, 100%);
  min-height: 100%;
  margin: 0 auto;
  padding: 34px 28px 0;
}

.thread-empty {
  display: flex;
  min-height: min(520px, 58dvh);
  align-items: center;
  justify-content: center;
  flex-direction: column;
  color: var(--ink-soft);
  text-align: center;
}

.empty-glyph {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  margin-bottom: 18px;
  border: 1px solid var(--line-strong);
  border-radius: 11px;
  color: var(--accent);
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: 17px;
  font-weight: 650;
}

.thread-empty h2 {
  margin: 0;
  color: var(--ink);
  font-size: 20px;
  font-weight: 630;
  letter-spacing: -0.015em;
}

.thread-empty > p {
  max-width: 500px;
  margin: 10px auto 20px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.65;
}

.prompt-notes {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 7px;
}

.prompt-notes span {
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--ink-muted);
  background: var(--surface-subtle);
  font-family: var(--font-utility);
  font-size: 10px;
}

.message {
  padding: 0 0 30px;
}

.message.user {
  width: min(650px, 88%);
  margin-left: auto;
}

.message-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.015em;
}

.message.user .message-label {
  justify-content: flex-end;
}

.message-label time,
.working-label {
  color: var(--ink-faint);
  font-size: 9px;
  font-weight: 500;
}

.working-label {
  color: var(--accent);
  text-transform: uppercase;
}

.message-content {
  color: var(--ink);
  font-size: 14px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}

.message.user .message-content {
  padding: 11px 14px;
  border: 1px solid var(--line);
  border-radius: 11px 11px 3px 11px;
  background: var(--user-message);
  font-size: 13.5px;
}

.scroll-spacer {
  height: 10px;
}

@media (max-width: 640px) {
  .message-column {
    padding: 26px 16px 0;
  }

  .message.user {
    width: 94%;
  }

  .thread-empty {
    min-height: 52dvh;
  }

  .prompt-notes span:nth-child(n + 3) {
    display: none;
  }
}
</style>
