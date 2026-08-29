<script setup lang="ts">
import { computed, ref } from 'vue'

import type { RunEventEnvelope, RunStatus } from '../../runs/types'
import { presentRunEvent } from '../../runs/display'

const props = defineProps<{
  events: RunEventEnvelope[]
  status: RunStatus
}>()

const expanded = ref(true)
const items = computed(() => props.events.map(presentRunEvent))
const active = computed(() =>
  ['starting', 'running', 'waiting_approval', 'cancelling'].includes(props.status),
)
const traceSummary = computed(() => {
  const decisions = props.events.filter((item) => item.event === 'model.completed').length
  const tools = props.events.filter((item) => item.event === 'tool.completed').length
  return `${decisions} 次决策 · ${tools} 次反馈`
})
</script>

<template>
  <section class="activity-spine" aria-labelledby="activity-title">
    <button class="spine-toggle" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span>
        <strong id="activity-title">执行轨迹</strong>
        <small>{{ traceSummary }}</small>
      </span>
      <span class="chevron" :class="{ expanded }" aria-hidden="true">⌄</span>
    </button>

    <div v-if="expanded" class="spine-items" aria-live="polite">
      <div
        v-for="(item, index) in items"
        :key="item.seq"
        class="spine-item"
        :class="item.tone"
        :aria-current="active && index === items.length - 1 ? 'step' : undefined"
      >
        <span class="node"><span /></span>
        <div class="event-copy">
          <div class="event-title-row">
            <span class="stage-chip" :class="item.stage">{{ item.stageLabel }}</span>
            <span class="event-title">{{ item.title }}</span>
            <span v-if="item.meta" class="event-meta">{{ item.meta }}</span>
          </div>
          <p v-if="item.detail" :class="{ 'is-code': item.detailCode }">{{ item.detail }}</p>
        </div>
      </div>
      <div v-if="items.length === 0" class="spine-item active">
        <span class="node"><span /></span>
        <div class="event-copy waiting-copy">正在等待第一个运行事件…</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.activity-spine {
  padding: 0 18px 18px;
}

.spine-toggle {
  display: flex;
  width: 100%;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0;
  color: var(--ink);
  background: transparent;
  text-align: left;
}

.spine-toggle > span:first-child {
  display: grid;
  gap: 1px;
}

.spine-toggle strong {
  font-size: 12px;
  font-weight: 700;
}

.spine-toggle small {
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.chevron {
  color: var(--ink-faint);
  font-size: 15px;
  transform: rotate(-90deg);
  transition: transform 180ms var(--ease-out);
}

.chevron.expanded {
  transform: rotate(0);
}

.spine-items {
  position: relative;
  padding: 2px 0 2px 24px;
}

.spine-items::before {
  position: absolute;
  inset: 9px auto 10px 7px;
  width: 1px;
  background: var(--activity-line);
  content: '';
}

.spine-item {
  position: relative;
  min-height: 50px;
  padding: 5px 0 11px;
  color: var(--ink-soft);
}

.node {
  position: absolute;
  top: 9px;
  left: -24px;
  display: grid;
  width: 15px;
  height: 15px;
  place-items: center;
  border: 2px solid var(--surface-subtle);
  border-radius: 50%;
  background: var(--line-strong);
}

.node span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.spine-item.active .node span {
  background: var(--accent);
}

.spine-item.active[aria-current="step"] .node {
  box-shadow: 0 0 0 4px var(--accent-soft);
}

.spine-item.success .node span {
  background: var(--success);
}

.spine-item.warning .node span {
  background: var(--warning);
}

.spine-item.danger .node span {
  background: var(--danger);
}

.event-copy {
  min-width: 0;
}

.event-title-row {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.stage-chip {
  min-width: 31px;
  flex: none;
  padding: 1px 4px;
  border-radius: 4px;
  color: var(--ink-muted);
  background: var(--surface-hover);
  font-family: var(--font-utility);
  font-size: 8px;
  font-weight: 750;
  text-align: center;
}

.stage-chip.decision {
  color: var(--accent);
  background: var(--accent-soft);
}

.stage-chip.execution,
.stage-chip.approval {
  color: var(--warning);
  background: var(--warning-soft);
}

.stage-chip.feedback {
  color: var(--success);
  background: var(--success-soft);
}

.event-title {
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-copy p {
  margin: 4px 0 0;
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1.45;
}

.event-copy p.is-code {
  overflow-wrap: anywhere;
  color: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 9.5px;
}

.event-meta {
  flex: none;
  margin-left: auto;
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 8px;
}

.waiting-copy {
  padding-top: 3px;
  color: var(--ink-muted);
  font-size: 11px;
}
</style>
