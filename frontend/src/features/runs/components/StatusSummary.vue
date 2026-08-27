<script setup lang="ts">
import { computed } from 'vue'

import type { HealthResponse, RunSummary, StreamPhase } from '../types'

const props = defineProps<{
  run: RunSummary | null
  elapsedSeconds: number
  stream: StreamPhase
  limits: HealthResponse | null
}>()

const statusLabels: Record<RunSummary['status'], string> = {
  starting: '正在启动',
  running: '执行中',
  waiting_approval: '等待审批',
  cancelling: '正在取消',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  budget_exhausted: '预算耗尽',
}

const statusLabel = computed(() => (props.run ? statusLabels[props.run.status] : '尚未运行'))
const statusTone = computed(() => {
  if (!props.run) return 'neutral'
  if (props.run.status === 'completed') return 'success'
  if (props.run.status === 'waiting_approval' || props.run.status === 'cancelled') return 'warning'
  if (props.run.status === 'failed' || props.run.status === 'budget_exhausted') return 'danger'
  return 'active'
})

function compactNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function duration(value: number): string {
  const whole = Math.max(0, Math.floor(value))
  const minutes = Math.floor(whole / 60)
  const seconds = whole % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
</script>

<template>
  <section class="summary" aria-label="运行状态计数">
    <div class="summary__status" :class="`summary__status--${statusTone}`">
      <span class="summary__signal" aria-hidden="true"></span>
      <div>
        <span class="summary__label">状态</span>
        <strong>{{ statusLabel }}</strong>
      </div>
      <span v-if="run && stream !== 'closed'" class="summary__stream mono">{{ stream }}</span>
    </div>

    <dl class="summary__metrics">
      <div>
        <dt>模型调用</dt>
        <Transition name="count" mode="out-in">
          <dd :key="run?.model_calls ?? 0" class="mono">
            {{ run?.model_calls ?? 0 }}<small v-if="limits">/{{ limits.max_model_calls }}</small>
          </dd>
        </Transition>
      </div>
      <div>
        <dt>工具调用</dt>
        <Transition name="count" mode="out-in">
          <dd :key="run?.tool_calls ?? 0" class="mono">
            {{ run?.tool_calls ?? 0 }}<small v-if="limits">/{{ limits.max_tool_calls }}</small>
          </dd>
        </Transition>
      </div>
      <div>
        <dt>总 token</dt>
        <Transition name="count" mode="out-in">
          <dd :key="run?.usage.total_tokens ?? 0" class="mono">
            {{ compactNumber(run?.usage.total_tokens ?? 0) }}
            <small v-if="limits">/{{ compactNumber(limits.max_total_tokens) }}</small>
          </dd>
        </Transition>
      </div>
      <div>
        <dt>已用时间</dt>
        <Transition name="count" mode="out-in">
          <dd :key="Math.floor(elapsedSeconds)" class="mono">{{ duration(elapsedSeconds) }}</dd>
        </Transition>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.summary {
  display: grid;
  grid-template-columns: minmax(180px, 0.9fr) minmax(420px, 2fr);
  gap: clamp(18px, 3vw, 42px);
  padding: 18px 0 20px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}

.summary__status {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  color: var(--ink-soft);
}

.summary__signal {
  width: 12px;
  height: 12px;
  border: 3px solid currentColor;
  border-radius: 50%;
}

.summary__status--active {
  color: var(--cobalt);
}

.summary__status--success {
  color: var(--success);
}

.summary__status--warning {
  color: var(--amber);
}

.summary__status--danger {
  color: var(--danger);
}

.summary__label,
dt {
  display: block;
  color: var(--ink-muted);
  font-size: 10px;
  font-weight: 500;
}

strong {
  display: block;
  margin-top: 2px;
  color: currentColor;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 650;
}

.summary__stream {
  color: var(--ink-muted);
  font-size: 9px;
}

.summary__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(78px, 1fr));
  gap: 18px;
  margin: 0;
}

.summary__metrics div {
  min-width: 0;
}

dd {
  margin: 5px 0 0;
  color: var(--ink);
  font-size: clamp(16px, 2vw, 21px);
  font-weight: 560;
  letter-spacing: -0.045em;
  line-height: 1;
}

small {
  margin-left: 3px;
  color: var(--ink-muted);
  font-size: 10px;
  font-weight: 400;
  letter-spacing: 0;
}

.count-enter-active,
.count-leave-active {
  transition:
    opacity 150ms var(--ease-out),
    transform 150ms var(--ease-out);
}

.count-enter-from {
  opacity: 0;
  transform: translateY(3px);
}

.count-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}

@media (min-width: 921px) and (max-width: 1150px) {
  .summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .summary {
    grid-template-columns: 1fr;
  }

  .summary__metrics {
    grid-template-columns: repeat(2, 1fr);
    row-gap: 16px;
  }
}
</style>
