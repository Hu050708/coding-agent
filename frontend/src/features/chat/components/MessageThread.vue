<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { ChatMessage, RunSummary } from '../../../shared/api/types'
import AppIcon from '../../../shared/components/AppIcon.vue'
import MessageContent from './MessageContent.vue'

const props = defineProps<{
  messages: ChatMessage[]
  run: RunSummary | null
}>()

const scroller = ref<HTMLElement | null>(null)
const showJumpToLatest = ref(false)
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

function nearEnd(): boolean {
  const element = scroller.value
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight < 120
}

async function followUpdates(): Promise<void> {
  const shouldFollow = nearEnd()
  await nextTick()
  const element = scroller.value
  if (!element) return
  if (shouldFollow) {
    element.scrollTop = element.scrollHeight
    showJumpToLatest.value = false
  } else {
    showJumpToLatest.value = true
  }
}

function onScroll(): void {
  showJumpToLatest.value = !nearEnd()
}

async function jumpToLatest(): Promise<void> {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  showJumpToLatest.value = false
}

watch(
  () => [props.messages.length, props.run?.status, props.run?.final_content],
  () => void followUpdates(),
  { immediate: true },
)
</script>

<template>
  <div ref="scroller" class="message-scroller" @scroll.passive="onScroll">
    <div class="message-column">
      <div v-if="messages.length === 0 && !run" class="thread-empty">
        <span class="empty-glyph" aria-hidden="true"><AppIcon name="terminal" /></span>
        <p class="empty-eyebrow">READY FOR A TASK</p>
        <h2>把编码任务交给 Agent</h2>
        <p class="empty-description">描述要修改的代码、期望结果和不能触碰的范围。Agent 会先检查项目，再执行必要的工具和测试。</p>
        <div class="prompt-notes" aria-label="任务描述建议">
          <div><strong>说明问题</strong><span>当前行为和错误现象</span></div>
          <div><strong>定义结果</strong><span>期望输出和验收标准</span></div>
          <div><strong>给出边界</strong><span>不能修改的文件或依赖</span></div>
        </div>
      </div>

      <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
        <div class="message-label">
          <span class="author-mark" aria-hidden="true">{{ message.role === 'user' ? '你' : '>_' }}</span>
          <span>{{ message.role === 'user' ? '你' : 'Coding Agent' }}</span>
          <time :datetime="message.created_at">{{ displayTime(message.created_at) }}</time>
        </div>
        <div v-if="message.role === 'user'" class="user-content">{{ message.content }}</div>
        <MessageContent v-else :content="message.content" />
      </article>

      <article v-if="run && !runAssistantMessageId" class="message assistant active-turn" role="status" aria-live="polite">
        <div class="message-label">
          <span class="author-mark agent" aria-hidden="true">&gt;_</span>
          <span>Coding Agent</span>
          <span class="working-label">{{ run.status === 'waiting_approval' ? '等待确认' : '正在处理' }}</span>
        </div>
        <div v-if="run.final_content" class="assistant-final"><MessageContent :content="run.final_content" /></div>
        <div v-else class="working-state">
          <span class="working-dots" aria-hidden="true"><i /><i /><i /></span>
          <span>{{ run.status === 'waiting_approval' ? '操作需要你的确认，运行已安全暂停。' : '正在根据工作区事实继续处理…' }}</span>
        </div>
      </article>

      <div class="scroll-spacer" aria-hidden="true" />
    </div>

    <button v-if="showJumpToLatest" class="jump-latest" type="button" @click="jumpToLatest">
      <AppIcon name="chevron-down" />
      查看最新消息
    </button>
  </div>
</template>

<style scoped>
.message-scroller {
  position: relative;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.message-column {
  width: min(840px, 100%);
  min-height: 100%;
  margin: 0 auto;
  padding: 42px 32px 0;
}

.thread-empty {
  display: flex;
  min-height: min(560px, 62dvh);
  align-items: center;
  justify-content: center;
  flex-direction: column;
  color: var(--ink-soft);
  text-align: center;
}

.empty-glyph {
  display: grid;
  width: 54px;
  height: 54px;
  place-items: center;
  margin-bottom: 15px;
  border: 1px solid var(--line-strong);
  border-radius: 15px;
  color: var(--accent);
  background: var(--surface);
  box-shadow: 0 8px 24px rgb(24 32 43 / 6%);
}

.empty-eyebrow {
  margin: 0 0 5px;
  color: var(--accent);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.11em;
}

.thread-empty h2 {
  margin: 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 25px;
  font-weight: 730;
  letter-spacing: -0.025em;
}

.empty-description {
  max-width: 560px;
  margin: 11px auto 24px;
  color: var(--ink-muted);
  font-size: 14px;
  line-height: 1.65;
}

.prompt-notes {
  display: grid;
  width: min(600px, 100%);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.prompt-notes div {
  display: grid;
  gap: 2px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  text-align: left;
}

.prompt-notes strong {
  color: var(--ink);
  font-size: 11px;
}

.prompt-notes span {
  color: var(--ink-muted);
  font-size: 10px;
  line-height: 1.4;
}

.message {
  padding: 0 0 36px;
}

.message.user {
  width: min(660px, 88%);
  margin-left: auto;
}

.message-label {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 10px;
  color: var(--ink-soft);
  font-family: var(--font-utility);
  font-size: 11px;
  font-weight: 700;
}

.message.user .message-label {
  justify-content: flex-end;
}

.author-mark {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 7px;
  color: white;
  background: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 9px;
}

.message.user .author-mark {
  order: 3;
  color: var(--accent);
  background: var(--accent-soft);
}

.message-label time,
.working-label {
  color: var(--ink-faint);
  font-size: 9px;
  font-weight: 550;
}

.working-label {
  padding: 2px 6px;
  border-radius: 999px;
  color: var(--accent);
  background: var(--accent-soft);
}

.user-content {
  padding: 13px 16px;
  border: 1px solid #d8e2f1;
  border-radius: 14px 14px 4px 14px;
  color: var(--ink);
  background: var(--user-message);
  font-size: 14.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.working-state {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  color: var(--ink-muted);
  font-size: 13px;
}

.working-dots {
  display: inline-flex;
  gap: 3px;
}

.working-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  animation: thinking 1.2s infinite ease-in-out;
}

.working-dots i:nth-child(2) {
  animation-delay: 120ms;
}

.working-dots i:nth-child(3) {
  animation-delay: 240ms;
}

@keyframes thinking {
  0%, 70%, 100% { opacity: 0.25; transform: translateY(0); }
  35% { opacity: 1; transform: translateY(-2px); }
}

.scroll-spacer {
  height: 16px;
}

.jump-latest {
  position: sticky;
  bottom: 14px;
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 6px;
  margin: 0 auto 14px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--ink-soft);
  background: var(--surface);
  box-shadow: 0 6px 18px rgb(24 32 43 / 12%);
  font-size: 11px;
  font-weight: 650;
}

.jump-latest :deep(svg) {
  width: 14px;
  height: 14px;
}

@media (max-width: 640px) {
  .message-column {
    padding: 30px 16px 0;
  }

  .message.user {
    width: 94%;
  }

  .thread-empty {
    min-height: 54dvh;
  }

  .thread-empty h2 {
    font-size: 21px;
  }

  .prompt-notes {
    grid-template-columns: 1fr;
  }

  .prompt-notes div:nth-child(n + 3) {
    display: none;
  }
}
</style>
