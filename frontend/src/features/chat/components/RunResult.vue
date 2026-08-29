<script setup lang="ts">
import { computed } from 'vue'

import type { ChangeCheckSummary, RunSummary } from '../../runs/types'
import AppIcon from '../../../shared/components/AppIcon.vue'
import { presentChangeCheck, presentRunOutcome } from '../../runs/display'

const props = defineProps<{ run: RunSummary; changeCheck?: ChangeCheckSummary | null }>()
const outcome = computed(() => presentRunOutcome(props.run))
const check = computed(() => presentChangeCheck(props.changeCheck ?? null))

function formatCount(value: number | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(value ?? 0)
}

function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`
}
</script>

<template>
  <section class="outcome-card" :class="outcome.tone" aria-labelledby="run-outcome-title">
    <div class="outcome-heading">
      <span class="outcome-icon" aria-hidden="true"><AppIcon name="check" /></span>
      <div>
        <p class="eyebrow">运行结论</p>
        <h3 id="run-outcome-title">{{ outcome.title }}</h3>
      </div>
      <span class="outcome-status">{{ outcome.statusLabel }}</span>
    </div>

    <p class="outcome-description">{{ outcome.description }}</p>

    <div class="change-check-card" :class="check.tone">
      <span class="change-check-icon" aria-hidden="true"><AppIcon name="check" /></span>
      <div>
        <p>修改后检查</p>
        <strong>{{ check.label }}</strong>
        <small>{{ check.detail }}</small>
      </div>
    </div>

    <dl class="evidence-grid">
      <div>
        <dt>终止原因</dt>
        <dd>{{ outcome.reasonLabel }}</dd>
      </div>
      <div>
        <dt>独立验收</dt>
        <dd>尚未执行</dd>
      </div>
      <div>
        <dt>模型调用</dt>
        <dd>{{ formatCount(run.model_calls) }} 次</dd>
      </div>
      <div>
        <dt>工具调用</dt>
        <dd>{{ formatCount(run.tool_calls) }} 次</dd>
      </div>
      <div>
        <dt>Token</dt>
        <dd>{{ formatCount(run.usage.total_tokens) }}</dd>
      </div>
      <div>
        <dt>总耗时</dt>
        <dd>{{ formatDuration(run.duration_ms) }}</dd>
      </div>
    </dl>

    <p class="verification-note">
      <span aria-hidden="true">i</span>
      最终回答只是模型的停止信号；测试、静态检查或工作区外 verifier 才能提供成功证据。
    </p>
  </section>
</template>

<style scoped>
.outcome-card {
  margin: 0 14px 18px;
  padding: 15px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 3px 12px rgb(24 32 43 / 4%);
}

.outcome-card.warning {
  border-color: var(--warning-border);
}

.outcome-card.danger {
  border-color: var(--danger-border);
}

.outcome-heading {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
}

.outcome-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 8px;
  color: var(--ink-soft);
  background: var(--surface-hover);
}

.warning .outcome-icon {
  color: var(--warning);
  background: var(--warning-soft);
}

.danger .outcome-icon {
  color: var(--danger);
  background: var(--danger-soft);
}

.eyebrow,
h3,
.outcome-description,
.verification-note {
  margin: 0;
}

.eyebrow {
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h3 {
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outcome-status {
  padding: 3px 7px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--ink-soft);
  background: var(--surface-subtle);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 700;
}

.warning .outcome-status {
  border-color: var(--warning-border);
  color: var(--warning);
  background: var(--warning-soft);
}

.danger .outcome-status {
  border-color: var(--danger-border);
  color: var(--danger);
  background: var(--danger-soft);
}

.outcome-description {
  margin-top: 11px;
  color: var(--ink-soft);
  font-size: 11px;
  line-height: 1.55;
}

.change-check-card {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
}

.change-check-card.success {
  border-color: var(--success-border, #b9dec8);
}

.change-check-card.warning {
  border-color: var(--warning-border);
}

.change-check-card.danger {
  border-color: var(--danger-border);
}

.change-check-icon {
  display: grid;
  width: 24px;
  height: 24px;
  flex: none;
  place-items: center;
  border-radius: 7px;
  color: var(--ink-muted);
  background: var(--surface);
}

.success .change-check-icon {
  color: var(--success);
}

.warning .change-check-icon {
  color: var(--warning);
}

.danger .change-check-icon {
  color: var(--danger);
}

.change-check-card p,
.change-check-card strong,
.change-check-card small {
  display: block;
  margin: 0;
}

.change-check-card p {
  color: var(--ink-muted);
  font-size: 9px;
}

.change-check-card strong {
  margin-top: 1px;
  font-size: 11px;
}

.change-check-card small {
  margin-top: 2px;
  color: var(--ink-muted);
  font-size: 9px;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 13px 0 0;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
}

.evidence-grid > div {
  min-width: 0;
  padding: 9px 10px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.evidence-grid > div:nth-child(2n) {
  border-right: 0;
}

.evidence-grid > div:nth-last-child(-n + 2) {
  border-bottom: 0;
}

dt {
  margin-bottom: 3px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 9px;
}

dd {
  margin: 0;
  overflow: hidden;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.verification-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 11px;
  color: var(--ink-muted);
  font-size: 10px;
  line-height: 1.45;
}

.verification-note > span {
  display: grid;
  width: 15px;
  height: 15px;
  flex: none;
  place-items: center;
  margin-top: 1px;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  font-family: var(--font-utility);
  font-size: 8px;
  font-weight: 750;
}
</style>
