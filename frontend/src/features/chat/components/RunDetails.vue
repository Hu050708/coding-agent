<script setup lang="ts">
import { computed } from 'vue'

import type { RunEventEnvelope, RunSummary } from '../../runs/types'
import AppIcon from '../../../shared/components/AppIcon.vue'
import RunResult from './RunResult.vue'
import RunTimeline from './RunTimeline.vue'

const props = defineProps<{
  run: RunSummary | null
  events: RunEventEnvelope[]
  stream: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'
  actionBusy: boolean
}>()

defineEmits<{ close: []; stop: [] }>()

const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'budget_exhausted', 'interrupted'])
const active = computed(() => props.run !== null && !terminalStatuses.has(props.run.status))
const terminal = computed(() => props.run !== null && terminalStatuses.has(props.run.status))

const statusCopy: Record<string, { label: string; detail: string }> = {
  starting: { label: '正在启动', detail: '等待本机执行器接管任务' },
  running: { label: 'Agent 正在工作', detail: '模型正在根据工具反馈继续决策' },
  waiting_approval: { label: '等待你的确认', detail: '待审批操作尚未执行' },
  cancelling: { label: '正在安全停止', detail: '已发送取消请求' },
  completed: { label: '模型已结束', detail: '最终回答仍需外部验证' },
  failed: { label: '运行失败', detail: '查看终止原因后可以重新发起任务' },
  cancelled: { label: '运行已停止', detail: '本次运行未形成验证结论' },
  budget_exhausted: { label: '达到安全上限', detail: '控制循环已按预算边界停止' },
  interrupted: { label: '运行被中断', detail: '事件已保存，可以重新发起任务' },
}

const streamCopy = computed(() => {
  if (props.stream === 'live') return '事件流在线'
  if (props.stream === 'reconnecting') return '事件流重连中'
  if (props.stream === 'connecting') return '正在连接事件流'
  return '事件流已关闭'
})
</script>

<template>
  <aside class="run-inspector" aria-label="运行检查器">
    <header class="inspector-header">
      <div>
        <p>RUN INSPECTOR</p>
        <h2>运行检查器</h2>
      </div>
      <button class="icon-button inspector-close" type="button" aria-label="关闭运行检查器" @click="$emit('close')">
        <AppIcon name="close" />
      </button>
    </header>

    <div class="inspector-scroll">
      <template v-if="run">
        <section class="run-state-card" :class="run.status" aria-live="polite">
          <div class="state-heading">
            <span class="state-indicator" :class="{ active }"><span /></span>
            <div>
              <strong>{{ statusCopy[run.status]?.label }}</strong>
              <p>{{ statusCopy[run.status]?.detail }}</p>
            </div>
          </div>
          <div class="run-context">
            <span>{{ run.model }}</span>
            <span class="stream-state" :class="stream">{{ streamCopy }}</span>
          </div>
          <button
            v-if="active"
            class="stop-run-button"
            type="button"
            :disabled="actionBusy"
            @click="$emit('stop')"
          >
            <AppIcon name="stop" />
            {{ actionBusy ? '正在处理…' : '停止本次运行' }}
          </button>
        </section>

        <RunTimeline :events="events" :status="run.status" />
        <RunResult v-if="terminal" :run="run" />
      </template>

      <div v-else class="inspector-empty">
        <span class="empty-icon" aria-hidden="true"><AppIcon name="panel-right" /></span>
        <h3>还没有运行记录</h3>
        <p>提交任务后，这里会显示模型决策、工具执行、事实反馈和终止原因。</p>
      </div>
    </div>

  </aside>
</template>

<style scoped>
.run-inspector {
  display: flex;
  width: var(--inspector-width);
  min-width: var(--inspector-width);
  height: 100%;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid var(--line);
  background: var(--surface-subtle);
}

.inspector-header {
  display: flex;
  min-height: var(--header-height);
  flex: none;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: rgb(255 255 255 / 86%);
  backdrop-filter: blur(12px);
}

.inspector-header p,
.inspector-header h2 {
  margin: 0;
}

.inspector-header p {
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 8px;
  font-weight: 750;
  letter-spacing: 0.1em;
}

.inspector-header h2 {
  margin-top: 1px;
  font-size: 13px;
  font-weight: 700;
}

.inspector-close {
  display: grid;
}

.inspector-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.run-state-card {
  margin: 16px 14px 5px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 3px 12px rgb(24 32 43 / 4%);
}

.run-state-card.waiting_approval,
.run-state-card.budget_exhausted,
.run-state-card.cancelled {
  border-color: var(--warning-border);
}

.run-state-card.failed,
.run-state-card.interrupted {
  border-color: var(--danger-border);
}

.state-heading {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.state-heading strong,
.state-heading p {
  margin: 0;
}

.state-heading strong {
  font-size: 13px;
  font-weight: 700;
}

.state-heading p {
  margin-top: 2px;
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1.45;
}

.state-indicator {
  display: grid;
  width: 18px;
  height: 18px;
  flex: none;
  place-items: center;
  margin-top: 1px;
  border-radius: 50%;
  background: var(--surface-hover);
}

.state-indicator span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-muted);
}

.state-indicator.active span {
  background: var(--accent);
  box-shadow: 0 0 0 4px var(--accent-soft);
}

.waiting_approval .state-indicator span,
.budget_exhausted .state-indicator span,
.cancelled .state-indicator span {
  background: var(--warning);
}

.failed .state-indicator span,
.interrupted .state-indicator span {
  background: var(--danger);
}

.run-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 13px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 9px;
}

.run-context > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stream-state {
  flex: none;
}

.stream-state.live {
  color: var(--success);
}

.stream-state.reconnecting,
.stream-state.connecting {
  color: var(--warning);
}

.stop-run-button {
  display: flex;
  width: 100%;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin-top: 12px;
  border: 1px solid var(--danger-border);
  border-radius: 8px;
  color: var(--danger);
  background: var(--danger-soft);
  font-size: 11px;
  font-weight: 650;
}

.stop-run-button:hover:not(:disabled) {
  background: #f8dfe4;
}

.stop-run-button :deep(svg) {
  width: 14px;
  height: 14px;
}

.inspector-empty {
  display: flex;
  min-height: 420px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 36px 32px;
  color: var(--ink-muted);
  text-align: center;
}

.empty-icon {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  margin-bottom: 14px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  color: var(--accent);
  background: var(--surface);
}

.inspector-empty h3,
.inspector-empty p {
  margin: 0;
}

.inspector-empty h3 {
  color: var(--ink);
  font-size: 13px;
}

.inspector-empty p {
  max-width: 260px;
  margin-top: 7px;
  font-size: 11px;
  line-height: 1.55;
}

@media (max-width: 1240px) {
  .run-inspector {
    position: fixed;
    inset: 0 0 0 auto;
    z-index: 60;
    width: min(390px, calc(100vw - 48px));
    min-width: 0;
    box-shadow: var(--shadow-panel);
  }
}
</style>
